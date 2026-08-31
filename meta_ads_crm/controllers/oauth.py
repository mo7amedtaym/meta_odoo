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
        code = kw.get('code')
        if not code:
            _logger.warning('Meta OAuth callback without code: %s', kw)
            return request.redirect(self._settings_action_url())

        icp = request.env['ir.config_parameter'].sudo()
        app_id = icp.get_param('meta.app.id')
        app_secret = icp.get_param('meta.app.secret')
        base_url = self._get_public_base_url(icp)
        redirect_uri = '%s/meta/oauth/callback' % base_url
        graph_version = self._get_graph_version(icp)

        if not app_id or not app_secret or not base_url:
            return request.redirect(self._settings_action_url())

        try:
            short_token = self._exchange_code_for_token(
                app_id, app_secret, redirect_uri, code, graph_version
            )
            long_token, expiry = self._exchange_for_long_lived_token(
                app_id, app_secret, short_token, graph_version
            )
        except Exception as e:
            _logger.exception('Meta OAuth token exchange failed: %s', e)
            return request.redirect(self._settings_action_url())

        icp.set_param('meta.long_lived_token', long_token)
        if expiry:
            icp.set_param('meta.token_expiry', expiry)

        try:
            self._fetch_and_store_pages(long_token, graph_version)
        except Exception as e:
            _logger.exception('Meta OAuth: page fetch failed: %s', e)

        return request.redirect(self._settings_action_url())

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
        env = request.env(su=True)
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

            existing = env['meta.page'].search([('page_id', '=', meta_page_id)], limit=1)
            if existing:
                existing.write(vals)
            else:
                env['meta.page'].create(vals)
