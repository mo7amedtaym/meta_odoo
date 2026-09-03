from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    gomla_is_supplier = fields.Boolean(string="Wholesale Produce Supplier")
    gomla_default_commission_percent = fields.Float(
        string="Default Supplier Commission %", digits=(12, 4)
    )
    gomla_uses_crates = fields.Boolean(string="Uses Crate Custody")
    gomla_agreement_notes = fields.Text(string="Agreement Notes")
    gomla_supplier_balance = fields.Monetary(
        string="Gomla Supplier Balance",
        compute="_compute_gomla_supplier_balance",
        currency_field="gomla_currency_id",
    )
    gomla_currency_id = fields.Many2one(
        "res.currency", related="company_id.currency_id", readonly=True
    )

    def _compute_gomla_supplier_balance(self):
        grouped = self.env["gomla.supplier.ledger"]._read_group(
            [("supplier_id", "in", self.ids)],
            ["supplier_id"],
            ["amount:sum"],
        )
        balances = {supplier.id: amount for supplier, amount in grouped}
        for partner in self:
            partner.gomla_supplier_balance = balances.get(partner.id, 0.0)
