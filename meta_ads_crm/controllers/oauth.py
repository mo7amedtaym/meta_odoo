import logging

import requests

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class MetaOAuthController(http.Controller):

    def _settings_action_url(self):
        # Current technical module name is meta_ads_crm.
        return '/web#action=meta_ads_crm.meta_config_settings_action'

    def _get_public_base_url(self, icp):
        base_url = (icp.get_param('meta.public.base.url') or icp.get_param('web.base.url') or '').strip().rstrip('/')
        if base_url.startswith('http://'):
            host = base_url[7:].split('/', 1)[0].split(':', 1)[0].lower()
            if host not in ('localhost', '127.0.0.1', '0.0.0.0'):
                base_url = 'https://' + base_url[7:]
        return base_url

    def _get_graph_version(self, icp):
        version = (icp.get_param('meta.graph_version') or 'v26.0').strip()
        return version if version.startswith('v') else 'v%s' % version

    @http.route('/meta/oauth/callback', type='http', auth='user', methods=['GET'], csrf=False)
    def oauth_callback(self, **kw):
        """Handle OAuth callback from Meta after user authorization."""
        icp = request.env['ir.config_parameter'].sudo()

        oauth_error = kw.get('error')
        if oauth_error:
            description = kw.get('error_description') or kw.get('error_message') or oauth_error
            icp.set_param('meta.oauth.last_status', 'Failed')
            icp.set_param('meta.oauth.last_error', str(description)[:2000])
            _logger.warning('Meta OAuth returned an error: %s', description)
            return request.redirect(self._settings_action_url())

        code = kw.get('code')
        if not code:
            msg = 'Meta returned to Odoo without an authorization code.'
            icp.set_param('meta.oauth.last_status', 'Failed')
            icp.set_param('meta.oauth.last_error', msg)
            _logger.warning('Meta OAuth callback without code: %s', {k: v for k, v in kw.items() if k != 'code'})
            return request.redirect(self._settings_action_url())

        app_id = icp.get_param('meta.app.id')
        app_secret = icp.get_param('meta.app.secret')
        base_url = self._get_public_base_url(icp)
        redirect_uri = '%s/meta/oauth/callback' % base_url
        graph_version = self._get_graph_version(icp)

        if not app_id or not app_secret or not base_url:
            msg = 'Meta App ID, App Secret, or Public Base URL is missing in Odoo settings.'
            icp.set_param('meta.oauth.last_status', 'Failed')
            icp.set_param('meta.oauth.last_error', msg)
            return request.redirect(self._settings_action_url())

        try:
            short_token = self._exchange_code_for_token(
                app_id, app_secret, redirect_uri, code, graph_version
            )
        except Exception as e:
            msg = self._safe_request_error(e)
            icp.set_param('meta.oauth.last_status', 'Failed - token exchange')
            icp.set_param('meta.oauth.last_error', msg)
            _logger.exception('Meta OAuth short token exchange failed: %s', msg)
            return request.redirect(self._settings_action_url())

        token_to_store = short_token
        expiry = False
        try:
            long_token, expiry = self._exchange_for_long_lived_token(
                app_id, app_secret, short_token, graph_version
            )
            if long_token:
                token_to_store = long_token
        except Exception as e:
            msg = self._safe_request_error(e)
            _logger.warning('Meta long-lived token exchange failed; using short-lived token: %s', msg)
            icp.set_param('meta.oauth.last_error', 'Connected with short-lived token. Long-lived exchange failed: %s' % msg)

        icp.set_param('meta.long_lived_token', token_to_store)
        if expiry:
            icp.set_param('meta.token_expiry', expiry)
        else:
            icp.set_param('meta.token_expiry', '')

        pages_count = 0
        try:
            pages_count = self._fetch_and_store_pages(token_to_store, graph_version) or 0
        except Exception as e:
            msg = self._safe_request_error(e)
            _logger.exception('Meta OAuth: page fetch failed: %s', msg)
            existing = icp.get_param('meta.oauth.last_error') or ''
            icp.set_param('meta.oauth.last_error', (existing + ('\n' if existing else '') + 'Page import failed: ' + msg)[:4000])

        icp.set_param('meta.oauth.last_status', 'Connected (%s page(s) imported)' % pages_count)
        return request.redirect(self._settings_action_url())

    def _safe_request_error(self, exc):
        """Return Meta error details without leaking access tokens or secrets."""
        response = getattr(exc, 'response', None)
        if response is not None:
            try:
                data = response.json()
                error = data.get('error') or {}
                parts = []
                if error.get('message'):
                    parts.append(str(error.get('message')))
                if error.get('type'):
                    parts.append('type=%s' % error.get('type'))
                if error.get('code') is not None:
                    parts.append('code=%s' % error.get('code'))
                if error.get('error_subcode') is not None:
                    parts.append('subcode=%s' % error.get('error_subcode'))
                if error.get('fbtrace_id'):
                    parts.append('fbtrace_id=%s' % error.get('fbtrace_id'))
                if parts:
                    return ' | '.join(parts)[:2000]
            except Exception:
                pass
            return 'HTTP %s from Meta API' % getattr(response, 'status_code', 'error')
        return str(exc)[:2000]

    def _exchange_code_for_token(self, app_id, app_secret, redirect_uri, code, graph_version):
        url = 'https://graph.facebook.com/%s/oauth/access_token' % graph_version
        resp = requests.get(url, params={
            'client_id': app_id,
            'client_secret': app_secret,
            'redirect_uri': redirect_uri,
            'code': code,
        }, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return data['access_token']

    def _exchange_for_long_lived_token(self, app_id, app_secret, short_token, graph_version):
        url = 'https://graph.facebook.com/%s/oauth/access_token' % graph_version
        resp = requests.get(url, params={
            'grant_type': 'fb_exchange_token',
            'client_id': app_id,
            'client_secret': app_secret,
            'fb_exchange_token': short_token,
        }, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        token = data.get('access_token', '')
        expires_in = data.get('expires_in', 0)
        from datetime import datetime, timedelta
        expiry = False
        if expires_in:
            expiry_dt = datetime.utcnow() + timedelta(seconds=int(expires_in))
            expiry = expiry_dt.strftime('%Y-%m-%d %H:%M:%S')
        return token, expiry

    def _fetch_and_store_pages(self, user_token, graph_version):
        env = request.env
        url = 'https://graph.facebook.com/%s/me/accounts' % graph_version
        resp = requests.get(url, params={
            'access_token': user_token,
            'fields': 'id,name,category,access_token',
        }, timeout=30)
        resp.raise_for_status()
        pages_data = resp.json().get('data', [])

        fernet_key = env['ir.config_parameter'].sudo().get_param('meta.fernet_key')

        for page_data in pages_data:
            meta_page_id = str(page_data.get('id', ''))
            page_token = page_data.get('access_token', '')

            encrypted_token = ''
            if page_token and fernet_key:
                try:
                    from cryptography.fernet import Fernet
                    fernet = Fernet(fernet_key.encode() if isinstance(fernet_key, str) else fernet_key)
                    encrypted_token = fernet.encrypt(
                        page_token.encode() if isinstance(page_token, str) else page_token
                    ).decode()
                except Exception as e:
                    _logger.warning('Failed to encrypt page token for %s: %s', meta_page_id, e)

            vals = {
                'page_id': meta_page_id,
                'name': page_data.get('name', 'Page %s' % meta_page_id),
                'category': page_data.get('category', ''),
                'access_token_encrypted': encrypted_token,
                'active': True,
            }

            MetaPage = env['meta.page'].sudo()
            existing = MetaPage.search([('page_id', '=', meta_page_id)], limit=1)
            if existing:
                existing.write(vals)
            else:
                MetaPage.create(vals)

        return len(pages_data)
