import logging
from urllib.parse import urlencode

from odoo import _, api, models
from odoo.exceptions import ValidationError
from odoo.tools.urls import urljoin

_logger = logging.getLogger(__name__)


class PaymentTransaction(models.Model):
    _inherit = "payment.transaction"

    def _get_specific_rendering_values(self, processing_values):
        if self.provider_code != "tap":
            return super()._get_specific_rendering_values(processing_values)

        self.ensure_one()
        if self.operation == "refund":
            return {}

        provider = self.provider_id
        base_url = provider.get_base_url()
        return_url = urljoin(base_url, "/payment/tap/return")
        webhook_url = urljoin(base_url, "/payment/tap/webhook")

        first_name, last_name = self._tap_split_name(self.partner_name or self.partner_id.name or "Customer")
        country_code, phone_number = self._tap_split_phone(self.partner_phone or self.partner_id.phone)

        payload = {
            "amount": self.amount,
            "currency": self.currency_id.name,
            "threeDSecure": True,
            "save_card": False,
            "customer_initiated": True,
            "description": self.reference,
            "metadata": {
                "odoo_reference": self.reference,
                "odoo_tx_id": str(self.id),
            },
            "reference": {
                "transaction": self.reference,
                "order": self.reference,
            },
            "customer": {
                "first_name": first_name,
                "last_name": last_name,
                "email": self.partner_email or self.partner_id.email or "no-reply@example.com",
            },
            "source": {"id": provider.tap_source_id or "src_all"},
            "post": {"url": webhook_url},
            "redirect": {"url": return_url},
        }
        if country_code and phone_number:
            payload["customer"]["phone"] = {
                "country_code": country_code,
                "number": phone_number,
            }
        if provider.tap_merchant_id:
            payload["merchant"] = {"id": provider.tap_merchant_id}

        charge = provider._tap_make_request("POST", "charges/", payload=payload)
        charge_id = charge.get("id")
        transaction_url = (charge.get("transaction") or {}).get("url")
        status = charge.get("status")

        if charge_id:
            self.provider_reference = charge_id

        # Process any immediate terminal state before redirecting.
        self._process("tap", charge)

        if not transaction_url and status not in {"CAPTURED", "AUTHORIZED"}:
            raise ValidationError(_("Tap did not return a checkout URL for this transaction."))

        return {
            "api_url": transaction_url or f"{return_url}?{urlencode({'tap_id': charge_id})}",
            "url_params": {},
        }

    def _send_refund_request(self):
        if self.provider_code != "tap":
            return super()._send_refund_request()

        self.ensure_one()
        source_tx = self.source_transaction_id
        if not source_tx or not source_tx.provider_reference:
            raise ValidationError(_("The original Tap charge reference is missing."))

        provider = self.provider_id
        webhook_url = urljoin(provider.get_base_url(), "/payment/tap/webhook")
        payload = {
            "charge_id": source_tx.provider_reference,
            "amount": -self.amount,
            "currency": self.currency_id.name,
            "reason": "requested_by_customer",
            "post": {"url": webhook_url},
            "metadata": {
                "odoo_reference": self.reference,
                "odoo_source_reference": source_tx.reference,
            },
            "reference": {
                "merchant": self.reference,
            },
        }
        refund = provider._tap_make_request("POST", "refunds/", payload=payload)
        self._process("tap", refund)

    @api.model
    def _extract_reference(self, provider_code, payment_data):
        if provider_code != "tap":
            return super()._extract_reference(provider_code, payment_data)
        metadata = payment_data.get("metadata") or {}
        reference = payment_data.get("reference") or {}
        return (
            metadata.get("odoo_reference")
            or reference.get("transaction")
            or reference.get("merchant")
        )

    def _extract_amount_data(self, payment_data):
        if self.provider_code != "tap":
            return super()._extract_amount_data(payment_data)
        amount = payment_data.get("amount")
        currency = payment_data.get("currency")
        if amount is None or not currency:
            return None
        # Odoo refund child transactions store a negative amount; Tap reports a positive refund amount.
        if self.operation == "refund":
            amount = -float(amount)
        return {"amount": float(amount), "currency_code": currency}

    def _apply_updates(self, payment_data):
        if self.provider_code != "tap":
            return super()._apply_updates(payment_data)

        self.ensure_one()
        object_id = payment_data.get("id")
        if object_id:
            self.provider_reference = object_id

        status = (payment_data.get("status") or "").upper()
        if not status:
            self._set_error(_("Tap returned a payment response without a status."))
            return

        if status in {"INITIATED", "IN_PROGRESS", "PENDING"}:
            self._set_pending()
        elif status in {"CAPTURED", "SUCCESS", "SUCCEEDED", "REFUNDED"}:
            self._set_done()
        elif status in {"AUTHORIZED"}:
            self._set_authorized()
        elif status in {"CANCELLED", "ABANDONED", "VOID"}:
            self._set_canceled()
        elif status in {"FAILED", "DECLINED", "RESTRICTED", "TIMEDOUT", "UNKNOWN"}:
            response = payment_data.get("response") or {}
            message = response.get("message") or response.get("code") or status
            self._set_error(_("Tap payment failed: %s", message))
        else:
            self._set_pending(state_message=_("Tap returned status: %s", status))

    @staticmethod
    def _tap_split_name(name):
        parts = (name or "Customer").strip().split(None, 1)
        return parts[0][:40], (parts[1] if len(parts) > 1 else "-")[:40]

    @staticmethod
    def _tap_split_phone(phone):
        digits = "".join(ch for ch in (phone or "") if ch.isdigit())
        if not digits:
            return None, None
        # Good defaults for GCC/Egypt while avoiding hard dependence on phonenumbers.
        country_lengths = {"20": 10, "966": 9, "971": 9, "965": 8, "973": 8, "974": 8, "968": 8}
        for code, national_len in country_lengths.items():
            if digits.startswith(code) and len(digits) >= len(code) + national_len:
                return code, digits[len(code):]
        if digits.startswith("00"):
            digits = digits[2:]
        return None, None
