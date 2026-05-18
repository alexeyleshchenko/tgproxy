"""
Tests for update_proxies.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from update_proxies import (
    extract_timestamp,
    normalize_url,
    is_valid,
)


class TestExtractTimestamp:
    """Tests for extract_timestamp function."""

    def test_url_with_timestamp(self):
        url = "tg://proxy?server=example.com&port=443&secret=abc|2026-05-18T15:46:51"
        result = extract_timestamp(url)
        assert result == ("tg://proxy?server=example.com&port=443&secret=abc", "2026-05-18T15:46:51")

    def test_url_without_timestamp(self):
        url = "tg://proxy?server=example.com&port=443&secret=abc"
        result = extract_timestamp(url)
        assert result == ("tg://proxy?server=example.com&port=443&secret=abc", None)

    def test_url_with_date_not_timestamp(self):
        """A URL that has |2026 but not a valid timestamp format should not be stripped."""
        url = "tg://proxy?server=example.com&port=443&secret=abc|2026"
        result = extract_timestamp(url)
        assert result == (url, None)

    def test_empty_url(self):
        result = extract_timestamp("")
        assert result == ("", None)

    def test_timestamp_with_extra_pipes(self):
        """Timestamp with extra pipes at end - the regex stops at the timestamp, doesn't include **|."""
        url = "tg://proxy?server=example.com&port=443&secret=abc|2026-05-18T15:46:51**|"
        result = extract_timestamp(url)
        # The timestamp regex matches |2026-...T... but stops before **|, so full url is returned
        assert result == ("tg://proxy?server=example.com&port=443&secret=abc|2026-05-18T15:46:51**|", None)


class TestNormalizeUrl:
    """Tests for normalize_url function."""

    def test_https_t_me_proxy_conversion(self):
        url = "https://t.me/proxy?server=example.com&port=443&secret=abc"
        result = normalize_url(url)
        assert result == "tg://proxy?server=example.com&port=443&secret=abc"

    def test_already_tg_proxy(self):
        url = "tg://proxy?server=example.com&port=443&secret=abc"
        result = normalize_url(url)
        assert result == "tg://proxy?server=example.com&port=443&secret=abc"

    def test_trailing_slash(self):
        url = "https://t.me/proxy?server=example.com&port=443&secret=abc/"
        result = normalize_url(url)
        assert result == "tg://proxy?server=example.com&port=443&secret=abc/"

    def test_vmess_returns_none(self):
        """vmess:// URLs are not normalized to tg://proxy format."""
        url = "vmess://eyJhbGciOiJIUzI1NiIsInB5ciI6Ik..."
        result = normalize_url(url)
        assert result is None

    def test_trojan_returns_none(self):
        """trojan:// URLs are not normalized to tg://proxy format."""
        url = "trojan://password@example.com:443"
        result = normalize_url(url)
        assert result is None

    def test_empty_url_returns_none(self):
        result = normalize_url("")
        assert result is None


class TestIsValid:
    """Tests for is_valid function."""

    def test_good_tg_proxy(self):
        url = "tg://proxy?server=example.com&port=443&secret=abc"
        assert is_valid(url) is True

    def test_asterisk_in_server(self):
        url = "tg://proxy?server=144*.*.*&port=443&secret=abc"
        assert is_valid(url) is False

    def test_double_pipe_suffix(self):
        url = "tg://proxy?server=example.com&port=443&secret=abc**|"
        assert is_valid(url) is False

    def test_double_paren_pipe_suffix(self):
        url = "tg://proxy?server=example.com&port=8443&secret=...relay.duckdns.org)**|"
        assert is_valid(url) is False

    def test_double_dot(self):
        url = "tg://proxy?server=example..com&port=443&secret=abc"
        assert is_valid(url) is False

    def test_space_in_url(self):
        url = "tg://proxy?server=example.com&port=443&secret=abc "
        assert is_valid(url) is False

    def test_undefined(self):
        url = "tg://proxy?server=undefined&port=443&secret=abc"
        assert is_valid(url) is False

    def test_backtick(self):
        url = "tg://proxy?server=example.com&port=443&secret=abc```"
        assert is_valid(url) is False

    def test_closing_paren_at_end(self):
        url = "tg://proxy?server=example.com&port=443&secret=abc)"
        assert is_valid(url) is False

    def test_missing_server(self):
        url = "tg://proxy?port=443&secret=abc"
        assert is_valid(url) is False

    def test_missing_port(self):
        url = "tg://proxy?server=example.com&secret=abc"
        assert is_valid(url) is False

    def test_empty_url(self):
        assert is_valid("") is False


class TestTimestampPreservation:
    """Integration tests for timestamp preservation through pipeline."""

    def test_timestamp_preserved_in_normalize(self):
        """Timestamp should survive the full pipeline."""
        line = "https://t.me/proxy?server=example.com&port=443&secret=abc|2026-05-18T15:46:51"

        url, ts = extract_timestamp(line)
        url = normalize_url(url)
        final = f"{url}|{ts}" if ts else url

        assert final == "tg://proxy?server=example.com&port=443&secret=abc|2026-05-18T15:46:51"

    def test_bad_url_with_timestamp_still_rejected(self):
        """Bad URLs should be rejected regardless of timestamp."""
        line = "tg://proxy?server=144*.*.*&port=443&secret=abc|2026-05-18T15:46:51"

        url, ts = extract_timestamp(line)
        url = normalize_url(url)

        assert is_valid(url) is False

    def test_multiple_bad_patterns_in_one_url(self):
        """URLs with multiple bad patterns should all be caught."""
        assert is_valid("tg://proxy?server=144*.*.*&port=443&secret=**|") is False
        assert is_valid("tg://proxy?server=sub..relay&port=443&secret=abc```") is False
        assert is_valid("tg://proxy?server=bad )&port=443&secret=abc") is False
