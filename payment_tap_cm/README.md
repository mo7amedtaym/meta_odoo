# Tap Payments Provider for Odoo 19

Native Odoo 19 payment provider integration using Tap Payments API v2.

## Features

- Odoo 19 `payment.provider` integration.
- Test / Enabled states controlled by Odoo.
- Tap hosted checkout (`src_all` by default).
- Arabic / English checkout language.
- Charge creation using `POST /v2/charges/`.
- Return URL handling with authoritative charge retrieval.
- Server-to-server webhook endpoint with Tap HMAC SHA-256 `hashstring` verification.
- Odoo transaction state mapping.
- Full and partial refunds using `POST /v2/refunds/`.
- Portal / eCommerce / invoice payment compatibility through Odoo's standard payment framework.
- No card number / CVV storage in Odoo.

## Installation

1. Copy `payment_tap_cm` to your custom addons path.
2. Restart Odoo.
3. Update Apps List.
4. Install **Tap Payments Provider**.
5. Go to **Accounting / Configuration / Payment Providers** (or Website payment providers).
6. Open **Tap Payments**.
7. Enter your Tap Publishable API Key and Secret API Key.
8. Keep provider in **Test Mode** while testing.
9. Choose the checkout source (`src_all` is recommended initially).
10. Publish / enable the provider when ready.

## Endpoints

- Return: `/payment/tap/return`
- Webhook: `/payment/tap/webhook`

These URLs are sent automatically when Odoo creates the Tap charge.

## Sandbox test

1. Put Tap test credentials (`pk_test_...`, `sk_test_...`) in the provider.
2. Set provider state to **Test Mode**.
3. Open an unpaid customer invoice or website checkout.
4. Click **Pay Now** and choose Tap Payments.
5. Odoo creates a Tap charge and redirects to Tap hosted checkout.
6. Complete payment with a Tap test payment method/card.
7. Tap redirects to `/payment/tap/return?tap_id=chg_...`.
8. Odoo retrieves the charge directly from Tap and processes its status.
9. Confirm the Odoo `payment.transaction` state becomes **Done** when Tap returns `CAPTURED`.
10. Confirm the invoice is reconciled/paid by Odoo's standard post-processing flow.

## Refund test

From the confirmed payment transaction, use Odoo's **Refund** action. Odoo 19 can create full or partial refund child transactions. The module sends the refund to Tap using the original charge ID.

## Security notes

- Never put Tap secret keys in source code.
- The Secret API Key is stored in the payment provider record and restricted to system administrators in the UI.
- Webhooks are rejected if Tap's `hashstring` does not match the HMAC-SHA256 calculation.
- The return route does not trust browser status parameters; it retrieves the charge from Tap before processing.
- Card numbers and CVV are entered on Tap-hosted pages and are not stored by this module.

## Important production checks

Before enabling production:

- Configure the real Odoo base URL and HTTPS.
- Confirm Tap can reach `/payment/tap/webhook` publicly.
- Confirm the merchant account supports your required currencies/payment methods.
- Perform a small real charge and refund.
- Review Odoo logs for webhook delivery and transaction post-processing.
