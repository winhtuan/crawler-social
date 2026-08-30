from crawlfb.config import Proxy, Config

def test_proxy_parse_plain():
    p = Proxy.from_url("http://127.0.0.1:8080")
    assert p.server == "http://127.0.0.1:8080"
    assert p.username is None and p.password is None

def test_proxy_parse_with_auth():
    p = Proxy.from_url("http://user:pass@127.0.0.1:8080")
    assert p.username == "user" and p.password == "pass"
    assert p.server == "http://127.0.0.1:8080"

def test_config_normalizes_page_url():
    cfg = Config(page_url="https://www.facebook.com/CotSongGenZ.Page", output="out.json")
    assert cfg.normalized_page_url() == "https://www.facebook.com/CotSongGenZ.Page/"
