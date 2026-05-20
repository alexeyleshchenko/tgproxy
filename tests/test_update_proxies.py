"""
Tests for update_proxies.py
"""

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from update_proxies import (
    PROXY_PATTERN,
    TS_FORMAT,
    extract_proxies,
    get_existing_proxies,
    merge_proxies,
    parse_timestamp,
    proxies_unchanged,
    write_proxies_atomic,
)


class TestProxyPattern:
    """Tests for PROXY_PATTERN regex."""

    def test_tg_proxy(self):
        url = "tg://proxy?server=example.com&port=443&secret=abc123"
        assert PROXY_PATTERN.search(url) is not None

    def test_https_t_me_proxy(self):
        url = "https://t.me/proxy?server=example.com&port=443&secret=abc123"
        assert PROXY_PATTERN.search(url) is not None

    def test_https_t_me_socks(self):
        url = "https://t.me/socks?server=example.com&port=1080&secret=abc123"
        assert PROXY_PATTERN.search(url) is not None

    def test_https_t_me_killer(self):
        url = "https://t.me/killer?server=example.com&port=443&secret=abc123"
        assert PROXY_PATTERN.search(url) is not None

    def test_vmess_not_matched(self):
        url = "vmess://eyJhbGciOiJIUzI1NiIsInB5ciI6Ik..."
        assert PROXY_PATTERN.search(url) is None

    def test_trojan_not_matched(self):
        url = "trojan://password@example.com:443"
        assert PROXY_PATTERN.search(url) is None

    def test_ss_not_matched(self):
        url = "ss://YmY5ZTQ4ZDQtNWQyMC00NDQwLWI2YzEtODQwZjYyZTkyZjFk@1.2.3.4:8388"
        assert PROXY_PATTERN.search(url) is None

    def test_url_without_server(self):
        url = "tg://proxy?port=443&secret=abc123"
        assert PROXY_PATTERN.search(url) is None

    def test_url_without_port(self):
        url = "tg://proxy?server=example.com&secret=abc123"
        assert PROXY_PATTERN.search(url) is None

    def test_url_without_secret(self):
        url = "tg://proxy?server=example.com&port=443"
        assert PROXY_PATTERN.search(url) is None

    def test_partial_match(self):
        text = "Check this tg://proxy?server=example.com&port=443&secret=abc123 please"
        match = PROXY_PATTERN.search(text)
        assert match is not None
        assert match.group(0) == "tg://proxy?server=example.com&port=443&secret=abc123"


class TestTimestampFormat:
    def test_format_string(self):
        assert TS_FORMAT == '%Y-%m-%dT%H:%M:%S'


class TestProxyPatternEdgeCases:
    def test_port_443(self):
        url = "tg://proxy?server=example.com&port=443&secret=abc"
        assert PROXY_PATTERN.search(url) is not None

    def test_port_8443(self):
        url = "tg://proxy?server=example.com&port=8443&secret=abc"
        assert PROXY_PATTERN.search(url) is not None

    def test_ipv4_server(self):
        url = "tg://proxy?server=1.2.3.4&port=443&secret=abc"
        assert PROXY_PATTERN.search(url) is not None

    def test_secret_with_special_chars(self):
        url = "tg://proxy?server=example.com&port=443&secret=ee3f8a91c2d7e04b6a9f12c5e8370bd4"
        assert PROXY_PATTERN.search(url) is not None

    def test_server_with_dash(self):
        url = "tg://proxy?server=my-server.example.com&port=443&secret=abc"
        assert PROXY_PATTERN.search(url) is not None

    def test_server_with_underscore(self):
        url = "tg://proxy?server=my_server.example.com&port=443&secret=abc"
        assert PROXY_PATTERN.search(url) is not None


def make_proxy(url, days_ago):
    ts = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return (url, ts.strftime(TS_FORMAT))


def make_proxies(url_template, count, start_day, step=1):
    return [make_proxy(url_template.format(i), start_day + i * step) for i in range(count)]


class TestParseTimestamp:
    def test_iso_string_with_z(self):
        msg = {'date': '2026-05-19T12:34:56Z'}
        assert parse_timestamp(msg) == '2026-05-19T12:34:56'

    def test_iso_string_naive_treated_as_utc(self):
        msg = {'date': '2026-05-19T12:34:56'}
        assert parse_timestamp(msg) == '2026-05-19T12:34:56'

    def test_unix_timestamp(self):
        dt = datetime(2026, 5, 19, 12, 0, 0, tzinfo=timezone.utc)
        msg = {'date': dt.timestamp()}
        assert parse_timestamp(msg) == '2026-05-19T12:00:00'

    def test_missing_date(self):
        assert parse_timestamp({}) == ''


class TestExtractProxies:
    def test_extracts_from_text(self):
        url = "tg://proxy?server=example.com&port=443&secret=abc"
        messages = [
            {'text': f'Use {url}', 'date': '2026-05-19T10:00:00Z'},
        ]
        found = extract_proxies(messages)
        assert len(found) == 1
        assert found[0][0] == url
        assert found[0][1] == '2026-05-19T10:00:00'

    def test_deduplicates_urls(self):
        url = "tg://proxy?server=example.com&port=443&secret=abc"
        messages = [
            {'text': url, 'date': '2026-05-19T10:00:00Z'},
            {'text': url, 'date': '2026-05-18T10:00:00Z'},
        ]
        assert len(extract_proxies(messages)) == 1


class TestProxyMerge:
    def test_25_existing_10_new_preserves_all_new(self):
        new_proxies = make_proxies("tg://new{}|secret", 10, start_day=0)
        existing = make_proxies("tg://existing{}|secret", 25, start_day=10)

        merged = merge_proxies(new_proxies, existing)

        assert len(merged) == 30
        all_urls = [p[0] for p in merged]
        for i in range(10):
            assert any(f"new{i}" in url for url in all_urls)

    def test_truncation_drops_oldest_existing(self):
        new_proxies = make_proxies("tg://new{}|secret", 10, start_day=0)
        existing = make_proxies("tg://existing{}|secret", 25, start_day=10)

        merged = merge_proxies(new_proxies, existing)
        merged_urls = [u for u, _ in merged]

        for i in range(20, 25):
            assert not any(f"existing{i}" in u for u in merged_urls)
        assert any("existing0" in u for u in merged_urls)
        assert any("existing19" in u for u in merged_urls)

    def test_newest_first_order(self):
        proxies = make_proxies("tg://p{}|secret", 3, start_day=0)
        merged = merge_proxies(proxies, [])
        timestamps = [ts for _, ts in merged]
        assert timestamps == sorted(timestamps, reverse=True)

    def test_caps_when_new_exceeds_max_size(self):
        new_proxies = make_proxies("tg://new{}|secret", 47, start_day=0)
        merged = merge_proxies(new_proxies, [], max_size=30)
        assert len(merged) == 30
        merged_urls = [u for u, _ in merged]
        for i in range(30):
            assert any(f"new{i}" in u for u in merged_urls)
        for i in range(30, 47):
            assert not any(f"new{i}" in u for u in merged_urls)


class TestProxiesUnchanged:
    def test_same_set_and_timestamps(self):
        a = make_proxies("tg://a{}|secret", 2, start_day=0)
        assert proxies_unchanged(a, list(a))

    def test_different_url(self):
        a = make_proxies("tg://a{}|secret", 2, start_day=0)
        b = make_proxies("tg://b{}|secret", 2, start_day=0)
        assert not proxies_unchanged(a, b)

    def test_order_ignored(self):
        a = make_proxies("tg://a{}|secret", 2, start_day=0)
        b = list(reversed(a))
        assert proxies_unchanged(a, b)


class TestGetExistingProxies:
    def test_loads_file(self, tmp_path, monkeypatch):
        import update_proxies as mod
        path = tmp_path / 'proxies.txt'
        path.write_text(
            "tg://proxy?server=a&port=1&secret=x|2026-01-01T00:00:00\n"
            "tg://proxy?server=b&port=2&secret=y\n"
        )
        monkeypatch.setattr(mod, 'PROXIES_FILE', str(path))
        loaded = get_existing_proxies()
        assert len(loaded) == 2
        assert 'server=b' in loaded[0][0]
        assert loaded[0][1] == ''


class TestWriteProxiesAtomic:
    def test_writes_timestamped_lines(self, tmp_path, monkeypatch):
        import update_proxies as mod
        path = tmp_path / 'proxies.txt'
        monkeypatch.setattr(mod, 'PROXIES_FILE', str(path))
        write_proxies_atomic([
            ('tg://proxy?server=a&port=1&secret=x', '2026-01-01T00:00:00'),
            ('tg://proxy?server=b&port=2&secret=y', ''),
        ])
        content = path.read_text()
        assert 'tg://proxy?server=a&port=1&secret=x|2026-01-01T00:00:00' in content
        assert 'tg://proxy?server=b&port=2&secret=y\n' in content
