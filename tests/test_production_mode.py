"""Valida o app REAL em APP_ENV=production: fail-closed, 401, auth, /docs desligado, /health e dashboard no browser."""
import base64
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
PORT = 18771
BASE = f"http://127.0.0.1:{PORT}"
USER, PWD, KEY = "scout", "senha-super-segura-123", "chave-api-super-segura-0123456789"


def run_server(extra_env):
    env = {**os.environ, "APP_ENV": "production", "PORT": str(PORT), "PYTHONIOENCODING": "utf-8", **extra_env}
    for k in ("API_KEY", "BASIC_AUTH_USER", "BASIC_AUTH_PASSWORD", "ALLOW_PUBLIC"):
        if k not in extra_env:
            env.pop(k, None)
    return subprocess.Popen([PY, "-m", "uvicorn", "api.main:app", "--port", str(PORT)], cwd=ROOT, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")


def req(path, headers=None):
    r = urllib.request.Request(BASE + path, headers=headers or {})
    try:
        with urllib.request.urlopen(r, timeout=10) as resp:
            return resp.status, resp.read(), {k.lower(): v for k, v in resp.headers.items()}
    except urllib.error.HTTPError as e:
        return e.code, e.read(), {k.lower(): v for k, v in e.headers.items()}


def wait_up():
    for _ in range(60):
        try:
            urllib.request.urlopen(BASE + "/health", timeout=1)
            return
        except urllib.error.HTTPError:
            return
        except Exception:
            time.sleep(0.3)
    raise RuntimeError("servidor nao subiu")


# 1) Fail-closed: producao sem credenciais NAO inicia.
p = run_server({})
try:
    out, _ = p.communicate(timeout=30)
finally:
    if p.poll() is None:
        p.kill()
assert p.returncode != 0 and "APP_ENV=production exige" in out, out[-600:]
print("[OK] Producao sem credenciais recusa iniciar (fail-closed)")

# 2) Producao com Basic Auth + API key.
srv = run_server({"API_KEY": KEY, "BASIC_AUTH_USER": USER, "BASIC_AUTH_PASSWORD": PWD, "RATE_LIMIT_PER_MIN": "1000"})
try:
    wait_up()
    st, body, hd = req("/health")
    assert st == 200 and json.loads(body)["database"] is True
    print(f"[OK] /health publico -> {st} {body.decode()}")

    for path in ("/", "/dashboard", "/players", "/metadata", "/explorer/schema", "/analytics/rankings?metric=goals"):
        st, _, hd = req(path)
        assert st == 401 and "Basic" in hd.get("www-authenticate", ""), (path, st)
    print("[OK] Todas as rotas de dados/dashboard exigem autenticacao (401 + WWW-Authenticate)")

    assert req("/static/js/app.js")[0] == 401
    print("[OK] Assets estaticos tambem protegidos")

    st, _, hd = req("/explorer/schema", {"X-API-Key": KEY})
    assert st == 200 and hd["x-content-type-options"] == "nosniff"
    st, _, _ = req("/explorer/schema", {"Authorization": "Bearer " + KEY})
    assert st == 200
    cred = base64.b64encode(f"{USER}:{PWD}".encode()).decode()
    st, _, _ = req("/dashboard", {"Authorization": "Basic " + cred})
    assert st == 200
    print("[OK] X-API-Key, Bearer e Basic Auth liberam o acesso")

    for path in ("/docs", "/redoc", "/openapi.json"):
        st, _, _ = req(path, {"X-API-Key": KEY})
        assert st == 404, (path, st)
    print("[OK] /docs, /redoc e /openapi.json desligados em producao")

    # 3) Dashboard completo no navegador via Basic Auth (fetch same-origin reaproveita as credenciais).
    from playwright.sync_api import sync_playwright
    errors = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, http_credentials={"username": USER, "password": PWD})
        page = ctx.new_page()
        page.on("pageerror", lambda e: errors.append(f"PAGEERROR: {e}"))
        page.on("console", lambda m: errors.append(f"CONSOLE: {m.text}") if m.type == "error" else None)
        page.goto(BASE + "/dashboard", wait_until="networkidle")
        page.wait_for_selector(".ex-card", timeout=15000)
        n = page.locator("#ex-stats .ex-stat-item").count()
        assert n == 141, n
        page.locator("button[data-action='radar']").first.click()
        page.wait_for_selector("#dossier-all-stats details.rx-cat-card", timeout=12000)
        page.click("button.nav-tab-btn[data-tab='rankings']")
        page.wait_for_selector("#rankings-table-body tr td:nth-child(2)", timeout=8000)
        browser.close()
    assert not errors, errors
    print("[OK] Dashboard (Explorador, Raio-X, Rankings) funciona no navegador com Basic Auth, 0 erros JS")
finally:
    srv.terminate()
    srv.wait(timeout=10)

print("\n>>> SUCESSO: app real validado em modo producao <<<")
