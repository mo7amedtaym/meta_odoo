from odoo import api, models, Command

class MetaLeadFormBridge(models.Model):
    _inherit = 'meta.lead.form'

    def _prepare_crm_lead_values(self, lead_data):
        vals = super()._prepare_crm_lead_values(lead_data)
        # Standard Odoo assignment policy: team leader first, never a form-level salesperson.
        if self.team_id:
            vals['team_id'] = self.team_id.id
            vals['user_id'] = self.team_id.user_id.id if self.team_id.user_id else False
        else:
            vals.pop('user_id', None)
        return vals

    def _sync_social_form(self):
        SocialForm = self.env['social.lead.form'].sudo()
        for old in self:
            if not old.form_id:
                continue
            rec = SocialForm.search([('provider','=','meta'),('external_form_id','=',old.form_id)], limit=1)
            vals = {
                'provider':'meta','external_form_id':old.form_id,'name':old.name or old.form_id,
                'status':old.status or 'ACTIVE','questions_json':old.questions_json,
                'privacy_policy_url':old.privacy_policy_url,'import_mode':old.import_mode or 'lead',
                'stage_id':old.stage_id.id or False,'team_id':old.team_id.id or False,
                'tag_ids':[Command.set(old.tag_ids.ids)],'legacy_meta_form_id':old.id,
                'notify_on_new_lead':old.notify_on_new_lead,
                'notification_user_ids':[Command.set(old.notification_user_ids.ids)],
                'notify_assigned_salesperson':old.notify_assigned_salesperson,
                'create_notification_activity':old.create_notification_activity,
                'auto_mapping_enabled':old.auto_mapping_enabled,
                'unmapped_field_policy':old.unmapped_field_policy or 'notes',
            }
            rec.write(vals) if rec else SocialForm.create(vals)
        return True

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._sync_social_form()
        return records

    def write(self, vals):
        result = super().write(vals)
        watched = {'form_id','name','status','questions_json','privacy_policy_url','import_mode','stage_id','team_id','tag_ids',
                   'notify_on_new_lead','notification_user_ids','notify_assigned_salesperson','create_notification_activity',
                   'auto_mapping_enabled','unmapped_field_policy'}
        if watched.intersection(vals):
            self._sync_social_form()
        return result

class MetaLeadLogBridge(models.Model):
    _inherit = 'meta.lead.log'

    def _process_lead(self):
        result = super()._process_lead()
        for rec in self:
            if not rec.leadgen_id:
                continue
            generic_form = self.env['social.lead.form'].sudo().search([
                ('provider','=','meta'),('external_form_id','=',rec.form_id.form_id if rec.form_id else '')
            ], limit=1)
            Log = self.env['social.lead.log'].sudo()
            log = Log.search([('provider','=','meta'),('external_lead_id','=',rec.leadgen_id)], limit=1)
            vals = {
                'provider':'meta','external_lead_id':rec.leadgen_id,'form_id':generic_form.id if generic_form else False,
                'external_campaign_id':rec.campaign_id,'external_ad_id':rec.ad_id,'payload_json':rec.payload_json,
                'status':'created' if rec.crm_lead_id else ('error' if rec.status == 'Error' else 'pending'),
                'crm_lead_id':rec.crm_lead_id.id if rec.crm_lead_id else False,
                'error_message':rec.error_message or False,
            }
            log.write(vals) if log else None
            log = log or Log.create(vals)
            if rec.crm_lead_id:
                rec.crm_lead_id.sudo().write({
                    'social_provider':'meta','social_external_lead_id':rec.leadgen_id,
                    'social_form_id':generic_form.id if generic_form else False,
                    'social_lead_log_id':log.id,'social_raw_data':rec.payload_json,
                })
        return result
