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
        graph_version = (self.env['ir.config_parameter'].sudo().get_param(
            'meta.graph_version', 'v26.0'
        ) or 'v26.0').strip()
        if not graph_version.startswith('v'):
            graph_version = 'v%s' % graph_version
        url = 'https://graph.facebook.com/%s/%s' % (graph_version, self.leadgen_id)
        params = {'access_token': access_token}
        try:
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            response = getattr(e, 'response', None)
            detail = 'Network error while contacting Meta.'
            if response is not None:
                try:
                    payload = response.json()
                    error = payload.get('error', {}) if isinstance(payload, dict) else {}
                    detail = 'Meta API error: %s (code=%s, subcode=%s, trace=%s)' % (
                        error.get('message') or 'Unknown error',
                        error.get('code'),
                        error.get('error_subcode'),
                        error.get('fbtrace_id'),
                    )
                except Exception:
                    detail = 'Meta API returned HTTP %s.' % response.status_code
            self._mark_error(detail)
            return None

    def _create_crm_lead(self, lead_data):
        """Map Meta field_data to CRM lead fields and create the record."""
        if not self.form_id:
            self._mark_error(
                'No linked lead form. Create/sync a meta.lead.form record for form_id "%s".'
                % (lead_data.get('form_id', '?'))
            )
            return None

        form = self.form_id
        lead_vals = form._prepare_crm_lead_values(lead_data)

        # Set type and defaults configured on the Meta form.
        lead_vals['type'] = 'lead' if form.import_mode == 'lead' else 'opportunity'
        if form.team_id:
            lead_vals.setdefault('team_id', form.team_id.id)
        if form.user_id:
            lead_vals.setdefault('user_id', form.user_id.id)
        if form.tag_ids:
            lead_vals['tag_ids'] = [(6, 0, form.tag_ids.ids)]

        # Meta traceability fields.
        lead_vals.update({
            'meta_leadgen_id': self.leadgen_id,
            'meta_form_id': form.id,
            'meta_campaign_id': self.campaign_id or lead_data.get('campaign_id') or False,
            'meta_ad_id': self.ad_id or lead_data.get('ad_id') or False,
            'meta_platform': self.platform or lead_data.get('platform') or 'facebook',
            'meta_raw_data': lead_data,
            'is_meta_lead': True,
        })

        # crm.lead.name is required; use meaningful customer data whenever possible.
        if not lead_vals.get('name'):
            lead_vals['name'] = (
                lead_vals.get('contact_name')
                or lead_vals.get('partner_name')
                or lead_vals.get('email_from')
                or 'Meta Lead %s' % self.leadgen_id
            )

        try:
            lead = self.env['crm.lead'].create(lead_vals)
            form.last_lead_time = fields.Datetime.now()
            return lead
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
