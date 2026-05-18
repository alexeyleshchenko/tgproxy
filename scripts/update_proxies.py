#!/usr/bin/env python3
"""
Update Telegram proxy list from @telemtrs Free Proxy topic.
Reads TG_MCP_TOKEN from environment variable.
"""

import re
import json
import os
import subprocess
import sys
import urllib.request
import urllib.error

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROXIES_FILE = os.path.join(REPO_DIR, "docs", "proxies.txt")
MAX_PROXIES = 30
MCP_SERVER = "https://tg-mcp.l1979.ru/v1/mcp"
MCP_TOKEN = os.environ.get("TG_MCP_TOKEN", "")
MAX_RETRIES = 3

PROXY_PATTERN = re.compile(r'https://t\.me/(?:socks|proxy|killer)\?server=[^&\s]+')


def mcp_call(tool: str, params: dict) -> list[dict]:
    """Call MCP server via HTTP."""
    payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": tool, "arguments": params},
        "id": 1
    }
    
    for attempt in range(MAX_RETRIES):
        try:
            req = urllib.request.Request(
                MCP_SERVER,
                data=json.dumps(payload).encode(),
                headers={
                    "Authorization": f"Bearer {MCP_TOKEN}",
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream"
                },
                method="POST"
            )
            
            with urllib.request.urlopen(req, timeout=30) as response:
                result_text = response.read().decode()
            
            proxies = []
            for line in result_text.split('\n'):
                if line.startswith('data: '):
                    try:
                        data = json.loads(line[6:])
                        if 'result' in data and 'content' in data['result']:
                            content = data['result']['content']
                            if isinstance(content, list) and len(content) > 0:
                                text = content[0].get('text', '')
                                msg_data = json.loads(text)
                                if 'messages' in msg_data:
                                    proxies.extend(msg_data['messages'])
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
            return proxies
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                continue
            return []
    return []


def extract_proxies(messages: list[dict]) -> list[str]:
    """Extract proxy URLs from messages."""
    found = set()
    for msg in messages:
        text = msg.get('text', '') or msg.get('message', '')
        for match in PROXY_PATTERN.finditer(text):
            found.add(match.group(0))
    return sorted(found)


def get_existing_proxies() -> list[str]:
    """Load existing proxies from file."""
    if not os.path.exists(PROXIES_FILE):
        return []
    with open(PROXIES_FILE) as f:
        return [line.strip() for line in f if line.strip()]


def git_push() -> bool:
    """Commit and push changes if there are any."""
    try:
        subprocess.run(["git", "add", "docs/proxies.txt"], check=True, capture_output=True)
        result = subprocess.run(
            ["git", "commit", "-m", f"Update proxies {__import__('datetime').date.today()}"],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            subprocess.run(["git", "push"], check=True, capture_output=True)
            return True
        return False
    except subprocess.CalledProcessError:
        return False


def main():
    if not MCP_TOKEN:
        print("ERROR: TG_MCP_TOKEN environment variable not set")
        sys.exit(1)
    
    print("Fetching proxies from Telegram topic...")
    messages = mcp_call("get_messages", {
        "chat_id": "telemtrs",
        "reply_to_id": 16160,
        "query": "t.me",
        "limit": 50
    })
    
    if not messages:
        print("No messages fetched")
        sys.exit(1)
    
    new_proxies = extract_proxies(messages)
    print(f"Found {len(new_proxies)} unique proxies in messages")
    
    existing = get_existing_proxies()
    print(f"Existing proxies: {len(existing)}")
    
    # Deduplicate preserving order: new first, then existing
    seen = set()
    combined = []
    for p in new_proxies:
        if p not in seen:
            seen.add(p)
            combined.append(p)
    for p in existing:
        if p not in seen:
            seen.add(p)
            combined.append(p)
    
    all_proxies = combined[:MAX_PROXIES]
    
    new_count = len(all_proxies) - len(existing)
    if new_count <= 0:
        print(f"No new proxies to add (total: {len(all_proxies)})")
        sys.exit(0)
    
    print(f"Adding {new_count} new proxies (total: {len(all_proxies)})")
    
    with open(PROXIES_FILE, 'w') as f:
        for p in all_proxies:
            f.write(p + '\n')
    
    if git_push():
        print("Done!")
    else:
        print("Git push failed or no changes to commit")


if __name__ == "__main__":
    main()
