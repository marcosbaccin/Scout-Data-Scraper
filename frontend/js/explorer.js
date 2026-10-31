/**
 * SCOUT DATA INTELLIGENCE - EXPLORADOR CONFIGURÁVEL (143+ ESTATÍSTICAS)
 *
 * Inspirado na Plataforma de Scout do Scout-Brazil-Serie-A:
 * - Configuração de intervalos (mínimo e máximo) em TODAS as estatísticas coletadas nas 4 fontes.
 * - Três modos por estatística: Total no recorte, Por 90' (/90) e Percentil posicional (0–100%).
 * - Filtros completos de Recorte (temporadas, competições, minutagem) e Identificação
 *   (nome, função, posição, pé, idade, valor de mercado, altura, peso, liga, clube, características).
 * - Perfis táticos prontos + salvamento de perfis personalizados no navegador (localStorage).
 * - Cards paginados com expansão inline de "Visualizar ficha completa", atalho para "Raio-X & Radar" e exportação CSV.
 */

(function () {
    const EX_API = window.location.origin.includes('5500') || window.location.origin.includes('file://')
        ? 'http://localhost:8000'
        : window.location.origin;

    const SAVED_PROFILES_KEY = 'scout_explorer_saved_profiles_v1';

    const Ex = {
        schema: null,
        statMap: {},
        bounds: {},
        playersInScope: 0,

        scope: {
            season_mode: 'latest',
            seasons: [],
            competitions: [],
            min_minutes: 450,
        },

        identity: {
            name: '',
            roles: [],
            positions: [],
            leagues: [],
            teams: [],
            foot: [],
            age_min: null,
            age_max: null,
            height_min: null,
            height_max: null,
            weight_min: null,
            weight_max: null,
            value_min: null, // EUR
            value_max: null, // EUR
            strengths: [],
            exclude_weaknesses: [],
            require_sources: [],
        },

        // key -> { mode: 'total'|'p90'|'pct', min: number|null, max: number|null }
        stats: {},

        sortBy: '',
        sortDir: 'desc',
        page: 1,
        pageSize: 10,

        openSheets: {},   // sofascore_id -> sheet data | 'loading'
        statWidgets: {},  // key -> DOM refs & updater
        idWidgets: {},    // demographic range slider updaters
        multiWidgets: {}, // multi-select updaters

        searchTimer: null,
        boundsTimer: null,
        allExpanded: false,
    };

    // =========================================================================
    // UTILITÁRIOS
    // =========================================================================
    function fold(str) {
        return String(str || '')
            .normalize('NFD')
            .replace(/[\u0300-\u036f]/g, '')
            .toLowerCase()
            .trim();
    }

    function esc(str) {
        return String(str ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function roundStep(val, step) {
        if (!Number.isFinite(val)) return val;
        const s = step && step > 0 ? step : 0.01;
        const decimals = (String(s).split('.')[1] || '').length;
        const snapped = Math.round(val / s) * s;
        return Number(snapped.toFixed(Math.min(decimals + 1, 4)));
    }

    function fmtNum(val, decimals = 0, unit = '') {
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

    function fmtMetric(statDef, mode, val) {
        if (val === null || val === undefined) return '—';
        if (mode === 'pct') return `P${Math.round(Number(val))}`;
        if (mode === 'p90') return fmtNum(val, Math.max(statDef.decimals, 2), statDef.unit ? `${statDef.unit}/90` : '/90');
        return fmtNum(val, statDef.decimals, statDef.unit);
    }

    function modeLabel(mode) {
        if (mode === 'p90') return "/90'";
        if (mode === 'pct') return 'Pct';
        return 'Total';
    }

    function isAutoSearch() {
        const el = document.getElementById('ex-auto-search');
        return !el || el.checked;
    }

    function scheduleSearch(immediate = false) {
        Ex.page = 1;
        updateActiveBadgesAndChips();
        applyStatVisibilityFilter();
        if (!immediate && !isAutoSearch()) return;
        clearTimeout(Ex.searchTimer);
        Ex.searchTimer = setTimeout(runSearch, immediate ? 0 : 240);
    }

    function scheduleScopeRefresh(immediate = false) {
        Ex.page = 1;
        Ex.openSheets = {};
        clearTimeout(Ex.boundsTimer);
        Ex.boundsTimer = setTimeout(async () => {
            await loadBounds();
            if (immediate || isAutoSearch()) {
                await runSearch();
            }
        }, immediate ? 0 : 280);
    }

    // =========================================================================
    // INICIALIZAÇÃO
    // =========================================================================
    document.addEventListener('DOMContentLoaded', initExplorer);

    async function initExplorer() {
        const root = document.getElementById('ex-stats');
        if (!root) return;

        bindGlobalButtons();

        try {
            const res = await fetch(`${EX_API}/explorer/schema`);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            Ex.schema = await res.json();

            Ex.schema.stats.forEach(s => {
                Ex.statMap[s.key] = s;
                Ex.stats[s.key] = { mode: 'total', min: null, max: null };
            });

            renderTopMeta();
            renderProfilesSelect();
            renderScopeSection();
            renderIdentitySection();
            renderSortSelect();
            renderStatsAccordions();

            await loadBounds();
            await runSearch();
        } catch (err) {
            console.error('Erro ao inicializar Explorador:', err);
            const resEl = document.getElementById('ex-results');
            if (resEl) {
                resEl.innerHTML = `
                    <div class="empty-state">
                        <div class="empty-icon">⚠️</div>
                        <h3>Falha ao inicializar o Explorador</h3>
                        <p>Verifique se o servidor FastAPI está em execução (<code>python main.py dashboard</code>).</p>
                    </div>
                `;
            }
        }
    }

    function renderTopMeta() {
        const el = document.getElementById('ex-meta-caption');
        if (!el || !Ex.schema) return;
        el.innerHTML = `
            📅 Dados atualizados em: <strong>${esc(Ex.schema.data_updated_at)}</strong>
            &nbsp;•&nbsp; <strong>${Ex.schema.total_players}</strong> atletas brasileiros monitorados
            &nbsp;•&nbsp; <strong>${Ex.schema.stats.length}</strong> estatísticas configuráveis nas 4 fontes
        `;
    }

    function bindGlobalButtons() {
        // Como Usar toggle
        const aboutBtn = document.getElementById('ex-about-btn');
        const aboutBox = document.getElementById('ex-about-box');
        if (aboutBtn && aboutBox) {
            aboutBtn.addEventListener('click', () => {
                const open = aboutBox.hasAttribute('hidden');
                if (open) aboutBox.removeAttribute('hidden');
                else aboutBox.setAttribute('hidden', '');
                aboutBtn.setAttribute('aria-expanded', String(open));
            });
        }

        // Executar Pesquisa
        document.getElementById('ex-run-search')?.addEventListener('click', () => {
            Ex.page = 1;
            runSearch();
        });

        // Limpar tudo
        document.getElementById('ex-clear')?.addEventListener('click', resetAllFilters);

        // Expandir / Recolher todas as categorias de estatística
        const toggleAllBtn = document.getElementById('ex-toggle-all');
        if (toggleAllBtn) {
            toggleAllBtn.addEventListener('click', () => {
                Ex.allExpanded = !Ex.allExpanded;
                document.querySelectorAll('#ex-stats details.ex-section').forEach(d => {
                    if (!d.hidden) d.open = Ex.allExpanded;
                });
                toggleAllBtn.textContent = Ex.allExpanded ? 'Recolher todas' : 'Expandir todas';
            });
        }

        // Busca textual de estatísticas e toggle "Só ativos"
        document.getElementById('ex-stat-search')?.addEventListener('input', applyStatVisibilityFilter);
        document.getElementById('ex-only-active')?.addEventListener('change', applyStatVisibilityFilter);

        // Ordenação e paginação
        document.getElementById('ex-sort')?.addEventListener('change', (e) => {
            Ex.sortBy = e.target.value;
            Ex.page = 1;
            runSearch();
        });

        const sortDirBtn = document.getElementById('ex-sort-dir');
        if (sortDirBtn) {
            sortDirBtn.addEventListener('click', () => {
                Ex.sortDir = Ex.sortDir === 'desc' ? 'asc' : 'desc';
                sortDirBtn.textContent = Ex.sortDir === 'desc' ? '↓ Maior' : '↑ Menor';
                Ex.page = 1;
                runSearch();
            });
        }

        document.getElementById('ex-page-size')?.addEventListener('change', (e) => {
            Ex.pageSize = Number(e.target.value) || 10;
            Ex.page = 1;
            runSearch();
        });

        // Exportar CSV
        document.getElementById('ex-export')?.addEventListener('click', exportCsv);

        // Perfis prontos e salvos
        document.getElementById('ex-profile-select')?.addEventListener('change', updateProfileDescription);
        document.getElementById('ex-profile-apply')?.addEventListener('click', applySelectedProfile);
        document.getElementById('ex-profile-save')?.addEventListener('click', saveCurrentProfile);
        document.getElementById('ex-profile-delete')?.addEventListener('click', deleteSelectedProfile);

        // Mobile Drawer
        const openDrawer = () => {
            document.getElementById('ex-panel')?.classList.add('is-open');
            document.getElementById('ex-backdrop')?.removeAttribute('hidden');
        };
        const closeDrawer = () => {
            document.getElementById('ex-panel')?.classList.remove('is-open');
            document.getElementById('ex-backdrop')?.setAttribute('hidden', '');
        };
        document.getElementById('ex-panel-open')?.addEventListener('click', openDrawer);
        document.getElementById('ex-panel-close')?.addEventListener('click', closeDrawer);
        document.getElementById('ex-backdrop')?.addEventListener('click', closeDrawer);
        document.getElementById('ex-panel-apply')?.addEventListener('click', () => {
            closeDrawer();
            Ex.page = 1;
            runSearch();
        });
    }

    // =========================================================================
    // PERFIS PRONTOS & PERFIS SALVOS (localStorage)
    // =========================================================================
    function loadSavedProfiles() {
        try {
            return JSON.parse(localStorage.getItem(SAVED_PROFILES_KEY) || '[]');
        } catch (_) {
            return [];
        }
    }

    function persistSavedProfiles(list) {
        localStorage.setItem(SAVED_PROFILES_KEY, JSON.stringify(list));
    }

    function renderProfilesSelect(selectedValue = '') {
        const sel = document.getElementById('ex-profile-select');
        if (!sel || !Ex.schema) return;

        const saved = loadSavedProfiles();
        let html = '<option value="">— Escolha um perfil tático —</option>';

        if (saved.length > 0) {
            html += '<optgroup label="⭐ Meus Perfis Salvos">';
            saved.forEach(p => {
                html += `<option value="saved:${esc(p.id)}">${esc(p.name)}</option>`;
            });
            html += '</optgroup>';
        }

        html += '<optgroup label="⚽ Perfis Táticos Prontos">';
        Ex.schema.presets.forEach(p => {
            html += `<option value="preset:${esc(p.id)}">${esc(p.name)}</option>`;
        });
        html += '</optgroup>';

        sel.innerHTML = html;
        sel.value = selectedValue;
        updateProfileDescription();
    }

    function getSelectedProfileObject() {
        const val = document.getElementById('ex-profile-select')?.value || '';
        if (!val) return null;
        if (val.startsWith('preset:')) {
            const id = val.slice(7);
            const p = Ex.schema.presets.find(x => x.id === id);
            return p ? { type: 'preset', profile: p } : null;
        }
        if (val.startsWith('saved:')) {
            const id = val.slice(6);
            const p = loadSavedProfiles().find(x => x.id === id);
            return p ? { type: 'saved', profile: p } : null;
        }
        return null;
    }

    function updateProfileDescription() {
        const descEl = document.getElementById('ex-profile-desc');
        const delBtn = document.getElementById('ex-profile-delete');
        const found = getSelectedProfileObject();
        if (descEl) {
            descEl.textContent = found ? (found.profile.description || '') : '';
        }
        if (delBtn) {
            delBtn.disabled = !found || found.type !== 'saved';
        }
    }

    async function applySelectedProfile() {
        const found = getSelectedProfileObject();
        if (!found) return;
        const p = found.profile;

        // Reseta filtros atuais preservando ou aplicando scope se salvo
        clearStateOnly();
        if (p.scope) {
            Object.assign(Ex.scope, p.scope);
        }
        if (p.identity) {
            Object.keys(Ex.identity).forEach(k => {
                if (p.identity[k] !== undefined) {
                    Ex.identity[k] = Array.isArray(p.identity[k]) ? [...p.identity[k]] : p.identity[k];
                }
            });
        }
        if (Array.isArray(p.stats)) {
            p.stats.forEach(sf => {
                if (Ex.stats[sf.key]) {
                    Ex.stats[sf.key] = {
                        mode: sf.mode || 'total',
                        min: sf.min ?? null,
                        max: sf.max ?? null,
                    };
                }
            });
        }

        syncAllControlsFromState();
        await loadBounds();
        syncAllStatWidgets();
        updateActiveBadgesAndChips();
        Ex.page = 1;
        await runSearch();
    }

    function saveCurrentProfile() {
        const activeStats = getActiveStatsPayload();
        const name = window.prompt('Nome para salvar este perfil de busca (ex: "Volante Construtor Sub-23"):', '');
        if (!name || !name.trim()) return;

        const saved = loadSavedProfiles();
        const id = 'u_' + Date.now();
        saved.unshift({
            id,
            name: name.trim(),
            description: `${activeStats.length} filtro(s) estatístico(s) • Min. ${Ex.scope.min_minutes}'`,
            scope: JSON.parse(JSON.stringify(Ex.scope)),
            identity: JSON.parse(JSON.stringify(Ex.identity)),
            stats: activeStats,
        });
        persistSavedProfiles(saved);
        renderProfilesSelect(`saved:${id}`);
    }

    function deleteSelectedProfile() {
        const found = getSelectedProfileObject();
        if (!found || found.type !== 'saved') return;
        const saved = loadSavedProfiles().filter(x => x.id !== found.profile.id);
        persistSavedProfiles(saved);
        renderProfilesSelect('');
    }

    // =========================================================================
    // SEÇÃO 1: RECORTE ESTATÍSTICO
    // =========================================================================
    function renderScopeSection() {
        const box = document.getElementById('ex-scope');
        if (!box) return;

        box.innerHTML = `
            <div class="ex-field">
                <label class="filter-label" for="ex-season-mode">Modo de Temporada</label>
                <select id="ex-season-mode" class="filter-select">
                    <option value="latest" selected>Última temporada com amostra mínima</option>
                    <option value="selected">Temporadas específicas selecionadas</option>
                    <option value="all">Carreira completa agregada</option>
                </select>
            </div>

            <div id="ex-seasons-wrap" class="ex-field" hidden>
                <label class="filter-label">Escolher Temporadas</label>
                <div id="ex-multi-seasons"></div>
            </div>

            <div class="ex-field">
                <div class="ex-field-head">
                    <label class="filter-label" for="ex-min-minutes">Minutagem Mínima no Recorte</label>
                </div>
                <div class="ex-row">
                    <input id="ex-min-minutes" type="number" min="0" step="90" value="450" class="ex-input-sm" style="max-width: 105px;">
                    <div class="ex-pills" id="ex-min-pills">
                        ${[0, 180, 450, 900, 1800].map(m => `
                            <button type="button" class="ex-pill ${m === 450 ? 'active' : ''}" data-min="${m}">${m}'</button>
                        `).join('')}
                    </div>
                </div>
            </div>

            <div class="ex-field">
                <label class="filter-label">Filtrar Competições (opcional)</label>
                <div id="ex-multi-competitions"></div>
            </div>
        `;

        const modeSel = document.getElementById('ex-season-mode');
        const seasonsWrap = document.getElementById('ex-seasons-wrap');
        modeSel.addEventListener('change', () => {
            Ex.scope.season_mode = modeSel.value;
            if (Ex.scope.season_mode === 'selected') {
                seasonsWrap.removeAttribute('hidden');
                if (Ex.scope.seasons.length === 0 && Ex.schema.seasons.length > 0) {
                    // Pré-seleciona as temporadas atuais (Europa + Calendário)
                    const defaults = Ex.schema.seasons.slice(0, 2).map(s => s.value);
                    Ex.scope.seasons = defaults;
                    Ex.multiWidgets.seasons?.refresh();
                }
            } else {
                seasonsWrap.setAttribute('hidden', '');
            }
            scheduleScopeRefresh();
        });

        const minInput = document.getElementById('ex-min-minutes');
        const syncMinPills = () => {
            document.querySelectorAll('#ex-min-pills .ex-pill').forEach(btn => {
                btn.classList.toggle('active', Number(btn.dataset.min) === Ex.scope.min_minutes);
            });
        };
        minInput.addEventListener('input', () => {
            Ex.scope.min_minutes = Math.max(0, Number(minInput.value) || 0);
            syncMinPills();
            scheduleScopeRefresh();
        });
        document.querySelectorAll('#ex-min-pills .ex-pill').forEach(btn => {
            btn.addEventListener('click', () => {
                Ex.scope.min_minutes = Number(btn.dataset.min);
                minInput.value = String(Ex.scope.min_minutes);
                syncMinPills();
                scheduleScopeRefresh(true);
            });
        });

        Ex.multiWidgets.seasons = createMultiSelect({
            container: document.getElementById('ex-multi-seasons'),
            placeholder: 'Filtrar temporadas (ex: 25/26, 2025)...',
            options: Ex.schema.seasons.map(s => ({
                value: s.value,
                label: s.value,
                meta: `${s.players} atl.`,
            })),
            getSelected: () => Ex.scope.seasons,
            onChange: (vals) => {
                Ex.scope.seasons = vals;
                if (Ex.scope.season_mode === 'selected' && vals.length === 0) return;
                scheduleScopeRefresh();
            },
        });

        Ex.multiWidgets.competitions = createMultiSelect({
            container: document.getElementById('ex-multi-competitions'),
            placeholder: 'Buscar competição (Brasileirão, Premier League, Champions)...',
            options: Ex.schema.competitions.map(c => ({
                value: c.value,
                label: c.value,
                meta: `${c.players} atl.`,
            })),
            getSelected: () => Ex.scope.competitions,
            onChange: (vals) => {
                Ex.scope.competitions = vals;
                scheduleScopeRefresh();
            },
        });
    }

    // =========================================================================
    // SEÇÃO 2: DADOS DE IDENTIFICAÇÃO & DEMOGRAFIA
    // =========================================================================
    function renderIdentitySection() {
        const box = document.getElementById('ex-identity');
        if (!box || !Ex.schema) return;

        box.innerHTML = `
            <div class="ex-field">
                <label class="filter-label" for="ex-id-name">Nome do Atleta</label>
                <input id="ex-id-name" type="search" class="ex-input-sm" placeholder="Ex: Vinícius, Estêvão, Pedro, Murillo...">
            </div>

            <div class="ex-field">
                <label class="filter-label">Função Tática (Scout Role)</label>
                <div id="ex-pills-roles" class="ex-pills"></div>
            </div>

            <div class="ex-field">
                <label class="filter-label">Posições Táticas</label>
                <div id="ex-pills-positions" class="ex-pills"></div>
            </div>

            <div class="ex-field">
                <label class="filter-label">Pé Dominante</label>
                <div id="ex-pills-foot" class="ex-pills"></div>
            </div>

            <div id="ex-range-age"></div>
            <div id="ex-range-value"></div>
            <div id="ex-range-height"></div>
            <div id="ex-range-weight"></div>

            <div class="ex-field">
                <label class="filter-label">Liga Atual (11 Ligas Alvo)</label>
                <div id="ex-multi-leagues"></div>
            </div>

            <div class="ex-field">
                <label class="filter-label">Clube Atual</label>
                <div id="ex-multi-teams"></div>
            </div>

            <div class="ex-field">
                <label class="filter-label">Exigir Pontos Fortes</label>
                <div id="ex-multi-strengths"></div>
            </div>

            <div class="ex-field">
                <label class="filter-label">Excluir Pontos Fracos</label>
                <div id="ex-multi-weaknesses"></div>
            </div>
        `;

        // Nome
        const nameInput = document.getElementById('ex-id-name');
        nameInput.addEventListener('input', () => {
            Ex.identity.name = nameInput.value;
            scheduleSearch();
        });

        // Pills: Roles, Positions, Foot, Sources
        Ex.multiWidgets.roles = createPillGroup({
            container: document.getElementById('ex-pills-roles'),
            options: Ex.schema.roles,
            getSelected: () => Ex.identity.roles,
            onChange: (vals) => { Ex.identity.roles = vals; scheduleSearch(); },
        });

        Ex.multiWidgets.positions = createPillGroup({
            container: document.getElementById('ex-pills-positions'),
            options: Ex.schema.positions.map(p => ({ value: p.value, label: p.value, title: p.label })),
            getSelected: () => Ex.identity.positions,
            onChange: (vals) => { Ex.identity.positions = vals; scheduleSearch(); },
        });

        Ex.multiWidgets.foot = createPillGroup({
            container: document.getElementById('ex-pills-foot'),
            options: Ex.schema.feet,
            getSelected: () => Ex.identity.foot,
            onChange: (vals) => { Ex.identity.foot = vals; scheduleSearch(); },
        });

        Ex.multiWidgets.sources = createPillGroup({
            container: document.getElementById('ex-pills-sources'),
            options: Ex.schema.sources,
            getSelected: () => Ex.identity.require_sources,
            onChange: (vals) => { Ex.identity.require_sources = vals; scheduleSearch(); },
        });

        // Demographic Dual Range Sliders
        const ib = Ex.schema.identity_bounds;
        Ex.idWidgets.age = createDemographicRange({
            container: document.getElementById('ex-range-age'),
            label: 'Idade',
            unit: 'anos',
            lo: ib.age.min ?? 16,
            hi: ib.age.max ?? 45,
            step: 1,
            getMin: () => Ex.identity.age_min,
            getMax: () => Ex.identity.age_max,
            setRange: (mn, mx) => { Ex.identity.age_min = mn; Ex.identity.age_max = mx; scheduleSearch(); },
        });

        const maxValMillions = Math.max(10, Math.ceil((ib.value_eur.max || 130000000) / 1e6));
        Ex.idWidgets.value = createDemographicRange({
            container: document.getElementById('ex-range-value'),
            label: 'Valor de Mercado',
            unit: 'M €',
            lo: 0,
            hi: maxValMillions,
            step: 0.5,
            getMin: () => Ex.identity.value_min !== null ? Ex.identity.value_min / 1e6 : null,
            getMax: () => Ex.identity.value_max !== null ? Ex.identity.value_max / 1e6 : null,
            setRange: (mn, mx) => {
                Ex.identity.value_min = mn !== null ? Math.round(mn * 1e6) : null;
                Ex.identity.value_max = mx !== null ? Math.round(mx * 1e6) : null;
                scheduleSearch();
            },
        });

        Ex.idWidgets.height = createDemographicRange({
            container: document.getElementById('ex-range-height'),
            label: 'Altura',
            unit: 'cm',
            lo: ib.height.min ?? 160,
            hi: ib.height.max ?? 205,
            step: 1,
            getMin: () => Ex.identity.height_min,
            getMax: () => Ex.identity.height_max,
            setRange: (mn, mx) => { Ex.identity.height_min = mn; Ex.identity.height_max = mx; scheduleSearch(); },
        });

        Ex.idWidgets.weight = createDemographicRange({
            container: document.getElementById('ex-range-weight'),
            label: 'Peso',
            unit: 'kg',
            lo: ib.weight.min ?? 55,
            hi: ib.weight.max ?? 105,
            step: 1,
            getMin: () => Ex.identity.weight_min,
            getMax: () => Ex.identity.weight_max,
            setRange: (mn, mx) => { Ex.identity.weight_min = mn; Ex.identity.weight_max = mx; scheduleSearch(); },
        });

        // Multi-selects: Leagues, Teams, Strengths, Weaknesses
        Ex.multiWidgets.leagues = createMultiSelect({
            container: document.getElementById('ex-multi-leagues'),
            placeholder: 'Buscar país / liga...',
            options: Ex.schema.leagues.map(l => ({ value: l.value, label: l.label })),
            getSelected: () => Ex.identity.leagues,
            onChange: (vals) => {
                Ex.identity.leagues = vals;
                Ex.multiWidgets.teams?.refresh();
                scheduleSearch();
            },
        });

        Ex.multiWidgets.teams = createMultiSelect({
            container: document.getElementById('ex-multi-teams'),
            placeholder: 'Buscar clube (Flamengo, Real Madrid, Chelsea)...',
            getOptions: () => {
                const lSet = new Set(Ex.identity.leagues);
                return Ex.schema.teams
                    .filter(t => lSet.size === 0 || lSet.has(t.group) || Ex.identity.teams.includes(t.value))
                    .map(t => ({ value: t.value, label: t.value, meta: t.group || '' }));
            },
            getSelected: () => Ex.identity.teams,
            onChange: (vals) => { Ex.identity.teams = vals; scheduleSearch(); },
        });

        Ex.multiWidgets.strengths = createMultiSelect({
            container: document.getElementById('ex-multi-strengths'),
            placeholder: 'Buscar ponto forte (Finalização, Passe, Pressão)...',
            options: Ex.schema.characteristics.map(c => ({ value: c.value, label: c.label })),
            getSelected: () => Ex.identity.strengths,
            onChange: (vals) => { Ex.identity.strengths = vals; scheduleSearch(); },
        });

        Ex.multiWidgets.weaknesses = createMultiSelect({
            container: document.getElementById('ex-multi-weaknesses'),
            placeholder: 'Excluir quem tem ponto fraco em...',
            options: Ex.schema.characteristics.map(c => ({ value: c.value, label: c.label })),
            getSelected: () => Ex.identity.exclude_weaknesses,
            onChange: (vals) => { Ex.identity.exclude_weaknesses = vals; scheduleSearch(); },
        });
    }

    // =========================================================================
    // COMPONENTES REUTILIZÁVEIS DE FILTRO (PILLS, MULTISELECT, DUAL-RANGE)
    // =========================================================================
    function createPillGroup({ container, options, getSelected, onChange }) {
        function render() {
            const sel = new Set(getSelected());
            container.innerHTML = options.map(opt => `
                <button type="button"
                        class="ex-pill ${sel.has(opt.value) ? 'active' : ''}"
                        data-val="${esc(opt.value)}"
                        title="${esc(opt.title || opt.label)}">
                    ${esc(opt.label)}
                </button>
            `).join('');

            container.querySelectorAll('.ex-pill').forEach(btn => {
                btn.addEventListener('click', () => {
                    const v = btn.dataset.val;
                    const curr = new Set(getSelected());
                    if (curr.has(v)) curr.delete(v);
                    else curr.add(v);
                    onChange(Array.from(curr));
                    render();
                });
            });
        }
        render();
        return { refresh: render };
    }

    function createMultiSelect({ container, placeholder, options, getOptions, getSelected, onChange }) {
        container.innerHTML = `
            <div class="ex-multi">
                <input type="search" class="ex-multi-search" placeholder="${esc(placeholder)}">
                <div class="ex-multi-list"></div>
            </div>
        `;
        const searchEl = container.querySelector('.ex-multi-search');
        const listEl = container.querySelector('.ex-multi-list');

        function renderList() {
            const q = fold(searchEl.value);
            const sel = new Set(getSelected());
            const allOpts = getOptions ? getOptions() : options;
            // Mostra selecionados no topo
            const filtered = allOpts
                .filter(o => !q || fold(o.label + ' ' + (o.meta || '')).includes(q))
                .sort((a, b) => Number(sel.has(b.value)) - Number(sel.has(a.value)));

            if (filtered.length === 0) {
                listEl.innerHTML = '<div style="padding:0.35rem 0.5rem; font-size:0.74rem; color:var(--text-muted);">Nenhuma opção encontrada.</div>';
                return;
            }

            listEl.innerHTML = filtered.map(o => `
                <label class="ex-multi-opt">
                    <span class="ex-multi-opt-left">
                        <input type="checkbox" value="${esc(o.value)}" ${sel.has(o.value) ? 'checked' : ''}>
                        <span>${esc(o.label)}</span>
                    </span>
                    ${o.meta ? `<span class="ex-multi-meta">${esc(o.meta)}</span>` : ''}
                </label>
            `).join('');

            listEl.querySelectorAll('input[type="checkbox"]').forEach(cb => {
                cb.addEventListener('change', () => {
                    const curr = new Set(getSelected());
                    if (cb.checked) curr.add(cb.value);
                    else curr.delete(cb.value);
                    onChange(Array.from(curr));
                    renderList();
                });
            });
        }

        searchEl.addEventListener('input', renderList);
        renderList();
        return {
            refresh: () => {
                renderList();
            },
        };
    }

    function createDemographicRange({ container, label, unit, lo, hi, step, getMin, getMax, setRange }) {
        container.innerHTML = `
            <div class="ex-stat-item">
                <div class="ex-stat-top">
                    <span class="ex-stat-label">${esc(label)}</span>
                    <button type="button" class="ex-stat-reset" title="Resetar intervalo" hidden>↺</button>
                </div>
                <div class="ex-dual-range">
                    <div class="ex-range-track"></div>
                    <div class="ex-range-fill"></div>
                    <input type="range" class="r-min" min="${lo}" max="${hi}" step="${step}" value="${lo}">
                    <input type="range" class="r-max" min="${lo}" max="${hi}" step="${step}" value="${hi}">
                </div>
                <div class="ex-num-row">
                    <div class="ex-num-box">
                        <span class="ex-num-tag">Mín</span>
                        <input type="number" class="ex-num-input n-min" min="${lo}" max="${hi}" step="${step}" placeholder="${lo}">
                        <span class="ex-num-unit">${esc(unit)}</span>
                    </div>
                    <span class="ex-num-sep">–</span>
                    <div class="ex-num-box">
                        <span class="ex-num-tag">Máx</span>
                        <input type="number" class="ex-num-input n-max" min="${lo}" max="${hi}" step="${step}" placeholder="${hi}">
                        <span class="ex-num-unit">${esc(unit)}</span>
                    </div>
                </div>
            </div>
        `;

        const card = container.querySelector('.ex-stat-item');
        const fill = container.querySelector('.ex-range-fill');
        const rMin = container.querySelector('.r-min');
        const rMax = container.querySelector('.r-max');
        const nMin = container.querySelector('.n-min');
        const nMax = container.querySelector('.n-max');
        const resetBtn = container.querySelector('.ex-stat-reset');

        function paint() {
            const mn = getMin();
            const mx = getMax();
            const vLo = mn !== null ? Math.max(lo, Math.min(hi, mn)) : lo;
            const vHi = mx !== null ? Math.max(lo, Math.min(hi, mx)) : hi;
            rMin.value = String(vLo);
            rMax.value = String(vHi);
            rMin.style.zIndex = vLo >= hi - step ? '4' : '3';
            rMax.style.zIndex = vLo >= hi - step ? '3' : '4';

            const pLo = ((vLo - lo) / Math.max(hi - lo, 1e-9)) * 100;
            const pHi = ((vHi - lo) / Math.max(hi - lo, 1e-9)) * 100;
            fill.style.setProperty('--lo', `${Math.max(0, pLo)}%`);
            fill.style.setProperty('--span', `${Math.max(0, pHi - pLo)}%`);

            if (document.activeElement !== nMin) nMin.value = mn !== null ? String(mn) : '';
            if (document.activeElement !== nMax) nMax.value = mx !== null ? String(mx) : '';

            const active = mn !== null || mx !== null;
            card.classList.toggle('is-active', active);
            resetBtn.hidden = !active;
        }

        rMin.addEventListener('input', () => {
            const curMax = getMax() ?? hi;
            let v = Math.min(Number(rMin.value), curMax);
            const mn = Math.abs(v - lo) <= step * 0.25 ? null : roundStep(v, step);
            setRange(mn, getMax());
            paint();
        });

        rMax.addEventListener('input', () => {
            const curMin = getMin() ?? lo;
            let v = Math.max(Number(rMax.value), curMin);
            const mx = Math.abs(v - hi) <= step * 0.25 ? null : roundStep(v, step);
            setRange(getMin(), mx);
            paint();
        });

        nMin.addEventListener('change', () => {
            const raw = nMin.value.trim();
            setRange(raw === '' ? null : Number(raw), getMax());
            paint();
        });
        nMax.addEventListener('change', () => {
            const raw = nMax.value.trim();
            setRange(getMin(), raw === '' ? null : Number(raw));
            paint();
        });
        resetBtn.addEventListener('click', () => {
            setRange(null, null);
            paint();
        });

        paint();
        return { refresh: paint };
    }

    // =========================================================================
    // SEÇÃO 3: TODAS AS 143+ ESTATÍSTICAS COLETADAS (12 CATEGORIAS)
    // =========================================================================
    function renderSortSelect() {
        const sel = document.getElementById('ex-sort');
        if (!sel || !Ex.schema) return;

        let html = `
            <optgroup label="📌 Ordenação Principal">
                <option value="">Automática (1º filtro ativo ou Valor de Mercado)</option>
                <option value="market_value">Valor de Mercado (€)</option>
                <option value="minutes_played">Minutos Jogados</option>
                <option value="age">Idade</option>
                <option value="name">Nome (A–Z)</option>
            </optgroup>
        `;

        Ex.schema.categories.forEach(cat => {
            const catStats = Ex.schema.stats.filter(s => s.category === cat.id);
            if (!catStats.length) return;
            html += `<optgroup label="${esc(cat.icon)} ${esc(cat.label)}">`;
            catStats.forEach(s => {
                html += `<option value="${esc(s.key)}">${esc(s.label)}</option>`;
            });
            html += '</optgroup>';
        });

        sel.innerHTML = html;
    }

    function renderStatsAccordions() {
        const container = document.getElementById('ex-stats');
        if (!container || !Ex.schema) return;
        container.innerHTML = '';

        Ex.schema.categories.forEach((cat, idx) => {
            const catStats = Ex.schema.stats.filter(s => s.category === cat.id);
            if (!catStats.length) return;

            const details = document.createElement('details');
            details.className = 'ex-section';
            details.dataset.cat = cat.id;
            if (idx === 1) details.open = true; // Abre Gols & Finalização inicialmente como vitrine

            details.innerHTML = `
                <summary>
                    <span class="ex-summary-title">
                        <span>${esc(cat.icon)}</span>
                        <span>${esc(cat.label)}</span>
                        <span class="ex-cat-count">(${catStats.length})</span>
                    </span>
                    <span class="ex-summary-right">
                        <span id="ex-cat-badge-${esc(cat.id)}" class="ex-badge" hidden>0</span>
                        <span class="ex-chevron">▾</span>
                    </span>
                </summary>
                <div class="ex-section-body"></div>
            `;

            const body = details.querySelector('.ex-section-body');
            catStats.forEach(sd => {
                const widget = createStatWidget(sd);
                Ex.statWidgets[sd.key] = widget;
                body.appendChild(widget.el);
            });

            container.appendChild(details);
        });
    }

    function createStatWidget(sd) {
        const el = document.createElement('div');
        el.className = 'ex-stat-item';
        el.dataset.key = sd.key;
        el.dataset.search = fold(`${sd.label} ${sd.key} ${sd.description} ${sd.source_label}`);

        const modesHtml = sd.modes.map(m => `
            <button type="button" class="ex-mode-btn ${m === 'total' ? 'active' : ''}" data-mode="${m}">
                ${modeLabel(m)}
            </button>
        `).join('');

        el.innerHTML = `
            <div class="ex-stat-top">
                <div class="ex-stat-name-wrap">
                    <span class="ex-stat-label">
                        <span>${esc(sd.label)}</span>
                        <span class="ex-info-dot" title="${esc(sd.description)}">i</span>
                    </span>
                    <span class="ex-stat-sub"><span class="js-n">—</span> atletas</span>
                </div>
                <div class="ex-stat-controls-right">
                    <div class="ex-modes">${modesHtml}</div>
                    <button type="button" class="ex-stat-reset" title="Limpar este atributo" hidden>↺</button>
                </div>
            </div>
            <div class="ex-dual-range">
                <div class="ex-range-track"></div>
                <div class="ex-range-fill"></div>
                <input type="range" class="r-min" min="0" max="100" step="1" value="0">
                <input type="range" class="r-max" min="0" max="100" step="1" value="100">
            </div>
            <div class="ex-num-row">
                <div class="ex-num-box">
                    <span class="ex-num-tag">Mín</span>
                    <input type="number" class="ex-num-input n-min" placeholder="0">
                    <span class="ex-num-unit js-unit"></span>
                </div>
                <span class="ex-num-sep">–</span>
                <div class="ex-num-box">
                    <span class="ex-num-tag">Máx</span>
                    <input type="number" class="ex-num-input n-max" placeholder="100">
                    <span class="ex-num-unit js-unit"></span>
                </div>
            </div>
        `;

        const fill = el.querySelector('.ex-range-fill');
        const rMin = el.querySelector('.r-min');
        const rMax = el.querySelector('.r-max');
        const nMin = el.querySelector('.n-min');
        const nMax = el.querySelector('.n-max');
        const nSpan = el.querySelector('.js-n');
        const units = el.querySelectorAll('.js-unit');
        const resetBtn = el.querySelector('.ex-stat-reset');
        const modeBtns = el.querySelectorAll('.ex-mode-btn');

        function currentBound() {
            const st = Ex.stats[sd.key];
            const bObj = Ex.bounds[sd.key]?.[st.mode];
            return bObj || { available: true, min: 0, max: 100, step: 1, n: 0 };
        }

        function unitText(mode) {
            if (mode === 'pct') return 'pct';
            if (mode === 'p90') return sd.unit ? `${sd.unit}/90` : '/90';
            return sd.unit || '';
        }

        function paint() {
            const st = Ex.stats[sd.key];
            const b = currentBound();
            const lo = Number(b.min ?? 0);
            const hi = Number(b.max ?? 100);
            const step = Number(b.step ?? 1);

            modeBtns.forEach(btn => btn.classList.toggle('active', btn.dataset.mode === st.mode));

            rMin.min = rMax.min = String(lo);
            rMin.max = rMax.max = String(hi);
            rMin.step = rMax.step = String(step);
            nMin.step = nMax.step = String(step);
            nMin.placeholder = String(lo);
            nMax.placeholder = String(hi);

            const u = unitText(st.mode);
            units.forEach(uEl => { uEl.textContent = u; });
            nSpan.textContent = b.n ? `${b.n} atl.` : 'sem amostra';
            el.classList.toggle('is-unavailable', !b.available || b.n === 0);

            const vLo = st.min !== null ? Math.max(lo, Math.min(hi, st.min)) : lo;
            const vHi = st.max !== null ? Math.max(lo, Math.min(hi, st.max)) : hi;
            rMin.value = String(vLo);
            rMax.value = String(vHi);
            rMin.style.zIndex = vLo >= hi - step ? '4' : '3';
            rMax.style.zIndex = vLo >= hi - step ? '3' : '4';

            const span = Math.max(hi - lo, 1e-9);
            const pLo = ((vLo - lo) / span) * 100;
            const pHi = ((vHi - lo) / span) * 100;
            fill.style.setProperty('--lo', `${Math.max(0, Math.min(100, pLo))}%`);
            fill.style.setProperty('--span', `${Math.max(0, Math.min(100, pHi - pLo))}%`);

            if (document.activeElement !== nMin) nMin.value = st.min !== null ? String(st.min) : '';
            if (document.activeElement !== nMax) nMax.value = st.max !== null ? String(st.max) : '';

            const active = st.min !== null || st.max !== null;
            el.classList.toggle('is-active', active);
            resetBtn.hidden = !active;
        }

        modeBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                const nextMode = btn.dataset.mode;
                const st = Ex.stats[sd.key];
                if (st.mode === nextMode) return;
                const wasActive = st.min !== null || st.max !== null;
                st.mode = nextMode;
                st.min = null;
                st.max = null;
                paint();
                if (wasActive) scheduleSearch();
            });
        });

        rMin.addEventListener('input', () => {
            const st = Ex.stats[sd.key];
            const b = currentBound();
            const curMax = st.max ?? b.max;
            const v = Math.min(Number(rMin.value), curMax);
            st.min = Math.abs(v - b.min) <= b.step * 0.25 ? null : roundStep(v, b.step);
            paint();
            scheduleSearch();
        });

        rMax.addEventListener('input', () => {
            const st = Ex.stats[sd.key];
            const b = currentBound();
            const curMin = st.min ?? b.min;
            const v = Math.max(Number(rMax.value), curMin);
            st.max = Math.abs(v - b.max) <= b.step * 0.25 ? null : roundStep(v, b.step);
            paint();
            scheduleSearch();
        });

        nMin.addEventListener('change', () => {
            const raw = nMin.value.trim();
            Ex.stats[sd.key].min = raw === '' ? null : Number(raw);
            paint();
            scheduleSearch();
        });

        nMax.addEventListener('change', () => {
            const raw = nMax.value.trim();
            Ex.stats[sd.key].max = raw === '' ? null : Number(raw);
            paint();
            scheduleSearch();
        });

        resetBtn.addEventListener('click', () => {
            Ex.stats[sd.key].min = null;
            Ex.stats[sd.key].max = null;
            paint();
            scheduleSearch();
        });

        return { el, refresh: paint };
    }

    function syncAllStatWidgets() {
        Object.values(Ex.statWidgets).forEach(w => w.refresh());
    }

    function applyStatVisibilityFilter() {
        const q = fold(document.getElementById('ex-stat-search')?.value || '');
        const onlyActive = Boolean(document.getElementById('ex-only-active')?.checked);

        document.querySelectorAll('#ex-stats details.ex-section').forEach(sec => {
            let visibleInCat = 0;
            sec.querySelectorAll('.ex-stat-item').forEach(item => {
                const key = item.dataset.key;
                const st = Ex.stats[key];
                const isActive = st && (st.min !== null || st.max !== null);
                const matchesQuery = !q || item.dataset.search.includes(q);
                const show = matchesQuery && (!onlyActive || isActive);
                item.hidden = !show;
                if (show) visibleInCat++;
            });
            sec.hidden = visibleInCat === 0;
            if ((q || onlyActive) && visibleInCat > 0) {
                sec.open = true;
            }
        });
    }

    // =========================================================================
    // CARREGAMENTO DE LIMITES (/explorer/bounds) E BUSCA (/explorer/search)
    // =========================================================================
    async function loadBounds() {
        try {
            const res = await fetch(`${EX_API}/explorer/bounds`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(Ex.scope),
            });
            if (!res.ok) return;
            const data = await res.json();
            Ex.bounds = data.stats || {};
            Ex.playersInScope = data.players_in_scope || 0;
            syncAllStatWidgets();
        } catch (err) {
            console.warn('Falha ao atualizar limites do recorte:', err);
        }
    }

    function getActiveStatsPayload() {
        const list = [];
        Object.entries(Ex.stats).forEach(([key, st]) => {
            if (st.min !== null || st.max !== null) {
                list.push({ key, mode: st.mode, min: st.min, max: st.max });
            }
        });
        return list;
    }

    function buildQueryPayload() {
        const activeStats = getActiveStatsPayload();
        let sortBy = Ex.sortBy || null;
        let sortMode = null;
        if (sortBy && Ex.statMap[sortBy]) {
            const st = Ex.stats[sortBy];
            sortMode = (st && (st.min !== null || st.max !== null)) ? st.mode : 'total';
        }
        return {
            scope: Ex.scope,
            identity: {
                ...Ex.identity,
                name: Ex.identity.name?.trim() || null,
            },
            stats: activeStats,
            sort_by: sortBy,
            sort_mode: sortMode,
            sort_dir: Ex.sortDir,
            page: Ex.page,
            page_size: Ex.pageSize,
        };
    }

    async function runSearch() {
        const listEl = document.getElementById('ex-results');
        const countEl = document.getElementById('ex-count');
        const scopeDescEl = document.getElementById('ex-scope-desc');
        if (!listEl) return;

        updateActiveBadgesAndChips();

        try {
            const payload = buildQueryPayload();
            const res = await fetch(`${EX_API}/explorer/search`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            if (!res.ok) {
                const errJson = await res.json().catch(() => ({}));
                throw new Error(errJson.detail || `HTTP ${res.status}`);
            }
            const data = await res.json();

            if (countEl) {
                countEl.textContent = `Encontrados ${data.total} jogador${data.total === 1 ? '' : 'es'}`;
            }
            if (scopeDescEl) {
                const modeTxt = Ex.scope.season_mode === 'latest'
                    ? 'Última temporada com amostra'
                    : Ex.scope.season_mode === 'selected'
                        ? `Temporadas: ${Ex.scope.seasons.join(', ')}`
                        : 'Carreira completa';
                const compTxt = Ex.scope.competitions.length
                    ? ` • ${Ex.scope.competitions.length} competição(ões)`
                    : '';
                scopeDescEl.textContent = `${modeTxt} • Mínimo ${Ex.scope.min_minutes}' (${data.players_in_scope} atletas elegíveis no recorte) • ${data.elapsed_ms} ms${compTxt}`;
            }

            renderResultsList(data.items);
            renderPager(data);
        } catch (err) {
            listEl.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon">⚠️</div>
                    <h3>Não foi possível executar a busca</h3>
                    <p>${esc(err.message)}</p>
                </div>
            `;
        }
    }

    // =========================================================================
    // RENDERIZAÇÃO DE CHIPS, CARDS DE JOGADORES, FICHA COMPLETA E PAGINAÇÃO
    // =========================================================================
    function updateActiveBadgesAndChips() {
        if (!Ex.schema) return;

        // 1. Contagem de filtros de identificação
        const idChips = [];
        const id = Ex.identity;
        if (id.name?.trim()) {
            idChips.push({ label: `Nome: "${id.name.trim()}"`, clear: () => { id.name = ''; document.getElementById('ex-id-name').value = ''; } });
        }
        if (id.roles.length) {
            idChips.push({ label: `Função: ${id.roles.join(', ')}`, clear: () => { id.roles = []; Ex.multiWidgets.roles?.refresh(); } });
        }
        if (id.positions.length) {
            idChips.push({ label: `Posição: ${id.positions.join(', ')}`, clear: () => { id.positions = []; Ex.multiWidgets.positions?.refresh(); } });
        }
        if (id.foot.length) {
            const fMap = Object.fromEntries(Ex.schema.feet.map(f => [f.value, f.label]));
            idChips.push({ label: `Pé: ${id.foot.map(f => fMap[f] || f).join(', ')}`, clear: () => { id.foot = []; Ex.multiWidgets.foot?.refresh(); } });
        }
        if (id.age_min !== null || id.age_max !== null) {
            idChips.push({ label: `Idade: ${id.age_min ?? '…'}–${id.age_max ?? '…'} anos`, clear: () => { id.age_min = id.age_max = null; Ex.idWidgets.age?.refresh(); } });
        }
        if (id.value_min !== null || id.value_max !== null) {
            const a = id.value_min !== null ? `${id.value_min / 1e6}M` : '0';
            const b = id.value_max !== null ? `${id.value_max / 1e6}M` : 'máx';
            idChips.push({ label: `Valor: ${a}–${b} €`, clear: () => { id.value_min = id.value_max = null; Ex.idWidgets.value?.refresh(); } });
        }
        if (id.height_min !== null || id.height_max !== null) {
            idChips.push({ label: `Altura: ${id.height_min ?? '…'}–${id.height_max ?? '…'} cm`, clear: () => { id.height_min = id.height_max = null; Ex.idWidgets.height?.refresh(); } });
        }
        if (id.weight_min !== null || id.weight_max !== null) {
            idChips.push({ label: `Peso: ${id.weight_min ?? '…'}–${id.weight_max ?? '…'} kg`, clear: () => { id.weight_min = id.weight_max = null; Ex.idWidgets.weight?.refresh(); } });
        }
        if (id.leagues.length) {
            idChips.push({ label: `Ligas (${id.leagues.length})`, clear: () => { id.leagues = []; Ex.multiWidgets.leagues?.refresh(); Ex.multiWidgets.teams?.refresh(); } });
        }
        if (id.teams.length) {
            idChips.push({ label: `Clubes: ${id.teams.slice(0, 2).join(', ')}${id.teams.length > 2 ? '…' : ''}`, clear: () => { id.teams = []; Ex.multiWidgets.teams?.refresh(); } });
        }
        if (id.strengths.length) {
            idChips.push({ label: `Fortes (${id.strengths.length})`, clear: () => { id.strengths = []; Ex.multiWidgets.strengths?.refresh(); } });
        }
        if (id.exclude_weaknesses.length) {
            idChips.push({ label: `Sem fraqueza (${id.exclude_weaknesses.length})`, clear: () => { id.exclude_weaknesses = []; Ex.multiWidgets.weaknesses?.refresh(); } });
        }
        if (id.require_sources.length) {
            idChips.push({ label: `Fontes: ${id.require_sources.join(', ')}`, clear: () => { id.require_sources = []; Ex.multiWidgets.sources?.refresh(); } });
        }

        const idBadge = document.getElementById('ex-identity-badge');
        if (idBadge) {
            idBadge.textContent = String(idChips.length);
            idBadge.hidden = idChips.length === 0;
        }

        // 2. Contagem de filtros estatísticos por categoria
        const catCounts = {};
        const statChips = [];
        Object.entries(Ex.stats).forEach(([key, st]) => {
            if (st.min === null && st.max === null) return;
            const sd = Ex.statMap[key];
            if (!sd) return;
            catCounts[sd.category] = (catCounts[sd.category] || 0) + 1;

            const u = st.mode === 'pct' ? 'pct' : (st.mode === 'p90' ? '/90' : sd.unit);
            const rangeTxt = st.min !== null && st.max !== null
                ? `${st.min}–${st.max}${u ? ' ' + u : ''}`
                : st.min !== null
                    ? `≥ ${st.min}${u ? ' ' + u : ''}`
                    : `≤ ${st.max}${u ? ' ' + u : ''}`;

            statChips.push({
                label: `${sd.label} (${modeLabel(st.mode)}): ${rangeTxt}`,
                clear: () => {
                    Ex.stats[key].min = null;
                    Ex.stats[key].max = null;
                    Ex.statWidgets[key]?.refresh();
                },
            });
        });

        Ex.schema.categories.forEach(cat => {
            const cnt = catCounts[cat.id] || 0;
            const bEl = document.getElementById(`ex-cat-badge-${cat.id}`);
            const sec = document.querySelector(`#ex-stats details.ex-section[data-cat="${cat.id}"]`);
            if (bEl) {
                bEl.textContent = String(cnt);
                bEl.hidden = cnt === 0;
            }
            if (sec) sec.classList.toggle('has-active', cnt > 0);
        });

        const statsBadge = document.getElementById('ex-stats-badge');
        if (statsBadge) {
            statsBadge.textContent = String(statChips.length);
            statsBadge.hidden = statChips.length === 0;
        }

        const totalActive = idChips.length + statChips.length;
        const openBadge = document.getElementById('ex-open-badge');
        if (openBadge) openBadge.textContent = totalActive ? `(${totalActive})` : '';

        // 3. Renderiza barra de chips clicáveis
        const chipsBox = document.getElementById('ex-chips');
        if (!chipsBox) return;
        const allChips = [...idChips, ...statChips];
        chipsBox.innerHTML = allChips.map((c, idx) => `
            <span class="ex-chip">
                <span>${esc(c.label)}</span>
                <button type="button" data-idx="${idx}" aria-label="Remover filtro">✕</button>
            </span>
        `).join('');

        chipsBox.querySelectorAll('button').forEach(btn => {
            btn.addEventListener('click', () => {
                const idx = Number(btn.dataset.idx);
                allChips[idx]?.clear();
                scheduleSearch(true);
            });
        });
    }

    function renderResultsList(items) {
        const listEl = document.getElementById('ex-results');
        if (!listEl) return;

        if (!items || items.length === 0) {
            listEl.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon">🔍</div>
                    <h3>Nenhum jogador encontrado com os critérios selecionados</h3>
                    <p>Afrouxe algum intervalo de estatística, reduza a minutagem mínima ou clique em <b>Limpar tudo</b>.</p>
                </div>
            `;
            return;
        }

        const footMap = { Left: 'Canhoto', Right: 'Destro', Both: 'Ambidestro' };

        listEl.innerHTML = items.map(p => {
            const initials = p.name.split(' ').map(w => w[0]).slice(0, 2).join('');
            const posList = p.positions && p.positions.length ? p.positions.join(', ') : (p.position_raw || p.scout_role);
            const ageTxt = p.age !== null ? `<strong>${p.age} anos</strong>` : '';
            const footTxt = p.footed ? (footMap[p.footed] || p.footed) : '';
            const hwTxt = [p.height ? `${p.height} cm` : '', p.weight ? `${p.weight} kg` : ''].filter(Boolean).join(' / ');
            const mins = p.scope?.minutes_played !== null && p.scope?.minutes_played !== undefined
                ? `${Math.round(p.scope.minutes_played)}' (${Math.round(p.scope.appearances || 0)} j)`
                : 'Sem minutos no recorte';
            const seasonTag = p.scope?.seasons ? `Temp. ${p.scope.seasons}` : '';
            const isSheetOpen = Boolean(Ex.openSheets[p.sofascore_id]);

            const metricsHtml = (p.metrics || []).map(m => {
                const sd = Ex.statMap[m.key];
                if (!sd) return '';
                const mainVal = fmtMetric(sd, m.mode, m.value);
                const subParts = [];
                if (m.mode !== 'total' && m.total !== null) subParts.push(`Tot: ${fmtNum(m.total, sd.decimals, sd.unit)}`);
                if (m.mode !== 'p90' && m.p90 !== null) subParts.push(`${fmtNum(m.p90, Math.max(sd.decimals, 2))}/90`);
                const pct = m.pct !== null && m.pct !== undefined ? Math.round(m.pct) : null;

                return `
                    <div class="ex-metric-pill" style="${m.filtered ? 'border-color: rgba(16, 185, 129, 0.45); background: rgba(16, 185, 129, 0.08);' : ''}">
                        <div class="ex-metric-pill-head">
                            <span>${esc(sd.label)}</span>
                            <span>${pct !== null ? `P${pct}` : ''}</span>
                        </div>
                        <div class="ex-metric-pill-val">
                            <span>${esc(mainVal)}</span>
                            <span class="ex-metric-pill-sub">${esc(subParts.join(' • '))}</span>
                        </div>
                        ${pct !== null ? `<div class="ex-mini-bar"><div style="width:${Math.max(2, Math.min(100, pct))}%"></div></div>` : ''}
                    </div>
                `;
            }).join('');

            return `
                <article class="ex-card" data-sid="${p.sofascore_id}" data-mid="${p.mapping_id}">
                    <div class="ex-card-main">
                        <div class="ex-card-left">
                            <div class="player-avatar">${esc(initials)}</div>
                            <div>
                                <div class="ex-card-title-row">
                                    <h3 class="ex-card-name">👤 ${esc(p.name)}</h3>
                                    <span class="role-badge role-${esc(p.scout_role)}">${esc(p.scout_role)}</span>
                                    <span class="spec-chip">${esc(posList)}</span>
                                </div>
                                <div class="ex-card-meta">
                                    ${ageTxt ? `<span>${ageTxt}</span>` : ''}
                                    <span>🛡️ <strong>${esc(p.current_team || 'Sem clube')}</strong> (${esc(p.current_league || 'N/A')})</span>
                                    ${footTxt ? `<span>👟 ${esc(footTxt)}</span>` : ''}
                                    ${hwTxt ? `<span>📏 ${esc(hwTxt)}</span>` : ''}
                                    ${seasonTag ? `<span>📅 ${esc(seasonTag)} • ${esc(mins)}</span>` : `<span>⏱️ ${esc(mins)}</span>`}
                                </div>
                            </div>
                        </div>

                        <div class="ex-card-right">
                            <span class="valuation-tag">💰 ${esc(p.market_value_raw || 'Sob consulta')}</span>
                            <div class="ex-card-actions">
                                <button type="button" class="btn-sheet-toggle ${isSheetOpen ? 'open' : ''}" data-action="sheet" data-sid="${p.sofascore_id}">
                                    📋 ${isSheetOpen ? 'Ocultar ficha completa' : 'Visualizar ficha completa'}
                                </button>
                                <button type="button" class="btn-open-radar" data-action="radar" data-mid="${p.mapping_id}">
                                    🎯 Raio-X &amp; Radar ➔
                                </button>
                            </div>
                        </div>
                    </div>

                    ${metricsHtml ? `<div class="ex-card-metrics">${metricsHtml}</div>` : ''}

                    <div id="ex-sheet-${p.sofascore_id}" class="ex-sheet" ${isSheetOpen ? '' : 'hidden'}>
                        ${isSheetOpen && typeof Ex.openSheets[p.sofascore_id] === 'object'
                            ? renderSheetHtml(Ex.openSheets[p.sofascore_id])
                            : ''}
                    </div>
                </article>
            `;
        }).join('');

        // Bind card actions
        listEl.querySelectorAll('button[data-action="sheet"]').forEach(btn => {
            btn.addEventListener('click', () => togglePlayerSheet(Number(btn.dataset.sid), btn));
        });
        listEl.querySelectorAll('button[data-action="radar"]').forEach(btn => {
            btn.addEventListener('click', () => {
                if (typeof window.openPlayerDossier === 'function') {
                    window.openPlayerDossier(btn.dataset.mid, Ex.scope.min_minutes);
                }
            });
        });
    }

    async function togglePlayerSheet(sofascoreId, btn) {
        const box = document.getElementById(`ex-sheet-${sofascoreId}`);
        if (!box) return;

        if (Ex.openSheets[sofascoreId]) {
            delete Ex.openSheets[sofascoreId];
            box.hidden = true;
            box.innerHTML = '';
            btn.classList.remove('open');
            btn.textContent = '📋 Visualizar ficha completa';
            return;
        }

        Ex.openSheets[sofascoreId] = 'loading';
        box.hidden = false;
        btn.classList.add('open');
        btn.textContent = '📋 Ocultar ficha completa';
        box.innerHTML = '<div style="padding: 0.75rem; color: var(--text-muted); font-size: 0.84rem;">⏳ Carregando ficha completa das 4 fontes...</div>';

        try {
            const res = await fetch(`${EX_API}/explorer/sheet`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ player_id: sofascoreId, scope: Ex.scope }),
            });
            if (!res.ok) throw new Error('Atleta sem estatísticas neste recorte.');
            const sheetData = await res.json();
            Ex.openSheets[sofascoreId] = sheetData;
            box.innerHTML = renderSheetHtml(sheetData);
        } catch (err) {
            box.innerHTML = `<div style="padding: 0.75rem; color: var(--accent-rose); font-size: 0.84rem;">${esc(err.message)}</div>`;
        }
    }

    function renderSheetHtml(sheet) {
        if (!sheet || !sheet.categories || sheet.categories.length === 0) {
            return '<div style="color: var(--text-muted); font-size: 0.84rem;">Nenhuma estatística registrada neste recorte.</div>';
        }
        return sheet.categories.map(cat => `
            <div class="ex-sheet-cat">
                <div class="ex-sheet-cat-title">
                    <span>${esc(cat.icon)}</span>
                    <span>${esc(cat.label)}</span>
                </div>
                <div class="ex-sheet-grid">
                    ${cat.stats.map(st => {
                        const main = fmtNum(st.total, st.decimals, st.unit);
                        const extras = [];
                        if (st.p90 !== null && st.p90 !== undefined) extras.push(`${fmtNum(st.p90, Math.max(st.decimals, 2))}/90`);
                        if (st.pct !== null && st.pct !== undefined) extras.push(`P${Math.round(st.pct)}`);
                        return `
                            <div class="ex-sheet-cell" title="${esc(st.description)}">
                                <div class="ex-sheet-cell-label">${esc(st.label)}</div>
                                <div class="ex-sheet-cell-vals">
                                    <span class="ex-sheet-cell-main">${esc(main)}</span>
                                    <span class="ex-sheet-cell-extra">${esc(extras.join(' • '))}</span>
                                </div>
                            </div>
                        `;
                    }).join('')}
                </div>
            </div>
        `).join('');
    }

    function renderPager(data) {
        const pager = document.getElementById('ex-pager');
        if (!pager) return;
        if (!data.total) {
            pager.hidden = true;
            return;
        }
        pager.hidden = false;
        pager.innerHTML = `
            <button type="button" class="btn-mini" id="ex-prev" ${data.page <= 1 ? 'disabled' : ''}>⬅️ Anterior</button>
            <span class="ex-pager-info">Página ${data.page} de ${data.pages} (${data.total} jogadores)</span>
            <button type="button" class="btn-mini" id="ex-next" ${data.page >= data.pages ? 'disabled' : ''}>Próxima ➡️</button>
        `;

        document.getElementById('ex-prev')?.addEventListener('click', () => {
            if (Ex.page > 1) {
                Ex.page--;
                runSearch();
                window.scrollTo({ top: 0, behavior: 'smooth' });
            }
        });
        document.getElementById('ex-next')?.addEventListener('click', () => {
            if (Ex.page < data.pages) {
                Ex.page++;
                runSearch();
                window.scrollTo({ top: 0, behavior: 'smooth' });
            }
        });
    }

    // =========================================================================
    // RESET E EXPORTAÇÃO CSV
    // =========================================================================
    function clearStateOnly() {
        Ex.identity = {
            name: '',
            roles: [],
            positions: [],
            leagues: [],
            teams: [],
            foot: [],
            age_min: null,
            age_max: null,
            height_min: null,
            height_max: null,
            weight_min: null,
            weight_max: null,
            value_min: null,
            value_max: null,
            strengths: [],
            exclude_weaknesses: [],
            require_sources: [],
        };
        Object.keys(Ex.stats).forEach(k => {
            Ex.stats[k] = { mode: 'total', min: null, max: null };
        });
        Ex.openSheets = {};
    }

    function syncAllControlsFromState() {
        const nameEl = document.getElementById('ex-id-name');
        if (nameEl) nameEl.value = Ex.identity.name || '';

        const modeSel = document.getElementById('ex-season-mode');
        const seasonsWrap = document.getElementById('ex-seasons-wrap');
        if (modeSel) modeSel.value = Ex.scope.season_mode;
        if (seasonsWrap) {
            if (Ex.scope.season_mode === 'selected') seasonsWrap.removeAttribute('hidden');
            else seasonsWrap.setAttribute('hidden', '');
        }

        const minEl = document.getElementById('ex-min-minutes');
        if (minEl) minEl.value = String(Ex.scope.min_minutes);
        document.querySelectorAll('#ex-min-pills .ex-pill').forEach(btn => {
            btn.classList.toggle('active', Number(btn.dataset.min) === Ex.scope.min_minutes);
        });

        Object.values(Ex.multiWidgets).forEach(w => w?.refresh());
        Object.values(Ex.idWidgets).forEach(w => w?.refresh());
        syncAllStatWidgets();
    }

    async function resetAllFilters() {
        clearStateOnly();
        Ex.scope = { season_mode: 'latest', seasons: [], competitions: [], min_minutes: 450 };
        Ex.sortBy = '';
        Ex.sortDir = 'desc';
        Ex.page = 1;

        const sortSel = document.getElementById('ex-sort');
        if (sortSel) sortSel.value = '';
        const sortDirBtn = document.getElementById('ex-sort-dir');
        if (sortDirBtn) sortDirBtn.textContent = '↓ Maior';
        const profSel = document.getElementById('ex-profile-select');
        if (profSel) profSel.value = '';
        updateProfileDescription();

        const statSearch = document.getElementById('ex-stat-search');
        if (statSearch) statSearch.value = '';
        const onlyActive = document.getElementById('ex-only-active');
        if (onlyActive) onlyActive.checked = false;

        syncAllControlsFromState();
        applyStatVisibilityFilter();
        await loadBounds();
        await runSearch();
    }

    async function exportCsv() {
        const btn = document.getElementById('ex-export');
        if (!btn) return;
        const orig = btn.textContent;
        btn.disabled = true;
        btn.textContent = '⏳ Gerando...';

        try {
            const res = await fetch(`${EX_API}/explorer/export`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(buildQueryPayload()),
            });
            if (!res.ok) throw new Error('Falha ao exportar CSV');
            const blob = await res.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            const cd = res.headers.get('Content-Disposition') || '';
            const m = cd.match(/filename="([^"]+)"/);
            a.download = m ? m[1] : 'scout_explorer.csv';
            document.body.appendChild(a);
            a.click();
            a.remove();
            URL.revokeObjectURL(url);
        } catch (err) {
            alert('Erro ao baixar CSV: ' + err.message);
        } finally {
            btn.disabled = false;
            btn.textContent = orig;
        }
    }
})();

