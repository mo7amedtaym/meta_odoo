/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { ControlButtons } from "@point_of_sale/app/screens/product_screen/control_buttons/control_buttons";
import { SelectionPopup } from "@point_of_sale/app/components/popups/selection_popup/selection_popup";
import { NumberPopup } from "@point_of_sale/app/components/popups/number_popup/number_popup";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";

function toNumber(value) {
    if (value === undefined || value === null || value === false) {
        return null;
    }
    const parsed = Number(String(value).replace(",", "."));
    return Number.isFinite(parsed) ? parsed : null;
}

patch(ControlButtons.prototype, {
    async clickGomlaDetails() {
        const order = this.currentOrder;
        const line = order?.getSelectedOrderline();
        if (!line || line.gomla_charge_type !== "goods") {
            this.dialog.add(AlertDialog, {
                title: _t("Select a goods line"),
                body: _t("Select the produce line before entering shipment details."),
            });
            return;
        }

        const shipmentLines = this.pos.models["gomla.shipment.line"].filter(
            (shipmentLine) =>
                shipmentLine.product_id?.id === line.product_id.id &&
                shipmentLine.remaining_qty > 0 &&
                ["active", "nearly_finished"].includes(shipmentLine.shipment_id?.state)
        );
        if (!shipmentLines.length) {
            this.dialog.add(AlertDialog, {
                title: _t("No available shipment"),
                body: _t("Create an active shipment containing this product, then reload the POS."),
            });
            return;
        }

        const shipmentLine = await makeAwaitable(this.dialog, SelectionPopup, {
            title: _t("Choose shipment"),
            list: shipmentLines.map((item) => ({
                id: item.id,
                label: `${item.shipment_id.name} — ${item.remaining_qty} ${item.uom_id?.name || ""}`,
                isSelected: line.gomla_shipment_line_id?.id === item.id,
                item,
            })),
        });
        if (!shipmentLine) {
            return;
        }

        const weight = toNumber(await makeAwaitable(this.dialog, NumberPopup, {
            title: _t("Sold weight / quantity"),
            startingValue: line.gomla_weight || line.qty,
            isValid: (value) => toNumber(value) > 0 && toNumber(value) <= shipmentLine.remaining_qty,
        }));
        if (weight === null) {
            return;
        }
        const count = toNumber(await makeAwaitable(this.dialog, NumberPopup, {
            title: _t("Package or box count"),
            startingValue: line.gomla_count || 1,
            isValid: (value) => Number.isInteger(toNumber(value)) && toNumber(value) >= 0,
        }));
        if (count === null) {
            return;
        }
        const sellerCommission = toNumber(await makeAwaitable(this.dialog, NumberPopup, {
            title: _t("Seller commission / بياعة"),
            startingValue: line.gomla_seller_commission || 0,
            isValid: (value) => toNumber(value) >= 0,
        }));
        if (sellerCommission === null) {
            return;
        }
        const crateQty = toNumber(await makeAwaitable(this.dialog, NumberPopup, {
            title: _t("Crate quantity"),
            startingValue: line.gomla_crate_qty || 0,
            isValid: (value) => Number.isInteger(toNumber(value)) && toNumber(value) >= 0,
        }));
        if (crateQty === null) {
            return;
        }
        const crateUnitDeposit = crateQty
            ? toNumber(await makeAwaitable(this.dialog, NumberPopup, {
                title: _t("Deposit per crate"),
                startingValue: crateQty
                    ? line.gomla_crate_deposit / crateQty || this.pos.config.gomla_default_crate_deposit
                    : this.pos.config.gomla_default_crate_deposit,
                isValid: (value) => toNumber(value) >= 0,
            }))
            : 0;
        if (crateUnitDeposit === null) {
            return;
        }

        if (sellerCommission > 0 && !this.pos.config.gomla_seller_commission_product_id) {
            this._gomlaMissingChargeProduct(_t("Seller Commission Product"));
            return;
        }
        if (crateQty * crateUnitDeposit > 0 && !this.pos.config.gomla_crate_deposit_product_id) {
            this._gomlaMissingChargeProduct(_t("Crate Deposit Product"));
            return;
        }

        line.gomla_shipment_id = shipmentLine.shipment_id;
        line.gomla_shipment_line_id = shipmentLine;
        line.gomla_weight = weight;
        line.gomla_count = count;
        line.gomla_seller_commission = sellerCommission;
        line.gomla_crate_qty = crateQty;
        line.gomla_crate_deposit = crateQty * crateUnitDeposit;
        line.gomla_charge_type = "goods";
        line.setQuantity(weight);

        await this._gomlaUpsertChargeLine(
            line,
            "seller_commission",
            sellerCommission,
            this.pos.config.gomla_seller_commission_product_id
        );
        await this._gomlaUpsertChargeLine(
            line,
            "crate_deposit",
            line.gomla_crate_deposit,
            this.pos.config.gomla_crate_deposit_product_id
        );
        order.selectOrderline(line);
        this.notification.add(_t("Shipment details saved on the sale line."), { type: "success" });
    },

    _gomlaMissingChargeProduct(label) {
        this.dialog.add(AlertDialog, {
            title: _t("Missing POS configuration"),
            body: _t("Configure %s in the Gomla Wholesale tab.", label),
        });
    },

    async _gomlaUpsertChargeLine(sourceLine, chargeType, amount, product) {
        const order = sourceLine.order_id;
        const existing = order.lines.find(
            (item) =>
                item.gomla_charge_type === chargeType &&
                item.gomla_source_line_uuid === sourceLine.uuid
        );
        if (amount <= 0) {
            if (existing) {
                existing.delete();
            }
            return;
        }
        if (existing) {
            existing.setUnitPrice(amount);
            existing.setQuantity(1);
            return;
        }
        await this.pos.addLineToCurrentOrder({
            product_id: product,
            product_tmpl_id: product.product_tmpl_id,
            price_unit: amount,
            qty: 1,
            gomla_charge_type: chargeType,
            gomla_source_line_uuid: sourceLine.uuid,
        });
    },
});

