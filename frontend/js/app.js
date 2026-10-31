/**
 * SCOUT DATA INTELLIGENCE - FRONTEND CONTROLLER
 * Gerencia a navegação por abas, filtros dinâmicos, integração com a API FastAPI
 * e renderização dos Gráficos de Radar via Chart.js.
 */

// Configura o endpoint base da API
const API_BASE = window.location.origin.includes('5500') || window.location.origin.includes('file://')
    ? 'http://localhost:8000'
    : window.location.origin;

// Estado Global da Aplicação
const State = {
    metadata: null,
    players: [],
    selectedPlayerId: null,
    radarChart: null,
    compareChart: null,
    compareIds: [],
    debounceTimer: null,
};

// =============================================================================
// INICIALIZAÇÃO
// =============================================================================
document.addEventListener('DOMContentLoaded', async () => {
    setupTabNavigation();
    if (document.getElementById('players-grid')) {
        setupFilters();
        await loadMetadata();
        await loadPlayers();
    }
});

// =============================================================================
// NAVEGAÇÃO ENTRE ABAS
// =============================================================================
function setupTabNavigation() {
    const tabButtons = document.querySelectorAll('.nav-tab-btn');
    tabButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            const tabTarget = btn.getAttribute('data-tab');
            switchTab(tabTarget);
        });
    });
}

function switchTab(tabId) {
    document.querySelectorAll('.nav-tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));

    const targetBtn = document.querySelector(`.nav-tab-btn[data-tab="${tabId}"]`);
    const targetPane = document.getElementById(`tab-${tabId}`);

    if (targetBtn) targetBtn.classList.add('active');
    if (targetPane) targetPane.classList.add('active');

    if (tabId === 'rankings') {
        loadRankings();
    } else if (tabId === 'dossier') {
        if (!DossierState.currentPlayerId && !DossierState.loading) {
            openDefaultDossierIfNeeded();
        }
    }
}

// =============================================================================
// METADATA & FILTROS
// =============================================================================
async function loadMetadata() {
    try {
        const res = await fetch(`${API_BASE}/metadata`);
        if (!res.ok) return;
        const data = await res.json();
        State.metadata = data;

        populateDropdown('filter-league', data.leagues, 'Todas as Ligas');
        populateDropdown('filter-team', data.teams, 'Todos os Clubes');
    } catch (e) {
        console.warn('Erro ao carregar metadata:', e);
    }
}

function populateDropdown(elementId, items, defaultLabel) {
    const el = document.getElementById(elementId);
    if (!el) return;
    el.innerHTML = `<option value="">${defaultLabel}</option>`;
    items.forEach(item => {
        el.innerHTML += `<option value="${item}">${item}</option>`;
    });
}

function setupFilters() {
    const searchInput = document.getElementById('search-player');
    const roleSelect = document.getElementById('filter-role');
    const categorySelect = document.getElementById('filter-category');
    const leagueSelect = document.getElementById('filter-league');
    const teamSelect = document.getElementById('filter-team');
    const btnReset = document.getElementById('btn-reset-filters');

    if (searchInput) {
        searchInput.addEventListener('input', () => {
            clearTimeout(State.debounceTimer);
            State.debounceTimer = setTimeout(loadPlayers, 350);
        });
    }

    [roleSelect, categorySelect, leagueSelect, teamSelect].forEach(select => {
        if (select) select.addEventListener('change', loadPlayers);
    });

    if (btnReset) {
        btnReset.addEventListener('click', () => {
            if (searchInput) searchInput.value = '';
            if (roleSelect) roleSelect.value = '';
            if (categorySelect) categorySelect.value = '';
            if (leagueSelect) leagueSelect.value = '';
            if (teamSelect) teamSelect.value = '';
            loadPlayers();
        });
    }
}

// =============================================================================
// EXPLORADOR DE JOGADORES (TAB 1)
// =============================================================================
async function loadPlayers() {
    const grid = document.getElementById('players-grid');
    const countEl = document.getElementById('players-count');
    if (!grid) return;

    grid.innerHTML = '<div class="empty-state"><div class="empty-icon">⏳</div><p>Buscando atletas...</p></div>';

    const params = new URLSearchParams();
    const searchVal = document.getElementById('search-player')?.value.trim();
    const roleVal = document.getElementById('filter-role')?.value;
    const catVal = document.getElementById('filter-category')?.value;
    const leagueVal = document.getElementById('filter-league')?.value;
    const teamVal = document.getElementById('filter-team')?.value;

    if (searchVal) params.append('name', searchVal);
    if (roleVal) params.append('role', roleVal);
    if (catVal) params.append('category', catVal);
    if (leagueVal) params.append('league', leagueVal);
    if (teamVal) params.append('team', teamVal);
    params.append('page_size', '60');

    try {
        const res = await fetch(`${API_BASE}/players?${params.toString()}`);
        if (!res.ok) throw new Error('Falha na requisição');
        const data = await res.json();
        State.players = data.items;

        if (countEl) countEl.innerText = `${data.total} atletas monitorados`;

        if (data.items.length === 0) {
            grid.innerHTML = `
                <div class="empty-state" style="grid-column: 1 / -1;">
                    <div class="empty-icon">🔍</div>
                    <h3>Nenhum jogador encontrado</h3>
                    <p>Tente ajustar os filtros ou execute a coleta com <code>python main.py run-all</code>.</p>
                </div>
            `;
            return;
        }

        grid.innerHTML = data.items.map(p => renderPlayerCard(p)).join('');

        // Vincula cliques aos cards
        grid.querySelectorAll('.player-card').forEach(card => {
            card.addEventListener('click', () => {
                const pId = card.getAttribute('data-id');
                openPlayerDossier(pId);
            });
        });

    } catch (e) {
        grid.innerHTML = `
            <div class="empty-state" style="grid-column: 1 / -1;">
                <div class="empty-icon">⚠️</div>
                <h3>Falha ao carregar jogadores</h3>
                <p>Verifique se o servidor FastAPI está operando em <code>http://localhost:8000</code>.</p>
            </div>
        `;
    }
}

function renderPlayerCard(p) {
    const initials = p.name.split(' ').map(n => n[0]).slice(0, 2).join('');
    const valuation = p.market_value_raw || 'Sob Consulta';
    const roleClass = `role-${p.scout_role}`;

    return `
        <div class="player-card" data-id="${p.mapping_id || p.profile_id}">
            <div>
                <div class="card-top">
                    <div class="player-avatar">${initials}</div>
                    <span class="role-badge ${roleClass}">${p.scout_role}</span>
                </div>
                <div class="card-body">
                    <h3 class="player-name">${p.name}</h3>
                    <div class="player-team">
                        <span>🛡️ ${p.current_team || 'Sem clube'}</span>
                        <span>•</span>
                        <span>${p.current_league || ''}</span>
                    </div>
                    <div class="card-specs">
                        <span class="spec-chip">Categoria: ${p.scout_category}</span>
                        ${p.birth_date ? `<span class="spec-chip">Nasc: ${p.birth_date}</span>` : ''}
                    </div>
                </div>
            </div>
            <div class="card-footer">
                <span class="valuation-tag">💰 ${valuation}</span>
                <button class="btn-card-action">Ver Dossiê ➔</button>
            </div>
        </div>
    `;
}

// =============================================================================
// RAIO-X & RADAR DE SCOUTING (TAB 2 - TODAS AS 143 ESTATÍSTICAS)
// =============================================================================
const DossierState = {
    schema: null,
    players: [],
    currentPlayerId: null,
    comparePlayerId: '',
    season: 'latest',
    minMinutes: 450,
    dossierData: null,
    compareData: null,
    statMap: {},
    compareStatMap: {},
    radarKeys: [],
    lastRole: null,
    statFilterMode: 'all', // 'all' (143 estatísticas) | 'nonzero'
    statSearch: '',
    catFilter: '',
    loading: false,
    simTimer: null,
    debounceTimer: null,
};

function escHtml(str) {
    return String(str ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function pctBarClass(pct) {
    if (pct === null || pct === undefined) return 'rx-pct-low';
    if (pct >= 80) return 'rx-pct-elite';
    if (pct >= 60) return 'rx-pct-good';
    if (pct >= 40) return 'rx-pct-mid';
    return 'rx-pct-low';
}

async function ensureDossierCatalog() {
    if (!DossierState.schema) {
        if (RankingState.schema) {
            DossierState.schema = RankingState.schema;
        } else {
            const res = await fetch(`${API_BASE}/explorer/schema`);
            if (res.ok) {
                const schema = await res.json();
                DossierState.schema = schema;
                RankingState.schema = schema;
                schema.stats.forEach(s => { RankingState.statMap[s.key] = s; });
            }
        }
        populateDossierStaticOptions();
    }

    if (!DossierState.players.length) {
        const resP = await fetch(`${API_BASE}/explorer/players`);
        if (resP.ok) {
            const pData = await resP.json();
            DossierState.players = pData.players || [];
            populateDossierPlayerSelects();
        }
    }
}

function populateDossierStaticOptions() {
    const schema = DossierState.schema;
    if (!schema) return;

    const seasonSel = document.getElementById('dossier-season');
    if (seasonSel) {
        seasonSel.innerHTML = `
            <option value="latest">Última temporada c/ amostra</option>
            <option value="all">Carreira completa agregada</option>
            <optgroup label="Temporadas Específicas">
                ${schema.seasons.map(s => `<option value="${escHtml(s.value)}">${escHtml(s.value)} (${s.players} atl.)</option>`).join('')}
            </optgroup>
        `;
        seasonSel.value = DossierState.season || 'latest';
    }

    const catSel = document.getElementById('dossier-cat-filter');
    if (catSel) {
        catSel.innerHTML = '<option value="">Todas as 12 Categorias (143 estatísticas)</option>' +
            schema.categories.map(c => {
                const n = schema.stats.filter(s => s.category === c.id).length;
                return `<option value="${escHtml(c.id)}">${escHtml(c.icon)} ${escHtml(c.label)} (${n})</option>`;
            }).join('');
    }

    populateDossierRadarAddOptions('');
}

function populateDossierPlayerSelects(mainQuery = null, compQuery = null) {
    const mainSearch = mainQuery !== null ? mainQuery : (document.getElementById('dossier-player-search')?.value || '');
    const compSearch = compQuery !== null ? compQuery : (document.getElementById('dossier-compare-search')?.value || '');

    const mainSel = document.getElementById('dossier-player-select');
    if (mainSel && DossierState.players.length) {
        const q = foldRankStr(mainSearch);
        const filtered = q
            ? DossierState.players.filter(p => foldRankStr(`${p.name} ${p.current_team} ${p.scout_role} ${p.current_league}`).includes(q))
            : DossierState.players;

        const list = filtered.length ? filtered : DossierState.players.slice(0, 30);
        mainSel.innerHTML = list.map(p =>
            `<option value="${p.mapping_id}">${escHtml(p.name)} — ${escHtml(p.current_team)} (${escHtml(p.scout_role)})</option>`
        ).join('');

        if (DossierState.currentPlayerId && list.some(p => String(p.mapping_id) === String(DossierState.currentPlayerId))) {
            mainSel.value = String(DossierState.currentPlayerId);
        } else if (q && filtered.length) {
            mainSel.value = String(filtered[0].mapping_id);
        }
    }

    const compSel = document.getElementById('dossier-compare-select');
    if (compSel && DossierState.players.length) {
        const q2 = foldRankStr(compSearch);
        const filtered2 = DossierState.players.filter(p => {
            if (String(p.mapping_id) === String(DossierState.currentPlayerId)) return false;
            if (!q2) return true;
            return foldRankStr(`${p.name} ${p.current_team} ${p.scout_role} ${p.current_league}`).includes(q2);
        });

        let html = '<option value="">Sem comparação (apenas atleta principal)</option>';
        html += filtered2.map(p =>
            `<option value="${p.mapping_id}">⚔️ ${escHtml(p.name)} — ${escHtml(p.current_team)} (${escHtml(p.scout_role)})</option>`
        ).join('');
        compSel.innerHTML = html;

        if (DossierState.comparePlayerId && filtered2.some(p => String(p.mapping_id) === String(DossierState.comparePlayerId))) {
            compSel.value = String(DossierState.comparePlayerId);
        } else {
            compSel.value = '';
        }
    }

    const clearBtn = document.getElementById('dossier-compare-clear');
    if (clearBtn) clearBtn.hidden = !DossierState.comparePlayerId;
}

function populateDossierRadarAddOptions(filterText = '') {
    const sel = document.getElementById('dossier-radar-add');
    const schema = DossierState.schema;
    if (!sel || !schema) return;

    const q = foldRankStr(filterText);
    const activeSet = new Set(DossierState.radarKeys);
    let html = `<option value="">+ Adicionar estatística ao Radar (${schema.stats.length} disponíveis)...</option>`;

    schema.categories.forEach(cat => {
        const stats = schema.stats.filter(s => {
            if (s.category !== cat.id) return false;
            return matchesStatQuery(`${s.label} ${s.key} ${s.description} ${cat.label}`, filterText);
        });
        if (!stats.length) return;
        html += `<optgroup label="${escHtml(cat.icon)} ${escHtml(cat.label)} (${stats.length})">`;
        stats.forEach(s => {
            const onRadar = activeSet.has(s.key);
            html += `<option value="${escHtml(s.key)}" ${onRadar ? 'disabled' : ''}>${onRadar ? '✓ ' : ''}${escHtml(s.label)}</option>`;
        });
        html += '</optgroup>';
    });

    sel.innerHTML = html;
    sel.value = '';
}

async function openDefaultDossierIfNeeded() {
    await ensureDossierCatalog();
    if (!DossierState.currentPlayerId && DossierState.players.length > 0) {
        await openPlayerDossier(String(DossierState.players[0].mapping_id), DossierState.minMinutes);
    }
}

async function openPlayerDossier(playerId, minMinutes = null, season = null) {
    State.selectedPlayerId = String(playerId);
    DossierState.currentPlayerId = String(playerId);

    if (minMinutes !== null && minMinutes !== undefined) {
        DossierState.minMinutes = Math.max(0, Number(minMinutes) || 0);
        const minEl = document.getElementById('dossier-min-minutes');
        if (minEl) minEl.value = String(DossierState.minMinutes);
    }
    if (season) {
        DossierState.season = season;
        const sEl = document.getElementById('dossier-season');
        if (sEl) sEl.value = season;
    }

    if (String(DossierState.comparePlayerId) === String(playerId)) {
        DossierState.comparePlayerId = '';
        DossierState.compareData = null;
        DossierState.compareStatMap = {};
    }

    switchTab('dossier');
    window.scrollTo({ top: 0, behavior: 'smooth' });
    await loadCurrentDossier();
}
window.openPlayerDossier = openPlayerDossier;

async function setComparePlayer(compareId) {
    DossierState.comparePlayerId = compareId ? String(compareId) : '';
    const compSel = document.getElementById('dossier-compare-select');
    if (compSel) compSel.value = DossierState.comparePlayerId;
    const clearBtn = document.getElementById('dossier-compare-clear');
    if (clearBtn) clearBtn.hidden = !DossierState.comparePlayerId;
    await loadCurrentDossier();
}
window.setComparePlayer = setComparePlayer;

async function loadCurrentDossier() {
    if (!DossierState.currentPlayerId) return;
    DossierState.loading = true;

    try {
        await ensureDossierCatalog();
        populateDossierPlayerSelects();

        const params = new URLSearchParams({
            season: DossierState.season || 'latest',
            min_minutes: String(DossierState.minMinutes),
        });

        const fetches = [
            fetch(`${API_BASE}/players/${encodeURIComponent(DossierState.currentPlayerId)}/dossier?${params.toString()}`),
        ];
        if (DossierState.comparePlayerId && DossierState.comparePlayerId !== DossierState.currentPlayerId) {
            fetches.push(
                fetch(`${API_BASE}/players/${encodeURIComponent(DossierState.comparePlayerId)}/dossier?${params.toString()}`)
            );
        }

        const [resMain, resComp] = await Promise.all(fetches);
        if (!resMain.ok) throw new Error('Dossiê não encontrado');
        const mainData = await resMain.json();
        const compData = (resComp && resComp.ok) ? await resComp.json() : null;

        DossierState.dossierData = mainData;
        DossierState.compareData = compData;

        // Indexa todas as 143 estatísticas para acesso O(1) instantâneo no Radar e na Tabela
        DossierState.statMap = {};
        (mainData.categories || []).forEach(cat => {
            (cat.stats || []).forEach(st => {
                DossierState.statMap[st.key] = st;
            });
        });

        DossierState.compareStatMap = {};
        if (compData) {
            (compData.categories || []).forEach(cat => {
                (cat.stats || []).forEach(st => {
                    DossierState.compareStatMap[st.key] = st;
                });
            });
        }

        const role = mainData.profile.scout_role;
        if (!DossierState.radarKeys.length || DossierState.lastRole !== role) {
            DossierState.radarKeys = [...(mainData.default_radar_keys || [])];
            DossierState.lastRole = role;
        }

        // Sincroniza o seletor com o mapping_id resolvido
        DossierState.currentPlayerId = String(mainData.profile.mapping_id);
        const mainSel = document.getElementById('dossier-player-select');
        if (mainSel) mainSel.value = DossierState.currentPlayerId;

        renderDossierHero(mainData.profile, compData ? compData.profile : null);
        renderDossierQualitative(mainData.characteristics);
        populateDossierRadarAddOptions(document.getElementById('dossier-radar-search')?.value || '');
        renderDossierRadarSection();
        renderDossierAllStats();
        await refreshSimilarPlayers();
    } catch (err) {
        console.error('Erro ao carregar Raio-X & Radar:', err);
        renderEmptyRadar('Não foi possível carregar o Raio-X analítico deste atleta.');
    } finally {
        DossierState.loading = false;
    }
}

function renderDossierHero(prof, compProf = null) {
    const heroContainer = document.getElementById('dossier-hero');
    if (!heroContainer || !prof) return;

    const initials = prof.name.split(' ').map(n => n[0]).slice(0, 2).join('');
    const posChips = (prof.positions_labels && prof.positions_labels.length)
        ? prof.positions_labels.map(p => `<span class="spec-chip">${escHtml(p)}</span>`).join('')
        : (prof.position_raw ? `<span class="spec-chip">${escHtml(prof.position_raw)}</span>` : '');

    const bioItems = [];
    if (prof.age !== null && prof.age !== undefined) bioItems.push(`🎂 ${prof.age} anos${prof.birth_date ? ` (${prof.birth_date})` : ''}`);
    else if (prof.birth_date) bioItems.push(`📅 ${prof.birth_date}`);
    if (prof.footed_label) bioItems.push(`👟 Pé ${prof.footed_label}`);
    const hw = [prof.height ? `${prof.height} cm` : '', prof.weight ? `${prof.weight} kg` : ''].filter(Boolean).join(' / ');
    if (hw) bioItems.push(`📏 ${hw}`);

    const sampleSummary = `📅 Temp. ${prof.season || 'N/A'} • ${prof.appearances ?? 0} jogos (${prof.minutes_played ?? 0}') • Universo posicional (${prof.scout_role}): ${prof.role_pool_size ?? 0} atletas`;

    heroContainer.innerHTML = `
        <div class="dossier-hero-left">
            <div class="dossier-avatar-large">${escHtml(initials)}</div>
            <div>
                <div style="display: flex; align-items: center; gap: 0.65rem; flex-wrap: wrap;">
                    <h1 class="dossier-name">${escHtml(prof.name)}</h1>
                    <span class="role-badge role-${escHtml(prof.scout_role)}">${escHtml(prof.scout_role)}</span>
                    ${posChips}
                </div>
                ${prof.full_name && prof.full_name !== prof.name ? `<div style="font-size: 0.8rem; color: var(--text-muted); margin-top: 0.15rem;">${escHtml(prof.full_name)}</div>` : ''}
                <div class="dossier-subtitle" style="flex-wrap: wrap; margin-top: 0.35rem;">
                    <span>🛡️ <strong>${escHtml(prof.current_team || 'N/A')}</strong> (${escHtml(prof.current_league || 'N/A')})</span>
                    ${bioItems.map(b => `<span>• ${escHtml(b)}</span>`).join('')}
                </div>
                <div style="font-size: 0.8rem; color: var(--accent-emerald); margin-top: 0.4rem; font-weight: 500;">
                    ${escHtml(sampleSummary)}
                </div>
                ${compProf ? `
                    <div style="margin-top: 0.45rem; font-size: 0.8rem; color: var(--accent-cyan);">
                        ⚔️ Comparando no Radar com: <strong>${escHtml(compProf.name)}</strong> (${escHtml(compProf.current_team)} • ${compProf.minutes_played}' na temp. ${escHtml(compProf.season)})
                    </div>
                ` : ''}
                <div class="external-links">
                    ${prof.transfermarkt_url ? `<a href="${escHtml(prof.transfermarkt_url)}" target="_blank" rel="noopener" class="link-chip">Transfermarkt ↗</a>` : ''}
                    ${prof.whoscored_url ? `<a href="${escHtml(prof.whoscored_url)}" target="_blank" rel="noopener" class="link-chip">WhoScored ↗</a>` : ''}
                </div>
            </div>
        </div>
        <div class="dossier-hero-right">
            <div class="dossier-value-box">
                <div class="dossier-value-label">Valor de Mercado Atual</div>
                <div class="dossier-value-amount">${escHtml(prof.market_value_raw || 'Sob Consulta')}</div>
            </div>
        </div>
    `;
}

function renderDossierQualitative(chars) {
    const strengthsEl = document.getElementById('traits-strengths');
    const weaknessesEl = document.getElementById('traits-weaknesses');
    const stylesEl = document.getElementById('traits-styles');
    if (!chars) return;

    const mergedStrengths = [...(chars.player_strengths || []), ...(chars.sofascore_strengths || [])];
    const mergedWeaknesses = [...(chars.player_weaknesses || []), ...(chars.sofascore_weaknesses || [])];

    if (strengthsEl) strengthsEl.innerHTML = renderTraits(mergedStrengths, 'strength', 'Nenhum ponto forte catalogado nas fontes');
    if (weaknessesEl) weaknessesEl.innerHTML = renderTraits(mergedWeaknesses, 'weakness', 'Nenhum ponto fraco ou alerta registrado');
    if (stylesEl) stylesEl.innerHTML = renderStyles(chars.player_style_of_play, chars.team_style);
}

function renderDossierRadarSection() {
    const data = DossierState.dossierData;
    const tableContainer = document.getElementById('radar-table-body');
    const headRow = document.getElementById('radar-table-head-row');
    const axisCountEl = document.getElementById('dossier-radar-axis-count');
    if (!data) return;

    const compData = DossierState.compareData;
    const keys = DossierState.radarKeys;
    if (axisCountEl) axisCountEl.textContent = `${keys.length} eixos`;

    if (!data.has_stats) {
        renderEmptyRadar('Sem minutos registrados neste recorte de temporada.');
        if (tableContainer) {
            tableContainer.innerHTML = '<tr><td colspan="6" style="text-align:center;">Selecione outro recorte de temporada acima.</td></tr>';
        }
        return;
    }

    const radarItems = keys.map(k => DossierState.statMap[k]).filter(Boolean);
    const compItems = compData ? keys.map(k => DossierState.compareStatMap[k] || null) : null;

    renderRadarChart(radarItems, data.profile.name, compItems, compData ? compData.profile.name : null);

    if (headRow) {
        headRow.innerHTML = `
            <th>Atributo no Radar</th>
            <th>Total / Taxa</th>
            <th>Por 90'</th>
            <th>${compData ? `vs ${escHtml(compData.profile.name)}` : 'Média Função'}</th>
            <th>Percentil (${escHtml(data.profile.scout_role)})</th>
            <th></th>
        `;
    }

    if (tableContainer) {
        const canRemove = radarItems.length > 3;
        tableContainer.innerHTML = radarItems.map((st, idx) => {
            const rawTxt = fmtRankVal(st.raw_value, st.decimals, st.unit);
            const p90Txt = st.per90 ? fmtRankVal(st.p90_value, Math.max(st.decimals, 2), st.unit ? `${st.unit}/90` : '/90') : '—';
            let refTxt = '—';
            if (compItems) {
                const cSt = compItems[idx];
                if (cSt) {
                    refTxt = cSt.per90
                        ? `${fmtRankVal(cSt.p90_value, Math.max(cSt.decimals, 2), cSt.unit ? `${cSt.unit}/90` : '/90')} (P${Math.round(cSt.percentile || 0)})`
                        : `${fmtRankVal(cSt.raw_value, cSt.decimals, cSt.unit)} (P${Math.round(cSt.percentile || 0)})`;
                }
            } else {
                refTxt = st.per90
                    ? fmtRankVal(st.role_mean_p90, Math.max(st.decimals, 2), st.unit ? `${st.unit}/90` : '/90')
                    : fmtRankVal(st.role_mean_raw, Math.max(st.decimals, 1), st.unit);
            }
            const pct = st.percentile;

            return `
                <tr>
                    <td style="font-weight: 600;" title="${escHtml(st.description)}">
                        ${escHtml(st.label)}
                    </td>
                    <td>${escHtml(rawTxt)}</td>
                    <td style="color: var(--accent-cyan);">${escHtml(p90Txt)}</td>
                    <td style="color: ${compData ? 'var(--accent-cyan)' : 'var(--text-secondary)'}; font-size: 0.8rem;">${escHtml(refTxt)}</td>
                    <td>
                        <div style="display: flex; align-items: center; gap: 0.5rem;">
                            <div class="percentile-progress" style="min-width: 68px;">
                                <div class="percentile-fill ${pctBarClass(pct)}" style="width: ${pct || 0}%;"></div>
                            </div>
                            <span style="font-weight: 700; font-size: 0.8rem; width: 45px;">${pct !== null && pct !== undefined ? pct.toFixed(1) + '%' : 'N/A'}</span>
                        </div>
                    </td>
                    <td style="text-align: right;">
                        <button type="button" class="rx-axis-remove" data-remove-axis="${escHtml(st.key)}"
                                ${canRemove ? '' : 'disabled'} title="${canRemove ? 'Remover eixo do Radar' : 'Mínimo de 3 eixos no Radar'}">✕</button>
                    </td>
                </tr>
            `;
        }).join('');

        tableContainer.querySelectorAll('button[data-remove-axis]').forEach(btn => {
            btn.addEventListener('click', () => toggleRadarAxis(btn.dataset.removeAxis));
        });
    }
}

function toggleRadarAxis(statKey) {
    if (!statKey || !DossierState.statMap[statKey]) return;
    const idx = DossierState.radarKeys.indexOf(statKey);
    if (idx >= 0) {
        if (DossierState.radarKeys.length <= 3) return; // mantém polígono válido (>= 3 eixos)
        DossierState.radarKeys.splice(idx, 1);
    } else {
        if (DossierState.radarKeys.length >= 12) {
            DossierState.radarKeys.shift();
        }
        DossierState.radarKeys.push(statKey);
    }

    populateDossierRadarAddOptions(document.getElementById('dossier-radar-search')?.value || '');
    renderDossierRadarSection();
    syncPinButtonsInAllStats();

    clearTimeout(DossierState.simTimer);
    DossierState.simTimer = setTimeout(refreshSimilarPlayers, 250);
}

function syncPinButtonsInAllStats() {
    const activeSet = new Set(DossierState.radarKeys);
    document.querySelectorAll('#dossier-all-stats button[data-pin-key]').forEach(btn => {
        const isPinned = activeSet.has(btn.dataset.pinKey);
        btn.classList.toggle('active', isPinned);
        btn.title = isPinned ? 'Ativo no Radar (clique para remover)' : 'Adicionar este atributo ao Gráfico de Radar';
    });
}

function renderDossierAllStats() {
    const container = document.getElementById('dossier-all-stats');
    const summaryEl = document.getElementById('dossier-stats-summary');
    const data = DossierState.dossierData;
    if (!container || !data) return;

    const compData = DossierState.compareData;
    const q = foldRankStr(DossierState.statSearch);
    const catFilter = DossierState.catFilter;
    const onlyNonZero = DossierState.statFilterMode === 'nonzero';
    const activeRadarSet = new Set(DossierState.radarKeys);

    let shownStats = 0;
    let shownCats = 0;
    let html = '';

    (data.categories || []).forEach(cat => {
        if (catFilter && cat.id !== catFilter) return;

        const filteredStats = (cat.stats || []).filter(st => {
            if (onlyNonZero && !st.has_value) return false;
            return matchesStatQuery(`${st.label} ${st.key} ${st.description} ${st.source_label} ${cat.label}`, DossierState.statSearch);
        });

        if (!filteredStats.length) return;
        shownCats += 1;
        shownStats += filteredStats.length;

        html += `
            <details class="rx-cat-card" data-cat-id="${escHtml(cat.id)}" open>
                <summary>
                    <div class="ex-summary-title">
                        <span>${escHtml(cat.icon)}</span>
                        <span>${escHtml(cat.label)}</span>
                        <span class="ex-cat-count">(${filteredStats.length} de ${cat.total_count} estatísticas)</span>
                    </div>
                    <div class="ex-summary-right">
                        <span class="spec-chip">${cat.populated_count} c/ registro</span>
                        <span class="ex-chevron">▼</span>
                    </div>
                </summary>
                <div class="rx-cat-table-wrap">
                    <table class="rx-stats-table">
                        <thead>
                            <tr>
                                <th style="width: 48px;">Radar</th>
                                <th>Estatística</th>
                                <th>Total / Taxa</th>
                                <th>Por 90' (/90)</th>
                                ${compData ? `<th>vs ${escHtml(compData.profile.name)}</th>` : ''}
                                <th>Média (${escHtml(data.profile.scout_role)})</th>
                                <th style="min-width: 170px;">Percentil Posicional</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${filteredStats.map(st => {
                                const isPinned = activeRadarSet.has(st.key);
                                const rawTxt = fmtRankVal(st.raw_value, st.decimals, st.unit);
                                const p90Txt = st.per90
                                    ? fmtRankVal(st.p90_value, Math.max(st.decimals, 2), st.unit ? `${st.unit}/90` : '/90')
                                    : '—';
                                const meanTxt = st.per90
                                    ? fmtRankVal(st.role_mean_p90, Math.max(st.decimals, 2), st.unit ? `${st.unit}/90` : '/90')
                                    : fmtRankVal(st.role_mean_raw, Math.max(st.decimals, 1), st.unit);
                                const pct = st.percentile;
                                const mutedCls = !st.has_value ? 'rx-row-muted' : '';

                                let compCell = '';
                                if (compData) {
                                    const cSt = DossierState.compareStatMap[st.key];
                                    const cVal = cSt
                                        ? (cSt.per90 && cSt.p90_value !== null
                                            ? `${fmtRankVal(cSt.raw_value, cSt.decimals, cSt.unit)} (${fmtRankVal(cSt.p90_value, Math.max(cSt.decimals, 2))}/90)`
                                            : fmtRankVal(cSt.raw_value, cSt.decimals, cSt.unit))
                                        : '—';
                                    compCell = `<td style="color: var(--accent-cyan); font-weight: 600;">${escHtml(cVal)}</td>`;
                                }

                                return `
                                    <tr class="${mutedCls}" data-stat-key="${escHtml(st.key)}">
                                        <td>
                                            <button type="button" class="rx-pin-btn ${isPinned ? 'active' : ''}"
                                                    data-pin-key="${escHtml(st.key)}"
                                                    title="${isPinned ? 'Ativo no Radar (clique para remover)' : 'Adicionar este atributo ao Gráfico de Radar'}">
                                                🎯
                                            </button>
                                        </td>
                                        <td title="${escHtml(st.description)}">
                                            <span style="font-weight: 600; color: #f8fafc;">${escHtml(st.label)}</span>
                                            <div style="font-size: 0.73rem; color: var(--text-muted); margin-top: 0.1rem;">${escHtml(st.description)}</div>
                                        </td>
                                        <td style="font-weight: 700; color: #fff;">${escHtml(rawTxt)}</td>
                                        <td style="color: var(--accent-cyan); font-weight: 600;">${escHtml(p90Txt)}</td>
                                        ${compCell}
                                        <td style="color: var(--text-secondary);">${escHtml(meanTxt)}</td>
                                        <td>
                                            <div style="display: flex; align-items: center; gap: 0.55rem;">
                                                <div class="percentile-progress" style="width: 95px;">
                                                    <div class="percentile-fill ${pctBarClass(pct)}" style="width: ${pct || 0}%;"></div>
                                                </div>
                                                <span style="font-weight: 700; font-size: 0.8rem; min-width: 44px;">
                                                    ${pct !== null && pct !== undefined ? pct.toFixed(1) + '%' : '—'}
                                                </span>
                                            </div>
                                        </td>
                                    </tr>
                                `;
                            }).join('')}
                        </tbody>
                    </table>
                </div>
            </details>
        `;
    });

    if (!html) {
        container.innerHTML = '<div style="padding: 1.5rem; text-align: center; color: var(--text-muted);">Nenhuma estatística corresponde ao filtro aplicado.</div>';
    } else {
        container.innerHTML = html;
        container.querySelectorAll('button[data-pin-key]').forEach(btn => {
            btn.addEventListener('click', () => toggleRadarAxis(btn.dataset.pinKey));
        });
    }

    if (summaryEl) {
        summaryEl.textContent = `Exibindo ${shownStats} de ${data.total_stats || 143} estatísticas em ${shownCats} categorias (${data.populated_stats || 0} com registro > 0 no recorte • clique em 🎯 para fixar/remover no Radar).`;
    }
}

async function refreshSimilarPlayers() {
    const similarEl = document.getElementById('similar-list');
    const data = DossierState.dossierData;
    if (!similarEl || !data) return;

    try {
        const params = new URLSearchParams({
            top_n: '5',
            season: DossierState.season || 'latest',
            min_minutes: String(data.profile.effective_min_minutes ?? DossierState.minMinutes),
        });
        DossierState.radarKeys.forEach(k => params.append('metrics', k));

        const resSim = await fetch(`${API_BASE}/players/${encodeURIComponent(data.profile.mapping_id)}/similar?${params.toString()}`);
        if (resSim.ok) {
            const simData = await resSim.json();
            renderSimilarPlayers(simData.similar_players, similarEl);
        }
    } catch (e) {
        similarEl.innerHTML = '<p style="color: var(--text-muted); font-size: 0.85rem;">Não foi possível calcular atletas similares.</p>';
    }
}

function renderTraits(traits, type, emptyMsg) {
    if (!traits || traits.length === 0) {
        return `<span style="color: var(--text-muted); font-size: 0.85rem;">${emptyMsg}</span>`;
    }
    const cls = type === 'strength' ? 'trait-strength' : 'trait-weakness';
    const icon = type === 'strength' ? '▲' : '▼';
    const unique = [];
    const seen = new Set();
    traits.forEach(t => {
        const name = typeof t === 'object' ? `${t.name}${t.level ? ` (${t.level})` : ''}` : String(t);
        const key = foldRankStr(name);
        if (!seen.has(key)) {
            seen.add(key);
            unique.push(name);
        }
    });
    return unique.map(name => `<span class="trait-tag ${cls}">${icon} ${escHtml(name)}</span>`).join('');
}

function renderStyles(playerStyle, teamStyle) {
    let html = '';
    if (playerStyle && playerStyle.length > 0) {
        html += playerStyle.map(s => `<span class="trait-tag trait-style">👤 ${escHtml(s)}</span>`).join('');
    }
    if (teamStyle && teamStyle.length > 0) {
        html += teamStyle.map(s => `<span class="trait-tag trait-style">🛡️ Clube: ${escHtml(s)}</span>`).join('');
    }
    return html || '<span style="color: var(--text-muted); font-size: 0.85rem;">Estilo não catalogado</span>';
}

function renderSimilarPlayers(similars, container) {
    if (!container) return;
    if (!similars || similars.length === 0) {
        container.innerHTML = '<p style="color: var(--text-muted); font-size: 0.85rem;">Nenhum atleta similar identificado com a minutagem atual.</p>';
        return;
    }
    container.innerHTML = similars.map(sim => {
        const isComparing = String(DossierState.comparePlayerId) === String(sim.mapping_id);
        return `
            <div class="similar-item" onclick="openPlayerDossier('${sim.mapping_id}')">
                <div>
                    <strong>${escHtml(sim.player_name)}</strong>
                    <div style="font-size: 0.78rem; color: var(--text-muted);">
                        🛡️ ${escHtml(sim.current_team)} • ${escHtml(sim.market_value_raw || 'N/A')}
                    </div>
                </div>
                <div class="rx-sim-actions">
                    <button type="button" class="rx-btn-compare-mini"
                            onclick="event.stopPropagation(); setComparePlayer('${isComparing ? '' : sim.mapping_id}')">
                        ${isComparing ? '✕ Remover' : '⚔️ Comparar'}
                    </button>
                    <span class="similar-score">${sim.similarity_pct}%</span>
                </div>
            </div>
        `;
    }).join('');
}

function renderRadarChart(radarItems, playerName, compItems = null, compName = null) {
    const canvas = document.getElementById('radar-canvas');
    if (!canvas) return;

    if (State.radarChart) {
        State.radarChart.destroy();
    }

    const labels = radarItems.map(i => i.per90 ? `${i.label} /90` : i.label);
    const percentiles = radarItems.map(i => i.percentile ?? 0);

    const datasets = [
        {
            label: `${playerName}`,
            data: percentiles,
            backgroundColor: 'rgba(16, 185, 129, 0.26)',
            borderColor: '#10b981',
            borderWidth: 2.5,
            pointBackgroundColor: '#10b981',
            pointBorderColor: '#fff',
            pointHoverRadius: 6,
            pointRadius: 4,
        },
    ];

    if (compItems && compName) {
        datasets.push({
            label: `${compName}`,
            data: compItems.map(c => (c && c.percentile !== null && c.percentile !== undefined) ? c.percentile : 0),
            backgroundColor: 'rgba(6, 182, 212, 0.20)',
            borderColor: '#06b6d4',
            borderWidth: 2.2,
            pointBackgroundColor: '#06b6d4',
            pointBorderColor: '#fff',
            pointHoverRadius: 6,
            pointRadius: 4,
        });
    }

    datasets.push({
        label: 'Mediana da Posição (50%)',
        data: radarItems.map(() => 50),
        backgroundColor: 'transparent',
        borderColor: 'rgba(148, 163, 184, 0.35)',
        borderDash: [4, 4],
        borderWidth: 1.2,
        pointRadius: 0,
        pointHoverRadius: 0,
    });

    const ctx = canvas.getContext('2d');
    State.radarChart = new Chart(ctx, {
        type: 'radar',
        data: { labels, datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                r: {
                    min: 0,
                    max: 100,
                    ticks: {
                        stepSize: 20,
                        color: 'rgba(255, 255, 255, 0.4)',
                        backdropColor: 'transparent',
                        font: { size: 9 },
                    },
                    grid: { color: 'rgba(255, 255, 255, 0.08)' },
                    angleLines: { color: 'rgba(255, 255, 255, 0.1)' },
                    pointLabels: {
                        color: '#f8fafc',
                        font: { size: 10.5, family: "'Inter', sans-serif", weight: 600 },
                    }
                }
            },
            plugins: {
                legend: {
                    display: Boolean(compItems && compName),
                    labels: { color: '#cbd5e1', font: { size: 11 } },
                },
                tooltip: {
                    callbacks: {
                        label: (ctx) => {
                            if (ctx.datasetIndex === datasets.length - 1) {
                                return 'Mediana Posicional: 50%';
                            }
                            const sourceArr = (ctx.datasetIndex === 1 && compItems) ? compItems : radarItems;
                            const item = sourceArr[ctx.dataIndex];
                            if (!item) return `${ctx.dataset.label}: N/A`;
                            const lines = [`${ctx.dataset.label} — Percentil: ${Number(ctx.raw).toFixed(1)}%`];
                            if (item.per90) {
                                lines.push(`Por 90': ${fmtRankVal(item.p90_value, Math.max(item.decimals, 2), item.unit ? `${item.unit}/90` : '/90')}`);
                            }
                            lines.push(`Total / Taxa: ${fmtRankVal(item.raw_value, item.decimals, item.unit)}`);
                            return lines;
                        }
                    }
                }
            }
        }
    });
}

function renderEmptyRadar(message) {
    const canvas = document.getElementById('radar-canvas');
    if (!canvas) return;
    if (State.radarChart) State.radarChart.destroy();
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.font = "14px 'Inter', sans-serif";
    ctx.fillStyle = "#64748b";
    ctx.textAlign = "center";
    ctx.fillText(message, canvas.width / 2, canvas.height / 2);
}

// Vincula controles interativos do Raio-X & Radar (Tab 2)
document.addEventListener('DOMContentLoaded', () => {
    const pSearch = document.getElementById('dossier-player-search');
    const pSelect = document.getElementById('dossier-player-select');
    if (pSearch) {
        pSearch.addEventListener('input', async () => {
            await ensureDossierCatalog();
            populateDossierPlayerSelects(pSearch.value, null);
            if (pSelect && pSelect.value && pSelect.value !== DossierState.currentPlayerId) {
                clearTimeout(DossierState.debounceTimer);
                DossierState.debounceTimer = setTimeout(() => {
                    DossierState.currentPlayerId = pSelect.value;
                    loadCurrentDossier();
                }, 260);
            }
        });
    }
    if (pSelect) {
        pSelect.addEventListener('change', () => {
            if (pSelect.value) {
                DossierState.currentPlayerId = pSelect.value;
                loadCurrentDossier();
            }
        });
    }

    const cSearch = document.getElementById('dossier-compare-search');
    const cSelect = document.getElementById('dossier-compare-select');
    if (cSearch) {
        cSearch.addEventListener('input', async () => {
            await ensureDossierCatalog();
            populateDossierPlayerSelects(null, cSearch.value);
        });
    }
    if (cSelect) {
        cSelect.addEventListener('change', () => setComparePlayer(cSelect.value));
    }
    document.getElementById('dossier-compare-clear')?.addEventListener('click', () => {
        if (cSearch) cSearch.value = '';
        setComparePlayer('');
    });

    const seasonEl = document.getElementById('dossier-season');
    if (seasonEl) {
        seasonEl.addEventListener('change', () => {
            DossierState.season = seasonEl.value;
            loadCurrentDossier();
        });
    }

    const minEl = document.getElementById('dossier-min-minutes');
    if (minEl) {
        minEl.addEventListener('input', () => {
            clearTimeout(DossierState.debounceTimer);
            DossierState.debounceTimer = setTimeout(() => {
                DossierState.minMinutes = Math.max(0, Number(minEl.value) || 0);
                loadCurrentDossier();
            }, 320);
        });
    }

    const radarSearch = document.getElementById('dossier-radar-search');
    if (radarSearch) {
        radarSearch.addEventListener('input', () => populateDossierRadarAddOptions(radarSearch.value));
    }
    const radarAdd = document.getElementById('dossier-radar-add');
    if (radarAdd) {
        radarAdd.addEventListener('change', () => {
            if (radarAdd.value) toggleRadarAxis(radarAdd.value);
        });
    }
    document.getElementById('dossier-radar-reset')?.addEventListener('click', () => {
        if (DossierState.dossierData) {
            DossierState.radarKeys = [...(DossierState.dossierData.default_radar_keys || [])];
            populateDossierRadarAddOptions(radarSearch?.value || '');
            renderDossierRadarSection();
            syncPinButtonsInAllStats();
            refreshSimilarPlayers();
        }
    });

    const statSearch = document.getElementById('dossier-stat-search');
    if (statSearch) {
        statSearch.addEventListener('input', () => {
            DossierState.statSearch = statSearch.value;
            renderDossierAllStats();
        });
    }
    const catFilter = document.getElementById('dossier-cat-filter');
    if (catFilter) {
        catFilter.addEventListener('change', () => {
            DossierState.catFilter = catFilter.value;
            renderDossierAllStats();
        });
    }
    document.querySelectorAll('#dossier-stat-filter-toggle .ex-mode-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            DossierState.statFilterMode = btn.dataset.filter;
            document.querySelectorAll('#dossier-stat-filter-toggle .ex-mode-btn').forEach(b => b.classList.toggle('active', b === btn));
            renderDossierAllStats();
        });
    });

    document.getElementById('dossier-expand-all')?.addEventListener('click', () => {
        document.querySelectorAll('#dossier-all-stats details.rx-cat-card').forEach(d => { d.open = true; });
    });
    document.getElementById('dossier-collapse-all')?.addEventListener('click', () => {
        document.querySelectorAll('#dossier-all-stats details.rx-cat-card').forEach(d => { d.open = false; });
    });
});

// =============================================================================
// RANKINGS & LÍDERES (TAB 3 - TODAS AS 143+ ESTATÍSTICAS)
// =============================================================================
const RankingState = {
    schema: null,
    statMap: {},
    barChart: null,
    lastData: null,
    benchMode: 'category', // 'category' | 'role'
    preferredMode: 'p90',  // lembra a preferência do usuário ao alternar entre métricas com/sem /90
    debounceTimer: null,
};

function foldRankStr(s) {
    return String(s || '')
        .normalize('NFD')
        .replace(/[\u0300-\u036f]/g, '')
        .toLowerCase()
        .trim();
}

function matchesStatQuery(haystackRaw, queryRaw) {
    const q = foldRankStr(queryRaw);
    if (!q) return true;
    const hay = foldRankStr(haystackRaw);
    if (hay.includes(q)) return true;
    const tokens = q.split(/\s+/).filter(Boolean);
    return tokens.every(tok => {
        if (hay.includes(tok)) return true;
        if (tok.length >= 5) {
            const stem = tok.replace(/(oes|ais|[oa]s?)$/, '');
            if (stem.length >= 4 && hay.includes(stem)) return true;
        }
        return false;
    });
}

function fmtRankVal(val, decimals = 0, unit = '') {
    if (val === null || val === undefined || Number.isNaN(Number(val))) return '—';
    const n = Number(val);
    const d = Number.isInteger(n) && decimals === 0 ? 0 : decimals;
    const txt = n.toLocaleString('pt-BR', {
        minimumFractionDigits: 0,
        maximumFractionDigits: Math.max(d, 0),
    });
    if (!unit) return txt;
    return unit === '%' ? `${txt}%` : `${txt} ${unit}`;
}

async function ensureRankingCatalog() {
    if (!RankingState.schema) {
        if (DossierState.schema) {
            RankingState.schema = DossierState.schema;
        } else {
            const res = await fetch(`${API_BASE}/explorer/schema`);
            if (!res.ok) throw new Error('Falha ao carregar catálogo de estatísticas');
            RankingState.schema = await res.json();
        }
        RankingState.schema.stats.forEach(s => { RankingState.statMap[s.key] = s; });
    }

    if (RankingState.domPopulated) return RankingState.schema;
    const schema = RankingState.schema;
    RankingState.domPopulated = true;

    // Popula Liga Atual
    const leagueSel = document.getElementById('ranking-league');
    if (leagueSel) {
        leagueSel.innerHTML = '<option value="">Todas as 11 Ligas</option>' +
            schema.leagues.map(l => `<option value="${l.value}">${l.label}</option>`).join('');
    }

    // Popula Temporadas
    const seasonSel = document.getElementById('ranking-season');
    if (seasonSel) {
        seasonSel.innerHTML = `
            <option value="latest" selected>Última temporada c/ amostra</option>
            <option value="all">Carreira completa agregada</option>
            <optgroup label="Temporadas Específicas">
                ${schema.seasons.map(s => `<option value="${s.value}">${s.value} (${s.players} atl.)</option>`).join('')}
            </optgroup>
        `;
    }

    populateRankingMetricOptions('');
    syncRankingModeAvailability();
    return schema;
}

function populateRankingMetricOptions(filterText = '', preferredValue = null) {
    const metricSel = document.getElementById('ranking-metric');
    if (!metricSel || !RankingState.schema) return false;

    const prevVal = preferredValue || metricSel.value || 'goals';
    const q = foldRankStr(filterText);
    let html = '';
    let firstMatch = null;
    let prevStillVisible = false;

    RankingState.schema.categories.forEach(cat => {
        const stats = RankingState.schema.stats.filter(s => {
            if (s.category !== cat.id) return false;
            return matchesStatQuery(`${s.label} ${s.key} ${s.description} ${cat.label}`, filterText);
        });
        if (!stats.length) return;
        html += `<optgroup label="${cat.icon} ${cat.label} (${stats.length})">`;
        stats.forEach(s => {
            if (!firstMatch) firstMatch = s.key;
            if (s.key === prevVal) prevStillVisible = true;
            html += `<option value="${s.key}">${s.label}</option>`;
        });
        html += '</optgroup>';
    });

    if (!html) {
        metricSel.innerHTML = '<option value="goals">Nenhuma estatística corresponde ao filtro (exibindo Gols)</option>';
        metricSel.value = 'goals';
        return prevVal !== 'goals';
    }

    metricSel.innerHTML = html;
    const nextVal = prevStillVisible ? prevVal : firstMatch;
    metricSel.value = nextVal;
    return nextVal !== prevVal;
}

function syncRankingModeAvailability() {
    const metricSel = document.getElementById('ranking-metric');
    const modeSel = document.getElementById('ranking-mode');
    if (!metricSel || !modeSel) return;

    const sd = RankingState.statMap[metricSel.value];
    const p90Opt = modeSel.querySelector('option[value="p90"]');
    if (!sd || !p90Opt) return;

    if (!sd.per90) {
        p90Opt.disabled = true;
        modeSel.value = 'total';
    } else {
        p90Opt.disabled = false;
        modeSel.value = RankingState.preferredMode || 'p90';
    }
}

async function loadRankings() {
    const tableBody = document.getElementById('rankings-table-body');
    if (!tableBody) return;

    try {
        await ensureRankingCatalog();
    } catch (err) {
        tableBody.innerHTML = '<tr><td colspan="9" style="text-align: center; color: var(--accent-rose);">Erro ao carregar catálogo de estatísticas.</td></tr>';
        return;
    }

    syncRankingModeAvailability();

    const metric = document.getElementById('ranking-metric')?.value || 'goals';
    const mode = document.getElementById('ranking-mode')?.value || 'p90';
    const order = document.getElementById('ranking-order')?.value || 'desc';
    const role = document.getElementById('ranking-role')?.value || '';
    const league = document.getElementById('ranking-league')?.value || '';
    const season = document.getElementById('ranking-season')?.value || 'latest';
    const minMinutes = Math.max(0, Number(document.getElementById('ranking-min-minutes')?.value) || 0);
    const limit = document.getElementById('ranking-limit')?.value || '20';

    tableBody.innerHTML = '<tr><td colspan="9" style="text-align: center;">⏳ Calculando ranking e referências posicionais...</td></tr>';

    const params = new URLSearchParams({
        metric,
        mode,
        order,
        season,
        min_minutes: String(minMinutes),
        limit: String(limit),
    });
    if (role) params.append('role', role);
    if (league) params.append('league', league);

    try {
        const res = await fetch(`${API_BASE}/analytics/rankings?${params.toString()}`);
        if (!res.ok) throw new Error('Falha ao carregar ranking');
        const data = await res.json();
        RankingState.lastData = data;

        const meta = data.metric_meta || RankingState.statMap[metric] || { label: metric, decimals: 2, unit: '', per90: true, description: '', source_label: '' };
        const isP90 = data.effective_mode === 'p90';
        const effUnit = isP90 ? (meta.unit ? `${meta.unit}/90` : '/90') : (meta.unit || '');
        const effDec = isP90 ? Math.max(meta.decimals || 0, 2) : (meta.decimals || 0);

        // 1. Atualiza barra descritiva
        const metaBar = document.getElementById('ranking-meta-bar');
        if (metaBar) {
            metaBar.innerHTML = `
                <div>
                    <strong style="color: var(--accent-emerald);">${meta.label}</strong>
                    <span style="margin-left: 0.5rem;">${meta.description || ''}</span>
                </div>
                <div>
                    Amostra elegível: <strong>${data.eligible_players ?? data.total}</strong> atletas (mín. ${minMinutes}')
                </div>
            `;
        }

        // 2. Renderiza Benchmarks Posicionais
        renderRankingBenchmarks(data, effDec, effUnit);

        if (!data.rankings || data.rankings.length === 0) {
            renderEmptyRankingChart('Nenhum atleta atingiu os critérios selecionados.');
            tableBody.innerHTML = '<tr><td colspan="9" style="text-align: center;">Nenhum atleta atingiu a minutagem mínima neste recorte.</td></tr>';
            return;
        }

        // 3. Renderiza Gráfico Horizontal de Líderes
        renderRankingBarChart(data.rankings, meta, isP90, effDec, effUnit, minMinutes);

        // 4. Renderiza Tabela Analítica
        tableBody.innerHTML = data.rankings.map(r => {
            const medal = r.rank === 1 ? '🥇' : r.rank === 2 ? '🥈' : r.rank === 3 ? '🥉' : `#${r.rank}`;
            const rawTxt = fmtRankVal(r.raw_value, meta.decimals || 0, meta.unit || '');
            const p90Txt = meta.per90 && r.p90_value !== null
                ? fmtRankVal(r.p90_value, Math.max(meta.decimals || 0, 2), meta.unit ? `${meta.unit}/90` : '/90')
                : '—';
            const sampleTxt = `${r.season_used || ''} • ${r.minutes_played}'`;

            return `
                <tr style="cursor: pointer;" onclick="openPlayerDossier('${r.mapping_id}', ${minMinutes})">
                    <td style="font-weight: 700;">${medal}</td>
                    <td>
                        <div style="font-weight: 700; color: #fff;">${r.name}</div>
                        ${r.age ? `<div style="font-size: 0.74rem; color: var(--text-muted);">${r.age} anos</div>` : ''}
                    </td>
                    <td><span class="role-badge role-${r.scout_role}">${r.scout_role}</span></td>
                    <td>
                        <div>🛡️ ${r.current_team}</div>
                        <div style="font-size: 0.74rem; color: var(--text-muted);">${r.current_league || ''}</div>
                    </td>
                    <td style="font-size: 0.8rem; color: var(--text-secondary);">${sampleTxt}</td>
                    <td style="${!isP90 ? 'color: var(--accent-emerald); font-weight: 700;' : ''}">${rawTxt}</td>
                    <td style="${isP90 ? 'color: var(--accent-cyan); font-weight: 700;' : 'color: var(--text-muted);'}">${p90Txt}</td>
                    <td style="color: var(--accent-gold); font-weight: 600; font-size: 0.83rem;">${r.market_value_raw || 'N/A'}</td>
                    <td>
                        <div style="display: flex; align-items: center; gap: 0.5rem;">
                            <div class="percentile-progress" style="width: 80px;">
                                <div class="percentile-fill" style="width: ${r.percentile || 0}%;"></div>
                            </div>
                            <span>${r.percentile !== null && r.percentile !== undefined ? r.percentile.toFixed(1) + '%' : 'N/A'}</span>
                        </div>
                    </td>
                </tr>
            `;
        }).join('');

    } catch (e) {
        console.error('Erro ao consultar ranking:', e);
        tableBody.innerHTML = '<tr><td colspan="9" style="text-align: center; color: var(--accent-rose);">Erro ao consultar ranking.</td></tr>';
    }
}

function renderRankingBarChart(items, meta, isP90, effDec, effUnit, minMinutes) {
    const canvas = document.getElementById('ranking-bar-canvas');
    const wrap = document.getElementById('ranking-chart-wrap');
    const titleEl = document.getElementById('ranking-chart-title');
    if (!canvas || !wrap) return;

    if (titleEl) {
        titleEl.textContent = `📊 Top ${items.length} em ${meta.label} (${isP90 ? "Por 90'" : 'Total / Taxa'})`;
    }

    const dynamicHeight = Math.max(300, items.length * 28 + 60);
    wrap.style.height = `${dynamicHeight}px`;

    if (RankingState.barChart) {
        RankingState.barChart.destroy();
    }

    const labels = items.map(r => `#${r.rank} ${r.name} (${r.current_team})`);
    const values = items.map(r => (r.ranked_value !== undefined && r.ranked_value !== null)
        ? r.ranked_value
        : (isP90 ? r.p90_value : r.raw_value));

    const ctx = canvas.getContext('2d');
    RankingState.barChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels,
            datasets: [{
                label: meta.label,
                data: values,
                backgroundColor: items.map((_, i) => i < 3 ? 'rgba(16, 185, 129, 0.78)' : 'rgba(6, 182, 212, 0.52)'),
                borderColor: items.map((_, i) => i < 3 ? '#10b981' : '#06b6d4'),
                borderWidth: 1.5,
                borderRadius: 5,
            }],
        },
        options: {
            indexAxis: 'y',
            responsive: true,
            maintainAspectRatio: false,
            onClick: (_, elements) => {
                if (elements && elements.length > 0) {
                    const idx = elements[0].index;
                    const target = items[idx];
                    if (target) openPlayerDossier(String(target.mapping_id), minMinutes);
                }
            },
            scales: {
                x: {
                    grid: { color: 'rgba(255, 255, 255, 0.06)' },
                    ticks: { color: '#94a3b8', font: { size: 11 } },
                },
                y: {
                    grid: { display: false },
                    ticks: { color: '#f8fafc', font: { size: 11, weight: 600 } },
                },
            },
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: (ctx) => {
                            const r = items[ctx.dataIndex];
                            const lines = [
                                `${isP90 ? "Por 90'" : 'Valor'}: ${fmtRankVal(ctx.raw, effDec, effUnit)}`,
                            ];
                            if (isP90 && r.raw_value !== null) {
                                lines.push(`Total no recorte: ${fmtRankVal(r.raw_value, meta.decimals || 0, meta.unit || '')}`);
                            } else if (!isP90 && meta.per90 && r.p90_value !== null) {
                                lines.push(`Por 90': ${fmtRankVal(r.p90_value, Math.max(meta.decimals || 0, 2))}/90`);
                            }
                            lines.push(`Amostra: ${r.minutes_played}' (${r.season_used || 'N/A'}) • Percentil: ${r.percentile ?? 'N/A'}%`);
                            return lines;
                        },
                    },
                },
            },
        },
    });
}

function renderEmptyRankingChart(msg) {
    const canvas = document.getElementById('ranking-bar-canvas');
    const wrap = document.getElementById('ranking-chart-wrap');
    if (!canvas || !wrap) return;
    wrap.style.height = '140px';
    if (RankingState.barChart) RankingState.barChart.destroy();
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.font = "14px 'Inter', sans-serif";
    ctx.fillStyle = '#64748b';
    ctx.textAlign = 'center';
    ctx.fillText(msg, canvas.width / 2, canvas.height / 2);
}

function renderRankingBenchmarks(data, effDec, effUnit) {
    const box = document.getElementById('ranking-benchmarks');
    if (!box || !data) return;

    const list = RankingState.benchMode === 'role'
        ? (data.benchmarks_by_role || [])
        : (data.benchmarks_by_category || []);

    if (!list.length) {
        box.innerHTML = '<div style="color: var(--text-muted); font-size: 0.84rem;">Sem amostra suficiente para calcular referências posicionais.</div>';
        return;
    }

    box.innerHTML = list.map(b => `
        <div class="rk-bench-card">
            <div class="rk-bench-title">
                <span>${b.label}</span>
                <span class="rk-bench-count">${b.count} atletas</span>
            </div>
            <div class="rk-bench-metrics">
                <div class="rk-bench-item">
                    <div class="rk-bench-label">Média</div>
                    <div class="rk-bench-val">${fmtRankVal(b.mean, effDec, effUnit)}</div>
                </div>
                <div class="rk-bench-item">
                    <div class="rk-bench-label">Mediana (50%)</div>
                    <div class="rk-bench-val">${fmtRankVal(b.median, effDec, effUnit)}</div>
                </div>
                <div class="rk-bench-item">
                    <div class="rk-bench-label">Máximo</div>
                    <div class="rk-bench-val" style="color: var(--accent-emerald);">${fmtRankVal(b.max, effDec, effUnit)}</div>
                </div>
                <div class="rk-bench-item">
                    <div class="rk-bench-label">Mínimo</div>
                    <div class="rk-bench-val" style="color: var(--text-secondary);">${fmtRankVal(b.min, effDec, effUnit)}</div>
                </div>
            </div>
        </div>
    `).join('');
}

// Vincula controles de Rankings & Líderes
document.addEventListener('DOMContentLoaded', () => {
    const searchInput = document.getElementById('ranking-metric-search');
    if (searchInput) {
        searchInput.addEventListener('input', async () => {
            await ensureRankingCatalog();
            const changed = populateRankingMetricOptions(searchInput.value);
            if (changed) {
                syncRankingModeAvailability();
                loadRankings();
            }
        });
    }

    ['ranking-metric', 'ranking-mode', 'ranking-order', 'ranking-role', 'ranking-league', 'ranking-season', 'ranking-limit'].forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.addEventListener('change', () => {
                if (id === 'ranking-mode') RankingState.preferredMode = el.value;
                if (id === 'ranking-metric') syncRankingModeAvailability();
                loadRankings();
            });
        }
    });

    const minInput = document.getElementById('ranking-min-minutes');
    if (minInput) {
        minInput.addEventListener('input', () => {
            clearTimeout(RankingState.debounceTimer);
            RankingState.debounceTimer = setTimeout(loadRankings, 300);
        });
    }

    document.querySelectorAll('#ranking-bench-toggle .ex-mode-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            RankingState.benchMode = btn.dataset.bench;
            document.querySelectorAll('#ranking-bench-toggle .ex-mode-btn').forEach(b => b.classList.toggle('active', b === btn));
            if (RankingState.lastData) {
                const meta = RankingState.lastData.metric_meta || { decimals: 2, unit: '' };
                const isP90 = RankingState.lastData.effective_mode === 'p90';
                const effUnit = isP90 ? (meta.unit ? `${meta.unit}/90` : '/90') : (meta.unit || '');
                const effDec = isP90 ? Math.max(meta.decimals || 0, 2) : (meta.decimals || 0);
                renderRankingBenchmarks(RankingState.lastData, effDec, effUnit);
            }
        });
    });
});
