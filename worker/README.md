# Bitrix24 bot gateway

This Worker only relays signed alerts from GitHub Actions. It does not scrape sources or store alerts.

After the Bitrix24 administrator registers the bot, create a free Workers KV namespace and replace its public id in `wrangler.toml`. KV stores only the idempotency key and returned message id for 180 days. Then set each secret locally with `wrangler secret put`: `MONITOR_SHARED_SECRET`, `B24_REST_URL`, `B24_BOT_ID`, `B24_BOT_TOKEN`, `B24_DIALOG_ID`, then deploy with `wrangler deploy`. Do not place values in `wrangler.toml` or GitHub files.
