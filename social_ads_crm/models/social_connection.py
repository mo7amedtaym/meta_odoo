import logging
import requests
from datetime import timedelta
from odoo import api, fields, models, _, Command
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class SocialAdsConnection(models.Model):
    _name = 'social.ads.connection'
    _description = 'Social Ads Connection'
    _inherit = ['mail.thread', 'social.ads.secret.mixin']
    _order = 'provider, name'

    name = fields.Char(required=True, tracking=True)
    provider = fields.Selection([('meta','Meta'),('snapchat','Snapchat')], required=True, index=True, tracking=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    connection_status = fields.Selection([
        ('disconnected','Disconnected'),('connected','Connected'),('warning','Warning'),
        ('reauthorization_required','Reauthorization Required'),('error','Error')
    ], default='disconnected', tracking=True)
    access_token_encrypted = fields.Text(groups='social_ads_crm.group_social_ads_manager')
    refresh_token_encrypted = fields.Text(groups='social_ads_crm.group_social_ads_manager')
    token_expires_at = fields.Datetime()
    last_health_check_at = fields.Datetime(readonly=True)
    last_success_at = fields.Datetime(readonly=True)
    last_error_code = fields.Char(readonly=True)
    last_error_message = fields.Text(readonly=True)
    external_account_id = fields.Char(index=True)
    external_business_id = fields.Char(index=True)
    ad_account_ids = fields.One2many('social.ads.account','connection_id')
    form_ids = fields.One2many('social.lead.form','connection_id')

    def set_tokens(self, access_token, refresh_token=None, expires_in=None):
        self.ensure_one()
        vals = {'access_token_encrypted': self._encrypt_secret(access_token), 'connection_status': 'connected',
                'last_success_at': fields.Datetime.now(), 'last_error_code': False, 'last_error_message': False}
        if refresh_token:
            vals['refresh_token_encrypted'] = self._encrypt_secret(refresh_token)
        if expires_in:
            vals['token_expires_at'] = fields.Datetime.now() + timedelta(seconds=int(expires_in))
        self.write(vals)

    def get_access_token(self):
        self.ensure_one()
        return self._decrypt_secret(self.access_token_encrypted)

    def get_refresh_token(self):
        self.ensure_one()
        return self._decrypt_secret(self.refresh_token_encrypted)

    def _get_provider_service(self):
        self.ensure_one()
        if self.provider == 'snapchat':
            from .providers.snapchat_provider import SnapchatProvider
            return SnapchatProvider(self)
        raise UserError(_('This provider is managed by the compatibility connector in this release.'))

    def action_connect(self):
        self.ensure_one()
        return self._get_provider_service().get_authorization_action()

    def action_check_health(self):
        for rec in self:
            if rec.provider == 'snapchat':
                rec._get_provider_service().check_connection_health()
        return True

    def action_sync_accounts(self):
        for rec in self:
            if rec.provider == 'snapchat':
                rec._get_provider_service().sync_ad_accounts()
        return True

    @api.model
    def _cron_check_connection_health(self):
        for rec in self.search([('active','=',True),('provider','=','snapchat')]):
            try:
                rec._get_provider_service().check_connection_health()
            except Exception as exc:
                _logger.exception('Social connection health check failed for %s', rec.display_name)
                rec.write({'connection_status':'error','last_health_check_at':fields.Datetime.now(),
                           'last_error_message':str(exc)[:1000]})
