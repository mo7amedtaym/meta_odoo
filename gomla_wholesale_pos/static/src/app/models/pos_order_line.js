/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { PosOrderline } from "@point_of_sale/app/models/pos_order_line";

patch(PosOrderline.prototype, {
    setup(vals) {
        super.setup(vals);
        this.gomla_weight = this.gomla_weight || 0;
        this.gomla_count = this.gomla_count || 0;
        this.gomla_seller_commission = this.gomla_seller_commission || 0;
        this.gomla_crate_qty = this.gomla_crate_qty || 0;
        this.gomla_crate_deposit = this.gomla_crate_deposit || 0;
        this.gomla_charge_type = this.gomla_charge_type || "goods";
        this.gomla_source_line_uuid = this.gomla_source_line_uuid || false;
    },
});

