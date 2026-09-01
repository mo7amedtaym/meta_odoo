import json

from odoo import models, fields, api
from odoo.exceptions import UserError


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    meta_leadgen_id = fields.Char(string='Meta Leadgen ID', readonly=True, index=True)
    meta_form_id = fields.Many2one('meta.lead.form', string='Meta Form', readonly=True)
    meta_campaign_id = fields.Char(string='Meta Campaign ID', readonly=True)
    meta_ad_id = fields.Char(string='Meta Ad ID', readonly=True)
    meta_platform = fields.Char(string='Meta Platform', readonly=True)
    meta_raw_data = fields.Json(string='Meta Raw Data', readonly=True)
    meta_raw_data_pretty = fields.Text(
        string='Meta Raw Data (Formatted)',
        compute='_compute_meta_raw_data_pretty',
        readonly=True,
    )
    is_meta_lead = fields.Boolean(string='Is Meta Lead', default=False, index=True)

    @api.depends('meta_raw_data')
    def _compute_meta_raw_data_pretty(self):
        for lead in self:
            if lead.meta_raw_data:
                try:
                    lead.meta_raw_data_pretty = json.dumps(
                        lead.meta_raw_data,
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=False,
                    )
                except Exception:
                    lead.meta_raw_data_pretty = str(lead.meta_raw_data)
            else:
                lead.meta_raw_data_pretty = False

    def action_reapply_meta_mapping(self):
        """Re-map stored Meta raw data into CRM fields for existing Meta leads."""
        for lead in self:
            if not lead.is_meta_lead or not lead.meta_form_id or not lead.meta_raw_data:
                raise UserError('This lead does not contain enough Meta data to reapply mapping.')

            vals = lead.meta_form_id._prepare_crm_lead_values(lead.meta_raw_data)
            # Never overwrite traceability. Update mapped business fields only.
            vals.pop('type', None)
            if vals:
                lead.write(vals)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Meta Mapping Applied',
                'message': 'Meta data was mapped to the CRM lead fields.',
                'type': 'success',
                'sticky': False,
            },
        }
