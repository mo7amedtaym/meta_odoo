from odoo import fields, models

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    snapchat_client_id = fields.Char(config_parameter='social_ads.snapchat.client_id')
    snapchat_client_secret = fields.Char(config_parameter='social_ads.snapchat.client_secret')
    snapchat_signature_tolerance = fields.Integer(config_parameter='social_ads.snapchat.signature_tolerance', default=300)
