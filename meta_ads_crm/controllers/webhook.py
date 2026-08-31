import hashlib
import hmac
import json
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class MetaWebhookController(http.Controller):

    @http.route('/meta/webhook', type='http', auth='public', methods=['GET'], csrf=False)
    def verify_webhook(self, **kw):
        """Verify webhook subscription (Meta sends this during setup)."""
        verify_token = request.env['ir.config_parameter'].sudo().get_param('meta.webhook.verify_token')

        if kw.get('hub.mode') == 'subscribe' and kw.get('hub.verify_token') == verify_token:
            _logger.info('Meta webhook verified successfully')
            return kw.get('hub.challenge')

        _logger.warning('Meta webhook verification failed')
        return "Verification failed", 403

    @http.route('/meta/webhook', type='jsonrpc', auth='public', methods=['POST'], csrf=False)
    def incoming_webhook(self, **kw):
        """Receive real-time lead notifications from Meta."""
        # Validate HMAC signature
        app_secret = request.env['ir.config_parameter'].sudo().get_param('meta.app.secret')
        signature = request.httprequest.headers.get('X-Hub-Signature-256', '')

        if app_secret and signature:
            payload = request.httprequest.data
            expected_sig = hmac.new(
                app_secret.encode(), payload, hashlib.sha256
            ).hexdigest()
            if not hmac.compare_digest('sha256=%s' % expected_sig, signature):
                _logger.warning('Meta webhook: invalid signature')
                return {'status': 'error', 'message': 'Invalid signature'}

        data = request.jsonrequest
        if data.get('object') != 'page':
            return {'status': 'success'}

        env = request.env(su=True)
        processed = 0

        for entry in data.get('entry', []):
            for change in entry.get('changes', []):
                if change.get('field') != 'leadgen':
                    continue

                val = change.get('value', {})
                leadgen_id = val.get('leadgen_id')
                form_id_raw = val.get('form_id')
                page_id_raw = val.get('page_id')
                ad_id = val.get('ad_id')
                campaign_id = val.get('adgroup_id')

                if not leadgen_id:
                    continue

                # Deduplicate: skip if already logged
                existing_log = env['meta.lead.log'].search([
                    ('leadgen_id', '=', str(leadgen_id))
                ], limit=1)
                if existing_log:
                    _logger.info('Meta webhook: leadgen %s already logged, skipping', leadgen_id)
                    continue

                # Look up linked records by their char ID fields
                form_record = False
                if form_id_raw:
                    form_record = env['meta.lead.form'].search(
                        [('form_id', '=', str(form_id_raw))], limit=1
                    )

                page_record = False
                if page_id_raw:
                    page_record = env['meta.page'].search(
                        [('page_id', '=', str(page_id_raw))], limit=1
                    )

                # Create log entry
                log_vals = {
                    'leadgen_id': str(leadgen_id),
                    'form_id': form_record.id if form_record else False,
                    'page_id': page_record.id if page_record else False,
                    'ad_id': str(ad_id) if ad_id else False,
                    'campaign_id': str(campaign_id) if campaign_id else False,
                    'platform': 'facebook',
                    'payload_json': val,
                    'status': 'Pending',
                }
                log = env['meta.lead.log'].create(log_vals)

                # Try real-time processing
                try:
                    log._process_lead()
                    processed += 1
                except Exception as e:
                    _logger.warning(
                        'Meta webhook: real-time processing failed for %s: %s',
                        leadgen_id, e
                    )
                    # Cron will retry later

        return {'status': 'success'}
