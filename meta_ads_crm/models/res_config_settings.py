from urllib.parse import urlencode

from odoo import models, fields
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
    meta_graph_version = fields.Char(
        string='Graph API Version',
        config_parameter='meta.graph_version',
        default='v26.0'
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
        for record in self:
            token = self.env['ir.config_parameter'].sudo().get_param('meta.long_lived_token')
            record.meta_connected = bool(token)

    def action_generate_fernet_key(self):
        try:
            from cryptography.fernet import Fernet
            key = Fernet.generate_key().decode()
            self.env['ir.config_parameter'].sudo().set_param('meta.fernet_key', key)
        except ImportError:
            raise UserError('The cryptography package is not installed. Run: pip install cryptography')

    def action_connect_meta(self):
        """Redirect to Meta OAuth dialog using the configured public HTTPS URL."""
        self.ensure_one()
        if not self.meta_app_id:
            raise UserError('Please enter your Meta App ID first.')

        base_url = self._get_meta_public_base_url()
        if not base_url:
            raise UserError('Please configure the Public Base URL first.')
        if not base_url.startswith('https://'):
            raise UserError('Meta OAuth requires a public HTTPS URL. Please configure Public Base URL with https://')

        redirect_uri = '%s/meta/oauth/callback' % base_url
        graph_version = (self.meta_graph_version or 'v26.0').strip()
        if not graph_version.startswith('v'):
            graph_version = 'v%s' % graph_version

        scopes = ','.join([
            'leads_retrieval',
            'pages_show_list',
            'pages_read_engagement',
            'pages_manage_metadata',
            'ads_management',
        ])
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
        self.env['ir.config_parameter'].sudo().set_param('meta.long_lived_token', '')
        self.env['ir.config_parameter'].sudo().set_param('meta.token_expiry', '')
        self.env['meta.page'].search([]).write({'active': False})
