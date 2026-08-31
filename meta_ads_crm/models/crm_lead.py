from odoo import models, fields

class CrmLead(models.Model):
    _inherit = 'crm.lead'

    meta_leadgen_id = fields.Char(string='Meta Leadgen ID', readonly=True)
    meta_form_id = fields.Many2one('meta.lead.form', string='Meta Form', readonly=True)
    meta_campaign_id = fields.Char(string='Meta Campaign ID', readonly=True)
    meta_ad_id = fields.Char(string='Meta Ad ID', readonly=True)
    meta_platform = fields.Char(string='Meta Platform', readonly=True)
    meta_raw_data = fields.Json(string='Meta Raw Data', readonly=True)
    is_meta_lead = fields.Boolean(string='Is Meta Lead', default=False)
