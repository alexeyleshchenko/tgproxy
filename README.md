# tgproxy

Telegram proxy list published at **[tgproxy.l1979.ru](https://tgproxy.l1979.ru)** (GitHub Pages).

Proxy URLs are collected from the [@telemtrs](https://t.me/telemtrs) channel's "Free proxy" forum topic and published daily.

## How It Works

1. **Collection** — [`update_proxies.py`](update_proxies.py) runs on GitHub Actions ([`nightly-update.yml`](.github/workflows/nightly-update.yml), cron `0 3 * * *` UTC, plus `workflow_dispatch`). It calls [tg-mcp.l1979.ru](https://tg-mcp.l1979.ru) via HTTP MCP (`get_messages` on topic 16160).
2. **Processing** — Extract proxy URLs (`tg://proxy?...`, `https://t.me/proxy?...`, socks, killer).
3. **Merge** — Deduplicate, prefer new URLs from Telegram, keep up to 30 newest entries.
4. **Publishing** — the workflow commits `docs/proxies.txt` when the list changes and deploys `docs/` to GitHub Pages.

## Repository Structure

```
├── update_proxies.py      # Fetch, merge, write docs/proxies.txt
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

Both `tg://proxy?...` and `https://t.me/proxy?...` forms are normalized to `tg://` when stored.

## Configuration

| Env | Default | Purpose |
|-----|---------|---------|
| `TG_MCP_BEARER` | *(required)* | Bearer token for tg-mcp HTTP MCP |
| `TG_MCP_URL` | `https://tg-mcp.l1979.ru/v1/mcp` | MCP endpoint |
| `MAX_PROXIES` | `30` (in script) | Maximum entries in the list |
| `TOPIC_ID` | `16160` (in script) | Forum topic ID in @telemtrs |

### GitHub secret

Repository secret **`TG_MCP_BEARER`** (set on [alexeyleshchenko/tgproxy](https://github.com/alexeyleshchenko/tgproxy)). Use the token value only (no `Bearer ` prefix), or paste the full header — the script strips the prefix.

## Local Setup

```bash
pip install pytest==9.0.3

pytest tests/ -v

export TG_MCP_BEARER='<your-token>'
python3 update_proxies.py
```

The script updates `docs/proxies.txt` only; commit and push (or run the workflow) to publish.

## Hosting

- **Live site**: [https://tgproxy.l1979.ru](https://tgproxy.l1979.ru) — GitHub Pages from `docs/` on `main`.
- **Update flow**: Actions [`nightly-update.yml`](.github/workflows/nightly-update.yml) (needs `TG_MCP_BEARER`). Manual: **Actions → Nightly proxy update → Run workflow**.
- **Pages deploy**: [`pages.yml`](.github/workflows/pages.yml) on push to `main` and `workflow_dispatch`.

The itg-1 Caddy vhost and `0 3 * * * /opt/tgproxy/scripts/update.sh` cron were retired when this repo moved to **alexeyleshchenko**.

## Development

### Tests

```bash
pytest tests/ -v
```

Coverage includes URL regex, timestamps, merge logic, atomic writes, MCP response parsing, and no-change detection.

### Troubleshooting

**`TG_MCP_BEARER is required`:** Set the env var or GitHub secret.

**MCP call failed:** Check token validity and that tg-mcp.l1979.ru is reachable.

## License

Private — Alexey / l1979.ru
