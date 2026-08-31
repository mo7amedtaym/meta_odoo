from odoo import models, fields

class MetaPromotion(models.Model):
    _name = 'meta.promotion'
    _description = 'Meta Boost Post Promotion'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Name', required=True, tracking=True)
    source_post_id = fields.Many2one('meta.post', string='Source Post', tracking=True)
    source_social_account = fields.Selection([
        ('facebook', 'Facebook Page'),
        ('instagram', 'Instagram Business')
    ], string='Source Platform', tracking=True)
    
    delivery_page_id = fields.Many2one('meta.page', string='Delivery Page')
    delivery_ad_account_id = fields.Many2one('meta.ad.account', string='Delivery Ad Account')
    
    campaign_id = fields.Many2one('meta.campaign', string='Campaign', tracking=True)
    adset_id = fields.Many2one('meta.adset', string='Ad Set', tracking=True)
    ad_id = fields.Many2one('meta.ad', string='Ad', tracking=True)
    
    status = fields.Selection([
        ('Draft', 'Draft'),
        ('Paused', 'Paused'),
        ('Active', 'Active'),
        ('Completed', 'Completed')
    ], string='Status', default='Draft', tracking=True)
    
    budget = fields.Float(string='Daily Budget', tracking=True)
    schedule_start = fields.Datetime(string='Schedule Start', tracking=True)
    schedule_end = fields.Datetime(string='Schedule End', tracking=True)

    def action_activate_delivery(self):
        self.write({'status': 'Active'})
        # Logic to call Meta API and activate campaign, adset, ad

    def action_pause_delivery(self):
        self.write({'status': 'Paused'})
        # Logic to call Meta API and pause campaign, adset, ad
