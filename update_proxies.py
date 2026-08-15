#!/usr/bin/env python3
"""
Update Telegram proxy list from @telemtrs Free proxy topic.
Stores proxies with timestamps: URL|YYYY-MM-DDTHH:MM:SS
"""

import hashlib
import json
import logging
import os
import re
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

# === CONFIG ===
REPO_DIR = os.path.dirname(os.path.abspath(__file__))
PROXIES_FILE = os.path.join(REPO_DIR, 'docs', 'proxies.txt')
PROXIES_HASHED_NAME = re.compile(r'^proxies-[0-9a-f]{12}\.txt$')
INDEX_PROXIES_URL_RE = re.compile(
    r"const PROXIES_URL = '\./proxies(?:-[0-9a-f]{12})?\.txt'"
)
TELEGRAM_CHAT = 'telemtrs'
TOPIC_ID = 16160  # Free proxy forum topic in @telemtrs
MAX_PROXIES = 30
TG_MCP_URL = os.environ.get('TG_MCP_URL', 'https://tg-mcp.l1979.ru/v1/mcp')
MCP_PROTOCOL_VERSION = '2024-11-05'
PROXY_PATTERN = re.compile(
    r'(?:https://t\.me/|tg://)(?:socks|proxy|killer)'
    r'\?server=[^&\s]+&port=\d+&secret=[0-9a-fA-F]+'
)

# Captures the proxy type keyword (socks/proxy/killer) from either URL scheme.
_TYPE_PATTERN = re.compile(r'(?:tg://|https://t\.me/)(socks|proxy|killer)\?')
TS_FORMAT = '%Y-%m-%dT%H:%M:%S'

root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG)
root_logger.handlers.clear()
root_logger.addHandler(logging.StreamHandler(sys.stdout))
logger = logging.getLogger(__name__)
_FILE_LOG_FORMAT = logging.Formatter(
    '%(asctime)s %(levelname)s %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)


def _configure_file_logging():
    """Attach a file handler if a log path is writable. Skip on import (tests)."""
    errors = []
    for path in ('/var/log/tgproxy/update.log', os.path.expanduser('~/tgproxy/update.log')):
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            handler = logging.FileHandler(path)
            handler.setLevel(logging.INFO)
            handler.setFormatter(_FILE_LOG_FORMAT)
            root_logger.addHandler(handler)
            return
        except Exception as err:
            errors.append(str(err))
    print(f'Warning: file logging disabled ({"; ".join(errors)})', file=sys.stderr)


_mcp_initialized = False


def die(msg):
    """Log error and exit with code 1."""
    logger.error(msg)
    sys.exit(1)


def normalize_bearer(raw: str | None) -> str:
    """Return token value without Bearer prefix."""
    if not raw or not str(raw).strip():
        return ''
    value = str(raw).strip()
    if value.lower().startswith('bearer '):
        return value[7:].strip()
    return value


def get_mcp_bearer() -> str:
    bearer = normalize_bearer(os.environ.get('TG_MCP_BEARER'))
    if not bearer:
        die('TG_MCP_BEARER is required (Telegram MCP Bearer token)')
    return bearer


def parse_sse_response(raw: str) -> dict | None:
    """Extract the last JSON-RPC object from an SSE or plain JSON body."""
    last_obj = None
    for block in raw.split('\n\n'):
        for line in block.splitlines():
            if not line.startswith('data: '):
                continue
            try:
                last_obj = json.loads(line[6:])
            except json.JSONDecodeError:
                continue
    if last_obj is not None:
        return last_obj

    start = raw.find('{')
    if start == -1:
        return None
    try:
        return json.loads(raw[start:])
    except json.JSONDecodeError:
        return None


def parse_tool_result_messages(result: dict) -> list | None:
    """Extract message list from an MCP tools/call result object."""
    if result.get('isError'):
        return None
    if isinstance(result.get('messages'), list):
        return result['messages']

    messages = []
    for item in result.get('content', []):
        if item.get('type') != 'text':
            continue
        text = item.get('text', '')
        if not text:
            continue
        try:
            inner = json.loads(text)
        except json.JSONDecodeError:
            return None
        if isinstance(inner.get('messages'), list):
            messages.extend(inner['messages'])
    return messages


def _mcp_post(
    body: dict,
    bearer: str,
    timeout: int = 120,
    session_id: str | None = None,
) -> tuple[int, str, dict | None, str | None]:
    headers = {
        'Authorization': f'Bearer {bearer}',
        'Content-Type': 'application/json',
        'Accept': 'application/json, text/event-stream',
    }
    if session_id:
        headers['Mcp-Session-Id'] = session_id

    data = json.dumps(body).encode()
    req = urllib.request.Request(TG_MCP_URL, data=data, headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
            sid = resp.headers.get('Mcp-Session-Id') or resp.headers.get('mcp-session-id')
            return resp.status, raw, parse_sse_response(raw), sid
    except urllib.error.HTTPError as e:
        raw = e.read().decode() if e.fp else ''
        return e.code, raw, parse_sse_response(raw), None
    except urllib.error.URLError as e:
        logger.error('MCP HTTP request failed: %s', e.reason)
        return 0, '', None, None


def _ensure_mcp_initialized(bearer: str, timeout: int = 120) -> bool:
    global _mcp_initialized
    if _mcp_initialized:
        return True

    status, raw, msg, session_id = _mcp_post(
        {
            'jsonrpc': '2.0',
            'id': 1,
            'method': 'initialize',
            'params': {
                'protocolVersion': MCP_PROTOCOL_VERSION,
                'capabilities': {},
                'clientInfo': {'name': 'tgproxy', 'version': '1.0'},
            },
        },
        bearer,
        timeout=timeout,
    )
    if status != 200 or not msg or msg.get('error'):
        logger.error('MCP initialize failed (HTTP %s): %s', status, raw[:500])
        return False

    _mcp_post(
        {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
        bearer,
        timeout=timeout,
        session_id=session_id,
    )
    _mcp_initialized = True
    return True


def mcp_call(tool: str, params: dict, timeout: int = 120) -> list | None:
    """
    Call MCP tool via HTTP (Streamable HTTP / SSE).
    Returns message list on success (may be empty), or None on failure.
    """
    bearer = get_mcp_bearer()
    if not _ensure_mcp_initialized(bearer, timeout=timeout):
        return None

    status, raw, msg, _session = _mcp_post(
        {
            'jsonrpc': '2.0',
            'id': 2,
            'method': 'tools/call',
            'params': {'name': tool, 'arguments': params},
        },
        bearer,
        timeout=timeout,
    )
    if status != 200:
        logger.error('MCP tools/call failed (HTTP %s)', status)
        return None
    if not msg:
        logger.error('MCP tools/call returned no JSON-RPC payload')
        return None
    if msg.get('error'):
        logger.error('MCP tools/call error: %s', msg['error'])
        return None

    result = msg.get('result')
    if not isinstance(result, dict):
        logger.error('MCP tools/call missing result object')
        return None

    messages = parse_tool_result_messages(result)
    if messages is None:
        logger.error('MCP tools/call result could not be parsed')
        return None
    return messages


def _to_utc_naive(dt: datetime) -> datetime:
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def parse_timestamp(msg: dict) -> str:
    """Extract UTC timestamp from message date field as ISO string, or empty."""
    raw = msg.get('date')
    if not raw:
        return ''
    if isinstance(raw, str):
        try:
            ts = raw if raw.endswith('Z') or '+' in raw else raw + 'Z'
            dt = _to_utc_naive(datetime.fromisoformat(ts.replace('Z', '+00:00')))
            return dt.strftime(TS_FORMAT)
        except Exception:
            pass
    try:
        dt = _to_utc_naive(datetime.fromtimestamp(float(raw), tz=timezone.utc))
        return dt.strftime(TS_FORMAT)
    except Exception:
        pass
    return ''


def sanitize_proxy_url(url: str) -> str:
    """Return proxy URL without Telegram markdown junk in the secret field."""
    match = PROXY_PATTERN.search(url)
    return match.group(0) if match else url


def normalize_to_tg_url(url: str) -> str:
    """Convert t.me proxy links to tg:// scheme."""
    clean = sanitize_proxy_url(url)
    if clean.startswith('tg://'):
        return clean
    parsed = urlparse(clean)
    kind = parsed.path.lstrip('/')
    if kind and parsed.query:
        return f'tg://{kind}?{parsed.query}'
    return clean


def proxy_type(url: str) -> str:
    """Return the proxy type keyword (socks/proxy/killer), or '' if absent."""
    m = _TYPE_PATTERN.search(url)
    return m.group(1) if m else ''


def proxy_identity(url: str) -> tuple[str, str, str] | None:
    """Return (server, port, type) identity for deduplication, or None.

    The secret is intentionally NOT part of the identity: the same endpoint
    republished with a rotated secret is still the same proxy, so entries that
    share server, port and type collapse to one (see _prefer_candidate for which
    wins). The type IS part of the identity so distinct proxy kinds (MTProto vs
    SOCKS vs killer) sharing a host:port are kept as separate entries.
    """
    match = PROXY_PATTERN.search(url)
    if not match:
        return None
    params = parse_qs(urlparse(match.group(0)).query)
    try:
        server = params['server'][0]
        port = params['port'][0]
    except (KeyError, IndexError):
        return None
    return (server.lower(), port, proxy_type(match.group(0)))


def proxy_secret(url: str) -> str:
    """Return the lowercased secret from a proxy URL, or '' if absent."""
    match = PROXY_PATTERN.search(url)
    if not match:
        return ''
    params = parse_qs(urlparse(match.group(0)).query)
    return params.get('secret', [''])[0].lower()


_URL_RANK_PREFIXES = (
    'tg://proxy',
    'https://t.me/proxy',
    'https://t.me/socks',
    'https://t.me/killer',
)


def _url_rank(u: str) -> int:
    """Lower is preferred. tg:// proxy links beat https t.me variants."""
    for rank, prefix in enumerate(_URL_RANK_PREFIXES):
        if u.startswith(prefix):
            return rank
    return len(_URL_RANK_PREFIXES)


def _prefer_candidate(prev_url: str, prev_ts: str, cand_url: str, cand_ts: str) -> bool:
    """Decide whether a candidate entry replaces the stored one for an endpoint.

    Both entries share the same (server, port, type). The most recent publication wins;
    on equal/missing timestamps the more complete (longer) secret wins, then the
    preferred URL form. Collapses secret-rotated duplicates to the freshest,
    fullest entry regardless of the order entries are seen in.
    """
    prev_key, cand_key = prev_ts or '', cand_ts or ''
    if prev_key != cand_key:
        return cand_key > prev_key
    prev_len, cand_len = len(proxy_secret(prev_url)), len(proxy_secret(cand_url))
    if prev_len != cand_len:
        return cand_len > prev_len
    return _url_rank(cand_url) < _url_rank(prev_url)


def _store_proxy(found: dict, url: str, ts: str):
    """Insert or merge a proxy entry keyed by (server, port, type) identity.

    When an entry for the same server/port/type already exists (e.g. the secret
    was rotated), keep the more recent / more complete one via _prefer_candidate.
    """
    url = normalize_to_tg_url(url)
    identity = proxy_identity(url)
    if identity is None:
        return
    if identity not in found:
        found[identity] = (url, ts)
        return
    prev_url, prev_ts = found[identity]
    if _prefer_candidate(prev_url, prev_ts, url, ts):
        found[identity] = (url, ts)


def extract_proxies(messages: list) -> list:
    """
    Extract unique proxy URLs from messages with timestamps.
    Returns list of (url, timestamp) tuples, newest-first.
    """
    found = {}
    for msg in messages:
        text = msg.get('text', '') or msg.get('message', '')
        ts = parse_timestamp(msg)
        for match in PROXY_PATTERN.finditer(text):
            url = sanitize_proxy_url(match.group(0))
            _store_proxy(found, url, ts)
    return sorted(found.values(), key=lambda x: (x[1] or '', x[0]), reverse=True)


def get_existing_proxies() -> list:
    """
    Load existing proxies from file.
    Returns list of (url, timestamp) tuples, oldest-first.
    """
    if not os.path.exists(PROXIES_FILE):
        return []
    result = []
    with open(PROXIES_FILE) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if '|' in line:
                url, ts = line.rsplit('|', 1)
                result.append((normalize_to_tg_url(url.strip()), ts.strip()))
            else:
                result.append((normalize_to_tg_url(line), ''))
    result.sort(key=lambda x: (x[1] or '', x[0]))
    return result


def merge_proxies(new_proxies: list, existing: list, max_size: int = MAX_PROXIES) -> list:
    """
    Merge new and existing proxies, keeping at most max_size total.

    Proxies are keyed by (server, port, type); when the same endpoint appears in both
    lists (e.g. a rotated secret), the more recent / fuller entry wins. Remaining
    slots are filled from existing entries not already present, newest first.
    The result is capped at max_size; when over capacity, the oldest entries
    are dropped.

    Returns (url, timestamp) tuples, newest-first.
    """
    found = {}
    for url, ts in new_proxies:
        _store_proxy(found, url, ts)

    existing_extra = {}
    for url, ts in existing:
        identity = proxy_identity(url)
        if identity is None:
            continue
        if identity in found:
            # Same endpoint already kept from the new fetch; merge so a newer or
            # fuller existing entry can still win (rotated-secret dedup).
            _store_proxy(found, url, ts)
            continue
        _store_proxy(existing_extra, url, ts)

    slots = max(0, max_size - len(found))
    kept_existing = sorted(
        existing_extra.values(),
        key=lambda x: (x[1] or '', x[0]),
        reverse=True,
    )[:slots]
    for url, ts in kept_existing:
        _store_proxy(found, url, ts)

    combined = sorted(found.values(), key=lambda x: (x[1] or '', x[0]), reverse=True)
    return combined[:max_size]


def proxies_unchanged(combined: list, existing: list) -> bool:
    """True when URL set and timestamps match (order ignored)."""
    return sorted(combined, key=lambda x: x[0]) == sorted(existing, key=lambda x: x[0])


def write_proxies_atomic(proxies: list):
    """
    Write proxies to temp file then rename (atomic).
    Format: URL|YYYY-MM-DDTHH:MM:SS
    """
    dir_name = os.path.dirname(PROXIES_FILE)
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, prefix='.proxies_', suffix='.tmp')
    lines = [f'{url}|{ts}' if ts else url for url, ts in proxies]
    content = '\n'.join(lines) + '\n'
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(content)
        os.replace(tmp_path, PROXIES_FILE)
        publish_cache_busted_list(content)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def hashed_proxies_filename(content: str) -> str:
    digest = hashlib.sha256(content.encode()).hexdigest()[:12]
    return f'proxies-{digest}.txt'


def publish_cache_busted_list(content: str):
    """
    GitHub Pages caches same-path files (proxies.txt) across deploys.
    Publish a content-hashed copy and point index.html at it so browsers
    and the Pages CDN fetch a new URL after each list change.
    """
    docs_dir = os.path.dirname(PROXIES_FILE)
    busted_name = hashed_proxies_filename(content)
    busted_path = os.path.join(docs_dir, busted_name)
    with open(busted_path, 'w') as f:
        f.write(content)

    for name in os.listdir(docs_dir):
        if PROXIES_HASHED_NAME.match(name) and name != busted_name:
            os.unlink(os.path.join(docs_dir, name))

    index_path = os.path.join(docs_dir, 'index.html')
    if not os.path.isfile(index_path):
        return

    with open(index_path) as f:
        html = f.read()
    updated, n = INDEX_PROXIES_URL_RE.subn(
        f"const PROXIES_URL = './{busted_name}'",
        html,
        count=1,
    )
    if n != 1:
        logger.warning('Could not update PROXIES_URL in %s', index_path)
        return
    with open(index_path, 'w') as f:
        f.write(updated)


def main():
    _configure_file_logging()
    logger.info('Fetching proxies from Telegram...')
    messages = mcp_call('get_messages', {
        'chat_id': TELEGRAM_CHAT,
        'query': 'proxy',
        'limit': 200,
        'reply_to_id': TOPIC_ID,
    })

    if messages is None:
        die('MCP call failed')
    if not messages:
        logger.warning('No messages fetched from topic.')
        sys.exit(0)

    new_proxies = extract_proxies(messages)
    logger.info(f'Found {len(new_proxies)} unique proxy(s) in messages')

    existing = get_existing_proxies()
    combined = merge_proxies(new_proxies, existing)

    new_urls = {u for u, _ in combined} - {u for u, _ in existing}
    removed_urls = {u for u, _ in existing} - {u for u, _ in combined}
    logger.info(
        f'New: {len(new_urls)}, removed: {len(removed_urls)}, total: {len(combined)}'
    )

    if proxies_unchanged(combined, existing):
        logger.info('No changes to proxies list.')
        sys.exit(0)

    write_proxies_atomic(combined)
    logger.info('Updated docs/proxies.txt')


if __name__ == '__main__':
    main()
