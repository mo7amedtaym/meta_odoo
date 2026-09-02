import hashlib
import hmac
import json
import logging

import requests

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class PaymentProvider(models.Model):
    _inherit = "payment.provider"

    code = fields.Selection(
        selection_add=[("tap", "Tap Payments")],
        ondelete={"tap": "set default"},
    )

    tap_secret_key = fields.Char(
        string="Secret API Key",
        required_if_provider="tap",
        groups="base.group_system",
        copy=False,
    )
    tap_publishable_key = fields.Char(
        string="Publishable API Key",
        required_if_provider="tap",
        groups="base.group_system",
        copy=False,
    )
    tap_merchant_id = fields.Char(
        string="Merchant ID",
        help="Optional Tap Merchant ID. Leave empty unless Tap requires it for your account.",
        groups="base.group_system",
        copy=False,
    )
    tap_language = fields.Selection(
        selection=[("auto", "Automatic"), ("en", "English"), ("ar", "Arabic")],
        string="Checkout Language",
        default="auto",
        required_if_provider="tap",
    )
    tap_source_id = fields.Selection(
        selection=[
            ("src_all", "All enabled Tap payment methods"),
            ("src_card", "Cards only"),
            ("src_sa.mada", "mada"),
            ("src_kw.knet", "KNET"),
            ("src_bh.benefit", "Benefit"),
            ("src_om.omannet", "OmanNet"),
            ("src_eg.fawry", "Fawry"),
        ],
        string="Tap Payment Source",
        default="src_all",
        required_if_provider="tap",
        help="src_all uses the Tap hosted checkout and shows all payment methods enabled on the merchant account.",
    )

    @api.depends("code")
    def _compute_feature_support_fields(self):
        super()._compute_feature_support_fields()
        for provider in self.filtered(lambda p: p.code == "tap"):
            provider.support_refund = "partial"
            provider.support_tokenization = False
            provider.support_manual_capture = False
            provider.support_express_checkout = False

    def _get_supported_currencies(self):
        self.ensure_one()
        currencies = super()._get_supported_currencies()
        if self.code != "tap":
            return currencies
        # Currencies commonly supported by Tap. Availability still depends on the merchant account.
        supported = {
            "AED", "BHD", "EGP", "EUR", "GBP", "JOD", "KWD", "OMR", "QAR", "SAR", "USD"
        }
        return currencies.filtered(lambda c: c.name in supported)

    def _get_default_payment_method_codes(self):
        self.ensure_one()
        if self.code != "tap":
            return super()._get_default_payment_method_codes()
        return ["card"]

    def _tap_headers(self):
        self.ensure_one()
        if not self.tap_secret_key:
            raise ValidationError(_("Tap Secret API Key is missing."))
        lang = self.tap_language
        if lang == "auto":
            lang = "ar" if (self.env.context.get("lang") or "").startswith("ar") else "en"
        return {
            "Authorization": f"Bearer {self.tap_secret_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "lang_code": lang,
        }

    def _tap_make_request(self, method, endpoint, payload=None, timeout=30):
        self.ensure_one()
        url = f"https://api.tap.company/v2/{endpoint.lstrip('/')}"
        try:
            response = requests.request(
                method.upper(),
                url,
                headers=self._tap_headers(),
                data=json.dumps(payload) if payload is not None else None,
                timeout=timeout,
            )
        except (requests.ConnectionError, requests.Timeout) as exc:
            raise ValidationError(_("Could not connect to Tap Payments: %s", exc)) from exc

        try:
            data = response.json()
        except ValueError:
            data = {"raw": response.text}

        if not response.ok:
            errors = data.get("errors") if isinstance(data, dict) else None
            message = None
            if errors and isinstance(errors, list):
                message = "; ".join(
                    str(item.get("description") or item.get("message") or item)
                    for item in errors
                )
            if not message and isinstance(data, dict):
                message = data.get("message") or data.get("description") or data.get("raw")
            raise ValidationError(
                _("Tap API request failed (%(status)s): %(message)s", status=response.status_code, message=message or response.reason)
            )
        return data

    @staticmethod
    def _tap_amount_string(amount, currency):
        decimals = 3 if currency in {"BHD", "JOD", "KWD", "OMR"} else 2
        return f"{float(amount):.{decimals}f}"

    def _tap_verify_webhook(self, payload, posted_hash):
        """Validate Tap's HMAC-SHA256 hashstring for charge/refund webhooks."""
        self.ensure_one()
        if not posted_hash or not isinstance(payload, dict):
            return False

        currency = payload.get("currency") or ""
        amount = self._tap_amount_string(payload.get("amount") or 0, currency)
        reference = payload.get("reference") or {}
        transaction = payload.get("transaction") or {}
        object_id = payload.get("id") or ""
        gateway_reference = reference.get("gateway") or ""
        payment_reference = reference.get("payment") or ""
        status = payload.get("status") or ""
        created = transaction.get("created") or payload.get("created") or ""

        to_hash = (
            f"x_id{object_id}"
            f"x_amount{amount}"
            f"x_currency{currency}"
            f"x_gateway_reference{gateway_reference}"
            f"x_payment_reference{payment_reference}"
            f"x_status{status}"
            f"x_created{created}"
        )
        calculated = hmac.new(
            self.tap_secret_key.encode("utf-8"),
            to_hash.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(calculated.lower(), posted_hash.lower())
