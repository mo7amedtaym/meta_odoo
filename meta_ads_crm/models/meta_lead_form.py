import logging

from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Common Meta lead form field names and their Odoo CRM equivalents
_META_FIELD_DEFAULTS = {
    'full_name': 'contact_name',
    'first_name': 'contact_name',
    'last_name': 'contact_name',
    'email': 'email_from',
    'phone_number': 'phone',
    'phone': 'phone',
    'company_name': 'partner_name',
}


class MetaLeadForm(models.Model):
    _name = 'meta.lead.form'
    _description = 'Meta Lead Form'
    _inherit = ['mail.thread']
    _rec_name = 'name'

    form_id = fields.Char(string='Form ID', required=True, index=True)
    name = fields.Char(string='Name', required=True)
    status = fields.Selection([
        ('ACTIVE', 'Active'),
        ('ARCHIVED', 'Archived')
    ], string='Status', default='ACTIVE')
    locale = fields.Char(string='Locale')
    page_id = fields.Many2one('meta.page', string='Facebook Page', ondelete='cascade')
    questions_json = fields.Json(string='Questions Data')
    privacy_policy_url = fields.Char(string='Privacy Policy URL')
    thank_you_url = fields.Char(string='Thank You URL')
    follow_up_url = fields.Char(string='Follow Up URL')

    import_mode = fields.Selection([
        ('lead', 'Lead'),
        ('opportunity', 'Opportunity')
    ], string='Import Mode', default='lead')
    team_id = fields.Many2one('crm.team', string='Sales Team')
    user_id = fields.Many2one('res.users', string='Salesperson')
    tag_ids = fields.Many2many('crm.tag', string='Tags')

    field_mapping_ids = fields.One2many('meta.lead.form.field.map', 'form_id', string='Field Mapping')
    is_synced = fields.Boolean(string='Is Synced', default=True)
    last_lead_time = fields.Datetime(string='Last Lead Time')
    lead_count = fields.Integer(string='Leads', compute='_compute_lead_count')
    active = fields.Boolean(default=True)

    def action_sync_from_meta(self):
        """Sync this form's definition from Meta API via its parent page."""
        self.ensure_one()
        if not self.page_id:
            raise UserError('No Facebook Page linked to this form.')
        return self.page_id.action_sync_forms()

    def _compute_lead_count(self):
        for form in self:
            form.lead_count = self.env['meta.lead.log'].search_count([
                ('form_id', '=', form.id),
                ('status', '=', 'Created'),
            ])

    def _sync_field_mappings(self, questions):
        """Auto-create field mappings from Meta form questions."""
        if not questions:
            return

        existing_keys = self.field_mapping_ids.mapped('meta_key')
        vals_list = []
        for q in questions:
            # Meta questions can have sub_fields
            sub_fields = q.get('hints', q.get('options', []))
            key = q.get('key', q.get('label', ''))

            if key in existing_keys:
                continue

            # Try to auto-map common fields
            odoo_field = _META_FIELD_DEFAULTS.get(key, '')

            vals_list.append({
                'form_id': self.id,
                'meta_key': key,
                'meta_label': q.get('label', key),
                'odoo_field_name': odoo_field if odoo_field else False,
            })

        if vals_list:
            self.env['meta.lead.form.field.map'].create(vals_list)


class MetaLeadFormFieldMap(models.Model):
    _name = 'meta.lead.form.field.map'
    _description = 'Meta Lead Form Field Map'
    _rec_name = 'meta_label'

    form_id = fields.Many2one('meta.lead.form', string='Form', required=True, ondelete='cascade')
    meta_key = fields.Char(string='Meta Question Key', required=True)
    meta_label = fields.Char(string='Meta Label')

    odoo_field_name = fields.Selection(
        selection='_get_crm_lead_fields',
        string='Odoo Field Name'
    )
    is_custom = fields.Boolean(string='Is Custom')
    custom_field_id = fields.Char(string='Custom Field ID')

    @api.model
    def _get_crm_lead_fields(self):
        fields_dict = self.env['crm.lead'].fields_get()
        # Only include useful fields, exclude computed/readonly junk
        exclude = {'id', 'create_uid', 'write_uid', 'create_date', 'write_date',
                   'display_name', '__last_update', 'meta_raw_data'}
        return [
            (k, v.get('string', k))
            for k, v in sorted(fields_dict.items())
            if k not in exclude and not k.startswith('_')
        ]
