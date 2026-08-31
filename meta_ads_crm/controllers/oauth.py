import logging

import requests

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class MetaOAuthController(http.Controller):

    @http.route('/meta/oauth/callback', type='http', auth='user')
    def oauth_callback(self, **kw):
        """Handle OAuth callback from Meta after user authorization."""
        code = kw.get('code')
        if not code:
            return request.redirect('/web#action=meta_ads_crm_connector.meta_config_settings_action')

        icp = request.env['ir.config_parameter'].sudo()
        app_id = icp.get_param('meta.app.id')
        app_secret = icp.get_param('meta.app.secret')
        base_url = icp.get_param('web.base.url')
        redirect_uri = '%s/meta/oauth/callback' % base_url

        if not app_id or not app_secret:
            return request.redirect('/web#action=meta_ads_crm_connector.meta_config_settings_action')

        # Step 1: Exchange code for short-lived user token
        try:
            short_token = self._exchange_code_for_token(app_id, app_secret, redirect_uri, code)
        except Exception as e:
            _logger.error('Meta OAuth: code exchange failed: %s', e)
            return request.redirect('/web#action=meta_ads_crm_connector.meta_config_settings_action')

        # Step 2: Exchange for long-lived user token
        try:
            long_token, expiry = self._exchange_for_long_lived_token(app_id, app_secret, short_token)
        except Exception as e:
            _logger.error('Meta OAuth: long-lived token exchange failed: %s', e)
            return request.redirect('/web#action=meta_ads_crm_connector.meta_config_settings_action')

        # Step 3: Store the token
        icp.set_param('meta.long_lived_token', long_token)
        if expiry:
            icp.set_param('meta.token_expiry', expiry)

        # Step 4: Fetch and store pages with their tokens
        try:
            self._fetch_and_store_pages(long_token)
        except Exception as e:
            _logger.warning('Meta OAuth: page fetch failed: %s', e)

        return request.redirect('/web#action=meta_ads_crm_connector.meta_config_settings_action')

    def _exchange_code_for_token(self, app_id, app_secret, redirect_uri, code):
        """Exchange authorization code for short-lived user token."""
        url = 'https://graph.facebook.com/v21.0/oauth/access_token'
        resp = requests.get(url, params={
            'client_id': app_id,
            'client_secret': app_secret,
            'redirect_uri': redirect_uri,
            'code': code,
        }, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return data['access_token']

    def _exchange_for_long_lived_token(self, app_id, app_secret, short_token):
        """Exchange short-lived token for long-lived token (≈60 days)."""
        url = 'https://graph.facebook.com/v21.0/oauth/access_token'
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
        # Calculate expiry datetime
        from datetime import datetime, timedelta
        expiry = False
        if expires_in:
            expiry_dt = datetime.utcnow() + timedelta(seconds=int(expires_in))
            expiry = expiry_dt.strftime('%Y-%m-%d %H:%M:%S')
        return token, expiry

    def _fetch_and_store_pages(self, user_token):
        """Fetch Facebook Pages the user manages and store them with page tokens."""
        env = request.env(su=True)
        url = 'https://graph.facebook.com/v21.0/me/accounts'
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

            # Encrypt the page token
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
            }

            existing = env['meta.page'].search([('page_id', '=', meta_page_id)], limit=1)
            if existing:
                existing.write(vals)
            else:
                env['meta.page'].create(vals)
