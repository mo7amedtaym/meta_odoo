from odoo import api, fields, models


class PosConfig(models.Model):
    _inherit = "pos.config"

    gomla_pos_enabled = fields.Boolean(string="Enable Gomla Wholesale Mode")
    gomla_require_shipment = fields.Boolean(
        string="Require Shipment for Stockable Products", default=True
    )
    gomla_nearly_finished_percent = fields.Float(
        string="Nearly Finished Threshold %", default=10.0
    )
    gomla_seller_commission_product_id = fields.Many2one(
        "product.product",
        string="Seller Commission Product",
        domain="[('available_in_pos', '=', True), ('type', '=', 'service')]",
        default=lambda self: self.env["product.product"].search(
            [("default_code", "=", "GOMLA-BAYAA")], limit=1
        ),
    )
    gomla_crate_deposit_product_id = fields.Many2one(
        "product.product",
        string="Crate Deposit Product",
        domain="[('available_in_pos', '=', True), ('type', '=', 'service')]",
        default=lambda self: self.env["product.product"].search(
            [("default_code", "=", "GOMLA-CRATE-DEPOSIT")], limit=1
        ),
    )
    gomla_default_crate_deposit = fields.Monetary(
        string="Default Deposit per Crate", currency_field="currency_id"
    )

    @api.model
    def _load_pos_data_fields(self, config):
        fields_to_load = super()._load_pos_data_fields(config)
        return fields_to_load + [
            "gomla_pos_enabled",
            "gomla_require_shipment",
            "gomla_nearly_finished_percent",
            "gomla_seller_commission_product_id",
            "gomla_crate_deposit_product_id",
            "gomla_default_crate_deposit",
        ]


class PosSession(models.Model):
    _inherit = "pos.session"

    @api.model
    def _load_pos_data_models(self, config):
        models_to_load = super()._load_pos_data_models(config)
        if config.gomla_pos_enabled:
            models_to_load += ["gomla.shipment", "gomla.shipment.line"]
        return models_to_load
