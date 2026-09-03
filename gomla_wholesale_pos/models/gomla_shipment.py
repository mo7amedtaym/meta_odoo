from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare


FINAL_ORDER_STATES = ("paid", "done", "invoiced")


class GomlaShipment(models.Model):
    _name = "gomla.shipment"
    _description = "Wholesale Produce Shipment"
    _inherit = ["mail.thread", "mail.activity.mixin", "pos.load.mixin"]
    _order = "arrival_date desc, id desc"

    name = fields.Char(
        string="Shipment Number", required=True, copy=False, default="New", tracking=True
    )
    supplier_id = fields.Many2one(
        "res.partner",
        string="Supplier",
        required=True,
        tracking=True,
        domain="[('gomla_is_supplier', '=', True)]",
    )
    arrival_date = fields.Datetime(
        string="Arrival Date", required=True, default=fields.Datetime.now, tracking=True
    )
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )
    currency_id = fields.Many2one(
        "res.currency", related="company_id.currency_id", store=True
    )
    state = fields.Selection(
        [
            ("active", "Active"),
            ("nearly_finished", "Nearly Finished"),
            ("stock_finished", "Stock Finished"),
            ("pending_settlement", "Pending Settlement"),
            ("settled", "Settled / Closed"),
        ],
        default="active",
        required=True,
        copy=False,
        tracking=True,
    )
    line_ids = fields.One2many(
        "gomla.shipment.line", "shipment_id", string="Produce Lines", copy=True
    )
    supplier_commission_percent = fields.Float(
        string="Supplier Commission %", digits=(12, 4), tracking=True
    )
    freight_amount = fields.Monetary(string="Freight", tracking=True)
    aqlamiya_amount = fields.Monetary(string="El-Aqlamiya", tracking=True)
    notes = fields.Text(string="Notes")
    stock_finished_at = fields.Datetime(string="Stock Finished At", readonly=True, copy=False)
    settlement_id = fields.One2many(
        "gomla.shipment.settlement", "shipment_id", string="Settlement", readonly=True
    )
    received_qty = fields.Float(compute="_compute_totals", string="Received Quantity")
    sold_qty = fields.Float(compute="_compute_totals", string="Sold Quantity")
    remaining_qty = fields.Float(compute="_compute_totals", string="Remaining Quantity")
    gross_sales_amount = fields.Monetary(compute="_compute_totals", string="Gross Sales")
    seller_commission_amount = fields.Monetary(
        compute="_compute_totals", string="Seller Commission / بياعة"
    )
    supplier_net_preview = fields.Monetary(
        compute="_compute_totals", string="Supplier Net Preview"
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = self.env["ir.sequence"].next_by_code("gomla.shipment") or "New"
            if vals.get("supplier_id") and "supplier_commission_percent" not in vals:
                supplier = self.env["res.partner"].browse(vals["supplier_id"])
                vals["supplier_commission_percent"] = supplier.gomla_default_commission_percent
        return super().create(vals_list)

    def write(self, vals):
        protected = {
            "supplier_id", "arrival_date", "line_ids", "supplier_commission_percent",
            "freight_amount", "aqlamiya_amount", "company_id",
        }
        if protected.intersection(vals) and self.filtered(lambda item: item.state == "settled"):
            raise UserError(_("A settled shipment is immutable."))
        if vals.get("state") == "settled" and not self.env.context.get("gomla_settlement_approval"):
            raise UserError(_("Use Approve and Close Settlement to close a shipment."))
        return super().write(vals)

    @api.onchange("supplier_id")
    def _onchange_supplier_id(self):
        if self.supplier_id:
            self.supplier_commission_percent = (
                self.supplier_id.gomla_default_commission_percent
            )

    @api.depends(
        "line_ids.received_qty",
        "supplier_commission_percent",
        "freight_amount",
        "aqlamiya_amount",
    )
    def _compute_totals(self):
        PosLine = self.env["pos.order.line"]
        for shipment in self:
            shipment.received_qty = sum(shipment.line_ids.mapped("received_qty"))
            sold_lines = PosLine.search([
                ("gomla_shipment_id", "=", shipment.id),
                ("gomla_charge_type", "=", "goods"),
                ("order_id.state", "in", FINAL_ORDER_STATES),
            ])
            shipment.sold_qty = sum(sold_lines.mapped("qty"))
            shipment.remaining_qty = shipment.received_qty - shipment.sold_qty
            shipment.gross_sales_amount = sum(sold_lines.mapped("price_subtotal_incl"))
            shipment.seller_commission_amount = sum(
                sold_lines.mapped("gomla_seller_commission")
            )
            supplier_commission = (
                shipment.gross_sales_amount * shipment.supplier_commission_percent / 100.0
            )
            shipment.supplier_net_preview = (
                shipment.gross_sales_amount
                - supplier_commission
                - shipment.freight_amount
                - shipment.aqlamiya_amount
            )

    def _refresh_state(self):
        for shipment in self.filtered(lambda item: item.state != "settled"):
            shipment._compute_totals()
            if not shipment.line_ids:
                continue
            if float_compare(shipment.remaining_qty, 0.0, precision_digits=4) <= 0:
                values = {"state": "pending_settlement"}
                if not shipment.stock_finished_at:
                    values["stock_finished_at"] = fields.Datetime.now()
                    shipment.message_post(
                        body=_("Shipment stock is finished and is ready for settlement.")
                    )
                shipment.write(values)
                continue
            ratio = shipment.remaining_qty / shipment.received_qty * 100.0 if shipment.received_qty else 0.0
            thresholds = self.env["pos.config"].sudo().search([
                ("company_id", "=", shipment.company_id.id),
                ("gomla_pos_enabled", "=", True),
            ]).mapped("gomla_nearly_finished_percent")
            threshold = min(thresholds) if thresholds else 10.0
            shipment.state = "nearly_finished" if ratio <= threshold else "active"

    def action_settle(self):
        Settlement = self.env["gomla.shipment.settlement"]
        for shipment in self:
            if shipment.state != "pending_settlement":
                raise UserError(_("Only a shipment pending settlement can be settled."))
            if shipment.settlement_id.filtered(lambda item: item.status == "settled"):
                raise UserError(_("This shipment has already been settled."))
            shipment._compute_totals()
            amounts = shipment._calculate_settlement(
                shipment.gross_sales_amount,
                shipment.supplier_commission_percent,
                shipment.freight_amount,
                shipment.aqlamiya_amount,
            )
            settlement = Settlement.create({
                "shipment_id": shipment.id,
                "supplier_id": shipment.supplier_id.id,
                "gross_sales_amount": shipment.gross_sales_amount,
                "seller_commission_amount": shipment.seller_commission_amount,
                "supplier_commission_percent": shipment.supplier_commission_percent,
                "supplier_commission_amount": amounts["supplier_commission_amount"],
                "freight_amount": shipment.freight_amount,
                "aqlamiya_amount": shipment.aqlamiya_amount,
                "supplier_net_amount": amounts["supplier_net_amount"],
                "settled_by": self.env.user.id,
                "settled_at": fields.Datetime.now(),
                "status": "settled",
            })
            self.env["gomla.supplier.ledger"].create({
                "supplier_id": shipment.supplier_id.id,
                "shipment_id": shipment.id,
                "settlement_id": settlement.id,
                "date": fields.Date.context_today(self),
                "description": _("Settlement %s") % shipment.name,
                "amount": amounts["supplier_net_amount"],
            })
            shipment.with_context(gomla_settlement_approval=True).write({"state": "settled"})
        return True

    @api.model
    def _calculate_settlement(self, gross_sales, commission_percent, freight, aqlamiya):
        """Pure settlement rule. Seller commission is deliberately not an input."""
        supplier_commission = gross_sales * commission_percent / 100.0
        return {
            "supplier_commission_amount": supplier_commission,
            "supplier_net_amount": gross_sales - supplier_commission - freight - aqlamiya,
        }

    @api.model
    def _load_pos_data_domain(self, data, config):
        return [
            ("company_id", "=", config.company_id.id),
            ("state", "in", ["active", "nearly_finished"]),
        ]

    @api.model
    def _load_pos_data_fields(self, config):
        return ["name", "supplier_id", "arrival_date", "state", "company_id"]


class GomlaShipmentLine(models.Model):
    _name = "gomla.shipment.line"
    _description = "Wholesale Produce Shipment Line"
    _inherit = ["pos.load.mixin"]
    _order = "shipment_id desc, id"

    shipment_id = fields.Many2one(
        "gomla.shipment", required=True, ondelete="cascade", index=True
    )
    product_id = fields.Many2one(
        "product.product", required=True, domain="[('available_in_pos', '=', True)]"
    )
    received_qty = fields.Float(string="Received Quantity", required=True, digits="Product Unit")
    sold_qty = fields.Float(compute="_compute_sale_values", string="Sold Quantity")
    remaining_qty = fields.Float(compute="_compute_sale_values", string="Remaining Quantity")
    gross_sales_amount = fields.Monetary(compute="_compute_sale_values", string="Gross Sales")
    currency_id = fields.Many2one(related="shipment_id.currency_id")
    uom_id = fields.Many2one(related="product_id.uom_id", string="Unit of Measure")
    crate_qty_received = fields.Integer(string="Crates Received")
    note = fields.Char(string="Note")

    _unique_product_per_shipment = models.Constraint(
        "unique (shipment_id, product_id)",
        "A product can only appear once in the same shipment.",
    )
    _positive_received_qty = models.Constraint(
        "CHECK(received_qty > 0)", "Received quantity must be greater than zero."
    )

    def _compute_sale_values(self):
        PosLine = self.env["pos.order.line"]
        for line in self:
            sold_lines = PosLine.search([
                ("gomla_shipment_line_id", "=", line.id),
                ("gomla_charge_type", "=", "goods"),
                ("order_id.state", "in", FINAL_ORDER_STATES),
            ])
            line.sold_qty = sum(sold_lines.mapped("qty"))
            line.remaining_qty = line.received_qty - line.sold_qty
            line.gross_sales_amount = sum(sold_lines.mapped("price_subtotal_incl"))

    @api.constrains("product_id", "shipment_id")
    def _check_company(self):
        for line in self:
            if line.product_id.company_id and line.product_id.company_id != line.shipment_id.company_id:
                raise ValidationError(_("The product and shipment must belong to the same company."))

    @api.constrains("received_qty")
    def _check_received_not_below_sold(self):
        for line in self:
            line._compute_sale_values()
            if float_compare(line.received_qty, line.sold_qty, precision_digits=4) < 0:
                raise ValidationError(_("Received quantity cannot be lower than sold quantity."))

    @api.model
    def _load_pos_data_domain(self, data, config):
        shipment_ids = [record["id"] for record in data.get("gomla.shipment", [])]
        return [("shipment_id", "in", shipment_ids)]

    @api.model
    def _load_pos_data_fields(self, config):
        return [
            "shipment_id", "product_id", "received_qty", "sold_qty",
            "remaining_qty", "gross_sales_amount", "uom_id", "crate_qty_received",
        ]


class GomlaShipmentSettlement(models.Model):
    _name = "gomla.shipment.settlement"
    _description = "Immutable Shipment Settlement Snapshot"
    _order = "settled_at desc, id desc"

    shipment_id = fields.Many2one("gomla.shipment", required=True, ondelete="restrict", index=True)
    supplier_id = fields.Many2one("res.partner", required=True, ondelete="restrict")
    currency_id = fields.Many2one(related="shipment_id.currency_id", store=True)
    gross_sales_amount = fields.Monetary(required=True)
    seller_commission_amount = fields.Monetary(required=True)
    supplier_commission_percent = fields.Float(required=True, digits=(12, 4))
    supplier_commission_amount = fields.Monetary(required=True)
    freight_amount = fields.Monetary(required=True)
    aqlamiya_amount = fields.Monetary(required=True)
    supplier_net_amount = fields.Monetary(required=True)
    settled_at = fields.Datetime(required=True, readonly=True)
    settled_by = fields.Many2one("res.users", required=True, readonly=True)
    status = fields.Selection([("draft", "Draft"), ("settled", "Settled")], required=True)
    notes = fields.Text()

    _one_settlement_per_shipment = models.Constraint(
        "unique (shipment_id)", "Only one settlement is allowed per shipment."
    )

    def write(self, vals):
        if self.filtered(lambda item: item.status == "settled") and not self.env.context.get("gomla_reopen_settlement"):
            raise UserError(_("An approved settlement is immutable."))
        return super().write(vals)

    def unlink(self):
        if self.filtered(lambda item: item.status == "settled") and not self.env.context.get("gomla_reopen_settlement"):
            raise UserError(_("An approved settlement cannot be deleted."))
        return super().unlink()


class GomlaSupplierLedger(models.Model):
    _name = "gomla.supplier.ledger"
    _description = "Gomla Supplier Ledger"
    _order = "date desc, id desc"

    supplier_id = fields.Many2one("res.partner", required=True, ondelete="restrict", index=True)
    shipment_id = fields.Many2one("gomla.shipment", ondelete="restrict", index=True)
    settlement_id = fields.Many2one("gomla.shipment.settlement", ondelete="restrict")
    date = fields.Date(required=True, default=fields.Date.context_today)
    description = fields.Char(required=True)
    amount = fields.Monetary(required=True, help="Positive means payable to supplier.")
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, readonly=True
    )
    currency_id = fields.Many2one(
        "res.currency", related="company_id.currency_id", store=True, readonly=True
    )

    def write(self, vals):
        if self.settlement_id:
            raise UserError(_("Settlement ledger entries are immutable."))
        return super().write(vals)

    def unlink(self):
        if self.settlement_id:
            raise UserError(_("Settlement ledger entries cannot be deleted."))
        return super().unlink()
