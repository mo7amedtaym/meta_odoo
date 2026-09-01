import logging
import re

from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Canonical Meta lead form field names and their Odoo CRM equivalents.
# Keys are normalized through _normalize_meta_key(), so this works with
# FULL_NAME, Full Name, full-name, phone_number, PHONE, etc.
_META_FIELD_DEFAULTS = {
    'full_name': 'contact_name',
    'email': 'email_from',
    'phone': 'phone',
    'phone_number': 'phone',
    'mobile': 'mobile',
    'mobile_phone': 'mobile',
    'company': 'partner_name',
    'company_name': 'partner_name',
    'job_title': 'function',
    'job_position': 'function',
    'street': 'street',
    'city': 'city',
    'zip': 'zip',
}

# Meta/API aliases that should resolve to one canonical key.
_META_KEY_ALIASES = {
    'fullname': 'full_name',
    'name': 'full_name',
    'email_address': 'email',
    'emailaddress': 'email',
    'phone_no': 'phone',
    'phone_number': 'phone_number',
    'phonenumber': 'phone_number',
    'mobile_number': 'mobile_phone',
    'mobilenumber': 'mobile_phone',
    'companyname': 'company_name',
    'company': 'company',
    'jobtitle': 'job_title',
    'jobposition': 'job_position',
    'postal_code': 'zip',
    'zipcode': 'zip',
}


def _normalize_meta_key(key):
    """Normalize Meta question names for case-insensitive reliable mapping."""
    key = str(key or '').strip().lower()
    key = re.sub(r'[\s\-./]+', '_', key)
    # Keep Unicode letters/digits so Arabic/custom question keys remain mappable.
    key = re.sub(r'[^\w]+', '', key, flags=re.UNICODE)
    key = re.sub(r'_+', '_', key).strip('_')
    return _META_KEY_ALIASES.get(key, key)


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
        """Auto-create/update useful mappings from Meta form questions.

        Meta may return keys in uppercase (FULL_NAME / PHONE / COMPANY_NAME),
        lowercase, or custom/numeric keys. Standard fields are mapped
        automatically; custom keys are preserved so the user can map them.
        """
        self.ensure_one()
        if not questions:
            return

        existing_by_normalized = {
            _normalize_meta_key(m.meta_key): m
            for m in self.field_mapping_ids
            if m.meta_key
        }
        vals_list = []
        for q in questions:
            raw_key = q.get('key') or q.get('name') or q.get('label') or ''
            raw_key = str(raw_key)
            normalized_key = _normalize_meta_key(raw_key)
            if not raw_key:
                continue

            default_odoo_field = _META_FIELD_DEFAULTS.get(normalized_key)
            existing = existing_by_normalized.get(normalized_key)
            if existing:
                # Never overwrite a user's explicit mapping. Only fill empty
                # mappings for well-known Meta fields.
                if not existing.odoo_field_name and default_odoo_field:
                    existing.odoo_field_name = default_odoo_field
                if not existing.meta_label:
                    existing.meta_label = q.get('label') or raw_key
                continue

            vals_list.append({
                'form_id': self.id,
                'meta_key': raw_key,
                'meta_label': q.get('label') or raw_key,
                'odoo_field_name': default_odoo_field or False,
                'is_custom': not bool(default_odoo_field),
            })

        if vals_list:
            self.env['meta.lead.form.field.map'].create(vals_list)

    def _extract_meta_fields(self, lead_data):
        """Return normalized field lookup from Meta's field_data payload."""
        self.ensure_one()
        result = {}
        for item in (lead_data or {}).get('field_data', []) or []:
            raw_name = item.get('name') or item.get('key') or ''
            normalized = _normalize_meta_key(raw_name)
            if not normalized:
                continue
            values = item.get('values') or []
            if not isinstance(values, list):
                values = [values]
            # Keep original key too for exact custom mapping compatibility.
            result.setdefault(normalized, []).extend(values)
            exact = str(raw_name).strip()
            if exact and exact != normalized:
                result.setdefault(exact, []).extend(values)
        return result

    @api.model
    def _meta_value_to_text(self, values):
        values = values or []
        clean = [v for v in values if v not in (None, False, '')]
        if not clean:
            return False
        if len(clean) == 1:
            return str(clean[0])
        return ', '.join(str(v) for v in clean)

    def _convert_value_for_crm_field(self, field_name, values):
        """Convert a Meta value to a safe value for the selected crm.lead field."""
        self.ensure_one()
        crm_field = self.env['crm.lead']._fields.get(field_name)
        if not crm_field:
            return False

        text = self._meta_value_to_text(values)
        if text is False:
            return False

        try:
            if crm_field.type in ('char', 'text', 'html', 'selection'):
                return text
            if crm_field.type == 'boolean':
                return text.strip().lower() in ('1', 'true', 'yes', 'y', 'on')
            if crm_field.type == 'integer':
                return int(float(text))
            if crm_field.type in ('float', 'monetary'):
                return float(text)
            if crm_field.type == 'many2one':
                return int(text)
            # For date/datetime and other scalar fields, let ORM validate text.
            if crm_field.type in ('date', 'datetime'):
                return text
        except (TypeError, ValueError):
            return False
        return False

    def _prepare_crm_lead_values(self, lead_data):
        """Build crm.lead values from Meta data using explicit + default mappings."""
        self.ensure_one()
        meta_fields = self._extract_meta_fields(lead_data)
        lead_vals = {}

        # 1) Apply user/form mappings first. These always take precedence.
        for mapping in self.field_mapping_ids:
            if not mapping.odoo_field_name or not mapping.meta_key:
                continue
            normalized = _normalize_meta_key(mapping.meta_key)
            values = meta_fields.get(mapping.meta_key) or meta_fields.get(normalized) or []
            converted = self._convert_value_for_crm_field(mapping.odoo_field_name, values)
            if converted is not False:
                lead_vals[mapping.odoo_field_name] = converted

        # 2) Fill standard CRM fields from common Meta aliases when not already mapped.
        for meta_key, odoo_field in _META_FIELD_DEFAULTS.items():
            if odoo_field in lead_vals:
                continue
            values = meta_fields.get(_normalize_meta_key(meta_key), [])
            converted = self._convert_value_for_crm_field(odoo_field, values)
            if converted is not False:
                lead_vals[odoo_field] = converted

        # 3) Build a useful full name from first/last name when FULL_NAME is absent.
        if not lead_vals.get('contact_name'):
            first = self._meta_value_to_text(meta_fields.get('first_name'))
            last = self._meta_value_to_text(meta_fields.get('last_name'))
            full = ' '.join(v for v in (first, last) if v).strip()
            if full:
                lead_vals['contact_name'] = full

        # Prefer a real customer/company identity for the CRM lead title.
        lead_title = (
            lead_vals.get('contact_name')
            or lead_vals.get('partner_name')
            or lead_vals.get('email_from')
        )
        if lead_title:
            lead_vals.setdefault('name', lead_title)

        return lead_vals


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
        # Exclude technical/computed fields that should not receive Meta values.
        exclude = {
            'id', 'create_uid', 'write_uid', 'create_date', 'write_date',
            'display_name', '__last_update', 'meta_raw_data', 'meta_raw_data_pretty',
            'is_meta_lead', 'meta_leadgen_id', 'meta_form_id', 'meta_campaign_id',
            'meta_ad_id', 'meta_platform',
        }
        return [
            (k, v.get('string', k))
            for k, v in sorted(fields_dict.items())
            if k not in exclude and not k.startswith('_')
        ]
