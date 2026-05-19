# tgproxy

Auto-updated Telegram proxy list published at **tgproxy.l1979.ru**

Proxy URLs are collected from the [@telemtrs](https://t.me/telemtrs) channel's "Free proxy" forum topic and published daily.

## How It Works

1. **Collection** — Fetch messages from `@telemtrs`, topic "Free proxy" (topic_id: 16160)
2. **Processing** — Extract proxy URLs (`tg://proxy?...`, `https://t.me/proxy?...`)
3. **Cleaning** — Normalize to `tg://proxy` format, filter malformed entries, deduplicate
4. **Publishing** — Push to GitHub, GitHub Pages serves at tgproxy.l1979.ru

## Repository Structure

```
├── update_proxies.py      # Main script (run by cron)
├── tests/
│   └── test_update_proxies.py  # Pytest suite
├── docs/
│   ├── index.html         # Site with proxy list + copy buttons
│   ├── proxies.txt        # Live proxy URL list
│   └── CNAME              # tgproxy.l1979.ru
└── README.md              # This file
```

## Proxy URL Format

All URLs in `proxies.txt` are normalized to Telegram's proxy URI scheme:

```
tg://proxy?server=HOST&port=PORT&secret=SECRET
```

## Local Setup

```bash
# Install dependencies
pip install pytest

# Run tests
pytest tests/ -v

# Run the update script manually
python3 update_proxies.py
```

## CI/CD

- **Cron**: OpenCrabs agent runs `update_proxies.py` daily at 06:00 Moscow time (job ID: `6da1f200`)
- **Hosting**: GitHub Pages at https://leshchenko1979.github.io/tgproxy/
- **Domain**: tgproxy.l1979.ru (CNAME configured)

## Development

### Test the update script

```bash
python3 update_proxies.py
```

This reads `docs/proxies.txt`, normalizes URLs (converts `https://t.me/proxy?...` → `tg://proxy?...`), filters bad entries, deduplicates, and writes back.

### Add tests

```bash
pytest tests/ -v
```

Tests cover:
- `extract_timestamp()` — strips/preserves `|ISO-timestamp` suffix
- `normalize_url()` — URL format normalization
- `is_valid()` — filters malformed URLs (`*`, `**|`, backticks, etc.)

### Troubleshooting

**MCP/Telegram tools fail with chrondb errors:**

```bash
mv /root/.chrondb/lib/.tmp-extract-runtime/* /root/.chrondb/lib/
```

**Push access denied:** Ensure you have write access to the repository or use a deploy token.

## License

Private — Alexey / l1979.ru
