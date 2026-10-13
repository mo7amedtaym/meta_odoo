from odoo import fields, models

class SocialLeadFormFieldMap(models.Model):
    _name = 'social.lead.form.field.map'
    _description = 'Social Lead Form Field Mapping'
    _order = 'sequence, id'

    form_id = fields.Many2one('social.lead.form', required=True, ondelete='cascade', index=True)
    external_key = fields.Char(required=True)
    external_label = fields.Char()
    aliases = fields.Char()
    odoo_field_name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)
    _sql_constraints = [('social_form_map_key_uniq','unique(form_id, external_key)','A mapping already exists for this form field.')]
