from odoo import models, fields

class MetaBusinessAccount(models.Model):
    _name = 'meta.business.account'
    _description = 'Meta Business Account'

    business_id = fields.Char(string='Business ID', required=True)
    name = fields.Char(string='Name', required=True)
    access_token_encrypted = fields.Text(string='Encrypted Access Token')
    token_expiry = fields.Datetime(string='Token Expiry')
    status = fields.Selection([
        ('active', 'Active'),
        ('expired', 'Expired'),
        ('error', 'Error')
    ], string='Status', default='active')
    active = fields.Boolean(default=True)
