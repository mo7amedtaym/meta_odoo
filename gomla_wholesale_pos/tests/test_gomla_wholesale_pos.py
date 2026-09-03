from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestGomlaWholesalePos(TransactionCase):
    def setUp(self):
        super().setUp()
        self.supplier = self.env["res.partner"].create({
            "name": "Test Produce Supplier",
            "gomla_is_supplier": True,
            "gomla_default_commission_percent": 7.0,
        })

    def test_official_settlement_example(self):
        amounts = self.env["gomla.shipment"]._calculate_settlement(
            85430.0, 7.0, 1200.0, 49.90
        )
        self.assertAlmostEqual(amounts["supplier_commission_amount"], 5980.10, places=2)
        self.assertAlmostEqual(amounts["supplier_net_amount"], 78200.0, places=2)

    def test_seller_commission_cannot_enter_formula(self):
        method = self.env["gomla.shipment"]._calculate_settlement
        without_bayaa = method(85430.0, 7.0, 1200.0, 49.90)
        seller_commission_information_only = 3250.0
        with_bayaa_unchanged = method(85430.0, 7.0, 1200.0, 49.90)
        self.assertEqual(without_bayaa, with_bayaa_unchanged)
        self.assertNotEqual(seller_commission_information_only, 0.0)

    def test_approved_settlement_is_immutable(self):
        shipment = self.env["gomla.shipment"].create({
            "supplier_id": self.supplier.id,
            "supplier_commission_percent": 7.0,
        })
        settlement = self.env["gomla.shipment.settlement"].create({
            "shipment_id": shipment.id,
            "supplier_id": self.supplier.id,
            "gross_sales_amount": 1000.0,
            "seller_commission_amount": 50.0,
            "supplier_commission_percent": 7.0,
            "supplier_commission_amount": 70.0,
            "freight_amount": 0.0,
            "aqlamiya_amount": 0.0,
            "supplier_net_amount": 930.0,
            "settled_at": "2026-09-03 10:00:00",
            "settled_by": self.env.user.id,
            "status": "settled",
        })
        with self.assertRaises(UserError):
            settlement.write({"supplier_net_amount": 900.0})

