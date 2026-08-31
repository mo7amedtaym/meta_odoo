from odoo import models, fields

class MetaCampaign(models.Model):
    _name = 'meta.campaign'
    _description = 'Meta Ad Campaign'

    campaign_id = fields.Char(string='Campaign ID', required=True, index=True)
    name = fields.Char(string='Campaign Name', required=True)
    objective = fields.Char(string='Objective')
    status = fields.Selection([
        ('ACTIVE', 'Active'),
        ('PAUSED', 'Paused'),
        ('DELETED', 'Deleted'),
        ('ARCHIVED', 'Archived')
    ], string='Status', default='PAUSED')
    ad_account_id = fields.Many2one('meta.ad.account', string='Ad Account')
    promotion_ids = fields.One2many('meta.promotion', 'campaign_id', string='Promotions')
