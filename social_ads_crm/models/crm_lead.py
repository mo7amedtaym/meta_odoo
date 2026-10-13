import json
from odoo import api, fields, models

class CrmLead(models.Model):
    _inherit = 'crm.lead'

    social_provider = fields.Selection([('meta','Meta'),('snapchat','Snapchat')], index=True, readonly=True)
    social_external_lead_id = fields.Char(index=True, readonly=True)
    social_form_id = fields.Many2one('social.lead.form', readonly=True)
    social_lead_log_id = fields.Many2one('social.lead.log', readonly=True)
    social_raw_data = fields.Json(readonly=True, groups='social_ads_crm.group_social_ads_manager')
