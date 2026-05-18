# Telegram Proxy Publisher

Automatically collects proxy URLs from the @telemtrs chat's "Free proxy" forum topic and publishes them on GitHub Pages.

## Architecture

- **Source**: Telegram chat @telemtrs (chat_id: 7536401644), topic "Free proxy" (topic_id: 16160)
- **Cron**: OpenCrabs agent runs daily at 06:00 Moscow time
- **Storage**: `proxies.txt` — one proxy URL per line
- **Publishing**: GitHub Pages at https://leshchenko1979.github.io/tgproxy/
- **Domain**: tgproxy.l1979.ru (CNAME configured)

## Files

```
/
├── docs/
│   ├── index.html      # Main page with proxy list and copy buttons
│   ├── proxies.txt     # Proxy URLs (one per line)
│   └── CNAME           # Custom domain: tgproxy.l1979.ru
└── .github/
    └── workflows/
        └── publish.yml # GitHub Pages CI workflow
```

## Cron Job

OpenCrabs cron job ID: `6da1f200`

**Logic:**
1. Fetch recent messages from @telemtrs, topic 16160
2. Extract proxy URLs matching: `https://t\.me/(socks|proxy|killer)\?server=[^&]+&port=[^&]+&secret=[^&\s]+`
3. Fetch existing `proxies.txt` from GitHub
4. Append new unique proxies (keep most recent 30)
5. Push updated `proxies.txt` to GitHub
6. GitHub Actions CI publishes to GitHub Pages

## Proxy URL Formats

- `https://t.me/socks?server=X&port=Y&secret=Z`
- `https://t.me/proxy?server=X&port=Y&secret=Z`
- `http://t.me/killer?server=X&port=Y&secret=Z`

## Development

### Local testing

```bash
# Get messages from topic
mcp tg-mcp invoke_mtproto '{"method": "messages.getHistory", "params": {"peer": {"_": "InputPeerChat", "chat_id": 7536401644}, "offset_id": 0, "add_offset": 0, "limit": 50, "max_id": 0, "min_id": 0, "hash": 0, "reply_offset": 0, "reply_limit": 50, "top_msg_id": 16160}}'

# Or search for proxy URLs in the chat
# Use OpenCrabs tg_get_messages with query "t.me"
```

### Fix chrondb extraction bug

If MCP tools fail with chrondb errors, the native library may be in wrong location:

```bash
mv /root/.chrondb/lib/.tmp-extract-runtime/* /root/.chrondb/lib/
```

### Manual proxy list update

```bash
git clone https://github.com/leshchenko1979/tgproxy.git
# Edit proxies.txt
git add -A && git commit -m "update proxies" && git push
```
