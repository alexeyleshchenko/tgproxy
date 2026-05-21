#!/usr/bin/env python3
"""
Update Telegram proxy list from @telemtrs Free proxy topic.
Stores proxies with timestamps: URL|YYYY-MM-DDTHH:MM:SS
"""

import json
import logging
import os
import re
import subprocess
import sys
import tempfile
from datetime import date, datetime, timezone
from urllib.parse import parse_qs, urlparse

# === CONFIG ===
REPO_DIR = os.path.dirname(os.path.abspath(__file__))
PROXIES_FILE = os.path.join(REPO_DIR, 'docs', 'proxies.txt')
TELEGRAM_CHAT = 'telemtrs'
TOPIC_ID = 16160  # Free proxy forum topic in @telemtrs
MAX_PROXIES = 30
TG_MCP_CALL = os.environ.get('TG_MCP_CALL', '/usr/local/bin/tg-mcp-call')
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


def die(msg):
    """Log error and exit with code 1."""
    logger.error(msg)
    sys.exit(1)


def mcp_call(tool: str, params: dict, timeout: int = 120) -> list | None:
    """
    Call MCP server via shell command.
    Returns message list on success (may be empty), or None on failure.
    """
    args_json = json.dumps(params)
    cmd = [TG_MCP_CALL, tool, args_json]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if proc.returncode != 0:
            logger.error(
                'tg-mcp-call failed (exit %s): %s',
                proc.returncode,
                proc.stderr or proc.stdout,
            )
            return None

        output = proc.stdout.strip()
        if not output:
            return []

        ansi_escape = re.compile(r'\x1b\[[0-9;]*m')
        output = ansi_escape.sub('', output)

        start = output.find('{')
        if start == -1:
            logger.error('MCP output contained no JSON object')
            return None
        result = json.loads(output[start:])

        if isinstance(result.get('messages'), list):
            return result['messages']

        messages = []
        for item in result.get('content', []):
            if item.get('type') == 'text':
                text = item.get('text', '')
                if text:
                    inner = json.loads(text)
                    messages.extend(inner.get('messages', []))
        return messages
    except subprocess.TimeoutExpired:
        die('MCP call timed out')
    except Exception as e:
        logger.error(f'MCP call failed: {e}')
        return None


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


def read_proxies_file_bytes() -> bytes | None:
    if not os.path.exists(PROXIES_FILE):
        return None
    with open(PROXIES_FILE, 'rb') as f:
        return f.read()


def restore_proxies_file(backup: bytes | None):
    """Restore proxies.txt from pre-write backup."""
    if backup is None:
        if os.path.exists(PROXIES_FILE):
            os.unlink(PROXIES_FILE)
        return
    with open(PROXIES_FILE, 'wb') as f:
        f.write(backup)


def undo_last_commit():
    """Drop the last local commit; working tree should already match restored file."""
    subprocess.run(
        ['git', 'reset', '--mixed', 'HEAD~1'],
        cwd=REPO_DIR,
        capture_output=True,
        timeout=60,
    )
    subprocess.run(
        ['git', 'checkout', '--', 'docs/proxies.txt'],
        cwd=REPO_DIR,
        capture_output=True,
        timeout=60,
    )


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


def git_add_commit_push() -> str:
    """
    Git add, commit, push.
    Returns: 'pushed', 'no_changes', 'failed', or 'push_failed'.
    """
    try:
        sub = lambda cmd: subprocess.run(
            cmd,
            cwd=REPO_DIR,
            capture_output=True,
            text=True,
            timeout=60,
        )

        r = sub(['git', 'add', 'docs/proxies.txt'])
        if r.returncode != 0:
            logger.error(f'git add failed: {r.stderr}')
            return 'failed'

        r = sub(['git', 'diff', '--staged', '--quiet'])
        if r.returncode == 1:
            commit_msg = (
                f'Update proxies {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}'
            )
            r = sub(['git', 'commit', '-m', commit_msg])
            if r.returncode != 0:
                logger.error(f'git commit failed: {r.stderr}')
                return 'failed'

            r = sub(['git', 'push'])
            if r.returncode != 0:
                logger.error(f'git push failed: {r.stderr}')
                return 'push_failed'
            return 'pushed'
        return 'no_changes'
    except subprocess.TimeoutExpired:
        logger.error('Git command timed out')
        return 'failed'
    except Exception as e:
        logger.error(f'Git error: {e}')
        return 'failed'


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

    backup = read_proxies_file_bytes()
    write_proxies_atomic(combined)

    git_result = git_add_commit_push()
    if git_result == 'pushed':
        logger.info('Done!')
        sys.exit(0)

    restore_proxies_file(backup)
    if git_result == 'push_failed':
        undo_last_commit()
        die('proxies.txt reverted: git push failed after local commit')
    if git_result == 'no_changes':
        die('proxies.txt reverted: git reported no staged changes after write')
    die('proxies.txt reverted: git add/commit failed')


if __name__ == '__main__':
    main()
