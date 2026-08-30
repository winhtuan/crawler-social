import json
from crawlfb.stealth import USER_AGENT, STEALTH_JS, _load_storage_state
from crawlfb.config import Proxy

def test_ua_is_chrome_windows():
    assert "Chrome" in USER_AGENT
    assert "Windows NT" in USER_AGENT

def test_stealth_js_patches_webdriver():
    assert "navigator" in STEALTH_JS
    assert "webdriver" in STEALTH_JS

def test_proxy_to_playwright_dict():
    p = Proxy(server="http://1.2.3.4:8080", username="u", password="p")
    d = p.to_playwright()
    assert d == {"server": "http://1.2.3.4:8080", "username": "u", "password": "p"}

def test_load_storage_state_guards_shape(tmp_path):
    # missing file -> None
    assert _load_storage_state(str(tmp_path / "missing.json")) is None
    # file containing a JSON list -> None (list is not a Playwright storageState)
    list_path = tmp_path / "list.json"
    list_path.write_text(json.dumps([{"name": "x"}]), encoding="utf-8")
    assert _load_storage_state(str(list_path)) is None
    # well-formed object -> returned as-is
    dict_path = tmp_path / "ok.json"
    dict_path.write_text(json.dumps({"cookies": [], "origins": []}), encoding="utf-8")
    assert _load_storage_state(str(dict_path)) == {"cookies": [], "origins": []}
