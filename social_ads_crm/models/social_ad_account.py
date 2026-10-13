from odoo import fields, models

class SocialAdsAccount(models.Model):
    _name = 'social.ads.account'
    _description = 'Social Ads Account'
    _order = 'provider, name'

    provider = fields.Selection(related='connection_id.provider', store=True, index=True)
    connection_id = fields.Many2one('social.ads.connection', required=True, ondelete='cascade', index=True)
    external_id = fields.Char(required=True, index=True)
    name = fields.Char(required=True)
    currency = fields.Char()
    timezone = fields.Char()
    status = fields.Char()
    raw_data = fields.Json()
    active = fields.Boolean(default=True)
    form_ids = fields.One2many('social.lead.form','ad_account_id')
    _sql_constraints = [('social_ads_account_uniq','unique(provider, connection_id, external_id)','Ad account already exists for this connection.')]

    def action_sync_forms(self):
        for rec in self:
            rec.connection_id._get_provider_service().sync_lead_forms(rec)
        return True
