# tgproxy

Auto-updated Telegram proxy list published at **tgproxy.l1979.ru**

Proxy URLs are collected from the [@telemtrs](https://t.me/telemtrs) channel's "Free proxy" forum topic and published daily.

## How It Works

1. **Collection** — Fetch messages from `@telemtrs`, topic "Free proxy" (topic_id: 16160) via MCP
2. **Processing** — Extract proxy URLs (`tg://proxy?...`, `https://t.me/proxy?...`, socks, killer)
3. **Merge** — Deduplicate, prefer new URLs from Telegram, keep up to 30 newest entries
4. **Publishing** — Commit and push to GitHub; GitHub Pages serves at tgproxy.l1979.ru

## Repository Structure

```
├── update_proxies.py      # Main script (run by cron)
├── tests/
│   └── test_update_proxies.py
├── docs/
│   ├── index.html         # Site with proxy list + copy buttons
│   ├── proxies.txt        # Live proxy URL list
│   └── CNAME              # tgproxy.l1979.ru
└── README.md
```

## Proxy URL Format

Each line in `proxies.txt` is a proxy URL, optionally followed by a UTC timestamp:

```
tg://proxy?server=HOST&port=PORT&secret=SECRET|2026-05-19T12:34:56
```

Both `tg://proxy?...` and `https://t.me/proxy?...` forms are stored as found in messages.

## Configuration

| Constant | Default | Purpose |
|----------|---------|---------|
| `MCP_BIN` | `/root/.local/bin/mcp` | MCP CLI binary on the server |
| `MAX_PROXIES` | `30` | Maximum entries in the list |
| `TOPIC_ID` | `16160` | Forum topic ID in @telemtrs |

## Local Setup

```bash
pip install pytest

pytest tests/ -v

# Manual run (requires MCP_BIN and Telegram access on the host)
python3 update_proxies.py
```

## CI/CD

- **Cron**: OpenCrabs agent runs `update_proxies.py` daily at 06:00 Moscow time (job ID: `6da1f200`)
- **CI**: GitHub Actions runs `pytest` on push/PR; Pages deploys on push to `main`
- **Hosting**: GitHub Pages at https://leshchenko1979.github.io/tgproxy/
- **Domain**: tgproxy.l1979.ru (CNAME configured)

## Development

### Tests

```bash
pytest tests/ -v
```

Coverage includes URL regex matching, timestamp parsing, merge/eviction logic, atomic writes, and no-change detection.

### Troubleshooting

**MCP/Telegram tools fail with chrondb errors:**

```bash
mv /root/.chrondb/lib/.tmp-extract-runtime/* /root/.chrondb/lib/
```

**Push access denied:** Ensure the cron host has push access to the repository.

**Logs:** `/var/log/tgproxy/update.log` on the server, or `~/tgproxy/update.log` as fallback.

## License

Private — Alexey / l1979.ru
