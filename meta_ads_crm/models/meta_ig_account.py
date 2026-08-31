from odoo import models, fields

class MetaIgAccount(models.Model):
    _name = 'meta.ig.account'
    _description = 'Meta Instagram Account'

    ig_id = fields.Char(string='IG ID', required=True)
    username = fields.Char(string='Username')
    name = fields.Char(string='Name')
    profile_pic_url = fields.Char(string='Profile Picture URL')
    followers_count = fields.Integer(string='Followers Count')
    page_id = fields.Many2one('meta.page', string='Facebook Page', ondelete='cascade')
    active = fields.Boolean(default=True)
