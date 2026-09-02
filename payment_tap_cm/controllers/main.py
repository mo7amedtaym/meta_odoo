import json
import logging

from werkzeug.exceptions import Forbidden
from werkzeug.utils import redirect

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class TapController(http.Controller):

    @http.route(
        "/payment/tap/return",
        type="http",
        auth="public",
        methods=["GET", "POST"],
        csrf=False,
        save_session=False,
    )
    def tap_return(self, tap_id=None, **data):
        charge_id = tap_id or data.get("tap_id") or request.httprequest.args.get("tap_id")
        if not charge_id:
            _logger.warning("Tap return called without tap_id")
            return redirect("/payment/status")

        tx = request.env["payment.transaction"].sudo().search([
            ("provider_code", "=", "tap"),
            ("provider_reference", "=", charge_id),
        ], limit=1)
        if not tx:
            _logger.warning("No Odoo transaction found for Tap charge %s", charge_id)
            return redirect("/payment/status")

        try:
            charge = tx.provider_id.sudo()._tap_make_request("GET", f"charges/{charge_id}")
            tx._process("tap", charge)
        except Exception:
            _logger.exception("Failed to retrieve/process Tap charge %s on return", charge_id)
        return redirect("/payment/status")

    @http.route(
        "/payment/tap/webhook",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def tap_webhook(self, **kwargs):
        raw = request.httprequest.get_data(cache=False, as_text=True)
        try:
            payload = json.loads(raw or "{}")
        except json.JSONDecodeError:
            raise Forbidden("Invalid JSON")

        object_id = payload.get("id")
        if not object_id:
            raise Forbidden("Missing object id")

        Transaction = request.env["payment.transaction"].sudo()
        tx = Transaction.search([
            ("provider_code", "=", "tap"),
            ("provider_reference", "=", object_id),
        ], limit=1)

        # Refund webhooks have their own refund id, so fall back to Odoo metadata/reference.
        if not tx:
            reference = Transaction._extract_reference("tap", payload)
            if reference:
                tx = Transaction.search([
                    ("provider_code", "=", "tap"),
                    ("reference", "=", reference),
                ], limit=1)

        if not tx:
            _logger.warning("Ignoring Tap webhook for unknown object %s", object_id)
            return request.make_response("OK", status=200)

        provider = tx.provider_id.sudo()
        posted_hash = request.httprequest.headers.get("hashstring")
        if not provider._tap_verify_webhook(payload, posted_hash):
            _logger.warning("Rejected Tap webhook with invalid hash for %s", object_id)
            raise Forbidden("Invalid webhook signature")

        try:
            if str(object_id).startswith("chg_"):
                verified = provider._tap_make_request("GET", f"charges/{object_id}")
                tx._process("tap", verified)
            elif str(object_id).startswith("ref_"):
                # The signed refund payload is enough to update the child refund transaction.
                tx._process("tap", payload)
            else:
                tx._process("tap", payload)
        except Exception:
            _logger.exception("Error processing Tap webhook %s", object_id)
            return request.make_response("ERROR", status=500)

        return request.make_response("OK", status=200)
