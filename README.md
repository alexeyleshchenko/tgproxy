# tgproxy

Auto-updated Telegram proxy list published at **tgproxy.l1979.ru**

Proxy URLs are collected from the [@telemtrs](https://t.me/telemtrs) channel's "Free proxy" forum topic and published daily.

## How It Works

1. **Collection** — GitHub Actions runs [`update_proxies.py`](update_proxies.py) nightly; it calls [tg-mcp.l1979.ru](https://tg-mcp.l1979.ru) via HTTP MCP (`get_messages` on topic 16160).
2. **Processing** — Extract proxy URLs (`tg://proxy?...`, `https://t.me/proxy?...`, socks, killer).
3. **Merge** — Deduplicate, prefer new URLs from Telegram, keep up to 30 newest entries.
4. **Publishing** — The workflow commits `docs/proxies.txt` to `main` and deploys GitHub Pages inline (tgproxy.l1979.ru).

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

## CI/CD

| Workflow | Trigger | Role |
|----------|---------|------|
| [`nightly-update.yml`](.github/workflows/nightly-update.yml) | Cron `0 3 * * *` UTC (~06:00 Moscow), `workflow_dispatch` | Update proxies, commit, inline Pages deploy |
| [`pages.yml`](.github/workflows/pages.yml) | Push/PR to `main` | Tests; deploy on normal pushes |

- **Hosting**: GitHub Pages — https://leshchenko1979.github.io/tgproxy/
- **Domain**: tgproxy.l1979.ru (CNAME configured)

Nightly pushes use `GITHUB_TOKEN` and do not trigger `pages.yml`; the nightly job deploys Pages directly.

After the first successful nightly run, disable the legacy Hermes OpenCrabs cron job (`6da1f200`) if it is still enabled.

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
