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
    setupFilters();
    await loadMetadata();
    await loadPlayers();
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
// RAIO-X & RADAR DE SCOUTING (TAB 2)
// =============================================================================
async function openPlayerDossier(playerId) {
    State.selectedPlayerId = playerId;
    switchTab('dossier');

    const heroContainer = document.getElementById('dossier-hero');
    const tableContainer = document.getElementById('radar-table-body');
    const strengthsEl = document.getElementById('traits-strengths');
    const weaknessesEl = document.getElementById('traits-weaknesses');
    const stylesEl = document.getElementById('traits-styles');
    const similarEl = document.getElementById('similar-list');

    try {
        // 1. Busca perfil cadastral
        const resProf = await fetch(`${API_BASE}/players/${playerId}`);
        if (!resProf.ok) throw new Error('Perfil não encontrado');
        const prof = await resProf.json();

        // 2. Renderiza Hero
        const initials = prof.name.split(' ').map(n => n[0]).slice(0, 2).join('');
        heroContainer.innerHTML = `
            <div class="dossier-hero-left">
                <div class="dossier-avatar-large">${initials}</div>
                <div>
                    <h1 class="dossier-name">${prof.name}</h1>
                    <div class="dossier-subtitle">
                        <span class="role-badge role-${prof.scout_role}">${prof.scout_role}</span>
                        <span>🛡️ ${prof.current_team || 'N/A'}</span>
                        <span>•</span>
                        <span>${prof.current_league || 'N/A'}</span>
                        ${prof.birth_date ? `<span>• 📅 ${prof.birth_date}</span>` : ''}
                    </div>
                    <div class="external-links">
                        ${prof.transfermarkt_url ? `<a href="${prof.transfermarkt_url}" target="_blank" class="link-chip">Transfermarkt ↗</a>` : ''}
                        ${prof.whoscored_url ? `<a href="${prof.whoscored_url}" target="_blank" class="link-chip">WhoScored ↗</a>` : ''}
                    </div>
                </div>
            </div>
            <div class="dossier-hero-right">
                <div class="dossier-value-box">
                    <div class="dossier-value-label">Valor de Mercado Atual</div>
                    <div class="dossier-value-amount">${prof.market_value_raw || 'Sob Consulta'}</div>
                </div>
            </div>
        `;

        // 3. Renderiza Características Qualitativas (WhoScored / SofaScore)
        strengthsEl.innerHTML = renderTraits(prof.player_strengths, 'strength', 'Nenhum ponto forte registrado');
        weaknessesEl.innerHTML = renderTraits(prof.player_weaknesses, 'weakness', 'Nenhum ponto fraco registrado');
        stylesEl.innerHTML = renderStyles(prof.player_style_of_play, prof.team_style);

        // 4. Busca Dossiê Analítico (Radar & P90)
        try {
            const resDossier = await fetch(`${API_BASE}/players/${playerId}/dossier`);
            if (resDossier.ok) {
                const dossierData = await resDossier.json();
                renderRadarChart(dossierData.radar, prof.name);
                renderRadarTable(dossierData.radar, tableContainer);
            } else {
                renderEmptyRadar("Amostra estatística mínima ainda não atingida para radar.");
                if (tableContainer) tableContainer.innerHTML = '<tr><td colspan="4" style="text-align:center;">Sem dados de temporada no recorte.</td></tr>';
            }
        } catch (e) {
            renderEmptyRadar("Erro ao calcular radar de percentis.");
        }

        // 5. Busca Atletas Similares
        try {
            const resSim = await fetch(`${API_BASE}/players/${playerId}/similar?top_n=4`);
            if (resSim.ok) {
                const simData = await resSim.json();
                renderSimilarPlayers(simData.similar_players, similarEl);
            }
        } catch (e) {
            if (similarEl) similarEl.innerHTML = '<p class="text-muted">Aguardando dados adicionais.</p>';
        }

    } catch (e) {
        console.error('Erro ao abrir dossiê:', e);
    }
}

function renderTraits(traits, type, emptyMsg) {
    if (!traits || traits.length === 0) {
        return `<span style="color: var(--text-muted); font-size: 0.85rem;">${emptyMsg}</span>`;
    }
    const cls = type === 'strength' ? 'trait-strength' : 'trait-weakness';
    const icon = type === 'strength' ? '▲' : '▼';
    return traits.map(t => {
        const name = typeof t === 'object' ? `${t.name} (${t.level || ''})` : t;
        return `<span class="trait-tag ${cls}">${icon} ${name}</span>`;
    }).join('');
}

function renderStyles(playerStyle, teamStyle) {
    let html = '';
    if (playerStyle && playerStyle.length > 0) {
        html += playerStyle.map(s => `<span class="trait-tag trait-style">👤 ${s}</span>`).join('');
    }
    if (teamStyle && teamStyle.length > 0) {
        html += teamStyle.map(s => `<span class="trait-tag trait-style">🛡️ Clube: ${s}</span>`).join('');
    }
    return html || '<span style="color: var(--text-muted); font-size: 0.85rem;">Estilo não catalogado</span>';
}

function renderSimilarPlayers(similars, container) {
    if (!container) return;
    if (!similars || similars.length === 0) {
        container.innerHTML = '<p style="color: var(--text-muted); font-size: 0.85rem;">Nenhum atleta similar identificado com a minutagem atual.</p>';
        return;
    }
    container.innerHTML = similars.map(sim => `
        <div class="similar-item" onclick="openPlayerDossier('${sim.mapping_id}')">
            <div>
                <strong>${sim.player_name}</strong>
                <div style="font-size: 0.78rem; color: var(--text-muted);">
                    🛡️ ${sim.current_team} • ${sim.market_value_raw}
                </div>
            </div>
            <span class="similar-score">${sim.similarity_pct}%</span>
        </div>
    `).join('');
}

function renderRadarChart(radarItems, playerName) {
    const canvas = document.getElementById('radar-canvas');
    if (!canvas) return;

    if (State.radarChart) {
        State.radarChart.destroy();
    }

    const labels = radarItems.map(i => i.label);
    const percentiles = radarItems.map(i => i.percentile || 0);

    const ctx = canvas.getContext('2d');
    State.radarChart = new Chart(ctx, {
        type: 'radar',
        data: {
            labels: labels,
            datasets: [{
                label: `Percentis: ${playerName}`,
                data: percentiles,
                backgroundColor: 'rgba(16, 185, 129, 0.25)',
                borderColor: '#10b981',
                borderWidth: 2.5,
                pointBackgroundColor: '#06b6d4',
                pointBorderColor: '#fff',
                pointHoverRadius: 6,
                pointRadius: 4,
            }]
        },
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
                        font: { size: 11, family: "'Inter', sans-serif", weight: 600 },
                    }
                }
            },
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: (ctx) => {
                            const item = radarItems[ctx.dataIndex];
                            return [
                                `Percentil: ${ctx.raw.toFixed(1)}%`,
                                `Valor P90: ${item.p90_value !== null ? item.p90_value : 'N/A'}`,
                                `Valor Bruto: ${item.raw_value !== null ? item.raw_value : 'N/A'}`,
                            ];
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

function renderRadarTable(items, container) {
    if (!container) return;
    container.innerHTML = items.map(item => `
        <tr>
            <td style="font-weight: 600;">${item.label}</td>
            <td>${item.raw_value !== null ? item.raw_value : 'N/A'}</td>
            <td>${item.p90_value !== null ? item.p90_value : 'N/A'}</td>
            <td>
                <div style="display: flex; align-items: center; gap: 0.5rem;">
                    <div class="percentile-progress">
                        <div class="percentile-fill" style="width: ${item.percentile || 0}%;"></div>
                    </div>
                    <span style="font-weight: 700; font-size: 0.8rem; width: 45px;">${item.percentile ? item.percentile.toFixed(1) + '%' : 'N/A'}</span>
                </div>
            </td>
        </tr>
    `).join('');
}

// =============================================================================
// RANKINGS & LÍDERES (TAB 4)
// =============================================================================
async function loadRankings() {
    const tableBody = document.getElementById('rankings-table-body');
    const metricSelect = document.getElementById('ranking-metric');
    const roleSelect = document.getElementById('ranking-role');
    if (!tableBody) return;

    const metric = metricSelect ? metricSelect.value : 'goals';
    const role = roleSelect ? roleSelect.value : '';

    tableBody.innerHTML = '<tr><td colspan="7" style="text-align: center;">Carregando ranking...</td></tr>';

    const params = new URLSearchParams({ metric: metric, limit: '25' });
    if (role) params.append('role', role);

    try {
        const res = await fetch(`${API_BASE}/analytics/rankings?${params.toString()}`);
        if (!res.ok) throw new Error('Falha ao carregar ranking');
        const data = await res.json();

        if (data.rankings.length === 0) {
            tableBody.innerHTML = '<tr><td colspan="7" style="text-align: center;">Nenhum atleta atingiu a minutagem mínima no recorte.</td></tr>';
            return;
        }

        tableBody.innerHTML = data.rankings.map(r => {
            const medal = r.rank === 1 ? '🥇 ' : r.rank === 2 ? '🥈 ' : r.rank === 3 ? '🥉 ' : `#${r.rank}`;
            return `
                <tr style="cursor: pointer;" onclick="openPlayerDossier('${r.mapping_id}')">
                    <td style="font-weight: 700;">${medal}</td>
                    <td style="font-weight: 700; color: #fff;">${r.name}</td>
                    <td><span class="role-badge role-${r.scout_role}">${r.scout_role}</span></td>
                    <td>🛡️ ${r.current_team}</td>
                    <td>${r.raw_value !== null ? r.raw_value : 'N/A'}</td>
                    <td style="color: var(--accent-cyan); font-weight: 700;">${r.p90_value !== null ? r.p90_value : 'N/A'}</td>
                    <td>
                        <div style="display: flex; align-items: center; gap: 0.5rem;">
                            <div class="percentile-progress" style="width: 80px;">
                                <div class="percentile-fill" style="width: ${r.percentile || 0}%;"></div>
                            </div>
                            <span>${r.percentile ? r.percentile.toFixed(1) + '%' : 'N/A'}</span>
                        </div>
                    </td>
                </tr>
            `;
        }).join('');

    } catch (e) {
        tableBody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: var(--accent-rose);">Erro ao consultar ranking.</td></tr>';
    }
}

// Vincula selects de ranking
document.addEventListener('DOMContentLoaded', () => {
    const metricSelect = document.getElementById('ranking-metric');
    const roleSelect = document.getElementById('ranking-role');
    if (metricSelect) metricSelect.addEventListener('change', loadRankings);
    if (roleSelect) roleSelect.addEventListener('change', loadRankings);
});
