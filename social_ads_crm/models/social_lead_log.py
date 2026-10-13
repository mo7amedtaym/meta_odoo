import logging
from datetime import timedelta
from psycopg2 import IntegrityError
from odoo import api, fields, models, _, Command

_logger = logging.getLogger(__name__)

class SocialLeadLog(models.Model):
    _name = 'social.lead.log'
    _description = 'Social Lead Log'
    _order = 'received_at desc, id desc'

    provider = fields.Selection([('meta','Meta'),('snapchat','Snapchat')], required=True, index=True)
    external_lead_id = fields.Char(required=True, index=True)
    form_id = fields.Many2one('social.lead.form', ondelete='set null', index=True)
    ad_account_id = fields.Many2one('social.ads.account', ondelete='set null')
    external_campaign_id = fields.Char()
    campaign_name = fields.Char()
    external_adgroup_id = fields.Char()
    adgroup_name = fields.Char()
    external_ad_id = fields.Char()
    ad_name = fields.Char()
    received_at = fields.Datetime(default=fields.Datetime.now, index=True)
    payload_json = fields.Json(groups='social_ads_crm.group_social_ads_manager')
    normalized_json = fields.Json(groups='social_ads_crm.group_social_ads_manager')
    status = fields.Selection([('pending','Pending'),('created','Created'),('duplicate','Duplicate'),('error','Error')], default='pending', index=True)
    retry_count = fields.Integer(default=0)
    next_retry_at = fields.Datetime(index=True)
    permanent_error = fields.Boolean(default=False, index=True)
    error_code = fields.Char()
    error_message = fields.Text()
    crm_lead_id = fields.Many2one('crm.lead', ondelete='set null')
    _sql_constraints = [('social_lead_provider_external_uniq','unique(provider, external_lead_id)','This social lead was already received.')]

    def _process_normalized_lead(self, normalized_payload=None):
        self.ensure_one()
        payload = normalized_payload or self.normalized_json or {}
        if self.crm_lead_id:
            self.status = 'duplicate'
            return self.crm_lead_id
        if not self.form_id:
            self.write({'status':'error','permanent_error':True,'error_code':'missing_form','error_message':'Lead form is not configured.'})
            return False
        vals = self.form_id._prepare_crm_values(payload)
        vals.update({'social_provider':self.provider,'social_external_lead_id':self.external_lead_id,
                     'social_form_id':self.form_id.id,'social_lead_log_id':self.id,
                     'social_raw_data':self.payload_json or payload.get('raw')})
        lead = self.env['crm.lead'].sudo().create(vals)
        self.write({'crm_lead_id':lead.id,'status':'created','error_code':False,'error_message':False,
                    'permanent_error':False,'next_retry_at':False})
        self.form_id.last_lead_time = fields.Datetime.now()
        self._notify_new_lead(lead)
        return lead

    def _notify_new_lead(self, lead):
        form = self.form_id
        if not form.notify_on_new_lead:
            return
        users = form.notification_user_ids
        if form.notify_assigned_salesperson and lead.user_id:
            users |= lead.user_id
        partners = users.mapped('partner_id')
        if partners:
            lead.message_post(body=_('New %s lead received from social ads.') % self.provider.title(), partner_ids=partners.ids)

    def _mark_retryable_error(self, code, message):
        self.ensure_one()
        retries = self.retry_count + 1
        self.write({'status':'error','retry_count':retries,'permanent_error':False,'error_code':str(code or ''),
                    'error_message':str(message or '')[:2000], 'next_retry_at': fields.Datetime.now() + timedelta(minutes=min(60, 2 ** min(retries, 5)))})

    @api.model
    def _migrate_legacy_meta_logs(self):
        Form = self.env['social.lead.form'].sudo()
        for old in self.env['meta.lead.log'].sudo().search([]):
            if not old.leadgen_id:
                continue
            rec = self.search([('provider','=','meta'),('external_lead_id','=',old.leadgen_id)], limit=1)
            form = Form.search([('provider','=','meta'),('external_form_id','=',old.form_id.form_id if old.form_id else '')], limit=1)
            vals = {
                'provider':'meta','external_lead_id':old.leadgen_id,'form_id':form.id if form else False,
                'external_campaign_id':old.campaign_id,'external_ad_id':old.ad_id,'payload_json':old.payload_json,
                'status':'created' if old.crm_lead_id else ('error' if old.status == 'Error' else ('duplicate' if old.status == 'Duplicate' else 'pending')),
                'crm_lead_id':old.crm_lead_id.id if old.crm_lead_id else False,
                'error_message':old.error_message or False,'retry_count':old.retry_count or 0,
                'received_at':old.created_date or fields.Datetime.now(),
            }
            rec.write(vals) if rec else None
            rec = rec or self.create(vals)
            if old.crm_lead_id:
                old.crm_lead_id.sudo().write({
                    'social_provider':'meta','social_external_lead_id':old.leadgen_id,
                    'social_form_id':form.id if form else False,'social_lead_log_id':rec.id,
                    'social_raw_data':old.payload_json,
                })

    @api.model
    def _cron_retry_errors(self):
        domain = [('status','=','error'),('permanent_error','=',False),('retry_count','<',6),
                  '|',('next_retry_at','=',False),('next_retry_at','<=',fields.Datetime.now())]
        for log in self.search(domain, limit=100):
            try:
                log._process_normalized_lead()
            except Exception as exc:
                _logger.exception('Retry failed for social lead %s', log.external_lead_id)
                log._mark_retryable_error('retry_error', exc)
