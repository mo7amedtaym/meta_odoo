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
    meta_webhook_url = fields.Char(
        string='Webhook Callback URL',
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
        default='v21.0'
    )

    def _compute_meta_webhook_url(self):
        for record in self:
            base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
            record.meta_webhook_url = '%s/meta/webhook' % base_url

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
        """Redirect to Meta OAuth dialog."""
        if not self.meta_app_id:
            raise UserError('Please enter your Meta App ID first.')

        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        redirect_uri = '%s/meta/oauth/callback' % base_url
        scopes = ','.join([
            'leads_retrieval',
            'pages_show_list',
            'pages_read_engagement',
            'ads_management',
            'pages_manage_metadata',
        ])
        auth_url = (
            'https://www.facebook.com/v21.0/dialog/oauth'
            '?client_id=%s'
            '&redirect_uri=%s'
            '&scope=%s'
            '&response_type=code'
        ) % (self.meta_app_id, redirect_uri, scopes)

        return {
            'type': 'ir.actions.act_url',
            'url': auth_url,
            'target': 'new',
        }

    def action_disconnect_meta(self):
        """Clear stored token."""
        self.env['ir.config_parameter'].sudo().set_param('meta.long_lived_token', '')
        self.env['ir.config_parameter'].sudo().set_param('meta.token_expiry', '')
        # Archive all pages (tokens invalid)
        self.env['meta.page'].search([]).write({'active': False})
