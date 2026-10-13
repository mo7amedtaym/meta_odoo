from datetime import timedelta
from odoo import http, fields
from odoo.http import request

class SnapchatOAuthController(http.Controller):
    @http.route('/social_ads/snapchat/oauth/callback', type='http', auth='user', methods=['GET'], csrf=False)
    def callback(self, code=None, state=None, error=None, **kw):
        if error or not code or not state or ':' not in state:
            return request.redirect('/web#action=social_ads_crm.action_social_connection')
        sid, provided = state.split(':', 1)
        try:
            cid = int(sid)
        except ValueError:
            return request.make_response('Invalid OAuth state', status=400)
        conn = request.env['social.ads.connection'].sudo().browse(cid).exists()
        if not conn or conn.provider != 'snapchat':
            return request.make_response('Invalid OAuth connection', status=400)
        icp = request.env['ir.config_parameter'].sudo()
        expected = icp.get_param('social_ads.snapchat.oauth_state.%s' % cid)
        created_raw = icp.get_param('social_ads.snapchat.oauth_state_time.%s' % cid)
        icp.set_param('social_ads.snapchat.oauth_state.%s' % cid, '')
        icp.set_param('social_ads.snapchat.oauth_state_time.%s' % cid, '')
        try:
            created = fields.Datetime.to_datetime(created_raw)
        except Exception:
            created = False
        if not expected or provided != expected or not created or fields.Datetime.now() - created > timedelta(minutes=10):
            return request.make_response('OAuth state expired or invalid', status=403)
        redirect_uri = (icp.get_param('web.base.url') or '').rstrip('/') + '/social_ads/snapchat/oauth/callback'
        conn._get_provider_service().exchange_authorization_code(code, redirect_uri)
        conn._get_provider_service().sync_ad_accounts()
        return request.redirect('/web#action=social_ads_crm.action_social_connection')
