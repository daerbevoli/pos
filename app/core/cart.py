"""
Cart
The ticket being rung up, as a flat ordered list of entries that mirrors
the printed receipt (items, subtotals, discounts, partial payments), plus
the money rules on it: promos, discounts and how they split over lines,
reversals, VAT treatment per client, and the JSON snapshot it's saved as.
No database access — see sales_service.py for saving it.
"""
import json
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

WEIGHT_UNITS = {"kg", "g", "ml", "l"}

@dataclass
class ReceiptEntry:
    pass

@dataclass
class CartItem(ReceiptEntry):
    product_id: int
    product_name: str
    product_barcode: str
    unit_price: float
    quantity: float | None  # None = amount not entered yet (weight/volume units)
    unit: str = "pcs"
    tax_rate: int = 0
    base_tax_rate: int = 0  # the product's own rate; tax_rate may be zeroed by retax_for_client()
    base_unit_price: float = 0.0  # the domestic (VAT-incl.) price; unit_price may be netted down by retax_for_client()
    is_reversal: bool = False  # True for a line that reverses an earlier line on a reopened sale
    has_reversal: bool = False  # True once this original line has been reversed (blocks reversing it again)
    reversal_of: "CartItem | None" = None  # the original line this reverses; saved by position in to_snapshot()
    locked: bool = False  # True for a line already saved on a reopened sale: reversed, never edited or deleted
    is_open_price: bool = False  # True = unit_price is typed in per sale rather than fixed on the product
    promo_name: str | None = None    # label of the Promo attached to the product when this line was added, if any
    promo_type: str | None = None    # "percent" | "fixed" | None — copied from Promo.discount_type
    discount: float = 0.0            # copied from PromoItem.discount_value: a percent or a fixed amount per unit, per promo_type

    @property
    def pending(self) -> bool:
        """True while this line still needs an amount typed in before it can
        be paid: a weight/volume item awaiting its quantity, or an
        open-price item awaiting its price."""
        return self.quantity is None or (self.is_open_price and self.unit_price == 0.0)

    @property
    def article_count(self) -> float:
        """How many articles this line counts as on a subtotal: its quantity,
        or one for a weighed/measured line (1.25 kg of apples is one
        article), negative on a reversal/refund. Zero while pending."""
        if self.pending:
            return 0
        if self.unit in WEIGHT_UNITS:
            return -1 if self.quantity < 0 else 1
        return self.quantity

    @property
    def discount_amount(self) -> float:
        """Discount amount contributed by the attached promo, recomputed live off the
        current quantity/unit_price so it stays correct even for a pending
        weight/open-price item whose amount is filled in after this line
        already exists. Materialized into a real DiscountEntry by
        Cart.sync_promo_discounts() — not folded into line_total, so the
        item's own row keeps showing its full, undiscounted price and the
        promo shows up as its own labeled line, same as a manual discount.
        Sign-aware so a reversal line (negative quantity) yields a negative
        discount that exactly undoes the original line's."""
        if self.promo_type is None or self.quantity is None:
            return 0.0
        raw = self.unit_price * self.quantity
        if self.promo_type == "percent":
            return round(raw * self.discount / 100, 2)
        fixed = self.fixed_promo_per_unit * self.quantity
        return round(min(fixed, raw), 2) if raw >= 0 else round(max(fixed, raw), 2)

    @property
    def fixed_promo_per_unit(self) -> float:
        """A fixed promo's amount off per unit, in this line's VAT treatment.
        `discount` is a domestic (VAT-incl.) amount, like base_unit_price; a
        zero-rated line (non-domestic client) gets it netted of VAT the same
        way its price is (Cart._effective_price), so a foreign client pays the
        domestic promo price minus its VAT, not a bigger discount."""
        if self.tax_rate == self.base_tax_rate or self.base_tax_rate == 0:
            return self.discount
        return round(self.discount / (1 + self.base_tax_rate / 100), 2)

    @property
    def line_total(self):
        if self.quantity is None:
            return 0.0
        return round(self.unit_price * self.quantity, 2)

@dataclass
class SubtotalMarker(ReceiptEntry):
    pass


@dataclass
class Allocation:
    """The part of a discount that comes off one item."""
    item: CartItem
    amount: float  # VAT-inclusive, like CartItem.line_total


@dataclass
class DiscountEntry(ReceiptEntry):
    amount: float   # positive = deducts; negative for a VOID entry (or a refund line's promo) giving it back
    label: str      # display string, e.g. "10%" or "€5.00" or a promo's name
    is_promo: bool = False  # True = synthesized by Cart.sync_promo_discounts(), safe to drop and regenerate
    is_void: bool = False   # True = gives back a manual discount's share of a reversed line, see Cart.reverse()
    # Which items this discount comes off, and how much off each — fixed when
    # the discount is applied, so later edits (a reversal appended at the end,
    # a line removed) can't move it onto other items. Always sums to amount.
    # Empty for a discount built without them (older snapshots, tests): its
    # targets are then worked out from its position, see Cart._resolve().
    allocations: list[Allocation] = field(default_factory=list, compare=False, repr=False)

    @property
    def line_total(self) -> float:
        return -round(self.amount, 2)


@dataclass
class PaymentEntry(ReceiptEntry):
    """A partial tender applied toward the cart total before it's fully paid.
    Not part of subtotal/total — tracked separately via Cart.paid_total."""
    method: str
    amount: float

@dataclass(frozen=True)
class NetLine:
    """One CartItem's amounts after every discount that applies to it — see
    Cart.net_lines(). All VAT-inclusive except net_excl."""
    item: "CartItem"
    gross: float  # item.line_total: before discounts
    net: float    # after discounts: what was charged and what VAT is due on
    tax: float    # VAT portion of net

    @property
    def discount(self) -> float:
        return round(self.gross - self.net, 2)

    @property
    def net_excl(self) -> float:
        return round(self.net - self.tax, 2)


@dataclass
class Cart:
    entries: list[ReceiptEntry] = field(default_factory=list)
    is_domestic: bool = True  # whether the attached client is Belgian; affects unit_price/tax_rate
    is_refund: bool = False  # RF/CN mode: every line added goes in with a negative quantity

    def _effective_price(self, base_price: float, base_tax_rate: int) -> float:
        """The price actually charged: the domestic (VAT-incl.) price as-is
        for a Belgian client, netted of VAT for a non-domestic one — the
        store's own margin is unaffected either way, only the VAT portion
        it would otherwise have collected and remitted."""
        if self.is_domestic or base_tax_rate == 0:
            return base_price
        return round(base_price / (1 + base_tax_rate / 100), 2)

    @property
    def total(self) -> float:
        """Items minus discounts, VAT included. Partial payments don't count."""
        return round(sum(
            entry.line_total for entry in self.entries if isinstance(entry, (CartItem, DiscountEntry))
        ), 2)

    @property
    def paid_total(self) -> float:
        return round(sum(e.amount for e in self.entries if isinstance(e, PaymentEntry)), 2)

    @property
    def remaining_due(self) -> float:
        return round(self.total - self.paid_total, 2)

    def _resolve(self) -> tuple[list["CartItem"], dict[int, float], list[tuple["DiscountEntry", list[Allocation]]]]:
        """(items, id(item) -> net amount, each discount with its allocations).

        A discount uses its stored allocations. One without them is aimed by
        its position, the rule apply_discount() uses at the moment it's
        applied: right after an item (skipping earlier discount rows) it
        comes off that item; right after a SubtotalMarker it's spread over
        that section's items in proportion to their amounts, the last item
        taking the rounding remainder; with nothing before it, over the cart."""
        items = [e for e in self.entries if isinstance(e, CartItem)]
        net = {id(item): item.line_total for item in items}
        resolved = []
        section: list[CartItem] = []
        target: list[CartItem] = []  # what the next unallocated DiscountEntry applies to
        for entry in self.entries:
            if isinstance(entry, CartItem):
                section.append(entry)
                target = [entry]
            elif isinstance(entry, SubtotalMarker):
                target, section = section, []
            elif isinstance(entry, DiscountEntry):
                if entry.allocations:
                    allocations = [a for a in entry.allocations if id(a.item) in net]
                else:
                    allocations = _split(entry.amount, target or items, net)
                for a in allocations:
                    net[id(a.item)] = round(net[id(a.item)] - a.amount, 2)
                resolved.append((entry, allocations))
        return items, net, resolved

    def _pin_allocations(self):
        """Stores the position-derived allocations on every discount that has
        none yet, so the edit about to happen can't re-aim them. Called
        before every edit that adds, moves or removes lines around a
        discount, and on loading a snapshot."""
        for entry, allocations in self._resolve()[2]:
            if not entry.allocations:
                entry.allocations = allocations

    def _discount_targets(self) -> list["CartItem"]:
        """What a discount added now would come off: the last item, or right
        after a subtotal the last section's items (see _resolve()). A
        reversal and the line it voids never take a discount."""
        section, target = [], []
        for entry in self.entries:
            if isinstance(entry, CartItem):
                section.append(entry)
                target = [entry]
            elif isinstance(entry, SubtotalMarker):
                target, section = section, []
        return [item for item in target if not (item.is_reversal or item.has_reversal)]

    def discount_base(self) -> float | None:
        """The amount the next discount applies to: what's left of its
        targets after the discounts already on them, so stacked discounts
        can never take it below zero. None if nothing can be discounted there."""
        targets = self._discount_targets()
        if not targets:
            return None
        _, net, _ = self._resolve()
        return round(sum(net[id(item)] for item in targets), 2)

    def apply_percent_discount(self, percent: float) -> "DiscountEntry | None":
        """A manual % discount on the last item / last section (capped at
        100%). None if there's nothing to discount there."""
        base = self.discount_base()
        if base is None or base <= 0:
            return None
        percent = min(percent, 100.0)
        return self._add_discount(round(base * percent / 100.0, 2), f"{_MANUAL_PREFIX}{percent:g}%")

    def apply_amount_discount(self, amount: float) -> "DiscountEntry | None":
        """A manual € discount on the last item / last section, capped at
        what's left of it. None if there's nothing to discount there."""
        base = self.discount_base()
        if base is None or base <= 0:
            return None
        amount = round(min(amount, base), 2)
        return self._add_discount(amount, _amount_label(amount))

    def _add_discount(self, amount: float, label: str) -> "DiscountEntry":
        self._pin_allocations()
        _, net, _ = self._resolve()
        entry = DiscountEntry(amount=amount, label=label,
                              allocations=_split(amount, self._discount_targets(), net))
        self.entries.append(entry)
        return entry

    def reverse(self, item: "CartItem") -> "CartItem":
        """Voids a line already saved on a reopened sale: the original stays
        on the record and a negative-quantity reversal is appended. Each
        manual discount's share of the original is given back by a VOID
        discount on the reversal, and the original's promo line drops out
        (sync_promo_discounts skips reversed lines) — so original and
        reversal net to exactly zero. Returns the reversal line."""
        self._pin_allocations()
        item.has_reversal = True
        reversal = CartItem(
            product_id=item.product_id,
            product_name=item.product_name,
            product_barcode=item.product_barcode,
            unit_price=item.unit_price,
            base_unit_price=item.base_unit_price,
            tax_rate=item.tax_rate,
            base_tax_rate=item.base_tax_rate,
            quantity=-item.quantity,
            unit=item.unit,
            is_reversal=True,
            reversal_of=item,
            # promo fields deliberately not copied: the original's promo
            # line disappears instead (see sync_promo_discounts()).
        )
        manual = [e for e in self.entries if isinstance(e, DiscountEntry) and not e.is_promo and not e.is_void]
        self.entries.append(reversal)
        for discount in manual:
            share = round(sum(a.amount for a in discount.allocations if a.item is item), 2)
            if share:
                self.entries.append(DiscountEntry(
                    amount=-share, label=f"VOID {discount.label}", is_void=True,
                    allocations=[Allocation(reversal, -share)],
                ))
        self.sync_promo_discounts()
        return reversal

    def remove_entry(self, entry: ReceiptEntry) -> str | None:
        """What the Error key does to a selected row: "reversed" for a line
        already saved on a reopened sale (see reverse()), "removed" for
        anything else, None if nothing changed (a line reversed already).
        A promo or VOID discount row stands for the line it belongs to; a
        subtotal takes the discount rows right under it along."""
        self._pin_allocations()
        if isinstance(entry, SubtotalMarker):
            self._delete_subtotal(entry)
            return "removed"
        if isinstance(entry, DiscountEntry) and (entry.is_promo or entry.is_void) and entry.allocations:
            entry = entry.allocations[0].item
        if (isinstance(entry, CartItem) and entry.locked and entry.quantity is not None
                and not entry.is_reversal):
            if entry.has_reversal:
                return None  # capped at one reversal per line
            self.reverse(entry)
            return "reversed"
        if isinstance(entry, CartItem) and entry.is_reversal and entry.reversal_of is not None:
            # Removing the reversal itself un-caps the original line, so it
            # can be reversed again.
            entry.reversal_of.has_reversal = False
        self._delete(entry)
        return "removed"

    def _delete_subtotal(self, marker: SubtotalMarker):
        """Drops a subtotal and the discount rows directly under it: left
        behind, they'd read as coming off the last item rather than the
        block they were given on."""
        start = next(i for i, e in enumerate(self.entries) if e is marker)
        end = start + 1
        while end < len(self.entries) and isinstance(self.entries[end], DiscountEntry):
            end += 1
        del self.entries[start:end]

    def _delete(self, entry: ReceiptEntry):
        """Drops one entry (by identity: identical lines compare equal). A
        removed item's share comes off every discount on it, and a discount
        left on nothing goes too, so no discount slides onto another line."""
        self.entries = [e for e in self.entries if e is not entry]
        if isinstance(entry, CartItem):
            for discount in [e for e in self.entries if isinstance(e, DiscountEntry) and not e.is_promo]:
                mine = [a for a in discount.allocations if a.item is entry]
                if not mine:
                    continue
                discount.allocations = [a for a in discount.allocations if a.item is not entry]
                discount.amount = round(discount.amount - sum(a.amount for a in mine), 2)
                _relabel(discount)
                if not discount.allocations:
                    self.entries = [e for e in self.entries if e is not discount]
        self.sync_promo_discounts()

    def net_lines(self) -> list[NetLine]:
        """Every CartItem with its gross, discounted and VAT amounts — the
        one place these are worked out. The net is what VAT is due on (a
        discount the customer gets lowers the taxable amount; EU VAT
        Directive art. 79(b)), and the nets always sum to exactly self.total.
        Saving the sale, the invoice lines sent to the ERP and the invoice
        VAT/category breakdowns all read them from here, so they can't
        disagree with each other."""
        items, net, _ = self._resolve()
        return [
            NetLine(item=item, gross=item.line_total, net=net[id(item)], tax=calc_tax(net[id(item)], item.tax_rate))
            for item in items
        ]

    def subtotals(self) -> list[tuple[float, float]]:
        """(article count, amount) for each SubtotalMarker, in order: what the
        block of items since the previous subtotal comes to, net of the
        discounts on them that sit above the marker (one entered after it
        prints as its own line below it). A block holding only discounts
        re-totals the block before it, discounts included. The till,
        customer display and receipt all show these, so they agree."""
        _, _, resolved = self._resolve()
        allocations = {id(discount): allocs for discount, allocs in resolved}
        net: dict[int, float] = {}  # id(item) -> amount so far, at this point in the list
        block: list[CartItem] = []
        prev_block: list[CartItem] = []
        result = []
        for entry in self.entries:
            if isinstance(entry, CartItem):
                net[id(entry)] = entry.line_total
                block.append(entry)
            elif isinstance(entry, DiscountEntry):
                for a in allocations[id(entry)]:
                    if id(a.item) in net:
                        net[id(a.item)] -= a.amount
            elif isinstance(entry, SubtotalMarker):
                block = block or prev_block
                result.append((
                    sum(item.article_count for item in block),
                    round(sum(net[id(item)] for item in block), 2),
                ))
                prev_block, block = block, []
        return result

    def add_product(self, product, quantity: float | None = 1, price: float | None = None):
        """price overrides product.price for this line only — used for the
        cashier-typed amount on an open-price item."""
        base_price = product.price if price is None else price
        if quantity is not None and self.is_refund:
            quantity = -abs(quantity)

        promo_item = product.active_promo_item
        self.entries.append(
            CartItem(
                product_id=product.id,
                product_name=product.name,
                product_barcode=product.barcode or "",
                unit_price=self._effective_price(base_price, product.tax),
                quantity=quantity,
                unit=product.unit,
                tax_rate=product.tax if self.is_domestic else 0,
                base_tax_rate=product.tax,
                base_unit_price=base_price,
                is_open_price=product.is_open_price,
                promo_name=promo_item.promo.name if promo_item else None,
                promo_type=promo_item.discount_type if promo_item else None,
                discount=promo_item.discount_value if promo_item else 0.0,
            )
        )
        self.sync_promo_discounts()

    def sync_promo_discounts(self):
        """Rebuild every promo-driven DiscountEntry from scratch off each
        CartItem's *current* discount_amount. Call this after anything that
        could change a promo'd line's amount: add_product() already does,
        but also after +/- quantity, filling in a pending weight/open-price
        item's amount, reversing a line, or removing one — see callers in
        pos_screen.py. Safe to call repeatedly: it drops every existing
        is_promo entry first, so it never drifts or duplicates.

        A line with has_reversal set is skipped — once a reopened ticket's
        line has been voided by an (appended, negative-quantity) reversal,
        its promo discount line disappears rather than getting a second,
        offsetting entry next to it. The reversal line itself never carries
        promo fields, so it wouldn't generate one anyway."""
        self.entries = [e for e in self.entries if not (isinstance(e, DiscountEntry) and e.is_promo)]
        result = []
        for entry in self.entries:
            result.append(entry)
            if isinstance(entry, CartItem) and not entry.has_reversal and entry.discount_amount != 0:
                result.append(DiscountEntry(
                    amount=entry.discount_amount, label=entry.promo_name, is_promo=True,
                    allocations=[Allocation(entry, entry.discount_amount)],
                ))
        self.entries = result

    def retax_for_client(self, is_domestic: bool):
        """Re-derives every item's effective VAT rate and price for the
        client now attached to the sale: zero-rated and netted of VAT (EU
        reverse-charge / non-EU export) once a non-domestic client is on
        it, restored to the product's own rate/price otherwise. The
        store's margin is unaffected — only the VAT portion changes. Call
        whenever the attached client changes — see pos_screen.set_client().
        Promo lines are regenerated off the new prices, and each manual
        discount's share of an item scales with that item's price, so 10%
        stays 10% and a € discount comes off with or without VAT like the
        price it's on."""
        self._pin_allocations()
        old_gross = {id(e): e.line_total for e in self.entries if isinstance(e, CartItem)}
        self.is_domestic = is_domestic
        for entry in self.entries:
            if isinstance(entry, CartItem):
                entry.tax_rate = entry.base_tax_rate if is_domestic else 0
                entry.unit_price = self._effective_price(entry.base_unit_price, entry.base_tax_rate)
        for discount in self.entries:
            if not isinstance(discount, DiscountEntry) or discount.is_promo:
                continue
            for allocation in discount.allocations:
                before = old_gross[id(allocation.item)]
                if before:
                    allocation.amount = round(allocation.amount * allocation.item.line_total / before, 2)
            discount.amount = round(sum(a.amount for a in discount.allocations), 2)
            _relabel(discount)
        self.sync_promo_discounts()

    def set_open_price(self, entry: "CartItem", amount: float):
        """Records the cashier-typed price for a pending open-price line,
        applying the sale's current client VAT treatment the same way
        retax_for_client does."""
        entry.base_unit_price = amount
        entry.unit_price = self._effective_price(amount, entry.base_tax_rate)

    def add_subtotal(self):
        self.entries.append(SubtotalMarker())

    def clear(self):
        """Empties the ticket for the next sale. The client's VAT treatment
        goes with it (the caller drops the attached client too); refund mode
        stays on, since only the RF/CN button leaves it."""
        self.entries.clear()
        self.is_domestic = True

    def to_snapshot(self) -> str:
        """Serialize entries in order, exactly as displayed, for later replay.
        A reversal's link to the line it voids is saved as that line's
        position among the items ("reversal_of"), so a reopened ticket can
        still delete the reversal and un-void the original; a discount's
        allocations likewise, as [item position, amount] pairs."""
        item_positions = {
            id(e): i for i, e in enumerate(e for e in self.entries if isinstance(e, CartItem))
        }
        data = []
        for entry in self.entries:
            if isinstance(entry, CartItem):
                data.append({
                    "type": "item",
                    "product_id": entry.product_id,
                    "product_name": entry.product_name,
                    "product_barcode": entry.product_barcode,
                    "unit_price": entry.unit_price,
                    "quantity": entry.quantity,
                    "unit": entry.unit,
                    "tax_rate": entry.tax_rate,
                    "base_tax_rate": entry.base_tax_rate,
                    "base_unit_price": entry.base_unit_price,
                    "is_reversal": entry.is_reversal,
                    "has_reversal": entry.has_reversal,
                    "reversal_of": item_positions.get(id(entry.reversal_of)),
                    "is_open_price": entry.is_open_price,
                    "promo_name": entry.promo_name,
                    "promo_type": entry.promo_type,
                    "discount": entry.discount,
                    # Kept so a reopened ticket recovered after a crash still
                    # can't have its already-charged lines edited away.
                    "locked": entry.locked,
                })
            elif isinstance(entry, DiscountEntry):
                data.append({
                    "type": "discount", "amount": entry.amount, "label": entry.label,
                    "is_promo": entry.is_promo, "is_void": entry.is_void,
                    "allocations": [
                        [item_positions[id(a.item)], a.amount]
                        for a in entry.allocations if id(a.item) in item_positions
                    ],
                })
            elif isinstance(entry, SubtotalMarker):
                data.append({"type": "subtotal"})
        return json.dumps(data)

    @classmethod
    def from_snapshot(cls, snapshot: str) -> "Cart":
        """Rebuild a cart from a string produced by to_snapshot(). Discounts
        saved before allocations existed get them from their position, as
        they were charged (see _pin_allocations())."""
        entries: list[ReceiptEntry] = []
        items: list[CartItem] = []
        reversal_links: list[tuple[CartItem, int | None]] = []
        allocation_links: list[tuple[DiscountEntry, list]] = []
        for raw in json.loads(snapshot) if snapshot else []:
            kind = raw.get("type")
            if kind == "item":
                item = CartItem(
                    product_id=raw["product_id"],
                    product_name=raw["product_name"],
                    product_barcode=raw["product_barcode"],
                    unit_price=raw["unit_price"],
                    quantity=raw["quantity"],
                    unit=raw.get("unit", "pcs"),
                    tax_rate=raw.get("tax_rate", 0),
                    base_tax_rate=raw.get("base_tax_rate", raw.get("tax_rate", 0)),
                    base_unit_price=raw.get("base_unit_price", raw["unit_price"]),
                    is_reversal=raw.get("is_reversal", False),
                    has_reversal=raw.get("has_reversal", False),
                    is_open_price=raw.get("is_open_price", False),
                    promo_name=raw.get("promo_name"),
                    promo_type=raw.get("promo_type"),
                    # Snapshots saved before the rename still carry "promo_value".
                    discount=raw.get("discount", raw.get("promo_value", 0.0)),
                    locked=raw.get("locked", False),
                )
                entries.append(item)
                items.append(item)
                if item.is_reversal:
                    reversal_links.append((item, raw.get("reversal_of")))
            elif kind == "discount":
                discount = DiscountEntry(
                    amount=raw["amount"], label=raw["label"], is_promo=raw.get("is_promo", False),
                    is_void=raw.get("is_void", False),
                )
                entries.append(discount)
                if raw.get("allocations"):
                    allocation_links.append((discount, raw["allocations"]))
            elif kind == "subtotal":
                entries.append(SubtotalMarker())
        _relink_reversals(items, reversal_links)
        _relink_allocations(items, allocation_links)
        cart = cls(entries=entries)
        cart._pin_allocations()
        return cart


_MANUAL_PREFIX = "MANUAL DISCOUNT "


def _amount_label(amount: float) -> str:
    return f"{_MANUAL_PREFIX}{amount:.2f}"


def _relabel(discount: DiscountEntry):
    """A manual € discount's label shows its amount: keep it in step when the
    amount changes (a removed line, a client with other VAT treatment). A %
    label stays true as is."""
    if discount.label.startswith(_MANUAL_PREFIX) and not discount.label.endswith("%"):
        discount.label = _amount_label(discount.amount)


def _split(amount: float, recipients: list[CartItem], net: dict[int, float]) -> list[Allocation]:
    """`amount` spread over `recipients` in proportion to their current net
    amounts (evenly if those sum to 0), rounded to the cent, the last one
    taking the rounding remainder so the shares sum to exactly `amount`."""
    if not recipients:
        return []
    base = sum(net[id(item)] for item in recipients)
    remaining = round(amount, 2)
    allocations = []
    for i, item in enumerate(recipients):
        if i == len(recipients) - 1:
            share = remaining
        elif base:
            share = round(amount * net[id(item)] / base, 2)
        else:
            share = round(amount / len(recipients), 2)
        allocations.append(Allocation(item, share))
        remaining = round(remaining - share, 2)
    return allocations


def _relink_allocations(items: list[CartItem], links: list[tuple[DiscountEntry, list]]):
    """Restore each discount's allocations after from_snapshot() from their
    saved item positions. A discount whose positions don't fit the items is
    left without, and so gets them from its position like an old snapshot."""
    for discount, raw in links:
        try:
            allocations = [Allocation(items[position], amount) for position, amount in raw]
        except (IndexError, TypeError, ValueError):
            logger.warning("Snapshot discount %r has unusable allocations %r; aimed by position instead",
                           discount.label, raw)
            continue
        if round(sum(a.amount for a in allocations), 2) != round(discount.amount, 2):
            logger.warning("Snapshot discount %r allocations don't add up to %.2f; aimed by position instead",
                           discount.label, discount.amount)
            continue
        discount.allocations = allocations


def _relink_reversals(items: list[CartItem], links: list[tuple[CartItem, int | None]]):
    """Restore each reversal's reversal_of after from_snapshot(). Uses the
    saved position when there is one; snapshots saved before it existed
    fall back to the earliest still-unclaimed reversed line with the same
    product, price and opposite quantity — identical lines are
    interchangeable, so whichever one is picked voids the same amount."""
    claimed: set[int] = set()
    for reversal, position in links:
        original = None
        if position is not None and 0 <= position < len(items) and items[position].has_reversal:
            original = items[position]
        else:
            original = next(
                (
                    item for item in items
                    if item.has_reversal and not item.is_reversal and id(item) not in claimed
                    and item.product_id == reversal.product_id
                    and item.unit_price == reversal.unit_price
                    and item.quantity is not None and reversal.quantity is not None
                    and item.quantity == -reversal.quantity
                ),
                None,
            )
        if original is not None:
            reversal.reversal_of = original
            claimed.add(id(original))
        else:
            logger.warning("Snapshot reversal of %r (qty %s) has no matching original line",
                           reversal.product_name, reversal.quantity)


def calc_tax(line_total: float, tax_rate: int) -> float:
    """Return the VAT portion of a tax-inclusive line total."""
    if tax_rate == 0:
        return 0.0
    return round(line_total - line_total / (1 + tax_rate / 100), 2)
