from typing import Any
import requests

from app.core.sales_service import InvoiceLine


class ErpService:
    """
    Client that connect to the Odoo database via the external JSON-2 API.
    JSON-2
    """
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
        try:
            res = requests.post(
                f"{self.base_url}/{model}/{method}",
                headers=self.headers,
                json=payload,
                timeout=self.timeout,
            )
        except requests.RequestException as e:
            raise Exception(f"Connection error: {e}")

        if res.status_code != 200:
            raise Exception(
                f"HTTP {res.status_code} {model}.{method}: {res.text}"
            )

        data = res.json()

        if isinstance(data, dict) and data.get("error"):
            raise Exception(data["error"])

        return data

    def connect(self):
        """
        Validate JSON-2 API access.
        JSON-2 does NOT authenticate or return a uid.
        We verify access by calling a lightweight endpoint.
        """
        user_context = self._call(
            model="res.users",
            method="context_get",
            payload={}
        )

        if not user_context['uid']:
            raise PermissionError("Authentication failed: Check username/API key.")
        return True


    # ORM helpers
    def search(self, model, domain, limit = 1):
        payload = {"domain": domain}
        if limit:
            payload["limit"] = limit
        return self._call(model, "search", payload)

    def read(self, model, ids, fields):
        return self._call(model, "read", {
            "ids": ids,
            "fields": fields,
        })

    def create(self, model, vals, **kwargs):
        payload = {"vals_list": [vals]}
        payload.update(kwargs)
        ids = self._call(model, "create", payload)
        return ids[0]

    def button(self, model, method, ids, **kwargs):
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
        Create invoice lines based on totals.
        :param invoice_lines: the separate line items of the invoice
        :return: invoice lines
        """
        account_id = self.get_sales_account_id()  # Default 700000

        lines = []

        for invoiceLine in invoice_lines:
            if invoiceLine.is_discount:
                lines.append((0, 0, {
                    "name": invoiceLine.product_name,
                    "quantity": invoiceLine.quantity,
                    "price_unit": (-1)*invoiceLine.unit_price_excl_tax,
                    "discount": 0,
                    "account_id": account_id
                }))
            else:
                tax_id = self.get_sale_tax_id(invoiceLine.tax_rate)
                lines.append((0, 0, {
                    "name": invoiceLine.product_name,
                    "quantity": invoiceLine.quantity,
                    "price_unit": invoiceLine.unit_price_excl_tax,
                    "discount": invoiceLine.discount_percent,
                    "account_id": account_id,
                    "tax_ids": [(6, 0, [tax_id])]}))
        if not lines:
            raise ValueError("No invoice lines created. Check parsed totals.")
        print(lines)
        return lines


    def get_or_create_partner(self, customer_info: dict) -> tuple[int, Any]:
        vat = customer_info.get("vat")
        if not vat:
            raise ValueError("Customer VAT number is required.")

        # Search by VAT
        ids = self.search(
            model="res.partner",
            domain=[["vat", "=", vat]],
            limit=1,
        )
        if ids:
            partner_id = ids[0]
            partner_email = self.read(model="res.partner", ids=partner_id, fields=["email"])[0]["email"]
            return partner_id, partner_email


        # Create partner
        country_id = self.get_country_id("BE")

        new_partner = self.create(
            model="res.partner",
            vals={
                "name": customer_info["name"],
                "street": customer_info.get("street"),
                "city": customer_info.get("city"),
                "zip": customer_info.get("zip"),
                "phone": customer_info.get("phone") or False,
                "email": customer_info.get("email") or False,
                "country_id": country_id,
                "vat": vat,
                "lang": "nl_BE",
                "is_company": True,
                "invoice_sending_method": "peppol",
                "invoice_edi_format": "ubl_bis3",
            },
        )

        partner_email = self.read(model="res.partner", ids=new_partner, fields=["email"])[0]["email"]

        return new_partner, partner_email

    def create_post_invoice(self, invoice_data: dict) -> tuple[int, bool, str, str]:
        """
        Creates and post invoice from filepath
        :param invoice_data: data of invoice
        :return: invoice id
        """

        # 1. Parse invoice and extract data
        inv_num, inv_date, due_date, sender, receiver, items, notes =  (invoice_data["inv_num"], invoice_data["inv_date"],
                                                                        invoice_data["due_date"], invoice_data["from"],
                                                                        invoice_data["to"], invoice_data["items"], invoice_data["notes"])

        # "out_refund" for a credit note (CN-…), see generate_invoice_data()
        move_type = invoice_data.get("move_type", "out_invoice")

        if not inv_num or not inv_date:
            raise Exception(f"Missing crucial invoice data")

        # Get partner and journal id
        partner_id, partner_email = self.get_or_create_partner(receiver)
        journal_id = self.get_journal_id("VF")


        # 3. Check for duplicate -> return original invoice id
        existing = self.search(
            model="account.move",
            domain=[["move_type", "=", move_type], ["ref", "=", inv_num]],
            limit=1,
        )
        if existing:
            return 0, False, inv_num, inv_date

        # 4. No duplicate -> create invoice
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
            }
        )


        # 6. Post invoice
        self.button("account.move", "action_post", [invoice_id])

        return invoice_id, partner_email, inv_num, inv_date

    def send_invoice(
            self,
            invoice_id: int,
            use_peppol: bool = True,
            use_email: bool = True,
    ) -> tuple[bool, str]:
        """
        Send an invoice via Peppol and/or email through the Odoo "Send & Print" wizard.
        Each channel is only used if it is actually possible for this invoice/partner.

        :param invoice_id: id of the account.move to send
        :param use_peppol: try to send via the Peppol network
        :param use_email: try to send via email
        :return: (True, message) if at least one channel was triggered, (False, reason) otherwise
        """

        # 1. Read invoice + partner
        invoice = self.read(
            model="account.move",
            ids=[invoice_id],
            fields=["state", "partner_id", "peppol_move_state"],
        )[0]

        print(invoice)

        if invoice["state"] != "posted":
            return False, "Invoice is not posted"

        partner_id = invoice["partner_id"][0]
        move_state = invoice["peppol_move_state"]

        partner = self.read(
            model="res.partner",
            ids=[partner_id],
            fields=["email", "peppol_verification_state"])[0]

        print(partner)
        partner_state = partner["peppol_verification_state"]

        methods: list[str] = []
        notes: list[str] = []

        # # 2. Peppol eligibility
        # if use_peppol:
        #     if partner_state == "not_verified":
        #         # Trigger the verification, it can't be used for this run
        #         self.button(
        #             "res.partner",
        #             "button_account_peppol_check_partner_endpoint",
        #             [partner_id],
        #         )
        #         notes.append("Peppol partner verification triggered")
        #     elif partner_state != "valid":
        #         notes.append("Partner is not on Peppol")
        #     elif move_state in ("done", "processing"):
        #         notes.append("Invoice already sent via Peppol")
        #     elif move_state == "error":
        #         notes.append("Previous Peppol send failed")
        #     else:
        #         methods.append("peppol")

        # 3. Email eligibility
        if use_email:
            if partner["email"]:
                methods.append("email")
            else:
                notes.append("Partner has no email address")

        if not methods:
            return False, "; ".join(notes) or "No sending method available"

        # 4. Create the wizard. Building the context ourselves avoids an extra
        #    round trip; it is what the "Send & Print" button would pass.
        context = {"active_model": "account.move", "active_ids": [invoice_id]}

        wizard_id = self.create(
            model="account.move.send.wizard",
            vals={
                "move_id": invoice_id,
                "sending_methods": methods,
            },
            context=context,
        )

        # 5. Send (drop the context kwarg if your button() helper doesn't take one)
        self.button(
            "account.move.send.wizard",
            "action_send_and_print",
            [wizard_id],
            context=context,
        )

        # 6. Read back the Peppol state to confirm it was queued
        # if "peppol" in methods:
        #     new_state = self.read(
        #         model="account.move",
        #         ids=[invoice_id],
        #         fields=["peppol_move_state"],
        #     )[0]["peppol_move_state"]
        #     if new_state == "error":
        #         notes.append("Peppol send failed")
        #         return False, "; ".join(notes)

        message = "Invoice sent via " + " and ".join(methods)
        if notes:
            message += " (" + "; ".join(notes) + ")"
        return True, message