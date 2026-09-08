from urllib.parse import urlencode

from odoo import models, fields, api
from odoo.exceptions import UserError


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    meta_app_id = fields.Char(
        string='Meta App ID',
        config_parameter='meta.app.id'
    )
    meta_app_secret = fields.Char(
        string='Meta App Secret',
        config_parameter='meta.app.secret'
    )
    meta_webhook_verify_token = fields.Char(
        string='Webhook Verify Token',
        config_parameter='meta.webhook.verify_token'
    )
    meta_public_base_url = fields.Char(
        string='Public Base URL',
        config_parameter='meta.public.base.url',
        help='Public HTTPS URL of this Odoo instance, e.g. https://testmeta.o.cm.sa',
    )
    meta_webhook_url = fields.Char(
        string='Webhook Callback URL',
        compute='_compute_meta_webhook_url',
        readonly=True
    )
    meta_oauth_redirect_url = fields.Char(
        string='OAuth Redirect URL',
        compute='_compute_meta_webhook_url',
        readonly=True
    )
    meta_fernet_key = fields.Char(
        string='Fernet Encryption Key',
        config_parameter='meta.fernet_key'
    )
    meta_long_lived_token = fields.Char(
        string='Long-Lived User Token',
        config_parameter='meta.long_lived_token'
    )
    meta_token_expiry = fields.Datetime(
        string='Token Expiry',
        config_parameter='meta.token_expiry'
    )
    meta_connected = fields.Boolean(
        string='Connected',
        compute='_compute_meta_connected'
    )
    meta_oauth_last_status = fields.Char(
        string='Last OAuth Status',
        compute='_compute_meta_oauth_diagnostics',
        readonly=True,
    )
    meta_oauth_last_error = fields.Text(
        string='Last OAuth Error',
        compute='_compute_meta_oauth_diagnostics',
        readonly=True,
    )
    meta_graph_version = fields.Char(
        string='Graph API Version',
        config_parameter='meta.graph_version',
        default='v26.0'
    )
    meta_request_pages_manage_metadata = fields.Boolean(
        string='Request pages_manage_metadata',
        config_parameter='meta.oauth.request_pages_manage_metadata',
        default=True,
        help='Keep enabled when the Meta app is allowed to request pages_manage_metadata. Disable it only when Meta rejects this permission during OAuth; the permission remains fully supported by the module and can be re-enabled later without a code update.',
    )
    meta_effective_oauth_scopes = fields.Char(
        string='OAuth Scopes Used',
        compute='_compute_meta_effective_oauth_scopes',
        readonly=True,
    )
    meta_connection_status = fields.Char(
        string='Connection Status',
        compute='_compute_meta_connection_health',
        readonly=True,
    )
    meta_active_page_count = fields.Integer(
        string='Active Meta Pages',
        compute='_compute_meta_connection_health',
        readonly=True,
    )
    meta_webhook_last_received_at = fields.Datetime(
        string='Last Webhook Received',
        compute='_compute_meta_runtime_status',
        readonly=True,
    )
    meta_webhook_last_lead_at = fields.Datetime(
        string='Last Leadgen Event',
        compute='_compute_meta_runtime_status',
        readonly=True,
    )
    meta_recovery_enabled = fields.Boolean(
        string='Automatic Missing Leads Recovery',
        config_parameter='meta.recovery.enabled',
        default=True,
        help='Periodically pull recent leads from Meta Lead Forms to recover any lead missed by the webhook.',
    )
    meta_recovery_lookback_days = fields.Integer(
        string='Initial Recovery Lookback (Days)',
        config_parameter='meta.recovery.lookback_days',
        default=7,
        help='When a form has never been recovered before, scan this many days back. Subsequent runs overlap the previous recovery window.',
    )
    meta_recovery_last_run_at = fields.Datetime(
        string='Last Recovery Run',
        compute='_compute_meta_runtime_status',
        readonly=True,
    )

    def _get_meta_public_base_url(self):
        icp = self.env['ir.config_parameter'].sudo()
        base_url = (icp.get_param('meta.public.base.url') or icp.get_param('web.base.url') or '').strip()
        base_url = base_url.rstrip('/')
        # Odoo is commonly behind an HTTPS reverse proxy while web.base.url may be HTTP.
        # For public non-local hosts, Meta requires HTTPS, so normalize the public URL.
        if base_url.startswith('http://'):
            host = base_url[7:].split('/', 1)[0].split(':', 1)[0].lower()
            if host not in ('localhost', '127.0.0.1', '0.0.0.0'):
                base_url = 'https://' + base_url[7:]
        return base_url

    def _compute_meta_webhook_url(self):
        for record in self:
            base_url = record._get_meta_public_base_url()
            record.meta_webhook_url = '%s/meta/webhook' % base_url if base_url else False
            record.meta_oauth_redirect_url = '%s/meta/oauth/callback' % base_url if base_url else False

    def _compute_meta_connected(self):
        icp = self.env['ir.config_parameter'].sudo()
        has_user_token = bool(icp.get_param('meta.long_lived_token'))
        has_page_token = bool(self.env['meta.page'].sudo().search_count([
            ('active', '=', True),
            ('access_token_encrypted', '!=', False),
        ]))
        for record in self:
            # A valid stored Page token is enough for lead retrieval/recovery even
            # if the user OAuth token has expired or was cleared.
            record.meta_connected = has_user_token or has_page_token

    def _compute_meta_connection_health(self):
        icp = self.env['ir.config_parameter'].sudo()
        has_user_token = bool(icp.get_param('meta.long_lived_token'))
        pages = self.env['meta.page'].sudo().search([
            ('active', '=', True),
            ('access_token_encrypted', '!=', False),
        ])
        page_count = len(pages)
        if has_user_token and page_count:
            status = 'Connected: user OAuth token + %s active Page token(s)' % page_count
        elif page_count:
            status = 'Operational via %s Page token(s); user OAuth token is missing/expired. Reconnect when possible.' % page_count
        elif has_user_token:
            status = 'User OAuth token exists, but no active Page tokens are stored. Reconnect or import Pages.'
        else:
            status = 'Not connected: no user token and no active Page token.'
        for record in self:
            record.meta_connection_status = status
            record.meta_active_page_count = page_count

    def _compute_meta_runtime_status(self):
        icp = self.env['ir.config_parameter'].sudo()
        def parse_dt(key):
            value = icp.get_param(key) or False
            if not value:
                return False
            try:
                return fields.Datetime.to_datetime(value)
            except Exception:
                return False
        last_webhook = parse_dt('meta.webhook.last_received_at')
        last_lead = parse_dt('meta.webhook.last_lead_at')
        last_recovery = parse_dt('meta.recovery.last_run_at')
        for record in self:
            record.meta_webhook_last_received_at = last_webhook
            record.meta_webhook_last_lead_at = last_lead
            record.meta_recovery_last_run_at = last_recovery

    def action_run_meta_recovery_now(self):
        self.ensure_one()
        result = self.env['meta.lead.form'].sudo()._cron_recover_missing_leads(force=True)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Meta Leads Recovery',
                'message': result or 'Recovery completed.',
                'type': 'success',
                'sticky': True,
            },
        }

    def _compute_meta_oauth_diagnostics(self):
        icp = self.env['ir.config_parameter'].sudo()
        status = icp.get_param('meta.oauth.last_status') or ''
        error = icp.get_param('meta.oauth.last_error') or ''
        for record in self:
            record.meta_oauth_last_status = status
            record.meta_oauth_last_error = error

    def _get_meta_oauth_scopes(self):
        scopes = [
            'leads_retrieval',
            'pages_show_list',
            'pages_read_engagement',
            'pages_manage_ads',
            'ads_management',
        ]
        if self.meta_request_pages_manage_metadata:
            scopes.insert(3, 'pages_manage_metadata')
        return scopes

    def _compute_meta_effective_oauth_scopes(self):
        for record in self:
            record.meta_effective_oauth_scopes = ', '.join(record._get_meta_oauth_scopes())

    def action_generate_fernet_key(self):
        icp = self.env['ir.config_parameter'].sudo()
        if icp.get_param('meta.fernet_key'):
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Encryption Key',
                    'message': 'An encryption key already exists. It was not replaced to avoid invalidating stored Page tokens.',
                    'type': 'info',
                    'sticky': False,
                },
            }
        try:
            from cryptography.fernet import Fernet
            key = Fernet.generate_key().decode()
            icp.set_param('meta.fernet_key', key)
        except ImportError:
            raise UserError('The cryptography package is not installed. Run: pip install cryptography')
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Encryption Key',
                'message': 'Encryption key generated successfully.',
                'type': 'success',
                'sticky': False,
            },
        }

    def action_connect_meta(self):
        """Redirect to Meta OAuth dialog using the configured public HTTPS URL."""
        self.ensure_one()
        if not self.meta_app_id:
            raise UserError('Please enter your Meta App ID first.')
        if not self.meta_app_secret:
            raise UserError('Please enter your Meta App Secret first.')

        icp = self.env['ir.config_parameter'].sudo()
        icp.set_param('meta.oauth.last_status', 'Connecting')
        icp.set_param('meta.oauth.last_error', '')

        # Page access tokens are encrypted locally. Ensure the encryption key
        # exists before OAuth so page tokens are never imported unencrypted.
        if not icp.get_param('meta.fernet_key'):
            try:
                from cryptography.fernet import Fernet
                icp.set_param('meta.fernet_key', Fernet.generate_key().decode())
            except ImportError:
                raise UserError('The cryptography package is not installed. Run: pip install cryptography')

        base_url = self._get_meta_public_base_url()
        if not base_url:
            raise UserError('Please configure the Public Base URL first.')
        if not base_url.startswith('https://'):
            raise UserError('Meta OAuth requires a public HTTPS URL. Please configure Public Base URL with https://')

        redirect_uri = '%s/meta/oauth/callback' % base_url
        graph_version = (self.meta_graph_version or 'v26.0').strip()
        if not graph_version.startswith('v'):
            graph_version = 'v%s' % graph_version

        scopes = ','.join(self._get_meta_oauth_scopes())
        icp.set_param('meta.oauth.last_requested_scopes', scopes)
        params = urlencode({
            'client_id': self.meta_app_id,
            'redirect_uri': redirect_uri,
            'scope': scopes,
            'response_type': 'code',
        })
        auth_url = 'https://www.facebook.com/%s/dialog/oauth?%s' % (graph_version, params)

        return {
            'type': 'ir.actions.act_url',
            'url': auth_url,
            'target': 'new',
        }

    def action_disconnect_meta(self):
        """Clear stored token."""
        icp = self.env['ir.config_parameter'].sudo()
        icp.set_param('meta.long_lived_token', '')
        icp.set_param('meta.token_expiry', '')
        icp.set_param('meta.oauth.last_status', 'Disconnected')
        icp.set_param('meta.oauth.last_error', '')
        self.env['meta.page'].search([]).write({
            'active': False,
            'access_token_encrypted': False,
            'webhook_subscribed': False,
        })
