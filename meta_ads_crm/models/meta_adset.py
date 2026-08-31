from odoo import models, fields

class MetaAdset(models.Model):
    _name = 'meta.adset'
    _description = 'Meta Ad Set'

    adset_id = fields.Char(string='AdSet ID', required=True, index=True)
    name = fields.Char(string='Name', required=True)
    campaign_id = fields.Many2one('meta.campaign', string='Campaign', ondelete='cascade')
    daily_budget = fields.Float(string='Daily Budget')
    lifetime_budget = fields.Float(string='Lifetime Budget')
    targeting_json = fields.Json(string='Targeting JSON')
    status = fields.Selection([
        ('ACTIVE', 'Active'),
        ('PAUSED', 'Paused'),
        ('DELETED', 'Deleted'),
        ('ARCHIVED', 'Archived')
    ], string='Status', default='PAUSED')
    start_time = fields.Datetime(string='Start Time')
    end_time = fields.Datetime(string='End Time')
    promotion_ids = fields.One2many('meta.promotion', 'adset_id', string='Promotions')
