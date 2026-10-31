"""Testes da camada de segurança (core/security.py). Execução: `python tests/test_security.py` (ou pytest)."""
import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.security import SecuritySettings, SlidingWindowLimiter, install_security, load_security_settings

KEY = "k" * 32
PWD = "p" * 20


def make_client(**kw) -> TestClient:
    app = FastAPI()

    @app.get("/data")
    def data():
        return {"ok": True}

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/static/x.js")
    def static_asset():
        return {"asset": True}

    base = dict(env="development", rate_limit_per_min=0)
    base.update(kw)
    install_security(app, SecuritySettings(**base))
    return TestClient(app)


def basic(user: str, pwd: str) -> dict:
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{pwd}".encode()).decode()}


def test_dev_without_auth_is_open():
    c = make_client()
    assert c.get("/data").status_code == 200


def test_api_key_header_and_bearer():
    c = make_client(api_key=KEY)
    r = c.get("/data")
    assert r.status_code == 401 and "Basic" in r.headers["www-authenticate"]
    assert c.get("/data", headers={"X-API-Key": KEY}).status_code == 200
    assert c.get("/data", headers={"Authorization": f"Bearer {KEY}"}).status_code == 200
    assert c.get("/data", headers={"X-API-Key": "errada"}).status_code == 401


def test_basic_auth():
    c = make_client(basic_user="scout", basic_password=PWD)
    assert c.get("/data").status_code == 401
    assert c.get("/data", headers=basic("scout", PWD)).status_code == 200
    assert c.get("/data", headers=basic("scout", "errada")).status_code == 401
    assert c.get("/data", headers=basic("outro", PWD)).status_code == 401
    assert c.get("/data", headers={"Authorization": "Basic !!!nao-base64!!!"}).status_code == 401


def test_api_key_is_not_accepted_as_basic_password():
    c = make_client(api_key=KEY, basic_user="scout", basic_password=PWD)
    assert c.get("/data", headers=basic("scout", KEY)).status_code == 401
    assert c.get("/data", headers=basic("scout", PWD)).status_code == 200
    assert c.get("/data", headers={"X-API-Key": KEY}).status_code == 200


def test_health_is_public():
    c = make_client(api_key=KEY)
    assert c.get("/health").status_code == 200


def test_security_headers_present_even_on_401():
    c = make_client(api_key=KEY)
    for r in (c.get("/data"), c.get("/health"), c.get("/data", headers={"X-API-Key": KEY})):
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["x-frame-options"] == "DENY"


def test_rate_limit_and_static_exempt():
    c = make_client(rate_limit_per_min=3)
    assert [c.get("/data").status_code for _ in range(3)] == [200, 200, 200]
    r = c.get("/data")
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1
    assert all(c.get("/static/x.js").status_code == 200 for _ in range(10))
    assert c.get("/health").status_code == 200


def test_bruteforce_lockout_blocks_even_correct_credentials():
    c = make_client(api_key=KEY)
    for _ in range(10):
        assert c.get("/data", headers={"X-API-Key": "chute"}).status_code == 401
    assert c.get("/data", headers={"X-API-Key": KEY}).status_code == 429


def test_challenge_without_credentials_never_triggers_lockout():
    """Regressão: o navegador envia requisições sem credenciais (desafio 401) antes do Basic Auth."""
    c = make_client(basic_user="scout", basic_password=PWD)
    for _ in range(50):
        assert c.get("/data").status_code == 401
    assert c.get("/data", headers=basic("scout", PWD)).status_code == 200


def test_cors_restricted_to_allowed_origins():
    c = make_client(api_key=KEY, allowed_origins=("https://scout.exemplo.com",))
    ok = c.options("/data", headers={"Origin": "https://scout.exemplo.com", "Access-Control-Request-Method": "GET"})
    assert ok.status_code == 200 and ok.headers["access-control-allow-origin"] == "https://scout.exemplo.com"
    bad = c.options("/data", headers={"Origin": "https://malicioso.com", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in bad.headers
    # A resposta 401 também carrega CORS (o navegador consegue ler o erro).
    r = c.get("/data", headers={"Origin": "https://scout.exemplo.com"})
    assert r.status_code == 401 and r.headers["access-control-allow-origin"] == "https://scout.exemplo.com"


def test_trust_proxy_uses_last_forwarded_ip():
    c = make_client(rate_limit_per_min=2, trust_proxy=True)
    h1 = {"X-Forwarded-For": "1.1.1.1, 9.9.9.9"}
    h2 = {"X-Forwarded-For": "1.1.1.1, 8.8.8.8"}
    assert c.get("/data", headers=h1).status_code == 200
    assert c.get("/data", headers=h1).status_code == 200
    assert c.get("/data", headers=h1).status_code == 429
    # IP falsificado à esquerda não permite burlar: o que vale é o IP anexado pelo proxy (último).
    assert c.get("/data", headers=h2).status_code == 200


def test_without_trust_proxy_forwarded_header_is_ignored():
    c = make_client(rate_limit_per_min=2, trust_proxy=False)
    for i in range(2):
        assert c.get("/data", headers={"X-Forwarded-For": f"10.0.0.{i}"}).status_code == 200
    assert c.get("/data", headers={"X-Forwarded-For": "10.0.0.99"}).status_code == 429


def test_production_fails_closed():
    for bad in (
        SecuritySettings(env="production"),
        SecuritySettings(env="production", api_key="curta"),
        SecuritySettings(env="production", basic_user="u", basic_password="curta"),
        SecuritySettings(env="development", basic_user="so-usuario"),
    ):
        try:
            bad.validate()
        except RuntimeError:
            continue
        raise AssertionError(f"deveria falhar: {bad}")
    SecuritySettings(env="production", api_key=KEY).validate()
    SecuritySettings(env="production", allow_public=True).validate()


def test_load_settings_from_env(monkeypatch=None):
    import os
    saved = {k: os.environ.get(k) for k in ("APP_ENV", "ALLOWED_ORIGINS", "API_KEY", "DOCS_ENABLED", "RATE_LIMIT_PER_MIN")}
    try:
        os.environ.update(APP_ENV="production", ALLOWED_ORIGINS="https://a.com/, https://b.com", API_KEY=KEY,
                          RATE_LIMIT_PER_MIN="abc")
        os.environ.pop("DOCS_ENABLED", None)
        s = load_security_settings()
        assert s.is_production and s.docs_enabled is False
        assert s.allowed_origins == ("https://a.com", "https://b.com")
        assert s.rate_limit_per_min == 300  # valor inválido cai no padrão
    finally:
        for k, v in saved.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


def test_limiter_window_expires():
    lim = SlidingWindowLimiter(limit=2, window_s=0.2)
    assert lim.hit("a")[0] and lim.hit("a")[0] and not lim.hit("a")[0]
    import time
    time.sleep(0.25)
    assert lim.hit("a")[0]


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    for name, fn in tests:
        fn()
        print(f"  [OK] {name}")
    print(f"\n>>> {len(tests)} testes de segurança passaram <<<")
