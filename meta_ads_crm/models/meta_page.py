import logging
import requests

from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class MetaPage(models.Model):
    _name = 'meta.page'
    _description = 'Meta Page'
    _rec_name = 'name'

    page_id = fields.Char(string='Page ID', required=True, index=True)
    name = fields.Char(string='Name', required=True)
    category = fields.Char(string='Category')
    access_token_encrypted = fields.Text(string='Encrypted Page Token')
    fb_user_id = fields.Char(string='Facebook User ID')
    webhook_subscribed = fields.Boolean(string='Webhook Subscribed', default=False)
    ig_connected = fields.Boolean(string='IG Connected', default=False)
    active = fields.Boolean(default=True)

    ig_account_ids = fields.One2many('meta.ig.account', 'page_id', string='Instagram Accounts')
    lead_form_ids = fields.One2many('meta.lead.form', 'page_id', string='Lead Forms')

    def decrypt_token(self):
        """Decrypt the Fernet-encrypted page access token."""
        self.ensure_one()
        if not self.access_token_encrypted:
            return False
        try:
            from cryptography.fernet import Fernet
            fernet_key = self.env['ir.config_parameter'].sudo().get_param('meta.fernet_key')
            if not fernet_key:
                return False
            fernet = Fernet(fernet_key.encode() if isinstance(fernet_key, str) else fernet_key)
            token = self.access_token_encrypted
            if isinstance(token, str):
                token = token.encode()
            decrypted = fernet.decrypt(token)
            return decrypted.decode()
        except Exception as e:
            _logger.warning('Failed to decrypt page token for %s: %s', self.page_id, e)
            return False


    def action_subscribe_webhook(self):
        """Subscribe this Facebook Page to the app's leadgen webhook field."""
        self.ensure_one()
        access_token = self.decrypt_token()
        if not access_token:
            raise UserError('No valid access token for this page. Re-authorize via Settings.')

        graph_version = self.env['ir.config_parameter'].sudo().get_param(
            'meta.graph_version', 'v26.0'
        )
        url = 'https://graph.facebook.com/%s/%s/subscribed_apps' % (graph_version, self.page_id)
        try:
            resp = requests.post(url, data={
                'access_token': access_token,
                'subscribed_fields': 'leadgen',
            }, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            detail = getattr(e.response, 'text', '') if getattr(e, 'response', None) is not None else ''
            raise UserError('Meta webhook subscription failed: %s %s' % (str(e), detail))

        if not data.get('success'):
            raise UserError('Meta did not confirm the webhook subscription: %s' % data)

        self.webhook_subscribed = True
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Webhook Subscribed',
                'message': 'Page %s is subscribed to leadgen.' % self.name,
                'type': 'success',
                'sticky': False,
            }
        }

    def action_check_webhook_subscription(self):
        """Check whether this Page is subscribed to the app and leadgen field."""
        self.ensure_one()
        access_token = self.decrypt_token()
        if not access_token:
            raise UserError('No valid access token for this page. Re-authorize via Settings.')

        graph_version = self.env['ir.config_parameter'].sudo().get_param(
            'meta.graph_version', 'v26.0'
        )
        url = 'https://graph.facebook.com/%s/%s/subscribed_apps' % (graph_version, self.page_id)
        try:
            resp = requests.get(url, params={
                'access_token': access_token,
                'fields': 'id,name,subscribed_fields',
            }, timeout=30)
            resp.raise_for_status()
            data = resp.json().get('data', [])
        except requests.RequestException as e:
            detail = getattr(e.response, 'text', '') if getattr(e, 'response', None) is not None else ''
            raise UserError('Could not check Meta webhook subscription: %s %s' % (str(e), detail))

        subscribed = any('leadgen' in (item.get('subscribed_fields') or []) for item in data)
        self.webhook_subscribed = subscribed
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Webhook Subscription',
                'message': 'Subscribed to leadgen.' if subscribed else 'Not subscribed to leadgen.',
                'type': 'success' if subscribed else 'warning',
                'sticky': False,
            }
        }

    def action_sync_forms(self):
        """Fetch lead forms from Meta Graph API and create/update local records."""
        self.ensure_one()
        access_token = self.decrypt_token()
        if not access_token:
            raise UserError('No valid access token for this page. Re-authorize via Settings.')

        graph_version = self.env['ir.config_parameter'].sudo().get_param(
            'meta.graph_version', 'v26.0'
        )
        url = 'https://graph.facebook.com/%s/%s/leadgen_forms' % (graph_version, self.page_id)
        params = {
            'access_token': access_token,
            'fields': 'id,name,status,locale,questions,privacy_policy,thank_you_page,follow_up',
        }
        try:
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            raise UserError('Meta API request failed: %s' % str(e))

        forms = data.get('data', [])
        created, updated = 0, 0
        for form_data in forms:
            meta_form_id = str(form_data.get('id', ''))
            questions = form_data.get('questions', [])

            vals = {
                'form_id': meta_form_id,
                'name': form_data.get('name', 'Form %s' % meta_form_id),
                'status': form_data.get('status', 'ACTIVE'),
                'locale': form_data.get('locale', ''),
                'page_id': self.id,
                'questions_json': form_data,
            }

            existing = self.env['meta.lead.form'].search([('form_id', '=', meta_form_id)], limit=1)
            if existing:
                existing.write(vals)
                updated += 1
                # Sync field mappings from questions
                existing._sync_field_mappings(questions)
            else:
                form_rec = self.env['meta.lead.form'].create(vals)
                form_rec._sync_field_mappings(questions)
                created += 1

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Lead Forms Synced',
                'message': '%d created, %d updated' % (created, updated),
                'sticky': False,
            }
        }



