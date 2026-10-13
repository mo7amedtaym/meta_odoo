import secrets
import requests
from urllib.parse import urlencode
from odoo import fields, _, Command
from odoo.exceptions import UserError

class SnapchatProvider:
    AUTH_URL = 'https://accounts.snapchat.com/login/oauth2/authorize'
    TOKEN_URL = 'https://accounts.snapchat.com/login/oauth2/access_token'
    API = 'https://adsapi.snapchat.com/v1'
    SCOPE = 'snapchat-marketing-api'

    def __init__(self, connection):
        self.connection = connection
        self.env = connection.env

    def _config(self, key):
        return self.env['ir.config_parameter'].sudo().get_param('social_ads.snapchat.%s' % key)

    def _base_url(self):
        return (self.env['ir.config_parameter'].sudo().get_param('web.base.url') or '').rstrip('/')

    def get_authorization_action(self):
        client_id = self._config('client_id')
        if not client_id:
            raise UserError(_('Configure Snapchat Client ID first.'))
        state = secrets.token_urlsafe(32)
        icp = self.env['ir.config_parameter'].sudo()
        icp.set_param('social_ads.snapchat.oauth_state.%s' % self.connection.id, state)
        icp.set_param('social_ads.snapchat.oauth_state_time.%s' % self.connection.id, fields.Datetime.to_string(fields.Datetime.now()))
        redirect_uri = self._base_url() + '/social_ads/snapchat/oauth/callback'
        query = urlencode({'client_id':client_id,'redirect_uri':redirect_uri,'response_type':'code','scope':self.SCOPE,
                           'state':'%s:%s' % (self.connection.id, state)})
        return {'type':'ir.actions.act_url','url':'%s?%s' % (self.AUTH_URL, query),'target':'self'}

    def exchange_authorization_code(self, code, redirect_uri):
        data = {'client_id':self._config('client_id'),'client_secret':self._config('client_secret'),'code':code,
                'grant_type':'authorization_code','redirect_uri':redirect_uri}
        resp = requests.post(self.TOKEN_URL, data=data, timeout=25)
        payload = resp.json() if resp.content else {}
        if not resp.ok or not payload.get('access_token'):
            raise UserError(_('Snapchat OAuth token exchange failed.'))
        self.connection.set_tokens(payload['access_token'], payload.get('refresh_token'), payload.get('expires_in'))
        return payload

    def _request(self, method, path, **kwargs):
        token = self.connection.get_access_token()
        if not token:
            raise UserError(_('Snapchat connection has no access token.'))
        headers = dict(kwargs.pop('headers', {}) or {})
        headers['Authorization'] = 'Bearer %s' % token
        headers.setdefault('Content-Type','application/json')
        resp = requests.request(method, self.API + path, headers=headers, timeout=30, **kwargs)
        if resp.status_code in (401,403):
            self.connection.write({'connection_status':'reauthorization_required','last_health_check_at':fields.Datetime.now(),
                                   'last_error_code':str(resp.status_code),'last_error_message':'Snapchat authorization rejected.'})
            raise UserError(_('Snapchat authorization needs to be renewed.'))
        if not resp.ok:
            raise UserError(_('Snapchat API error HTTP %s') % resp.status_code)
        return resp.json() if resp.content else {}

    def check_connection_health(self):
        data = self._request('GET','/me/organizations')
        self.connection.write({'connection_status':'connected','last_health_check_at':fields.Datetime.now(),
                               'last_success_at':fields.Datetime.now(),'last_error_code':False,'last_error_message':False})
        return data

    def sync_ad_accounts(self):
        # /me/organizations is the standard Marketing API discovery flow; adaccounts are nested/fetched per org.
        orgs = self._request('GET','/me/organizations').get('organizations', [])
        count = 0
        Account = self.env['social.ads.account'].sudo()
        for wrapper in orgs:
            org = wrapper.get('organization', wrapper)
            oid = org.get('id')
            if not oid:
                continue
            accounts = self._request('GET','/organizations/%s/adaccounts' % oid).get('adaccounts', [])
            for aw in accounts:
                account = aw.get('adaccount', aw)
                ext = account.get('id')
                if not ext:
                    continue
                vals = {'connection_id':self.connection.id,'external_id':ext,'name':account.get('name') or ext,
                        'currency':account.get('currency'),'timezone':account.get('timezone'),'status':account.get('status'),
                        'raw_data':account}
                rec = Account.search([('connection_id','=',self.connection.id),('external_id','=',ext)], limit=1)
                rec.write(vals) if rec else Account.create(vals)
                count += 1
        return count

    def sync_lead_forms(self, ad_account):
        data = self._request('GET','/adaccounts/%s/lead_generation_forms' % ad_account.external_id)
        forms = data.get('lead_generation_forms', [])
        Form = self.env['social.lead.form'].sudo()
        count = 0
        for wrapper in forms:
            f = wrapper.get('lead_generation_form', wrapper)
            ext = f.get('id')
            if not ext:
                continue
            vals = {'provider':'snapchat','connection_id':self.connection.id,'ad_account_id':ad_account.id,
                    'external_form_id':ext,'name':f.get('name') or f.get('title') or ext,'status':f.get('status') or 'ACTIVE',
                    'questions_json':f.get('form_fields') or [],'privacy_policy_url':f.get('privacy_policy_url'),
                    'last_sync_at':fields.Datetime.now()}
            rec = Form.search([('provider','=','snapchat'),('external_form_id','=',ext)], limit=1)
            rec.write(vals) if rec else None
            rec = rec or Form.create(vals)
            rec._import_mapping_candidates(f.get('form_fields') or [])
            count += 1
        return count

    def _integration_list(self, form):
        return self._request('GET','/lead_gen/forms/%s/integrations?partner_type=PUBLIC_WEBHOOK' % form.external_form_id).get('partnerIntegrations', [])

    def register_webhook(self, form):
        existing = self._integration_list(form)
        base_url = self._base_url()
        webhook_url = base_url + '/social_ads/snapchat/webhook'
        if existing:
            ours = [x for x in existing if (x.get('genericWebhookHandlerInfo') or {}).get('webhookUrl') == webhook_url]
            if ours:
                form.write({'webhook_status':'active','webhook_integration_id':ours[0].get('integrationId'),'webhook_url':webhook_url})
                return ours[0]
            form.write({'webhook_status':'external','last_error':'Another public webhook already owns this Snapchat form.'})
            raise UserError(_('This Snapchat form already has a public webhook integration. It will not be replaced automatically.'))
        payload = {'webhook_integrations':[{'form_id':form.external_form_id,'webhook_url':webhook_url}]}
        data = self._request('POST','/lead_gen/integrations/public_webhook', json=payload)
        rows = data.get('webhookIntegrations') or []
        integ = (rows[0].get('webhookIntegration') if rows else None) or {}
        if not integ.get('integrationId') or not integ.get('hmacSecret'):
            raise UserError(_('Snapchat did not return a webhook integration ID/HMAC secret.'))
        form.write({'webhook_status':'active','webhook_integration_id':integ['integrationId'],
                    'webhook_secret_encrypted':form._encrypt_secret(integ['hmacSecret']),'webhook_url':webhook_url,'last_error':False})
        return integ

    def delete_webhook(self, form):
        if not form.webhook_integration_id:
            return True
        self._request('DELETE','/lead_gen/integrations/%s' % form.webhook_integration_id)
        form.write({'webhook_status':'not_registered','webhook_integration_id':False,'webhook_secret_encrypted':False,'webhook_url':False})
        return True

    def send_test_lead(self, form):
        if form.webhook_status != 'active' or not form.webhook_integration_id:
            raise UserError(_('Register the Snapchat webhook before sending a test lead.'))
        from datetime import timedelta
        form.test_pending_until = fields.Datetime.now() + timedelta(minutes=10)
        return self._request('GET','/lead_gen/integrations/%s/test' % form.webhook_integration_id)
