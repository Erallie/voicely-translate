Voicely Translate Ko-fi Shop Worker

Files in this ZIP:
- worker.js: updated Worker
- schema.sql: your existing D1 schema
- wrangler.toml: your existing Wrangler configuration

Before deploying, create/set this Cloudflare Worker secret:

    wrangler secret put VOICELY_SHOP_ITEM_CODE

Paste the direct_link_code for your Voicely Translate Credits Ko-fi Shop item.

Your existing secrets are still used:
- KOFI_VERIFICATION_TOKEN
- BOT_API_SECRET
- EXISTING_WEBHOOK_URL

Then deploy:

    wrangler deploy

Behavior:
- All valid Ko-fi webhook events continue to be forwarded to EXISTING_WEBHOOK_URL.
- Donations, memberships, commissions, and unrelated Shop products do not add Voicely credit.
- Only the configured Voicely Shop item adds credit.
- The buyer must include the VT-XXXXXX code in the Ko-fi order message.
- Mixed carts containing the Voicely item plus unrelated items are not credited.
