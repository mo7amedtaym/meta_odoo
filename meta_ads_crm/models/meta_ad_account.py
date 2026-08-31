from odoo import models, fields

class MetaAdAccount(models.Model):
    _name = 'meta.ad.account'
    _description = 'Meta Ad Account'

    account_id = fields.Char(string='Ad Account ID', required=True) # Usually starts with act_
    name = fields.Char(string='Name', required=True)
    account_status = fields.Char(string='Account Status')
    currency = fields.Char(string='Currency')
    timezone = fields.Char(string='Timezone')
    business_id = fields.Many2one('meta.business.account', string='Business Account')
    active = fields.Boolean(default=True)
