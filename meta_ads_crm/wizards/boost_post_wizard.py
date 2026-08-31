from odoo import models, fields

class BoostPostWizard(models.TransientModel):
    _name = 'boost.post.wizard'
    _description = 'Boost Post Wizard'

    post_id = fields.Many2one('meta.post', string='Source Post', required=True)
    ad_account_id = fields.Many2one('meta.ad.account', string='Ad Account', required=True)
    objective = fields.Selection([
        ('OUTCOME_ENGAGEMENT', 'Engagement'),
        ('OUTCOME_TRAFFIC', 'Traffic'),
        ('OUTCOME_LEADS', 'Leads')
    ], string='Campaign Objective', required=True)
    
    daily_budget = fields.Float(string='Daily Budget', required=True)
    start_time = fields.Datetime(string='Start Time', required=True)
    end_time = fields.Datetime(string='End Time')

    def action_confirm_boost(self):
        # Implementation for creating Campaign -> AdSet -> Creative -> Ad chain
        # 1. Create Campaign
        # 2. Create AdSet
        # 3. Create Ad Creative with object_story_id to preserve engagement
        # 4. Create Ad
        # 5. Create meta.promotion record linking them all
        
        # Mock logic
        self.env['meta.promotion'].create({
            'name': f'Boost of {self.post_id.name or "Post"}',
            'source_post_id': self.post_id.id,
            'budget': self.daily_budget,
            'schedule_start': self.start_time,
            'schedule_end': self.end_time,
            'status': 'Paused' # As requested, PAUSED by default
        })
        return {'type': 'ir.actions.act_window_close'}
