import json
import logging
import requests

from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class MetaLeadLog(models.Model):
    _name = 'meta.lead.log'
    _description = 'Meta Lead Log'
    _rec_name = 'leadgen_id'
    _order = 'created_date desc'

    leadgen_id = fields.Char(string='Leadgen ID', required=True, index=True)
    form_id = fields.Many2one('meta.lead.form', string='Lead Form')
    page_id = fields.Many2one('meta.page', string='Facebook Page')
    ad_id = fields.Char(string='Ad ID')
    campaign_id = fields.Char(string='Campaign ID')
    platform = fields.Char(string='Platform')
    payload_json = fields.Json(string='Payload JSON')

    status = fields.Selection([
        ('Pending', 'Pending'),
        ('Created', 'Created'),
        ('Duplicate', 'Duplicate'),
        ('Error', 'Error')
    ], string='Status', default='Pending', index=True)

    error_message = fields.Text(string='Error Message')
    crm_lead_id = fields.Many2one('crm.lead', string='Created CRM Lead')
    created_date = fields.Datetime(string='Created Date', default=fields.Datetime.now)
    retry_count = fields.Integer(string='Retry Count', default=0)

    def action_process(self):
        """Manually retry processing pending/errored leads."""
        for log in self:
            if log.status not in ('Pending', 'Error'):
                continue
            log._process_lead()

    def _process_lead(self):
        """Fetch lead data from Meta API and create a CRM lead."""
        self.ensure_one()
        if not self.page_id:
            self._mark_error('No linked Facebook Page found.')
            return

        # Check for duplicate
        existing = self.env['crm.lead'].search([
            ('meta_leadgen_id', '=', self.leadgen_id)
        ], limit=1)
        if existing:
            self.write({'status': 'Duplicate', 'crm_lead_id': existing.id})
            return

        # Get page access token
        access_token = self.page_id.decrypt_token()
        if not access_token:
            self._mark_error('No valid access token for page "%s".' % self.page_id.name)
            return

        # Fetch lead data from Meta Graph API
        lead_data = self._fetch_lead_data(access_token)
        if not lead_data:
            return  # error already recorded

        # Create CRM lead
        crm_lead = self._create_crm_lead(lead_data)
        if crm_lead:
            self.write({
                'status': 'Created',
                'crm_lead_id': crm_lead.id,
                'payload_json': lead_data,
            })
            _logger.info(
                'Meta lead %s converted to crm.lead %s', self.leadgen_id, crm_lead.id
            )

    def _fetch_lead_data(self, access_token):
        """Call Meta Graph API to get full lead data."""
        graph_version = self.env['ir.config_parameter'].sudo().get_param(
            'meta.graph_version', 'v21.0'
        )
        url = 'https://graph.facebook.com/%s/%s' % (graph_version, self.leadgen_id)
        params = {'access_token': access_token}
        try:
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            self._mark_error('Meta API request failed: %s' % str(e))
            return None

    def _create_crm_lead(self, lead_data):
        """Map Meta field_data to CRM lead fields and create the record."""
        if not self.form_id:
            self._mark_error('No linked lead form. Create a meta.lead.form record for form_id "%s".' % (
                lead_data.get('form_id', '?')
            ))
            return None

        form = self.form_id
        field_data = lead_data.get('field_data', [])

        # Build a lookup: meta field name -> list of values
        meta_fields = {}
        for fd in field_data:
            name = fd.get('name', '')
            values = fd.get('values', [])
            meta_fields[name] = values

        # Apply field mappings
        lead_vals = {}
        for mapping in form.field_mapping_ids:
            odoo_field = mapping.odoo_field_name
            meta_values = meta_fields.get(mapping.meta_key, [])
            if not odoo_field or not meta_values:
                continue

            value = meta_values[0] if len(meta_values) == 1 else ', '.join(str(v) for v in meta_values)

            # Handle Many2one fields (partner_name, user_id, team_id, stage_id)
            if odoo_field in ('user_id', 'team_id'):
                try:
                    lead_vals[odoo_field] = int(value)
                except (ValueError, TypeError):
                    pass
            elif odoo_field == 'stage_id':
                try:
                    lead_vals[odoo_field] = int(value)
                except (ValueError, TypeError):
                    pass
            else:
                lead_vals[odoo_field] = value

        # Set type
        lead_vals['type'] = 'lead' if form.import_mode == 'lead' else 'opportunity'

        # Stamp defaults from form config
        if form.team_id:
            lead_vals.setdefault('team_id', form.team_id.id)
        if form.user_id:
            lead_vals.setdefault('user_id', form.user_id.id)
        if form.tag_ids:
            lead_vals['tag_ids'] = [(6, 0, form.tag_ids.ids)]

        # Meta traceability fields
        lead_vals.update({
            'meta_leadgen_id': self.leadgen_id,
            'meta_form_id': form.id,
            'meta_campaign_id': self.campaign_id or False,
            'meta_ad_id': self.ad_id or False,
            'meta_platform': self.platform or 'facebook',
            'meta_raw_data': lead_data,
            'is_meta_lead': True,
        })

        # Fallback: if no name was mapped, build one from available data
        if not lead_vals.get('contact_name') and not lead_vals.get('name'):
            name_parts = []
            for key in ('full_name', 'first_name', 'last_name', 'name'):
                vals = meta_fields.get(key, [])
                if vals:
                    name_parts.append(str(vals[0]))
                    break
            if name_parts:
                lead_vals['contact_name'] = name_parts[0]
            else:
                lead_vals['contact_name'] = 'Meta Lead %s' % self.leadgen_id

        # Ensure name field (crm.lead required)
        if 'name' not in lead_vals:
            lead_vals['name'] = lead_vals.get('contact_name', 'Meta Lead %s' % self.leadgen_id)

        try:
            return self.env['crm.lead'].create(lead_vals)
        except Exception as e:
            self._mark_error('Failed to create CRM lead: %s' % str(e))
            return None

    def _mark_error(self, message):
        """Set status to Error with message."""
        self.write({
            'status': 'Error',
            'error_message': message,
            'retry_count': self.retry_count + 1,
        })
        _logger.warning('Meta lead %s processing error: %s', self.leadgen_id, message)

    @api.model
    def _cron_process_pending(self):
        """Cron: pick up pending/errored leads that haven't exceeded retry limit."""
        pending = self.search([
            ('status', 'in', ('Pending', 'Error')),
            ('retry_count', '<', 3),
        ])
        for log in pending:
            log._process_lead()
        return len(pending)
