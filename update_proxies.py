#!/usr/bin/env python3
"""
Update Telegram proxy list from @telemtrs Free proxy topic.
Stores proxies with timestamps: URL|YYYY-MM-DDTHH:MM:SS
"""

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
TELEGRAM_CHAT = 'telemtrs'
TOPIC_ID = 16160  # Free proxy forum topic in @telemtrs
MAX_PROXIES = 30
TG_MCP_URL = os.environ.get('TG_MCP_URL', 'https://tg-mcp.l1979.ru/v1/mcp')
MCP_PROTOCOL_VERSION = '2024-11-05'
PROXY_PATTERN = re.compile(
    r'https://t\.me/(?:socks|proxy|killer)\?server=[^&\s]+&port=\d+&secret=[0-9a-fA-F]+'
    r'|tg://proxy\?server=[^&\s]+&port=\d+&secret=[0-9a-fA-F]+'
)
TS_FORMAT = '%Y-%m-%dT%H:%M:%S'

root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG)
root_logger.handlers.clear()
root_logger.addHandler(logging.StreamHandler(sys.stdout))

LOG_DIR = '/var/log/tgproxy'
LOG_FILE = os.path.join(LOG_DIR, 'update.log')
try:
    os.makedirs(LOG_DIR, exist_ok=True)
    file_handler = logging.FileHandler(LOG_FILE)
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))
    root_logger.addHandler(file_handler)
except Exception as primary_err:
    LOG_FILE = os.path.expanduser('~/tgproxy/update.log')
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        file_handler = logging.FileHandler(LOG_FILE)
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s %(levelname)s %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        ))
        root_logger.addHandler(file_handler)
    except Exception as fallback_err:
        print(
            f'Warning: file logging disabled ({primary_err}; {fallback_err})',
            file=sys.stderr,
        )

logger = logging.getLogger(__name__)

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
) -> tuple[int, str, dict | None]:
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
            ts = raw
            if ts[-1] != 'Z' and '+' not in ts:
                ts = ts + 'Z'
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


def proxy_identity(url: str) -> tuple[str, str, str] | None:
    """Return (server, port, secret) identity for deduplication, or None."""
    match = PROXY_PATTERN.search(url)
    if not match:
        return None
    params = parse_qs(urlparse(match.group(0)).query)
    try:
        server = params['server'][0]
        port = params['port'][0]
        secret = params['secret'][0]
    except (KeyError, IndexError):
        return None
    return (server.lower(), port, secret.lower())


def prefer_proxy_url(current: str, candidate: str) -> str:
    """Pick the stored URL when two links refer to the same proxy."""
    def rank(u: str) -> int:
        if u.startswith('tg://proxy'):
            return 0
        if u.startswith('https://t.me/proxy'):
            return 1
        if u.startswith('https://t.me/socks'):
            return 2
        if u.startswith('https://t.me/killer'):
            return 3
        return 4

    return candidate if rank(candidate) < rank(current) else current


def _store_proxy(found: dict, url: str, ts: str):
    """Insert or merge a proxy entry keyed by server/port/secret identity."""
    url = normalize_to_tg_url(url)
    identity = proxy_identity(url)
    if identity is None:
        return
    if identity not in found:
        found[identity] = (url, ts)
        return
    prev_url, prev_ts = found[identity]
    merged_ts = prev_ts if prev_ts or not ts else ts
    found[identity] = (prefer_proxy_url(prev_url, url), merged_ts)


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

    New proxies are preferred over existing ones. Remaining slots are filled from
    existing entries not already present, preferring the newest by timestamp.
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
            prev_url, prev_ts = found[identity]
            merged_ts = prev_ts if prev_ts or not ts else ts
            found[identity] = (prefer_proxy_url(prev_url, url), merged_ts)
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
    lines = []
    for url, ts in proxies:
        if ts:
            lines.append(f'{url}|{ts}')
        else:
            lines.append(url)
    try:
        with os.fdopen(fd, 'w') as f:
            f.write('\n'.join(lines) + '\n')
        os.replace(tmp_path, PROXIES_FILE)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def main():
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
    sys.exit(0)


if __name__ == '__main__':
    main()
