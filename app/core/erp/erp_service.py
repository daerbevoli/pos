import logging
import time
from typing import Any

import requests

from app.core.sale.sales_service import InvoiceLine
from app.utils.validators import normalize_vat

logger = logging.getLogger(__name__)

_PARTNER_FIELDS = (
    ("name", "name"),
    ("street", "street"),
    ("zip", "zip"),
    ("city", "city"),
    ("phone", "phone"),
    ("email", "email"),
)


def _partner_values(customer_info: dict) -> dict:
    """The res.partner values the POS has for the customer, leaving out the ones it has no value for"""
    values = {}
    for key, field in _PARTNER_FIELDS:
        value = (customer_info.get(key) or "").strip()
        if value:
            values[field] = value
    return values


# Request/response bodies are logged at DEBUG (pos.log only); cap their size
# so a big read() doesn't flood the file. Headers are never logged: they
# carry the API key.
_LOG_BODY_MAX = 2000

class ERPError(Exception):
    """ERP Error thrown at connection problem, bad HTTP request or error in received HTTP data"""


def _clip(value) -> str:
    text = str(value)
    return text if len(text) <= _LOG_BODY_MAX else text[:_LOG_BODY_MAX] + f"... ({len(text)} chars)"


class ErpService:
    """Client that connect to the Odoo database via the external RPC JSON-2 API"""
    def __init__(self, url: str, db: str, api_key: str, timeout: int = 15):
        self.base_url = f"{url}/json/2"
        self.db = db
        self.api_key = api_key
        self.timeout = timeout

        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "X-Odoo-Database": self.db,
            "Content-Type": "application/json",
        }

    def _call(self, model: str, method: str, payload: dict) -> Any:
        logger.debug("ERP -> %s.%s %s", model, method, _clip(payload))
        started = time.monotonic()
        try:
            res = requests.post(
                f"{self.base_url}/{model}/{method}",
                headers=self.headers,
                json=payload,
                timeout=self.timeout,
            )
        except requests.RequestException as e:
            logger.warning("ERP %s.%s connection error after %.2fs: %s",
                         model, method, time.monotonic() - started, e)
            raise ERPError(f"Connection error: {e}")
        elapsed = time.monotonic() - started

        if res.status_code != 200:
            logger.warning("ERP %s.%s HTTP %s after %.2fs: %s",
                         model, method, res.status_code, elapsed, _clip(res.text))
            raise ERPError(
                f"HTTP {res.status_code} {model}.{method}: {res.text}"
            )

        data = res.json()
        logger.debug("ERP <- %s.%s %.2fs %s", model, method, elapsed, _clip(data))

        if isinstance(data, dict) and data.get("error"):
            logger.warning("ERP %s.%s returned error: %s", model, method, data["error"])
            raise ERPError(data["error"])

        return data

    def connect(self) -> bool:
        """Validate JSON-2 API access. Verify access by calling a lightweight endpoint"""
        user_context = self._call(
            model="res.users",
            method="context_get",
            payload={}
        )

        if not user_context['uid']:
            logger.warning("ERP authentication failed for db %s (no uid returned)", self.db)
            raise PermissionError("Authentication failed: Check username/API key.")
        logger.info("ERP connection OK: db %s, uid %s", self.db, user_context["uid"])
        return True


    # ORM helpers
    def search(self, model, domain, limit = 1) -> Any:
        payload = {"domain": domain}
        if limit:
            payload["limit"] = limit
        return self._call(model, "search", payload)

    def read(self, model, ids, fields) -> Any:
        return self._call(model, "read", {
            "ids": ids,
            "fields": fields,
        })

    def create(self, model, vals, **kwargs) -> Any:
        payload = {"vals_list": [vals]}
        payload.update(kwargs)
        ids = self._call(model, "create", payload)
        return ids[0]

    def write(self, model, ids, vals) -> Any:
        return self._call(model, "write", {"ids": ids, "vals": vals})

    def button(self, model, method, ids, **kwargs) -> Any:
        payload = {"ids": ids, "context": {}}
        payload.update(kwargs)
        return self._call(model, method, payload)

    # Master data helpers
    def get_sales_account_id(self, code: str = "700000") -> int:
        ids = self.search(
            model="account.account",
            domain=[["code", "=", code]],
            limit=1,
        )
        if not ids:
            raise ValueError(f"Sales account {code} not found in Odoo.")
        return ids[0]

    def get_sale_tax_id(self, rate: float) -> int:
        ids = self.search(
            model="account.tax",
            domain=[
                ["type_tax_use", "=", "sale"],
                ["amount", "=", rate],
                ["active", "=", True],
            ],
            limit=1,
        )
        if not ids:
            raise ValueError(f"Sales tax for rate {rate}% not found.")
        return ids[0]

    def get_journal_id(self, code: str = "VF") -> int:
        ids = self.search(
            model="account.journal",
            domain=[["code", "=", code]],
            limit=1,
        )
        if not ids:
            raise ValueError(f"Journal '{code}' not found.")
        return ids[0]

    def get_country_id(self, code: str = "BE") -> int:
        ids = self.search(
            model="res.country",
            domain=[["code", "=", code]],
            limit=1,
        )
        if not ids:
            raise ValueError(f"Country code '{code}' not found.")
        return ids[0]

    def create_invoice_lines(self, invoice_lines: list[InvoiceLine]) -> list:
        """
        Create invoice lines based on invoiceLines data object and return it
        :param invoice_lines: the separate line items of the invoice
        :return: lines
        """
        account_id = self.get_sales_account_id()  # Default 700000

        lines = []
        tax_ids = {}  # rate -> Odoo tax id: one lookup per rate, not per line

        # Discounts travel as each line's discount_percent, not as lines of their own.
        for invoiceLine in invoice_lines:
            if invoiceLine.tax_rate not in tax_ids:
                tax_ids[invoiceLine.tax_rate] = self.get_sale_tax_id(invoiceLine.tax_rate)
            tax_id = tax_ids[invoiceLine.tax_rate]
            lines.append((0, 0, {
                "name": invoiceLine.product_name,
                "quantity": invoiceLine.quantity,
                "price_unit": invoiceLine.unit_price_excl_tax,
                "discount": invoiceLine.discount_percent,
                "account_id": account_id,
                "tax_ids": [(6, 0, [tax_id])]}))
        if not lines:
            raise ValueError("No invoice lines created. Check parsed totals.")
        logger.debug("Built %d invoice lines: %s", len(lines), _clip(lines))
        return lines


    def get_or_create_partner(self, customer_info: dict) -> int:
        """The Odoo partner for the invoice's customer, found by VAT number,
        created if there's none. The POS is the ground truth: a found
        partner gets every field the POS has a value for (see
        _sync_partner()); a field the POS leaves empty keeps Odoo's value."""
        vat = normalize_vat(customer_info.get("vat"))
        if not vat:
            raise ValueError("Customer VAT number is required.")
        country_id = self.get_country_id(customer_info["country"]) if customer_info.get("country") else None

        ids = self.search(
            model="res.partner",
            domain=[["vat", "=", vat]],
            limit=1,
        )
        if ids:
            partner_id = ids[0]
            logger.debug("ERP partner %s matched VAT %s", partner_id, vat)
            self._sync_partner(partner_id, customer_info, country_id)
            return partner_id

        vals = {
            "vat": vat,
            "lang": "nl_BE",
            "is_company": True,
            "invoice_sending_method": "peppol",
            "invoice_edi_format": "ubl_bis3",
        }
        vals.update(_partner_values(customer_info))
        if country_id:
            vals["country_id"] = country_id
        new_partner = self.create(model="res.partner", vals=vals)
        logger.info("ERP partner created: id %s (has email: %s)", new_partner, bool(vals.get("email")))
        logger.debug("ERP partner %s created for %s, VAT %s, country %s",
                     new_partner, customer_info.get("name"), vat, customer_info.get("country"))
        return new_partner

    def _sync_partner(self, partner_id: int, customer_info: dict, country_id: int | None):
        """Overwrites the Odoo partner's fields that differ from the POS's
        non-empty values, the POS is the ground truth."""
        wanted = _partner_values(customer_info)
        current = self.read(model="res.partner", ids=[partner_id],
                            fields=[field for _, field in _PARTNER_FIELDS] + ["country_id"])[0]
        changes = {field: value for field, value in wanted.items()
                   if value != (current.get(field) or "").strip()}
        if country_id and (current.get("country_id") or [None])[0] != country_id:
            changes["country_id"] = country_id
        if changes:
            self.write("res.partner", [partner_id], changes)
            # Field names only: the values are customer contact details.
            logger.info("ERP partner %s updated from the POS: %s", partner_id, ", ".join(sorted(changes)))

    def create_post_invoice(self, invoice_data: dict) -> tuple[int, bool]:
        """
        Creates and posts the invoice. One already in Odoo under the same
        number (ref) isn't created again: it's logged and picked up as
        it is (posted first if still a draft), so a retry can finish the job.
        :param invoice_data: data of invoice, see generate_invoice_data()
        :return: (invoice id, whether Odoo has already sent it)
        """
        inv_num, inv_date, due_date, receiver, items = (
            invoice_data["inv_num"], invoice_data["inv_date"], invoice_data["due_date"],
            invoice_data["to"], invoice_data["items"],
        )
        # "out_refund" for a credit note (CN-…)
        move_type = invoice_data.get("move_type", "out_invoice")

        if not inv_num or not inv_date:
            raise ValueError("Missing crucial invoice data")

        partner_id = self.get_or_create_partner(receiver)
        journal_id = self.get_journal_id("VF")

        existing = self.search(
            model="account.move",
            domain=[["move_type", "=", move_type], ["ref", "=", inv_num]],
            limit=1,
        )
        if existing:
            return self._resume_invoice(existing[0], inv_num)

        invoice_id = self.create(
            model="account.move",
            vals={
                "move_type": move_type,
                "journal_id": journal_id,
                "partner_id": partner_id,
                "invoice_date": inv_date,
                "invoice_date_due": due_date,
                "ref": inv_num,
                "invoice_line_ids": self.create_invoice_lines(items),
            },
        )
        logger.info("ERP %s %s created: id %s, partner %s, %d lines",
                    move_type, inv_num, invoice_id, partner_id, len(items))

        self.button("account.move", "action_post", [invoice_id])
        logger.info("ERP %s %s (id %s) posted", move_type, inv_num, invoice_id)
        return invoice_id, False

    def _resume_invoice(self, invoice_id: int, inv_num: str) -> tuple[int, bool]:
        """The invoice already in Odoo under this reference, taken as it is:
        logged, not compared with the POS nor created again. A draft is
        posted so it can be sent; a canceled one can't be sent at all."""
        move = self.read(
            model="account.move",
            ids=[invoice_id],
            fields=["state", "is_move_sent"],
        )[0]
        logger.info("ERP invoice %s already exists (id %s, state %s, sent %s)",
                    inv_num, invoice_id, move["state"], bool(move["is_move_sent"]))
        if move["state"] == "cancel":
            raise ERPError(f"Invoice {inv_num} is cancelled in the ERP")
        if move["state"] == "draft":
            self.button("account.move", "action_post", [invoice_id])
            logger.info("ERP invoice %s (id %s) posted", inv_num, invoice_id)
        return invoice_id, bool(move["is_move_sent"])

    def send_invoice(self, invoice_id: int, use_peppol: bool, use_email: bool) -> tuple[bool, str]:
        """
        Sends a posted invoice through the Odoo "Send & Print" wizard.

        :param invoice_id: id of the account.move to send
        :param use_peppol: Peppol is mandatory: a partner that isn't on
            Peppol gets nothing, not even the email, it has to be sent by
            hand. Off (development), Peppol isn't used or checked at all.
        :param use_email: email goes along when the partner has an address;
            without one it's left out, and that's logged.
        :return: (True, message) once sent, (False, reason) otherwise
        """
        invoice = self.read(
            model="account.move",
            ids=[invoice_id],
            fields=["state", "partner_id", "peppol_move_state"],
        )[0]
        if invoice["state"] != "posted":
            logger.warning("ERP invoice id %s not sent: state is %s, not posted", invoice_id, invoice["state"])
            return False, "Invoice is not posted"

        partner_id = invoice["partner_id"][0]
        partner = self.read(
            model="res.partner",
            ids=[partner_id],
            fields=["email", "peppol_verification_state"],
        )[0]

        methods: list[str] = []

        # 1. Peppol, mandatory when on: without it nothing is sent.
        if use_peppol:
            problem = self._peppol_problem(partner_id, partner["peppol_verification_state"],
                                           invoice["peppol_move_state"])
            if problem:
                logger.warning("ERP invoice id %s not sent: %s", invoice_id, problem)
                return False, problem
            methods.append("peppol")

        # 2. Email, optional: added when the partner has an address.
        if use_email:
            if partner["email"]:
                methods.append("email")
            else:
                logger.info("ERP invoice id %s: partner %s has no email address%s", invoice_id, partner_id,
                            ", sending via Peppol only" if methods else "")

        if not methods:
            reason = "Partner has no email address" if use_email else "No sending method switched on"
            logger.warning("ERP invoice id %s not sent: %s", invoice_id, reason)
            return False, reason

        # 3. The wizard. Building the context ourselves avoids an extra
        #    round trip; it is what the "Send & Print" button would pass.
        context = {"active_model": "account.move", "active_ids": [invoice_id]}
        wizard_id = self.create(
            model="account.move.send.wizard",
            vals={"move_id": invoice_id, "sending_methods": methods},
            context=context,
        )
        self.button("account.move.send.wizard", "action_send_and_print", [wizard_id], context=context)

        # 4. Read back the Peppol state to confirm it was queued.
        if "peppol" in methods:
            new_state = self.read(
                model="account.move",
                ids=[invoice_id],
                fields=["peppol_move_state"],
            )[0]["peppol_move_state"]
            if new_state == "error":
                logger.warning("ERP invoice id %s: Peppol send failed", invoice_id)
                return False, "Peppol send failed: check the invoice in the ERP"

        message = "Invoice sent via " + " and ".join(methods)
        if use_email and "email" not in methods:
            message += " (partner has no email address)"
        logger.info("ERP invoice id %s: send wizard %s created, methods %s", invoice_id, wizard_id, methods)
        return True, message

    def _peppol_problem(self, partner_id: int, partner_state: str, move_state: str) -> str | None:
        """Why the invoice can't go out via Peppol now, or None if it can.
        A partner never checked yet gets its Peppol check started; it can't
        be used for this send, but a later one can."""
        if partner_state == "not_verified":
            self.button("res.partner", "button_account_peppol_check_partner_endpoint", [partner_id])
            return "Partner's Peppol registration is being checked: send again later"
        if partner_state != "valid":
            return "Partner is not on Peppol: manual sending required"
        if move_state in ("done", "processing"):
            return "Invoice already sent via Peppol"
        if move_state == "error":
            return "Previous Peppol send failed"
        return None
