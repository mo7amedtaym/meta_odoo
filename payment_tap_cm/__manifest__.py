{
    "name": "Tap Payments Provider",
    "summary": "Tap Payments payment provider integration for Odoo 19",
    "version": "19.0.1.0.0",
    "category": "Accounting/Payment Providers",
    "author": "CubeMaster / CM",
    "website": "https://www.tap.company/",
    "license": "LGPL-3",
    "depends": ["payment"],
    "data": [
        "views/payment_tap_templates.xml",
        "data/payment_provider_data.xml",
        "views/payment_provider_views.xml",
    ],
    "assets": {},
    "installable": True,
    "application": False,
    "auto_install": False,
}
