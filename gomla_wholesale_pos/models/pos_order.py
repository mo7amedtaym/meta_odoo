from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.tools import float_compare

from .gomla_shipment import FINAL_ORDER_STATES


class PosOrderLine(models.Model):
    _inherit = "pos.order.line"

    gomla_shipment_id = fields.Many2one(
        "gomla.shipment", string="Shipment", ondelete="restrict", index=True
    )
    gomla_shipment_line_id = fields.Many2one(
        "gomla.shipment.line", string="Shipment Line", ondelete="restrict", index=True
    )
    gomla_weight = fields.Float(string="Weight", digits="Product Unit")
    gomla_count = fields.Integer(string="Package / Box Count")
    gomla_seller_commission = fields.Monetary(
        string="Seller Commission / بياعة", currency_field="currency_id"
    )
    gomla_crate_qty = fields.Integer(string="Crate Quantity")
    gomla_crate_deposit = fields.Monetary(
        string="Crate Deposit", currency_field="currency_id"
    )
    gomla_charge_type = fields.Selection(
        [
            ("goods", "Goods"),
            ("seller_commission", "Seller Commission"),
            ("crate_deposit", "Crate Deposit"),
        ],
        default="goods",
        required=True,
        index=True,
    )
    gomla_source_line_uuid = fields.Char(string="Source Goods Line UUID", index=True)

    @api.model
    def _load_pos_data_fields(self, config):
        return super()._load_pos_data_fields(config) + [
            "gomla_shipment_id",
            "gomla_shipment_line_id",
            "gomla_weight",
            "gomla_count",
            "gomla_seller_commission",
            "gomla_crate_qty",
            "gomla_crate_deposit",
            "gomla_charge_type",
            "gomla_source_line_uuid",
        ]

    @api.constrains("gomla_shipment_line_id", "gomla_shipment_id", "product_id")
    def _check_gomla_shipment_line(self):
        for line in self.filtered(lambda item: item.gomla_shipment_line_id):
            if line.gomla_shipment_line_id.shipment_id != line.gomla_shipment_id:
                raise ValidationError(_("The shipment line does not belong to the selected shipment."))
            if line.gomla_shipment_line_id.product_id != line.product_id:
                raise ValidationError(_("The selected shipment line belongs to another product."))


class PosOrder(models.Model):
    _inherit = "pos.order"

    gomla_goods_total = fields.Monetary(compute="_compute_gomla_totals", string="Goods Total")
    gomla_seller_commission_total = fields.Monetary(
        compute="_compute_gomla_totals", string="Seller Commission Total"
    )
    gomla_crate_deposit_total = fields.Monetary(
        compute="_compute_gomla_totals", string="Crate Deposit Total"
    )

    @api.depends(
        "lines.price_subtotal_incl",
        "lines.gomla_charge_type",
        "lines.gomla_seller_commission",
        "lines.gomla_crate_deposit",
    )
    def _compute_gomla_totals(self):
        for order in self:
            goods = order.lines.filtered(lambda line: line.gomla_charge_type == "goods")
            order.gomla_goods_total = sum(goods.mapped("price_subtotal_incl"))
            order.gomla_seller_commission_total = sum(goods.mapped("gomla_seller_commission"))
            order.gomla_crate_deposit_total = sum(goods.mapped("gomla_crate_deposit"))

    @api.model_create_multi
    def create(self, vals_list):
        orders = super().create(vals_list)
        orders._gomla_lock_and_validate()
        orders._gomla_refresh_shipments()
        return orders

    def write(self, vals):
        result = super().write(vals)
        if "state" in vals or "lines" in vals:
            self._gomla_lock_and_validate()
            self._gomla_refresh_shipments()
        return result

    def _gomla_lock_and_validate(self):
        orders = self.filtered(
            lambda order: order.config_id.gomla_pos_enabled and order.state in FINAL_ORDER_STATES
        )
        shipment_line_ids = orders.lines.gomla_shipment_line_id.ids
        if shipment_line_ids:
            self.env.cr.execute(
                "SELECT id FROM gomla_shipment_line WHERE id = ANY(%s) FOR UPDATE",
                [shipment_line_ids],
            )
        for order in orders:
            goods_lines = order.lines.filtered(
                lambda line: line.gomla_charge_type == "goods" and line.product_id.type != "service"
            )
            if order.config_id.gomla_require_shipment:
                missing = goods_lines.filtered(lambda line: not line.gomla_shipment_line_id)
                if missing:
                    raise ValidationError(
                        _("A shipment is required for: %s")
                        % ", ".join(missing.mapped("product_id.display_name"))
                    )
            for line in goods_lines.filtered("gomla_shipment_line_id"):
                if line.gomla_shipment_id.state not in ("active", "nearly_finished"):
                    raise ValidationError(_("The selected shipment is not available for sale."))
                other_lines = self.env["pos.order.line"].search([
                    ("id", "!=", line.id),
                    ("gomla_shipment_line_id", "=", line.gomla_shipment_line_id.id),
                    ("gomla_charge_type", "=", "goods"),
                    ("order_id.state", "in", FINAL_ORDER_STATES),
                ])
                available = line.gomla_shipment_line_id.received_qty - sum(other_lines.mapped("qty"))
                if float_compare(line.qty, available, precision_digits=4) > 0:
                    raise ValidationError(
                        _("Shipment %(shipment)s only has %(quantity)s available for %(product)s.")
                        % {
                            "shipment": line.gomla_shipment_id.name,
                            "quantity": available,
                            "product": line.product_id.display_name,
                        }
                    )

    def _gomla_refresh_shipments(self):
        self.lines.gomla_shipment_id._refresh_state()

