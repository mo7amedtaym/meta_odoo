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
            return request.make_response(kw.get('hub.challenge', ''), headers=[('Content-Type', 'text/plain')])

        _logger.warning('Meta webhook verification failed')
        return request.make_response('Verification failed', status=403)

    @http.route('/meta/webhook', type='http', auth='public', methods=['POST'], csrf=False)
    def incoming_webhook(self, **kw):
        """Receive standard Meta JSON webhook payloads over HTTP."""
        raw_payload = request.httprequest.get_data(cache=True) or b''
        app_secret = request.env['ir.config_parameter'].sudo().get_param('meta.app.secret')
        signature = request.httprequest.headers.get('X-Hub-Signature-256', '')

        if app_secret and signature:
            expected_sig = hmac.new(app_secret.encode(), raw_payload, hashlib.sha256).hexdigest()
            if not hmac.compare_digest('sha256=%s' % expected_sig, signature):
                _logger.warning('Meta webhook: invalid signature')
                return request.make_json_response({'status': 'error', 'message': 'Invalid signature'}, status=403)

        try:
            data = json.loads(raw_payload.decode('utf-8') or '{}')
        except (ValueError, UnicodeDecodeError):
            _logger.warning('Meta webhook: invalid JSON payload')
            return request.make_json_response({'status': 'error', 'message': 'Invalid JSON'}, status=400)

        if data.get('object') != 'page':
            return request.make_json_response({'status': 'success'})

        env = request.env(su=True)
        for entry in data.get('entry', []):
            for change in entry.get('changes', []):
                if change.get('field') != 'leadgen':
                    continue

                val = change.get('value', {}) or {}
                leadgen_id = val.get('leadgen_id')
                form_id_raw = val.get('form_id')
                page_id_raw = val.get('page_id') or entry.get('id')
                ad_id = val.get('ad_id')
                # Meta may provide adgroup_id; keep it as campaign tracking value for backward compatibility.
                campaign_id = val.get('campaign_id') or val.get('adgroup_id')

                if not leadgen_id:
                    continue

                existing_log = env['meta.lead.log'].search([
                    ('leadgen_id', '=', str(leadgen_id))
                ], limit=1)
                if existing_log:
                    _logger.info('Meta webhook: leadgen %s already logged, skipping', leadgen_id)
                    continue

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

                try:
                    log._process_lead()
                except Exception as e:
                    _logger.exception(
                        'Meta webhook: real-time processing failed for %s: %s',
                        leadgen_id, e
                    )

        return request.make_json_response({'status': 'success'})
