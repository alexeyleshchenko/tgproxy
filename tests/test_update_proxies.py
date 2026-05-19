"""
Tests for update_proxies.py
"""

import sys
import os
import re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from update_proxies import PROXY_PATTERN, TS_FORMAT


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
        """vmess:// URLs should not be matched by PROXY_PATTERN."""
        url = "vmess://eyJhbGciOiJIUzI1NiIsInB5ciI6Ik..."
        assert PROXY_PATTERN.search(url) is None

    def test_trojan_not_matched(self):
        """trojan:// URLs should not be matched by PROXY_PATTERN."""
        url = "trojan://password@example.com:443"
        assert PROXY_PATTERN.search(url) is None

    def test_ss_not_matched(self):
        """ss:// URLs should not be matched by PROXY_PATTERN."""
        url = "ss://YmY5ZTQ4ZDQtNWQyMC00NDQwLWI2YzEtODQwZjYyZTkyZjFk@1.2.3.4:8388"
        assert PROXY_PATTERN.search(url) is None

    def test_url_without_server(self):
        """URL without server param should not match."""
        url = "tg://proxy?port=443&secret=abc123"
        assert PROXY_PATTERN.search(url) is None

    def test_url_without_port(self):
        """URL without port param should not match."""
        url = "tg://proxy?server=example.com&secret=abc123"
        assert PROXY_PATTERN.search(url) is None

    def test_url_without_secret(self):
        """URL without secret param should not match."""
        url = "tg://proxy?server=example.com&port=443"
        assert PROXY_PATTERN.search(url) is None

    def test_partial_match(self):
        """Pattern should match full URL, not partial."""
        text = "Check this tg://proxy?server=example.com&port=443&secret=abc123 please"
        match = PROXY_PATTERN.search(text)
        assert match is not None
        assert match.group(0) == "tg://proxy?server=example.com&port=443&secret=abc123"


class TestTimestampFormat:
    """Tests for TS_FORMAT constant."""

    def test_format_string(self):
        assert TS_FORMAT == '%Y-%m-%dT%H:%M:%S'


class TestProxyPatternEdgeCases:
    """Edge cases for proxy URL matching."""

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
        """Secret can contain various base64 chars."""
        url = "tg://proxy?server=example.com&port=443&secret=ee3f8a91c2d7e04b6a9f12c5e8370bd4"
        assert PROXY_PATTERN.search(url) is not None

    def test_server_with_dash(self):
        url = "tg://proxy?server=my-server.example.com&port=443&secret=abc"
        assert PROXY_PATTERN.search(url) is not None

    def test_server_with_underscore(self):
        url = "tg://proxy?server=my_server.example.com&port=443&secret=abc"
        assert PROXY_PATTERN.search(url) is not None
