import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient
from api.main import app
from core.sofascore_metrics import RAW_METRICS, column_name
from core.explorer_catalog import STATS, STAT_INDEX, FBREF_SOURCE_COLUMNS, WHOSCORED_SOURCE_COLUMNS
from core.models import FbrefOutfieldStat, FbrefKeeperStat, WhoscoredPlayerSeasonStat
from explorer_engine import LEGACY_METRIC_ALIASES

print("=== 1. AUDITORIA DE COBERTURA DE 100% DAS ESTATÍSTICAS COLETADAS (SEM RATINGS NEM FONTES) ===")
sofa_cols = {column_name(k) for k in RAW_METRICS} - {"total_rating", "count_rating"}
catalog_keys = set(STAT_INDEX.keys())
missing_sofa = sofa_cols - catalog_keys
assert not missing_sofa, f"SofaScore cols faltando no catálogo: {missing_sofa}"
print(f"  [OK] SofaScore: {len(sofa_cols)}/{len(sofa_cols)} métricas brutas + derivadas presentes!")

fb_out_cols = {c.name for c in FbrefOutfieldStat.__table__.columns} - {"id", "player_id", "season", "squad", "comp", "is_national_team"}
fb_gk_cols = {c.name for c in FbrefKeeperStat.__table__.columns} - {"id", "player_id", "season", "squad", "comp", "is_national_team"}
mapped_fb_cols = set(FBREF_SOURCE_COLUMNS.values())
assert (fb_out_cols | fb_gk_cols) == mapped_fb_cols, f"FBref cols divergentes: {(fb_out_cols | fb_gk_cols) ^ mapped_fb_cols}"
print(f"  [OK] FBref (Linha + Goleiros): {len(mapped_fb_cols)}/{len(mapped_fb_cols)} métricas exclusivas presentes!")

ws_excl = {"motm", "through_balls_per_game", "dispossessed_per_game", "unsuccessful_touches_per_game"}
assert ws_excl == set(WHOSCORED_SOURCE_COLUMNS.values())
print(f"  [OK] WhoScored: {len(ws_excl)}/{len(ws_excl)} métricas exclusivas objetivas presentes!")

# Validação estrita: Nenhum Rating no catálogo
assert "rating" not in STAT_INDEX, "rating ainda presente em STAT_INDEX!"
assert "ws_rating" not in STAT_INDEX, "ws_rating ainda presente em STAT_INDEX!"
assert len(STATS) == 141, f"Esperava exatamente 141 estatísticas, encontrou {len(STATS)}"
print(f"  [OK] Total geral configurável nas 3 abas (Explorador, Raio-X & Radar, Rankings): {len(STATS)} estatísticas objetivas (100% livre de ratings)!")

print("\n=== 2. TESTES END-TO-END DA API FASTAPI (/explorer/* + /dashboard) ===")
client = TestClient(app)

for asset in ["/dashboard", "/static/css/style.css", "/static/js/explorer.js", "/static/js/app.js"]:
    r = client.get(asset)
    assert r.status_code == 200, f"Asset {asset} falhou: {r.status_code}"
    print(f"  [200 OK] GET {asset} ({len(r.content)} bytes)")

r = client.get("/explorer/schema")
assert r.status_code == 200
schema = r.json()
assert len(schema["stats"]) == 141
assert len(schema["categories"]) == 12

# Garante que as categorias não possuem menções a fontes
for cat in schema["categories"]:
    for forbidden in ["SofaScore", "FBref", "WhoScored"]:
        assert forbidden.lower() not in cat["label"].lower(), f"Menção à fonte encontrada na categoria: {cat['label']}"
print(f"  [200 OK] GET /explorer/schema -> {len(schema['stats'])} stats, {len(schema['presets'])} presets, 12 categorias sem fontes")

rp = client.get("/explorer/players")
assert rp.status_code == 200
p_dir = rp.json()
assert p_dir["total"] == 874
print(f"  [200 OK] GET /explorer/players -> {p_dir['total']}/874 atletas no diretório rápido")

r = client.post("/explorer/bounds", json={"season_mode": "latest", "min_minutes": 450})
assert r.status_code == 200
bounds = r.json()
assert bounds["players_in_scope"] > 700
print(f"  [200 OK] POST /explorer/bounds -> {bounds['players_in_scope']} atletas elegíveis no recorte")

r = client.post("/explorer/search", json={
    "scope": {"season_mode": "latest", "min_minutes": 450},
    "identity": {"roles": ["WNG", "ST"], "age_max": 26, "foot": ["Left", "Right"]},
    "stats": [
        {"key": "goals", "mode": "p90", "min": 0.25},
        {"key": "successful_dribbles", "mode": "pct", "min": 50},
        {"key": "accurate_passes_pct", "mode": "total", "min": 70.0, "max": 95.0},
    ],
    "page": 1,
    "page_size": 10,
})
assert r.status_code == 200, r.text
sr = r.json()
assert sr["total"] > 0
first = sr["items"][0]
print(f"  [200 OK] POST /explorer/search (multi-filtro) -> {sr['total']} encontrados (Top 1: {first['name']})")

print("\n=== 3. TESTES EXAUSTIVOS DE RAIO-X & RADAR (/players/{id}/dossier, /similar, /analytics/compare) ===")
# 3.1 Testa Dossiê Completo por nome ('Raphinha') -> deve trazer TODAS as 141 estatísticas nas 12 categorias + 8 eixos de radar
rd = client.get("/players/Raphinha/dossier", params={"min_minutes": 450})
assert rd.status_code == 200, rd.text
dos = rd.json()
assert dos["total_stats"] == 141
assert len(dos["categories"]) == 12
assert sum(len(c["stats"]) for c in dos["categories"]) == 141
assert len(dos["radar"]) == 8
# Garante que nenhum eixo do radar padrão seja rating
for axis in dos["radar"]:
    assert "rating" not in axis["metric_key"], f"Rating encontrado no radar: {axis['metric_key']}"
print(f"  [200 OK] GET /players/Raphinha/dossier -> {dos['total_stats']} estatísticas em {len(dos['categories'])} categorias ({dos['populated_stats']} preenchidas > 0, {len(dos['radar'])} eixos táticos no Radar)")

# 3.2 Testa Dossiê Completo de Goleiro (GK) -> 8 eixos táticos de goleiro + 141 estatísticas
gk_player = next(p for p in p_dir["players"] if p["scout_role"] == "GK")
rd_gk = client.get(f"/players/{gk_player['mapping_id']}/dossier")
assert rd_gk.status_code == 200
dos_gk = rd_gk.json()
assert len(dos_gk["radar"]) == 8
assert sum(len(c["stats"]) for c in dos_gk["categories"]) == 141
print(f"  [200 OK] GET /players/{gk_player['mapping_id']}/dossier (GK: {gk_player['name']}) -> {len(dos_gk['radar'])} eixos de goleiro + 141 estatísticas")

# 3.3 Testa customização dos eixos do Radar via parâmetro metrics + recorte 'all' (carreira)
custom_axes = ["top_speed", "fbref_team_ppm", "goals", "key_passes", "accurate_passes_pct"]
rd_cust = client.get(f"/players/{dos['profile']['mapping_id']}/dossier", params=[("season", "all"), *[("metrics", m) for m in custom_axes]])
assert rd_cust.status_code == 200
assert [x["metric_key"] for x in rd_cust.json()["radar"]] == custom_axes
print(f"  [200 OK] Customização de Radar via API (season=all, 5 eixos objetivos) verificada!")

# 3.4 Testa Similaridade Dinâmica com eixos customizados
r_sim = client.get(f"/players/{dos['profile']['mapping_id']}/similar", params=[("top_n", 4), *[("metrics", m) for m in custom_axes]])
assert r_sim.status_code == 200
sims = r_sim.json()["similar_players"]
assert len(sims) == 4
print(f"  [200 OK] GET /players/{dos['profile']['mapping_id']}/similar -> Top 1 similar: {sims[0]['player_name']} ({sims[0]['similarity_pct']}%)")

# 3.5 Testa Comparação lado a lado (/analytics/compare)
r_cmp = client.get("/analytics/compare", params=[("player_ids", dos["profile"]["mapping_id"]), ("player_ids", sims[0]["mapping_id"])])
assert r_cmp.status_code == 200
assert r_cmp.json()["count"] == 2
assert sum(len(c["stats"]) for c in r_cmp.json()["players"][0]["categories"]) == 141
print(f"  [200 OK] GET /analytics/compare ({dos['profile']['name']} vs {sims[0]['player_name']}) -> 2 dossiês de 141 estatísticas")

# 3.6 Jogador inexistente -> HTTP 404
assert client.get("/players/999999999/dossier").status_code == 404
print("  [404 OK] Atleta inexistente tratado com HTTP 404")

print("\n=== 4. TESTES DE /analytics/rankings (TODAS AS 141 ESTATÍSTICAS) ===")
# Valida rejeição de ratings
assert client.get("/analytics/rankings", params={"metric": "rating"}).status_code == 400
assert client.get("/analytics/rankings", params={"metric": "ws_rating"}).status_code == 400
print("  [400 OK] Tentativas de consultar rating ou ws_rating rejeitadas com HTTP 400")

for sd in STATS:
    rk_res = client.get("/analytics/rankings", params={"metric": sd.key, "min_minutes": 180, "limit": 3})
    assert rk_res.status_code == 200, f"Ranking falhou para {sd.key}"
print(f"  [200 OK] Todas as {len(STATS)}/{len(STATS)} estatísticas verificadas em /analytics/rankings!")
print("\n>>> SUCESSO TOTAL: Todos os testes E2E passaram sem nenhum erro! <<<")

