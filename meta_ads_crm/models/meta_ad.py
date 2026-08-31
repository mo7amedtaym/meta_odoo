from odoo import models, fields

class MetaAd(models.Model):
    _name = 'meta.ad'
    _description = 'Meta Ad'

    ad_id = fields.Char(string='Ad ID', required=True, index=True)
    name = fields.Char(string='Name', required=True)
    adset_id = fields.Many2one('meta.adset', string='Ad Set', ondelete='cascade')
    status = fields.Selection([
        ('ACTIVE', 'Active'),
        ('PAUSED', 'Paused'),
        ('DELETED', 'Deleted'),
        ('ARCHIVED', 'Archived')
    ], string='Status', default='PAUSED')
    preview_url = fields.Char(string='Preview URL')
    promotion_ids = fields.One2many('meta.promotion', 'ad_id', string='Promotions')
