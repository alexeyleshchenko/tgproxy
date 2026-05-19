#!/usr/bin/env python3
"""
Update Telegram proxy list from @telemtrs Free proxy topic.
Reads TG_MCP_TOKEN from environment variable or servers.json.
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

# === CONFIG ===
REPO_DIR = os.path.dirname(os.path.abspath(__file__))
PROXIES_FILE = os.path.join(REPO_DIR, 'docs', 'proxies.txt')
TELEGRAM_CHAT = 'telemtrs'
TOPIC_ID = 16160  # Free proxy forum topic in @telemtrs
MAX_PROXIES = 30
PROXY_PATTERN = re.compile(
    r'https://t\.me/(?:socks|proxy|killer)\?server=[^&\s]+&port=[^&\s]+&secret=[^&\s]+'
    r'|tg://proxy\?server=[^&\s]+&port=[^&\s]+&secret=[^&\s]+'
)
# ISO format for timestamps
TS_FORMAT = '%Y-%m-%dT%H:%M:%S'

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)s %(message)s',
    datefmt='%Y-%m-%dT%H:%M:%SZ',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


def die(msg):
    """Print error and exit with code 1."""
    logger.error(msg)
    sys.exit(1)


def mcp_call(tool: str, params: dict, timeout: int = 120) -> list:
    """Call MCP server via shell command (from tools.toml)."""
    import re
    args_json = json.dumps(params)
    cmd = ['/root/.local/bin/mcp', 'tg-mcp', tool, args_json]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        if proc.returncode != 0:
            logger.error(f'MCP failed: {proc.stderr}')
            return []

        output = proc.stdout.strip()
        if not output:
            return []

        # Strip ANSI escape codes
        ansi_escape = re.compile(r'\x1b\[[0-9;]*m')
        output = ansi_escape.sub('', output)

        # Find JSON object in output
        start = output.find('{')
        if start == -1:
            return []
        json_str = output[start:]

        # Parse outer JSON
        result = json.loads(json_str)

        # Extract messages from content[].text
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
        die(f'MCP call failed: {e}')
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

        r = sub(['git', 'add', 'docs/proxies.txt'])
        if r.returncode != 0:
            logger.error(f'git add failed: {r.stderr}')
            return False

        r = sub(['git', 'diff', '--staged', '--quiet'])
        if r.returncode == 1:
            r = sub(['git', 'commit', '-m', f'Update proxies {date.today()}'])
            if r.returncode != 0:
                logger.error(f'git commit failed: {r.stderr}')
                return False

            r = sub(['git', 'push'])
            if r.returncode != 0:
                logger.error(f'git push failed: {r.stderr}')
                return False
            return True
        return False
    except subprocess.TimeoutExpired:
        logger.error('Git command timed out')
        return False
    except Exception as e:
        logger.error(f'Git error: {e}')
        return False


def main():
    logger.info('Fetching proxies from Telegram...')
    messages = mcp_call('get_messages', {
        'chat_id': TELEGRAM_CHAT,
        'query': 'proxy',
        'limit': 200,
        'reply_to_id': TOPIC_ID
    })

    if not messages:
        logger.warning('No messages fetched from topic.')
        sys.exit(0)

    new_proxies = extract_proxies(messages)
    logger.info(f'Found {len(new_proxies)} unique proxy(s) in messages')

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
    logger.info(f'Adding {max(0, new_count)} new proxy(s) (total: {len(combined)})')

    if new_count <= 0 and existing == combined:
        logger.info('No new proxies to add.')
        sys.exit(0)

    write_proxies_atomic(combined)

    pushed = git_add_commit_push()
    if not pushed:
        logger.error('WARNING: proxies.txt updated locally but git push failed.')
        sys.exit(1)

    logger.info('Done!')
    sys.exit(0)


if __name__ == '__main__':
    main()
