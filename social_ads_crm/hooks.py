from odoo import api, SUPERUSER_ID

def post_init_hook(env):
    # Odoo 17 passes env to post_init_hook. Keep additive migration only.
    if not hasattr(env, '__getitem__'):
        env = api.Environment(env, SUPERUSER_ID, {})
    env['social.lead.form'].sudo()._migrate_legacy_meta()
    env['social.lead.log'].sudo()._migrate_legacy_meta_logs()
