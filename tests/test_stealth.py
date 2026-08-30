from crawlfb.stealth import USER_AGENT, STEALTH_JS
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
