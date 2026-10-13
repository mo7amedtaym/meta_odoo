import json
import logging
from odoo import http, fields
from psycopg2 import IntegrityError
from odoo.http import request
from ..lib.snapchat import verify_signature, timestamp_is_fresh, normalize_payload

_logger = logging.getLogger(__name__)

class SnapchatWebhookController(http.Controller):
    @http.route('/social_ads/snapchat/webhook', type='http', auth='public', methods=['POST'], csrf=False)
    def webhook(self, **kw):
        raw = request.httprequest.get_data(cache=True) or b''
        try:
            payload = json.loads(raw.decode('utf-8'))
        except Exception:
            return request.make_json_response({'status':'error','message':'Invalid JSON'}, status=400)
        form_ext = str(payload.get('form_id') or '')
        Form = request.env['social.lead.form'].sudo()
        form = Form.search([('provider','=','snapchat'),('external_form_id','=',form_ext),('webhook_status','=','active')], limit=1)
        timestamp = request.httprequest.headers.get('t')
        signature = request.httprequest.headers.get('Signature')
        tolerance = int(request.env['ir.config_parameter'].sudo().get_param('social_ads.snapchat.signature_tolerance') or 300)
        if not timestamp_is_fresh(timestamp, tolerance=tolerance):
            return request.make_json_response({'status':'error','message':'Stale webhook'}, status=403)
        # Snap's /test endpoint intentionally sends dummy form/account IDs. If the form ID
        # is unknown, only accept it when exactly one recently-requested test form validates
        # the HMAC. This keeps the test flow secure without trusting the dummy identifiers.
        candidates = form or Form.search([('provider','=','snapchat'),('webhook_status','=','active'),
                                          ('test_pending_until','>=',fields.Datetime.now())])
        matched = candidates.filtered(lambda f: verify_signature(timestamp, raw, f._decrypt_secret(f.webhook_secret_encrypted), signature))
        if len(matched) != 1:
            _logger.warning('Snapchat webhook rejected: no unique HMAC-matched form for %s', form_ext)
            return request.make_json_response({'status':'error','message':'Invalid signature/form'}, status=403)
        form = matched[0]
        if form.test_pending_until:
            form.test_pending_until = False
        normalized = normalize_payload(payload)
        lead_id = normalized.get('external_lead_id')
        if not lead_id:
            return request.make_json_response({'status':'error','message':'Missing lead_id'}, status=400)
        Log = request.env['social.lead.log'].sudo()
        log = Log.search([('provider','=','snapchat'),('external_lead_id','=',lead_id)], limit=1)
        if log:
            return request.make_json_response({'status':'success','duplicate':True})
        account = request.env['social.ads.account'].sudo().search([('connection_id','=',form.connection_id.id),('external_id','=',normalized.get('external_ad_account_id'))], limit=1)
        vals = {'provider':'snapchat','external_lead_id':lead_id,'form_id':form.id,'ad_account_id':account.id if account else False,
                'external_campaign_id':normalized.get('external_campaign_id'),'campaign_name':normalized.get('campaign_name'),
                'external_adgroup_id':normalized.get('external_adgroup_id'),'adgroup_name':normalized.get('adgroup_name'),
                'external_ad_id':normalized.get('external_ad_id'),'ad_name':normalized.get('ad_name'),
                'payload_json':payload,'normalized_json':normalized,'status':'pending'}
        try:
            with request.env.cr.savepoint():
                log = Log.create(vals)
        except IntegrityError:
            log = Log.search([('provider','=','snapchat'),('external_lead_id','=',lead_id)], limit=1)
            return request.make_json_response({'status':'success','duplicate':True})
        try:
            log._process_normalized_lead(normalized)
        except Exception as exc:
            _logger.exception('Snapchat lead accepted but CRM processing failed for %s', lead_id)
            log._mark_retryable_error('crm_processing', exc)
        return request.make_json_response({'status':'success'})
