import logging
from odoo import models, _
from odoo.exceptions import UserError
_logger = logging.getLogger(__name__)

class SocialSecretMixin(models.AbstractModel):
    _name = 'social.ads.secret.mixin'
    _description = 'Social Ads Secret Encryption'

    def _get_fernet(self):
        try:
            from cryptography.fernet import Fernet
        except ImportError as exc:
            raise UserError(_('Python package cryptography is required.')) from exc
        icp = self.env['ir.config_parameter'].sudo()
        key = icp.get_param('meta.fernet_key') or icp.get_param('social_ads.fernet_key')
        if not key:
            key = Fernet.generate_key().decode()
            # Reuse legacy Meta key namespace to preserve ciphertext compatibility.
            icp.set_param('meta.fernet_key', key)
            icp.set_param('social_ads.fernet_key', key)
        return Fernet(key.encode() if isinstance(key, str) else key)

    def _encrypt_secret(self, value):
        if not value:
            return False
        return self._get_fernet().encrypt(str(value).encode()).decode()

    def _decrypt_secret(self, value):
        if not value:
            return False
        try:
            return self._get_fernet().decrypt(str(value).encode()).decode()
        except Exception as exc:
            _logger.warning('Unable to decrypt social ads secret: %s', exc.__class__.__name__)
            return False
