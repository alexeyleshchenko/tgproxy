#!/usr/bin/env python3
"""
Update Telegram proxy list from @telemtrs Free proxy topic.
Reads TG_MCP_TOKEN from environment variable.
Stores proxies with timestamps: URL|YYYY-MM-DDTHH:MM:SS
"""

import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import date, datetime

# === CONFIG ===
REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROXIES_FILE = os.path.join(REPO_DIR, 'docs', 'proxies.txt')
MCP_URL = os.environ.get('MCP_URL', 'https://tg-mcp.l1979.ru/v1/mcp')
MCP_TOKEN = os.environ.get('TG_MCP_TOKEN')
TELEGRAM_CHAT = 'telemtrs'
TOPIC_ID = 16160  # Free proxy forum topic in @telemtrs
MAX_PROXIES = 30
PROXY_PATTERN = re.compile(
    r'https://t\.me/(?:socks|proxy|killer)\?server=[^&\s]+&port=[^&\s]+&secret=[^&\s]+'
    r'|tg://proxy\?server=[^&\s]+&port=[^&\s]+&secret=[^&\s]+'
)
# ISO format for timestamps
TS_FORMAT = '%Y-%m-%dT%H:%M:%S'


def die(msg):
    """Print error and exit with code 1."""
    print(msg, file=sys.stderr)
    sys.exit(1)


def check_token():
    """Fail fast if token is missing."""
    if not MCP_TOKEN:
        die('TG_MCP_TOKEN environment variable not set')


def mcp_call(tool: str, params: dict, timeout: int = 30) -> list:
    """Call MCP server via HTTP and return parsed result list."""
    import urllib.request

    payload = {
        'jsonrpc': '2.0',
        'id': 1,
        'method': 'tools/call',
        'params': {'name': tool, 'arguments': params}
    }

    req = urllib.request.Request(
        MCP_URL,
        data=json.dumps(payload).encode(),
        headers={
            'Authorization': f'Bearer {MCP_TOKEN}',
            'Content-Type': 'application/json',
            'Accept': 'application/json, text/event-stream'
        },
        method='POST'
    )

    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                result_text = ''
                for line in resp:
                    line = line.decode().strip()
                    if line.startswith('data: '):
                        data = json.loads(line[6:])
                        if 'result' in data and isinstance(data['result'], dict):
                            content = data['result'].get('content', [])
                            for item in content:
                                if item.get('type') == 'text':
                                    inner = None
                                    try:
                                        inner = json.loads(item['text'])
                                    except (json.JSONDecodeError, TypeError, KeyError):
                                        continue
                                    if inner and 'messages' in inner:
                                        return inner['messages']
                return []
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                die(f'Auth failed ({e.code}). Check TG_MCP_TOKEN.')
            if attempt < 2:
                print(f'HTTP error {e.code}, retrying...', file=sys.stderr)
                continue
            raise
        except Exception as e:
            if attempt < 2:
                print(f'Error: {e}, retrying...', file=sys.stderr)
                continue
            raise

    return []


def parse_timestamp(msg: dict) -> str:
    """Extract timestamp from message date field, return ISO string or empty string."""
    raw = msg.get('date')
    if not raw:
        return ''
    if isinstance(raw, str):
        try:
            ts = raw
            if ts[-1] != 'Z' and '+' not in ts:
                ts = ts + 'Z'
            dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
            return dt.strftime(TS_FORMAT)
        except Exception:
            pass
    try:
        dt = datetime.fromtimestamp(float(raw))
        return dt.strftime(TS_FORMAT)
    except Exception:
        pass
    return ''


def extract_proxies(messages: list) -> list:
    """
    Extract unique proxy URLs from messages with timestamps.
    Returns list of (url, timestamp) tuples.
    Sorts by timestamp DESC for determinism.
    """
    found = {}  # url -> timestamp (keep first/most recent)
    for msg in messages:
        text = msg.get('text', '') or msg.get('message', '')
        ts = parse_timestamp(msg)
        for match in PROXY_PATTERN.finditer(text):
            url = match.group(0)
            if url not in found or (ts and found[url] == ''):
                found[url] = ts
    return sorted(found.items(), key=lambda x: (x[1] or '', x[0]), reverse=True)


def get_existing_proxies() -> list:
    """
    Load existing proxies from file.
    Returns list of (url, timestamp) tuples, oldest-first for stable re-insertion.
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
                result.append((url.strip(), ts.strip()))
            else:
                result.append((line, ''))
    result.sort(key=lambda x: (x[1] or '', x[0]))
    return result


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


def git_add_commit_push() -> bool:
    """Git add, commit, push. Returns True on success, False on failure."""
    try:
        sub = lambda cmd: subprocess.run(
            cmd,
            cwd=REPO_DIR,
            capture_output=True,
            text=True,
            timeout=60
        )

        r = sub(['git', 'add', 'proxies.txt'])
        if r.returncode != 0:
            print(f'git add failed: {r.stderr}', file=sys.stderr)
            return False

        r = sub(['git', 'diff', '--staged', '--quiet'])
        if r.returncode == 1:
            r = sub(['git', 'commit', '-m', f'Update proxies {date.today()}'])
            if r.returncode != 0:
                print(f'git commit failed: {r.stderr}', file=sys.stderr)
                return False

            r = sub(['git', 'push'])
            if r.returncode != 0:
                print(f'git push failed: {r.stderr}', file=sys.stderr)
                return False
            return True
        return False
    except subprocess.TimeoutExpired:
        print('Git command timed out', file=sys.stderr)
        return False
    except Exception as e:
        print(f'Git error: {e}', file=sys.stderr)
        return False


def main():
    check_token()

    print('Fetching proxies from Telegram...')
    messages = mcp_call('get_messages', {
        'chat_id': TELEGRAM_CHAT,
        'query': 'proxy',
        'limit': 200
    })

    if not messages:
        print('No messages fetched from topic.')
        sys.exit(0)

    new_proxies = extract_proxies(messages)
    print(f'Found {len(new_proxies)} unique proxy(s) in messages')

    existing = get_existing_proxies()
    seen = {}
    combined = []

    for url, ts in new_proxies:
        if url not in seen:
            seen[url] = True
            combined.append((url, ts))

    for url, ts in existing:
        if url not in seen:
            seen[url] = True
            combined.append((url, ts))

    combined = combined[:MAX_PROXIES]

    new_count = len(combined) - len(existing)
    print(f'Adding {max(0, new_count)} new proxy(s) (total: {len(combined)})')

    if new_count <= 0 and existing == combined:
        print('No new proxies to add.')
        sys.exit(0)

    write_proxies_atomic(combined)

    pushed = git_add_commit_push()
    if not pushed:
        print('WARNING: proxies.txt updated locally but git push failed.', file=sys.stderr)
        sys.exit(1)

    print('Done!')
    sys.exit(0)


if __name__ == '__main__':
    main()
