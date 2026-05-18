#!/usr/bin/env python3
"""
Update proxies — read from docs/proxies.txt, normalize all to tg://proxy? format, filter bad, preserve timestamps.
"""
import re
from pathlib import Path

PROXIES_FILE = Path(__file__).parent / "docs" / "proxies.txt"

def extract_timestamp(url):
    """Split URL and timestamp. Returns (url, timestamp)."""
    url = url.strip()
    # Match |2026-... or |2025-... suffix
    m = re.search(r'\|(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[^|]*)$', url)
    if m:
        return url[:m.start()], m.group(1)
    return url, None

def normalize_url(url):
    """Convert URL to tg://proxy format."""
    if not url:
        return None

    # Already tg://proxy format
    if url.startswith('tg://proxy?'):
        return url

    # Convert https://t.me/proxy? → tg://proxy?
    if url.startswith('https://t.me/proxy?'):
        return 'tg://proxy?' + url[len('https://t.me/proxy?'):]

    # Skip other formats (vmess://, trojan://, ss://) - we only want tg://proxy
    return None

def is_valid(url):
    """Filter malformed URLs."""
    if not url:
        return False
    if 'server=' not in url or 'port=' not in url:
        return False
    bad = ['*', '**|', '**)', '..', ' ', 'undefined', '`', ')']
    for p in bad:
        if p in url:
            return False
    return True

def main():
    text = PROXIES_FILE.read_text()
    lines = text.strip().split('\n')

    normalized = []
    for line in lines:
        url, ts = extract_timestamp(line)
        url = normalize_url(url)
        if is_valid(url):
            if ts:
                url = f"{url}|{ts}"
            normalized.append(url)

    # Deduplicate by (url_base_without_timestamp), preserve order of first seen
    seen = set()
    unique = []
    for u in normalized:
        url_base, _ = extract_timestamp(u)
        if url_base not in seen:
            seen.add(url_base)
            unique.append(u)

    PROXIES_FILE.write_text('\n'.join(unique) + '\n')
    print(f"Wrote {len(unique)} clean tg://proxy URLs to {PROXIES_FILE}")

if __name__ == '__main__':
    main()
