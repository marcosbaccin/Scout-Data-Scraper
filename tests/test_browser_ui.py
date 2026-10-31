import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PORT = 18770
URL = f"http://127.0.0.1:{PORT}/dashboard"

python_exe = sys.executable

proc = subprocess.Popen(
    [python_exe, "-m", "uvicorn", "api.main:app", "--host", "127.0.0.1", "--port", str(PORT)],
    cwd=str(ROOT),
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)

try:
    for _ in range(40):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/", timeout=1) as resp:
                if resp.status == 200:
                    break
        except Exception:
            time.sleep(0.25)

    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.on("pageerror", lambda err: errors.append(f"PAGEERROR: {err}"))
        page.on("console", lambda msg: errors.append(f"CONSOLE_ERR: {msg.text}") if msg.type == "error" else None)

        page.goto(URL, wait_until="networkidle")
        page.wait_for_selector(".ex-card", timeout=12000)

        # 1. Explorador: verifica exatamente 141 estatísticas e 12 categorias
        n_stats = page.locator("#ex-stats .ex-stat-item").count()
        n_cats = page.locator("#ex-stats details.ex-section").count()
        print(f"[UI-Explorador] OK -> {n_cats} categorias, {n_stats} sliders estatísticos")
        assert n_stats == 141 and n_cats == 12

        # 1.1 Valida ausência total de menções a fontes e Ratings no Explorador
        cat_texts = page.locator("#ex-stats details.ex-section summary").all_inner_texts()
        for ctext in cat_texts:
            for forbidden in ["SofaScore", "FBref", "WhoScored"]:
                assert forbidden.lower() not in ctext.lower(), f"Fonte encontrada no resumo da categoria: {ctext}"
        print("[UI-Explorador] Categorias validadas: nenhuma menção a fontes!")

        sort_options = page.locator("#ex-sort option").all_inner_texts()
        assert not any("rating" in s.lower() for s in sort_options), f"Rating encontrado nas opções de ordenação: {sort_options}"
        print("[UI-Explorador] Ordenação validada: 100% livre de rating!")

        # 2. Clica em "Raio-X & Radar" do primeiro atleta no Explorador
        page.locator("button[data-action='radar']").first.click()
        page.wait_for_selector("#dossier-all-stats details.rx-cat-card", timeout=12000)
        page.wait_for_selector("#similar-list .similar-item", timeout=10000)

        dossier_name = page.locator("#dossier-hero .dossier-name").inner_text()
        radar_rows = page.locator("#radar-table-body tr").count()
        rx_cats = page.locator("#dossier-all-stats details.rx-cat-card").count()
        rx_stats = page.locator("#dossier-all-stats tr[data-stat-key]").count()
        radar_picker_opts = page.locator("#dossier-radar-add optgroup option").count()
        print(f"[UI-RaioX] Atleta '{dossier_name}' -> {radar_rows} eixos no Radar, {rx_cats} categorias e {rx_stats} estatísticas no Raio-X Completo ({radar_picker_opts} opções no seletor do Radar)")
        assert radar_rows == 8, f"Esperava 8 eixos padrão no Radar, obteve {radar_rows}"
        assert rx_cats == 12, f"Esperava 12 categorias no Raio-X, obteve {rx_cats}"
        assert rx_stats == 141, f"Esperava todas as 141 estatísticas no Raio-X, obteve {rx_stats}"
        assert radar_picker_opts == 141, f"Esperava 141 opções no seletor de eixos do Radar, obteve {radar_picker_opts}"

        # 2.1 Valida que não há menções a fontes no Raio-X e Radar
        radar_opts_texts = page.locator("#dossier-radar-add option").all_inner_texts()
        for r_opt in radar_opts_texts:
            for forbidden in ["[FBref]", "[WhoScored]", "[SofaScore]", "Rating SofaScore", "Rating WhoScored"]:
                assert forbidden.lower() not in r_opt.lower(), f"Tag proibida encontrada no seletor do radar: {r_opt}"
        print("[UI-RaioX] Seletor de eixos do Radar validado: 100% livre de menções a fontes e ratings!")

        # 3. Fixa uma nova estatística (top_speed) no Radar clicando no botão 🎯 da tabela de 141 estatísticas
        page.click("#dossier-all-stats button[data-pin-key='top_speed']")
        radar_rows_after_pin = page.locator("#radar-table-body tr").count()
        axis_badge = page.locator("#dossier-radar-axis-count").inner_text()
        print(f"[UI-RaioX] Pin 'top_speed' no Radar -> {radar_rows_after_pin} linhas na tabela do Radar ({axis_badge})")
        assert radar_rows_after_pin == 9 and "9" in axis_badge

        # 4. Restaura os 8 eixos padrão da função tática
        page.click("#dossier-radar-reset")
        assert page.locator("#radar-table-body tr").count() == 8
        print("[UI-RaioX] Reset para 'Padrão da Função' -> 8 eixos restaurados")

        # 5. Testa filtro "Com Registro (> 0)" e retorno para "Todas (141)"
        page.click("#dossier-stat-filter-toggle button[data-filter='nonzero']")
        nonzero_stats = page.locator("#dossier-all-stats tr[data-stat-key]").count()
        print(f"[UI-RaioX] Filtro 'Com Registro (> 0)' -> {nonzero_stats} estatísticas não-zeradas exibidas")
        assert 0 < nonzero_stats < 141
        page.click("#dossier-stat-filter-toggle button[data-filter='all']")
        assert page.locator("#dossier-all-stats tr[data-stat-key]").count() == 141

        # 6. Testa busca textual nas 141 estatísticas do Raio-X
        page.fill("#dossier-stat-search", "passes longos")
        filtered_rx = page.locator("#dossier-all-stats tr[data-stat-key]").count()
        print(f"[UI-RaioX] Busca 'passes longos' -> {filtered_rx} estatísticas filtradas")
        assert 1 <= filtered_rx < 20
        page.fill("#dossier-stat-search", "")
        assert page.locator("#dossier-all-stats tr[data-stat-key]").count() == 141

        # 7. Clica em "⚔️ Comparar" no primeiro atleta similar para sobrepor no Radar e na tabela de 141 estatísticas
        page.locator("#similar-list .rx-btn-compare-mini").first.click()
        page.wait_for_timeout(600)
        clear_hidden = page.locator("#dossier-compare-clear").is_hidden()
        hero_text = page.locator("#dossier-hero").inner_text()
        print(f"[UI-RaioX] Comparação 2º atleta ativada -> botão limpar visível={not clear_hidden} | 'Comparando no Radar' no hero={'Comparando no Radar' in hero_text}")
        assert not clear_hidden and "Comparando no Radar" in hero_text

        # 8. Navega para Tab 3: Rankings & Líderes e valida as 141 estatísticas
        page.click("button.nav-tab-btn[data-tab='rankings']")
        page.wait_for_selector("#ranking-metric optgroup", state="attached", timeout=8000)
        page.wait_for_selector("#rankings-table-body tr td:nth-child(2)", timeout=8000)
        assert page.locator("#ranking-metric option").count() == 141
        ranking_opts = page.locator("#ranking-metric option").all_inner_texts()
        for ropt in ranking_opts:
            for forbidden in ["[FBref]", "[WhoScored]", "[SofaScore]", "Rating SofaScore", "Rating WhoScored"]:
                assert forbidden.lower() not in ropt.lower(), f"Tag proibida encontrada no seletor de ranking: {ropt}"
        print("[UI-Rankings] 141 estatísticas verificadas no Rankings & Líderes (sem menção a fontes nem ratings)")

        browser.close()

    assert not errors, f"Erros JS detectados: {errors}"
    print("[UI] ZERO erros de console/JS nas 3 abas (Explorador + Raio-X & Radar 141 Stats + Rankings & Líderes 141 Stats)!")
finally:
    proc.terminate()
    proc.wait(timeout=5)
