import json
import logging
from odoo import api, fields, models, _, Command
from odoo.exceptions import UserError
from ..lib.core import normalize_key, default_odoo_field

_logger = logging.getLogger(__name__)

class SocialLeadForm(models.Model):
    _name = 'social.lead.form'
    _description = 'Social Lead Form'
    _inherit = ['mail.thread','social.ads.secret.mixin']
    _order = 'provider, name'

    provider = fields.Selection([('meta','Meta'),('snapchat','Snapchat')], required=True, index=True)
    connection_id = fields.Many2one('social.ads.connection', ondelete='cascade', index=True)
    ad_account_id = fields.Many2one('social.ads.account', ondelete='set null', index=True)
    external_form_id = fields.Char(required=True, index=True)
    name = fields.Char(required=True)
    status = fields.Char(default='ACTIVE')
    questions_json = fields.Json()
    privacy_policy_url = fields.Char()
    import_mode = fields.Selection([('lead','Lead'),('opportunity','Opportunity')], default='lead', required=True)
    stage_id = fields.Many2one('crm.stage', string='Opportunity Stage')
    team_id = fields.Many2one('crm.team', string='Sales Team')
    tag_ids = fields.Many2many('crm.tag', string='Tags')
    notify_on_new_lead = fields.Boolean(default=True)
    notification_user_ids = fields.Many2many('res.users','social_form_notify_user_rel','form_id','user_id', string='Users to Notify')
    notify_assigned_salesperson = fields.Boolean(default=True)
    create_notification_activity = fields.Boolean(default=False)
    auto_mapping_enabled = fields.Boolean(default=True)
    unmapped_field_policy = fields.Selection([('notes','Append to Notes'),('ignore','Ignore')], default='notes')
    mapping_ids = fields.One2many('social.lead.form.field.map','form_id', string='Field Mapping')
    webhook_status = fields.Selection([('not_registered','Not Registered'),('active','Active'),('external','External Webhook'),('error','Error')], default='not_registered')
    webhook_integration_id = fields.Char(readonly=True)
    webhook_secret_encrypted = fields.Text(groups='social_ads_crm.group_social_ads_manager')
    webhook_url = fields.Char(readonly=True)
    last_lead_time = fields.Datetime(readonly=True)
    last_sync_at = fields.Datetime(readonly=True)
    last_error = fields.Text(readonly=True)
    test_pending_until = fields.Datetime(readonly=True)
    legacy_meta_form_id = fields.Many2one('meta.lead.form', ondelete='set null', index=True)
    _sql_constraints = [('social_form_provider_ext_uniq','unique(provider, external_form_id)','This provider form is already imported.')]

    @api.model
    def _normalize_external_key(self, key):
        return normalize_key(key)

    def _prepare_crm_values(self, normalized_payload):
        self.ensure_one()
        values = {'type': self.import_mode, 'team_id': self.team_id.id or False}
        if self.import_mode == 'opportunity' and self.stage_id:
            values['stage_id'] = self.stage_id.id
        if self.tag_ids:
            values['tag_ids'] = [Command.set(self.tag_ids.ids)]
        if self.team_id and self.team_id.user_id:
            values['user_id'] = self.team_id.user_id.id
        else:
            values['user_id'] = False
        fields_payload = normalized_payload.get('fields') or {}
        explicit = {}
        for line in self.mapping_ids.filtered('active'):
            keys = [line.external_key] + [x.strip() for x in (line.aliases or '').split(',') if x.strip()]
            for key in keys:
                explicit[normalize_key(key)] = line.odoo_field_name
        unmapped = []
        for key, value in fields_payload.items():
            nkey = normalize_key(key)
            target = explicit.get(nkey) or (default_odoo_field(nkey) if self.auto_mapping_enabled else None)
            if target and target in self.env['crm.lead']._fields and target not in ('id','create_uid','write_uid'):
                values[target] = value
            elif value not in (None, False, ''):
                unmapped.append('%s: %s' % (key, value))
        if not values.get('contact_name'):
            values['contact_name'] = values.get('partner_name') or _('Social Lead')
        values.setdefault('name', values.get('contact_name') or _('Social Lead'))
        if unmapped and self.unmapped_field_policy == 'notes':
            values['description'] = (values.get('description') or '') + '\n\n' + '\n'.join(unmapped)
        return values

    def _import_mapping_candidates(self, form_fields):
        self.ensure_one()
        existing = {normalize_key(x.external_key) for x in self.mapping_ids}
        for index, field in enumerate(form_fields or []):
            ftype = field.get('type') or ''
            if ftype == 'CUSTOM':
                props = field.get('custom_form_field_properties') or {}
                label = props.get('description') or 'custom_%s' % index
                key = 'custom_%s' % index
            else:
                label = ftype.replace('_',' ').title()
                key = ftype
            nkey = normalize_key(key)
            target = default_odoo_field(nkey)
            if nkey not in existing and target:
                self.env['social.lead.form.field.map'].create({'form_id':self.id,'external_key':key,'external_label':label,'odoo_field_name':target})
                existing.add(nkey)

    def action_register_webhook(self):
        for rec in self:
            rec.connection_id._get_provider_service().register_webhook(rec)
        return True
    def action_delete_webhook(self):
        for rec in self:
            rec.connection_id._get_provider_service().delete_webhook(rec)
        return True
    def action_send_test_lead(self):
        for rec in self:
            rec.connection_id._get_provider_service().send_test_lead(rec)
        return True

    @api.model
    def _migrate_legacy_meta(self):
        legacy_forms = self.env['meta.lead.form'].sudo().search([])
        for old in legacy_forms:
            rec = self.search([('provider','=','meta'),('external_form_id','=',old.form_id)], limit=1)
            vals = {'provider':'meta','external_form_id':old.form_id,'name':old.name or old.form_id,
                    'status':old.status or 'ACTIVE','questions_json':old.questions_json,'privacy_policy_url':old.privacy_policy_url,
                    'import_mode':old.import_mode or 'lead','stage_id':old.stage_id.id or False,'team_id':old.team_id.id or False,
                    'tag_ids':[Command.set(old.tag_ids.ids)],'legacy_meta_form_id':old.id,
                    'notify_on_new_lead':old.notify_on_new_lead,
                    'notification_user_ids':[Command.set(old.notification_user_ids.ids)],
                    'notify_assigned_salesperson':old.notify_assigned_salesperson,
                    'create_notification_activity':old.create_notification_activity,
                    'auto_mapping_enabled':old.auto_mapping_enabled,
                    'unmapped_field_policy':old.unmapped_field_policy or 'notes'}
            rec.write(vals) if rec else None
            rec = rec or self.create(vals)
            existing_keys = {normalize_key(x.external_key) for x in rec.mapping_ids}
            for line in old.field_mapping_ids:
                key = normalize_key(line.meta_key)
                if key in existing_keys or not line.odoo_field_name:
                    continue
                self.env['social.lead.form.field.map'].create({
                    'form_id': rec.id, 'external_key': line.meta_key, 'external_label': line.meta_label,
                    'aliases': line.meta_aliases, 'odoo_field_name': line.odoo_field_name,
                    'active': line.active, 'sequence': line.sequence,
                })
                existing_keys.add(key)
