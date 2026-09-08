import logging
import re
from datetime import timedelta

import requests

from odoo import models, fields, api, _
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
    # English / Meta standard aliases
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

    # Arabic Lead Ads aliases used by real Meta forms.
    # Keep these in normalized form because _normalize_meta_key() runs first.
    'الاسم_بالكامل': 'full_name',
    'الاسم_الكامل': 'full_name',
    'الاسم': 'full_name',
    'رقم_الهاتف': 'phone',
    'الهاتف': 'phone',
    'رقم_الجوال': 'mobile_phone',
    'الجوال': 'mobile_phone',
    'رقم_الموبايل': 'mobile_phone',
    'الموبايل': 'mobile_phone',
    'اسم_الشركة': 'company_name',
    'الشركة': 'company_name',
    'المسمى_الوظيفي': 'job_title',
    'المسمي_الوظيفي': 'job_title',
    'الوظيفة': 'job_title',
    'المدينة': 'city',
    'المدينه': 'city',
    'البريد_الإلكتروني': 'email',
    'البريد_الالكتروني': 'email',
    'البريد_الإلكتروني_للعمل': 'email',
    'البريد_الالكتروني_للعمل': 'email',
    'ايميل': 'email',
}


# Default per-form mapping profile. These lines are only used when the user
# initializes defaults from the Lead Form. Existing user mappings are never
# overwritten. Aliases make the profile tolerant to payload/question renames.
_DEFAULT_FORM_MAPPING_PROFILE = [
    {
        'meta_key': 'full_name',
        'meta_label': 'Full Name / الاسم بالكامل',
        'odoo_field_name': 'contact_name',
        'meta_aliases': 'fullname, name, الاسم, الاسم_بالكامل, الاسم_الكامل',
    },
    {
        'meta_key': 'phone',
        'meta_label': 'Phone / رقم الهاتف',
        'odoo_field_name': 'phone',
        'meta_aliases': 'phone_number, phonenumber, phone_no, رقم_الهاتف, الهاتف',
    },
    {
        'meta_key': 'mobile',
        'meta_label': 'Mobile / الجوال',
        'odoo_field_name': 'mobile',
        'meta_aliases': 'mobile_phone, mobile_number, رقم_الجوال, الجوال, رقم_الموبايل, الموبايل',
    },
    {
        'meta_key': 'email',
        'meta_label': 'Email / البريد الإلكتروني',
        'odoo_field_name': 'email_from',
        'meta_aliases': 'email_address, emailaddress, البريد_الإلكتروني, البريد_الالكتروني, البريد_الإلكتروني_للعمل, البريد_الالكتروني_للعمل, ايميل',
    },
    {
        'meta_key': 'company_name',
        'meta_label': 'Company Name / اسم الشركة',
        'odoo_field_name': 'partner_name',
        'meta_aliases': 'company, companyname, اسم_الشركة, الشركة',
    },
    {
        'meta_key': 'job_title',
        'meta_label': 'Job Position / المسمى الوظيفي',
        'odoo_field_name': 'function',
        'meta_aliases': 'job_position, jobtitle, jobposition, المسمى_الوظيفي, المسمي_الوظيفي, الوظيفة',
    },
    {
        'meta_key': 'city',
        'meta_label': 'City / المدينة',
        'odoo_field_name': 'city',
        'meta_aliases': 'المدينة, المدينه',
    },
    {
        'meta_key': 'street',
        'meta_label': 'Street / العنوان',
        'odoo_field_name': 'street',
        'meta_aliases': 'address, street_address, العنوان, عنوان',
    },
    {
        'meta_key': 'zip',
        'meta_label': 'ZIP / Postal Code',
        'odoo_field_name': 'zip',
        'meta_aliases': 'postal_code, zipcode, zip_code, الرمز_البريدي',
    },
]


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
    stage_id = fields.Many2one(
        'crm.stage',
        string='Opportunity Stage',
        help='Stage assigned to CRM opportunities created from this Meta lead form.',
    )
    team_id = fields.Many2one('crm.team', string='Sales Team')
    user_id = fields.Many2one('res.users', string='Salesperson')
    tag_ids = fields.Many2many('crm.tag', string='Tags')

    notify_on_new_lead = fields.Boolean(
        string='Notify on New Lead',
        default=True,
        help='Send an in-app notification after a Meta lead is successfully created in CRM.',
    )
    notification_user_ids = fields.Many2many(
        'res.users',
        'meta_lead_form_notify_user_rel',
        'form_id',
        'user_id',
        string='Users to Notify',
        domain=[('share', '=', False)],
        help='Internal Odoo users who should receive a notification for new leads from this form.',
    )
    notify_assigned_salesperson = fields.Boolean(
        string='Notify Assigned Salesperson',
        default=True,
        help='Also notify the salesperson assigned to the created CRM lead.',
    )
    create_notification_activity = fields.Boolean(
        string='Create Follow-up Activity',
        default=False,
        help='Create a Call activity for each notified user so the lead is not missed when they are offline.',
    )

    auto_mapping_enabled = fields.Boolean(
        string='Enable Automatic Mapping',
        default=True,
        help='Use built-in Arabic/English aliases for standard CRM fields after explicit form mappings.',
    )
    unmapped_field_policy = fields.Selection([
        ('notes', 'Add to Lead Notes'),
        ('ignore', 'Ignore'),
    ], string='Unmapped Fields', default='notes', required=True,
       help='Choose what to do with Meta questions that are not mapped to a CRM field.')

    field_mapping_ids = fields.One2many('meta.lead.form.field.map', 'form_id', string='Field Mapping')
    is_synced = fields.Boolean(string='Is Synced', default=True)
    last_lead_time = fields.Datetime(string='Last Lead Time')
    lead_count = fields.Integer(string='Leads', compute='_compute_lead_count')
    active = fields.Boolean(default=True)
    last_recovery_at = fields.Datetime(string='Last Recovery At', readonly=True, copy=False)
    last_recovery_status = fields.Char(string='Last Recovery Status', readonly=True, copy=False)
    last_recovery_error = fields.Text(string='Last Recovery Error', readonly=True, copy=False)

    @api.onchange('import_mode')
    def _onchange_import_mode(self):
        """A stage only applies when this form creates opportunities."""
        if self.import_mode != 'opportunity':
            self.stage_id = False

    @api.onchange('team_id')
    def _onchange_team_id(self):
        """Clear a team-specific stage when it no longer matches the selected team."""
        if (
            self.stage_id
            and self.stage_id.team_id
            and (not self.team_id or self.stage_id.team_id != self.team_id)
        ):
            self.stage_id = False

    def action_initialize_default_mappings(self):
        """Add a safe default mapping profile without overwriting user mappings."""
        for form in self:
            existing_keys = set()
            for mapping in form.field_mapping_ids:
                if mapping.meta_key:
                    existing_keys.add(_normalize_meta_key(mapping.meta_key))
                for alias in mapping._get_alias_keys():
                    existing_keys.add(alias)

            vals_list = []
            for item in _DEFAULT_FORM_MAPPING_PROFILE:
                canonical = _normalize_meta_key(item['meta_key'])
                if canonical in existing_keys:
                    continue
                vals = dict(item)
                vals.update({
                    'form_id': form.id,
                    'active': True,
                    'is_custom': False,
                })
                vals_list.append(vals)
                existing_keys.add(canonical)
            if vals_list:
                self.env['meta.lead.form.field.map'].create(vals_list)
        return True

    def action_sync_mapping_from_questions(self):
        """Refresh mapping rows from the latest questions already stored on the form."""
        for form in self:
            form._sync_field_mappings(form.questions_json or [])
        return True

    def action_sync_from_meta(self):
        """Sync this form's definition from Meta API via its parent page."""
        self.ensure_one()
        if not self.page_id:
            raise UserError('No Facebook Page linked to this form.')
        return self.page_id.action_sync_forms()

    def _get_notification_users(self, lead):
        """Return internal users that should be notified for a newly created CRM lead."""
        self.ensure_one()
        users = self.notification_user_ids.filtered(lambda user: not user.share and user.active)
        if self.notify_assigned_salesperson and lead.user_id and not lead.user_id.share and lead.user_id.active:
            users |= lead.user_id
        return users

    def _notify_new_crm_lead(self, lead):
        """Send an Odoo notification and optionally create follow-up activities.

        This is called only after crm.lead.create() succeeds, so webhook and
        recovery imports share the same notification behavior without notifying
        on failed or duplicate leads.
        """
        self.ensure_one()
        if not self.notify_on_new_lead or not lead:
            return False

        users = self._get_notification_users(lead)
        if not users:
            _logger.info('Meta lead %s created without notification recipients.', lead.meta_leadgen_id or lead.id)
            return False

        display_name = lead.contact_name or lead.name or _('New Meta Lead')
        details = []
        if lead.partner_name:
            details.append(_('Company: %s') % lead.partner_name)
        phone = lead.phone or lead.mobile
        if phone:
            details.append(_('Phone: %s') % phone)
        if lead.email_from:
            details.append(_('Email: %s') % lead.email_from)
        message = display_name
        if details:
            message = '%s\n%s' % (display_name, '\n'.join(details))

        bus = self.env['bus.bus'].sudo()
        for user in users:
            try:
                bus._sendone(
                    user.partner_id,
                    'simple_notification',
                    {
                        'title': _('New Meta Lead'),
                        'message': message,
                        'type': 'success',
                        'sticky': False,
                    },
                )
            except Exception:
                _logger.exception('Could not send Meta lead notification to user %s.', user.id)

        if self.create_notification_activity:
            activity_type = self.env.ref('mail.mail_activity_data_call', raise_if_not_found=False)
            model_id = self.env['ir.model']._get_id('crm.lead')
            if activity_type and model_id:
                Activity = self.env['mail.activity'].sudo()
                for user in users:
                    # Avoid accidental duplicate activities if this method is retried.
                    existing = Activity.search([
                        ('res_model_id', '=', model_id),
                        ('res_id', '=', lead.id),
                        ('activity_type_id', '=', activity_type.id),
                        ('user_id', '=', user.id),
                        ('summary', '=', _('New Meta Lead')),
                    ], limit=1)
                    if existing:
                        continue
                    try:
                        Activity.create({
                            'res_model_id': model_id,
                            'res_id': lead.id,
                            'activity_type_id': activity_type.id,
                            'user_id': user.id,
                            'summary': _('New Meta Lead'),
                            'note': _('A new lead was received from Meta Lead Ads: %s') % display_name,
                            'date_deadline': fields.Date.context_today(self),
                        })
                    except Exception:
                        _logger.exception('Could not create Meta lead activity for user %s.', user.id)
        return True

    def action_recover_missing_leads(self):
        self.ensure_one()
        summary = self._recover_missing_leads(max_pages=10, manual=True)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Missing Leads Recovery',
                'message': summary,
                'type': 'success',
                'sticky': True,
            },
        }

    def _get_recovery_since(self):
        self.ensure_one()
        icp = self.env['ir.config_parameter'].sudo()
        now = fields.Datetime.now()
        if self.last_recovery_at:
            # overlap by 2 hours so a temporarily unavailable lead is retried.
            since_dt = self.last_recovery_at - timedelta(hours=2)
        else:
            try:
                days = int(icp.get_param('meta.recovery.lookback_days') or 7)
            except Exception:
                days = 7
            days = min(max(days, 1), 90)
            since_dt = now - timedelta(days=days)
        return int(fields.Datetime.to_datetime(since_dt).timestamp())

    def _recover_missing_leads(self, max_pages=5, manual=False):
        self.ensure_one()
        if not self.page_id or not self.page_id.active:
            self.write({'last_recovery_error': 'No active Facebook Page linked to this form.'})
            return 'Skipped %s: no active Page.' % self.name
        access_token = self.page_id.decrypt_token()
        if not access_token:
            self.write({'last_recovery_error': 'No valid Page access token.'})
            return 'Skipped %s: no valid Page access token.' % self.name

        graph_version = self.page_id._graph_version()
        url = 'https://graph.facebook.com/%s/%s/leads' % (graph_version, self.form_id)
        params = {
            'access_token': access_token,
            'fields': 'id,created_time,field_data,form_id,ad_id,campaign_id,platform',
            'limit': 100,
            'since': self._get_recovery_since(),
        }
        scanned = imported = retried = 0
        page_no = 0
        LeadLog = self.env['meta.lead.log'].sudo()
        try:
            while url and page_no < max_pages:
                resp = requests.get(url, params=params if page_no == 0 else None, timeout=30)
                if not resp.ok:
                    detail = self.page_id._meta_error_detail(resp) or 'HTTP %s' % resp.status_code
                    raise UserError(detail)
                payload = resp.json() or {}
                for lead_data in payload.get('data', []) or []:
                    leadgen_id = str(lead_data.get('id') or '')
                    if not leadgen_id:
                        continue
                    scanned += 1
                    log = LeadLog.search([('leadgen_id', '=', leadgen_id)], limit=1)
                    if log:
                        if log.status in ('Pending', 'Error') and log.retry_count < 6:
                            if not log.form_id:
                                log.form_id = self
                            if not log.page_id:
                                log.page_id = self.page_id
                            log._process_lead()
                            retried += 1
                        continue
                    if self.env['crm.lead'].sudo().search_count([('meta_leadgen_id', '=', leadgen_id)]):
                        continue
                    log = LeadLog.create({
                        'leadgen_id': leadgen_id,
                        'form_id': self.id,
                        'page_id': self.page_id.id,
                        'ad_id': str(lead_data.get('ad_id')) if lead_data.get('ad_id') else False,
                        'campaign_id': str(lead_data.get('campaign_id')) if lead_data.get('campaign_id') else False,
                        'platform': lead_data.get('platform') or 'facebook',
                        'payload_json': lead_data,
                        'status': 'Pending',
                    })
                    log._process_lead()
                    imported += 1
                paging = payload.get('paging') or {}
                url = paging.get('next')
                page_no += 1
            now = fields.Datetime.now()
            status = 'Scanned %s, imported %s, retried %s.' % (scanned, imported, retried)
            self.write({
                'last_recovery_at': now,
                'last_recovery_status': status,
                'last_recovery_error': False,
            })
            return status
        except Exception as exc:
            message = str(exc)[:4000]
            self.write({
                'last_recovery_status': 'Failed',
                'last_recovery_error': message,
            })
            _logger.exception('Meta recovery failed for form %s: %s', self.form_id, exc)
            if manual:
                raise UserError('Missing Leads Recovery failed.\n%s' % message)
            return 'Failed %s: %s' % (self.name, message)

    @api.model
    def _cron_recover_missing_leads(self, force=False):
        icp = self.env['ir.config_parameter'].sudo()
        enabled = str(icp.get_param('meta.recovery.enabled', 'True')).lower() in ('1', 'true', 'yes', 'on')
        if not enabled and not force:
            return 'Automatic recovery is disabled.'
        forms = self.search([
            ('active', '=', True),
            ('status', '=', 'ACTIVE'),
            ('page_id.active', '=', True),
        ])
        summaries = []
        for form in forms:
            try:
                summaries.append(form._recover_missing_leads(max_pages=3 if not force else 10, manual=False))
            except Exception as exc:
                _logger.exception('Meta recovery cron failed for form %s: %s', form.form_id, exc)
        icp.set_param('meta.recovery.last_run_at', fields.Datetime.to_string(fields.Datetime.now()))
        imported = sum(1 for s in summaries if s and 'imported' in s)
        return 'Recovery completed for %s form(s).' % len(forms) if forms else 'No active forms to recover.'

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
        """Build crm.lead values from Meta data using explicit + default mappings.

        Explicit mappings configured on the Meta form always win. Standard Meta
        fields (including Arabic aliases) are mapped automatically. Remaining
        custom questions are preserved in the CRM lead description so no lead
        information is silently lost.
        """
        self.ensure_one()
        meta_fields = self._extract_meta_fields(lead_data)
        lead_vals = {}
        consumed_keys = set()

        # 1) Apply user/form mappings first. These always take precedence.
        for mapping in self.field_mapping_ids.sorted(key=lambda m: (m.sequence, m.id)):
            if not mapping.active or not mapping.odoo_field_name or not mapping.meta_key:
                continue
            matched_key, values = mapping._find_values_in_meta_fields(meta_fields)
            converted = self._convert_value_for_crm_field(mapping.odoo_field_name, values)
            if converted is not False:
                lead_vals[mapping.odoo_field_name] = converted
                if matched_key:
                    consumed_keys.add(_normalize_meta_key(matched_key))

        # 2) Fill standard CRM fields from common Meta aliases when not already mapped.
        if self.auto_mapping_enabled:
            for raw_key, values in meta_fields.items():
                normalized = _normalize_meta_key(raw_key)
                odoo_field = _META_FIELD_DEFAULTS.get(normalized)
                if not odoo_field or odoo_field in lead_vals:
                    continue
                converted = self._convert_value_for_crm_field(odoo_field, values)
                if converted is not False:
                    lead_vals[odoo_field] = converted
                    consumed_keys.add(normalized)

        # 3) Build a useful full name from first/last name when FULL_NAME is absent.
        if not lead_vals.get('contact_name'):
            first = self._meta_value_to_text(meta_fields.get('first_name'))
            last = self._meta_value_to_text(meta_fields.get('last_name'))
            full = ' '.join(v for v in (first, last) if v).strip()
            if full:
                lead_vals['contact_name'] = full
                consumed_keys.update({'first_name', 'last_name'})

        # 4) Preserve custom/unmapped Meta questions in Notes/Description.
        # Use field_data directly to retain the original Arabic labels exactly.
        custom_lines = []
        explicit_map_keys = set()
        for mapping in self.field_mapping_ids:
            if not mapping.active or not mapping.odoo_field_name:
                continue
            if mapping.meta_key:
                explicit_map_keys.add(_normalize_meta_key(mapping.meta_key))
            explicit_map_keys.update(mapping._get_alias_keys())
        for item in (lead_data or {}).get('field_data', []) or []:
            raw_name = str(item.get('name') or item.get('key') or '').strip()
            normalized = _normalize_meta_key(raw_name)
            if not raw_name or normalized in consumed_keys or normalized in explicit_map_keys:
                continue
            value = self._meta_value_to_text(item.get('values') or [])
            if value:
                custom_lines.append('%s: %s' % (raw_name.replace('_', ' '), value.replace('_', ' ')))

        if custom_lines and self.unmapped_field_policy == 'notes':
            meta_notes = 'Meta Lead Details:\n' + '\n'.join(custom_lines)
            if lead_vals.get('description'):
                lead_vals['description'] = '%s\n\n%s' % (lead_vals['description'], meta_notes)
            else:
                lead_vals['description'] = meta_notes

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

    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    form_id = fields.Many2one('meta.lead.form', string='Form', required=True, ondelete='cascade')
    meta_key = fields.Char(string='Meta Question Key', required=True,
                           help='Primary field/question name received from Meta.')
    meta_label = fields.Char(string='Meta Label')
    meta_aliases = fields.Char(
        string='Aliases',
        help='Alternative Meta keys accepted for this mapping. Separate aliases with commas, semicolons, or new lines.',
    )

    odoo_field_name = fields.Selection(
        selection='_get_crm_lead_fields',
        string='Odoo Field Name'
    )
    is_custom = fields.Boolean(string='Is Custom')
    custom_field_id = fields.Char(string='Custom Field ID')

    def _get_alias_keys(self):
        self.ensure_one()
        aliases = re.split(r'[,;\n]+', self.meta_aliases or '')
        return {
            _normalize_meta_key(alias)
            for alias in aliases
            if str(alias or '').strip()
        }

    def _find_values_in_meta_fields(self, meta_fields):
        """Return (matched_key, values) using primary key then aliases."""
        self.ensure_one()
        candidates = [_normalize_meta_key(self.meta_key)]
        candidates.extend(sorted(self._get_alias_keys()))
        for candidate in candidates:
            if candidate in meta_fields and meta_fields[candidate]:
                return candidate, meta_fields[candidate]
        # Backward compatibility: exact raw key may also be present.
        if self.meta_key in meta_fields and meta_fields[self.meta_key]:
            return self.meta_key, meta_fields[self.meta_key]
        return False, []

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
