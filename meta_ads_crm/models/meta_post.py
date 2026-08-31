from odoo import models, fields

class MetaPost(models.Model):
    _name = 'meta.post'
    _description = 'Meta Post'

    post_id = fields.Char(string='Post ID', required=True, index=True)
    ig_media_id = fields.Char(string='IG Media ID')
    platform = fields.Selection([
        ('facebook', 'Facebook'),
        ('instagram', 'Instagram')
    ], string='Platform', required=True)
    message = fields.Text(string='Message/Caption')
    media_type = fields.Char(string='Media Type')
    media_url = fields.Char(string='Media URL')
    permalink_url = fields.Char(string='Permalink URL')
    like_count = fields.Integer(string='Like Count')
    comment_count = fields.Integer(string='Comment Count')
    share_count = fields.Integer(string='Share Count')
    is_eligible_for_boost = fields.Boolean(string='Eligible for Boost', default=False)
    posted_date = fields.Datetime(string='Posted Date')
    raw_json = fields.Json(string='Raw Data JSON')
    
    # Relationships
    page_id = fields.Many2one('meta.page', string='Facebook Page')
    ig_account_id = fields.Many2one('meta.ig.account', string='IG Account')
    promotion_ids = fields.One2many('meta.promotion', 'source_post_id', string='Promotions')
