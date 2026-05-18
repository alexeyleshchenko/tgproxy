#!/usr/bin/env python3
"""
Update Telegram proxy list from @telemtrs Free proxy topic.
Reads TG_MCP_TOKEN from environment variable.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import date

# === CONFIG ===
REPO_DIR = os.path.dirname(os.path.abspath(__file__))
PROXIES_FILE = os.path.join(REPO_DIR, 'proxies.txt')
MCP_URL = os.environ.get('MCP_URL', 'https://tg-mcp.l1979.ru/v1/mcp')
MCP_TOKEN = os.environ.get('TG_MCP_TOKEN')
TELEGRAM_CHAT = 'telemtrs'
TOPIC_ID = 16160  # Free proxy forum topic in @telemtrs
MAX_PROXIES = 30
PROXY_PATTERN = re.compile(
    r'https://t\.me/(?:socks|proxy|killer)\?server=[^&\s]+&port=[^&\s]+&secret=[^&\s]+'
)


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
            'Accept': 'text/event-stream'
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
                                    inner = json.loads(item['text'])
                                    if 'messages' in inner:
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


def extract_proxies(messages: list) -> list:
    """Extract unique proxy URLs from messages, sorted for determinism."""
    found = set()
    for msg in messages:
        text = msg.get('text', '') or msg.get('message', '')
        for match in PROXY_PATTERN.finditer(text):
            found.add(match.group(0))
    return sorted(found)


def get_existing_proxies() -> list:
    """Load existing proxies from file, newest-first by line order."""
    if not os.path.exists(PROXIES_FILE):
        return []
    with open(PROXIES_FILE) as f:
        return [line.strip() for line in f if line.strip()]


def write_proxies_atomic(proxies: list):
    """Write proxies to temp file then rename (atomic)."""
    dir_name = os.path.dirname(PROXIES_FILE)
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, prefix='.proxies_', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w') as f:
            f.write('\n'.join(proxies) + '\n')
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
            # There are staged changes
            r = sub(['git', 'commit', '-m', f'update: add proxies {date.today()}'])
            if r.returncode != 0:
                print(f'git commit failed: {r.stderr}', file=sys.stderr)
                return False

            r = sub(['git', 'push'])
            if r.returncode != 0:
                print(f'git push failed: {r.stderr}', file=sys.stderr)
                return False
            return True
        return False  # No changes
    except subprocess.TimeoutExpired:
        print('Git command timed out', file=sys.stderr)
        return False
    except Exception as e:
        print(f'Git error: {e}', file=sys.stderr)
        return False


def main():
    check_token()

    print('Fetching proxies from Telegram topic...')
    messages = mcp_call('get_messages', {
        'chat_id': TELEGRAM_CHAT,
        'reply_to_id': TOPIC_ID,
        'query': 't.me',
        'limit': 100
    })

    if not messages:
        print('No messages fetched from topic.')
        sys.exit(0)

    new_proxies = extract_proxies(messages)
    print(f'Found {len(new_proxies)} unique proxy(s) in messages')

    existing = get_existing_proxies()
    seen = set()
    combined = []

    # New proxies first (most recent)
    for p in new_proxies:
        if p not in seen:
            seen.add(p)
            combined.append(p)

    # Then existing proxies in file order (skip duplicates)
    for p in existing:
        if p not in seen:
            seen.add(p)
            combined.append(p)

    # Keep at most MAX_PROXIES
    combined = combined[:MAX_PROXIES]

    new_count = len(combined) - len(existing)
    print(f'Adding {max(0, new_count)} new proxy(s) (total: {len(combined)})')

    if new_count <= 0:
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
