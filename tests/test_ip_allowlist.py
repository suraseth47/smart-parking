from web.ip_allowlist import is_ip_allowed


def test_disabled_allows_any_ip():
    assert is_ip_allowed("1.2.3.4", {"enabled": False, "ips": ["127.0.0.1"]}) is True


def test_empty_setting_allows_any_ip():
    assert is_ip_allowed("1.2.3.4", {}) is True


def test_enabled_with_no_entries_allows_any_ip():
    # กันตั้งค่าเปิดใช้แล้วลืมใส่รายการ -> ล็อกตัวเองทันที
    assert is_ip_allowed("1.2.3.4", {"enabled": True, "ips": []}) is True


def test_enabled_exact_ip_match():
    allowlist = {"enabled": True, "ips": ["127.0.0.1"]}
    assert is_ip_allowed("127.0.0.1", allowlist) is True
    assert is_ip_allowed("10.0.0.1", allowlist) is False


def test_enabled_cidr_match():
    allowlist = {"enabled": True, "ips": ["192.168.1.0/24"]}
    assert is_ip_allowed("192.168.1.50", allowlist) is True
    assert is_ip_allowed("192.168.2.50", allowlist) is False


def test_enabled_multiple_entries():
    allowlist = {"enabled": True, "ips": ["127.0.0.1", "10.0.0.0/8"]}
    assert is_ip_allowed("10.5.5.5", allowlist) is True
    assert is_ip_allowed("127.0.0.1", allowlist) is True
    assert is_ip_allowed("8.8.8.8", allowlist) is False


def test_invalid_client_ip_is_rejected():
    allowlist = {"enabled": True, "ips": ["127.0.0.1"]}
    assert is_ip_allowed("not-an-ip", allowlist) is False


def test_invalid_entry_in_allowlist_is_skipped_not_crashed():
    allowlist = {"enabled": True, "ips": ["not-a-valid-entry", "127.0.0.1"]}
    assert is_ip_allowed("127.0.0.1", allowlist) is True
    assert is_ip_allowed("8.8.8.8", allowlist) is False
