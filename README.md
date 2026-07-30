# tgproxy

Telegram proxy list published at **tgproxy.l1979.ru** (self-hosted on itg-1 via Caddy — see [Hosting](#hosting))

Proxy URLs are collected from the [@telemtrs](https://t.me/telemtrs) channel's "Free proxy" forum topic and published daily.

## How It Works

1. **Collection** — [`update_proxies.py`](update_proxies.py) runs on **itg-1** via a server-side cron (`0 3 * * * /opt/tgproxy/scripts/update.sh`); the GitHub Actions nightly is inert (see [Hosting](#hosting)). It calls [tg-mcp.l1979.ru](https://tg-mcp.l1979.ru) via HTTP MCP (`get_messages` on topic 16160).
2. **Processing** — Extract proxy URLs (`tg://proxy?...`, `https://t.me/proxy?...`, socks, killer).
3. **Merge** — Deduplicate, prefer new URLs from Telegram, keep up to 30 newest entries.
4. **Publishing** — on **itg-1**, `update_proxies.py` regenerates `docs/proxies.txt` in place at `/opt/tgproxy/docs`, which the `static-sites` Caddy serves at tgproxy.l1979.ru. (No GitHub Pages — the account is shadowed.)

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

Add repository secret **`TG_MCP_BEARER`** with the token from Cursor `~/.cursor/mcp.json`:

```json
"mcpServers": {
  "telegram": {
    "headers": { "Authorization": "Bearer <TOKEN>" }
  }
}
```

Use the token value only (no `Bearer ` prefix), or paste the full header — the script strips the prefix.

## Local Setup

```bash
pip install pytest==9.0.3

pytest tests/ -v

export TG_MCP_BEARER='<your-token>'
python3 update_proxies.py
```

The script updates `docs/proxies.txt` only; commit and push manually if needed.

## Hosting

> ⚠️ **Self-hosted, not GitHub Pages.** The `leshchenko1979` GitHub account is **shadowed** — GitHub Actions and GitHub Pages are turned off. The `.github/workflows/*.yml` files are kept for reference but **do not run**.

- **Live site**: https://tgproxy.l1979.ru (+ mirror `tgproxy-mirror.l1979.ru`) — served by the **`static-sites` Caddy container on itg-1** (`144.31.188.163`) from `/opt/tgproxy/docs` (mounted into Caddy at `/data/tgproxy`).
- **Update flow (automated, server-side)**: a cron on itg-1 runs `0 3 * * * /opt/tgproxy/scripts/update.sh`, which runs `update_proxies.py` (needs `TG_MCP_BEARER` from `/opt/tgproxy/.env`) and regenerates `docs/proxies.txt` in place; Caddy serves the updated file. To refresh by hand: `ssh itg-1` then run `/opt/tgproxy/scripts/update.sh`.
- **GitHub Actions is NOT the update mechanism** — the nightly workflow is inert (account shadowed). The live mechanism is the itg-1 cron above.

The legacy workflows (inert):

| Workflow | Defined trigger | Status |
|----------|----------------|--------|
| [`nightly-update.yml`](.github/workflows/nightly-update.yml) | Cron `0 3 * * *` UTC, `workflow_dispatch` | ⛔ inert (Actions off) |
| [`pages.yml`](.github/workflows/pages.yml) | Push/PR to `main` | ⛔ inert (Pages off) |

## Development

### Tests

```bash
pytest tests/ -v
```

Coverage includes URL regex, timestamps, merge logic, atomic writes, MCP response parsing, and no-change detection.

### Troubleshooting

**`TG_MCP_BEARER is required`:** Set the env var or GitHub secret.

**MCP call failed:** Check token validity and that tg-mcp.l1979.ru is reachable.

**Logs (local):** `/var/log/tgproxy/update.log` or `~/tgproxy/update.log` as fallback.

## License

Private — Alexey / l1979.ru
