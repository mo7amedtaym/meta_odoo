# Social Ads CRM 17.0.2.0.0

Unified social lead connector for Odoo 17. This release adds a provider-neutral lead pipeline and Snapchat Lead Generation support while keeping `meta_ads_crm` as a compatibility dependency so existing Meta tables, OAuth, pages, campaigns, posts, forms and lead logs are not destructively renamed.

## Snapchat setup
1. Configure Client ID and Client Secret in Settings > Social Ads CRM.
2. Create a `Snapchat` connection from Social Ads CRM > Connections and click Connect / Reconnect.
3. After OAuth, sync Ad Accounts, then Lead Forms.
4. Select a standard Odoo Sales Team on each form. New leads are initially assigned to that team's leader (`crm.team.user_id`), or left unassigned when no leader exists.
5. Register the webhook and use Send Test Lead.

Webhook endpoint: `/social_ads/snapchat/webhook`.

## Upgrade safety
Do not uninstall `meta_ads_crm`. Install this module beside it for the first generalized release. Existing Meta data remains authoritative and is mirrored into the generic models additively.
