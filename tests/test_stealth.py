import json
from crawlfb.stealth import USER_AGENT, STEALTH_JS, _load_storage_state, _convert_cookie_editor
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
    # bare Cookie-Editor array -> converted to Playwright storageState shape
    list_path = tmp_path / "list.json"
    list_path.write_text(json.dumps([
        {"name": "xs", "value": "1", "domain": ".facebook.com", "path": "/",
         "sameSite": "no_restriction", "secure": True, "httpOnly": True,
         "expirationDate": 1819628928.0, "session": False},
    ]), encoding="utf-8")
    assert _load_storage_state(str(list_path)) == {"cookies": [{
        "name": "xs", "value": "1", "domain": ".facebook.com", "path": "/",
        "sameSite": "None", "secure": True, "httpOnly": True,
        "expires": 1819628928.0,
    }]}
    # JSON scalar -> None (not a storageState shape)
    scalar_path = tmp_path / "scalar.json"
    scalar_path.write_text(json.dumps(42), encoding="utf-8")
    assert _load_storage_state(str(scalar_path)) is None
    # well-formed object -> returned as-is
    dict_path = tmp_path / "ok.json"
    dict_path.write_text(json.dumps({"cookies": [], "origins": []}), encoding="utf-8")
    assert _load_storage_state(str(dict_path)) == {"cookies": [], "origins": []}


def test_convert_cookie_editor_maps_samesite_and_session():
    cookies = [
        {"name": "a", "value": "1", "sameSite": "lax", "expirationDate": 10.0, "session": False},
        {"name": "b", "value": "2", "sameSite": "strict", "session": True},
        {"name": "c", "value": "3", "sameSite": None},
        {"name": "d"},  # missing value -> skipped
    ]
    out = _convert_cookie_editor(cookies)["cookies"]
    assert out[0]["sameSite"] == "Lax" and out[0]["expires"] == 10.0
    assert out[1]["sameSite"] == "Strict" and out[1]["expires"] == -1
    assert out[2]["sameSite"] == "Lax"
    assert len(out) == 3
