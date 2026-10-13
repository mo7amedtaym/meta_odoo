from odoo import api, fields, models


class CrmStage(models.Model):
    _inherit = 'crm.stage'

    is_meta_default_stage = fields.Boolean(
        string='Meta Default',
        copy=False,
        help='Use this stage for opportunities created from Meta Lead Ads. Only one stage can be selected.',
    )

    @api.model
    def _get_meta_default_stage(self):
        return self.search([('is_meta_default_stage', '=', True)], limit=1)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        selected = records.filtered('is_meta_default_stage')
        if selected:
            # If several stages are created at once, the last selected one wins.
            winner = selected[-1]
            (self.search([
                ('is_meta_default_stage', '=', True),
                ('id', '!=', winner.id),
            ])).write({'is_meta_default_stage': False})
        return records

    def write(self, vals):
        result = super().write(vals)
        if vals.get('is_meta_default_stage'):
            # A checkbox in the stage list behaves as a single global selection.
            winner = self[-1]
            others = self.search([
                ('is_meta_default_stage', '=', True),
                ('id', '!=', winner.id),
            ])
            if others:
                super(CrmStage, others).write({'is_meta_default_stage': False})
        return result
