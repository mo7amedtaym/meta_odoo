from odoo import models, fields

class PreviewWizard(models.TransientModel):
    _name = 'preview.wizard'
    _description = 'Preview Wizard'

    preview_html = fields.Html(string='Preview HTML', readonly=True)
    
    def action_close(self):
        return {'type': 'ir.actions.act_window_close'}
