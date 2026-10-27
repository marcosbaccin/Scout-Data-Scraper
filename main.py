"""
⚽ Scout Data Scraper & Analytics - Orquestrador Principal do Pipeline

Ponto de entrada único para gerenciamento do ciclo de vida dos dados:
- Status e telemetria dos dados coletados e tabelas no banco de dados.
- Reset e higienização completa para coletas do zero.
- Execução isolada ou em lote dos scrapers (SofaScore, FBref, Transfermarkt, WhoScored).
- Execução dos loaders ETL e resolução de identidades (Entity Matching).
- Inicialização do servidor FastAPI.

Uso:
    python main.py status
    python main.py reset --force
    python main.py scrape all
    python main.py scrape sofascore
    python main.py load all
    python main.py match
    python main.py run-all --reset
    python main.py api --port 8000
"""
import argparse
import os
import subprocess
import sys
import time
from typing import List, Optional

# Garante acesso aos módulos internos
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from core.reset import (
    get_pipeline_status,
    reset_all_collected_data,
    reset_database,
    reset_sofascore_data,
    reset_fbref_data,
    reset_transfermarkt_data,
    reset_whoscored_data,
    clean_locks_and_temps,
)
from core.settings import BASE_DIR


# Cores ANSI para terminal
class Style:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    RESET = '\033[0m'


def print_banner():
    banner = f"""{Style.CYAN}{Style.BOLD}
================================================================================
           SCOUT DATA SCRAPER & ANALYTICS - PIPELINE ORCHESTRATOR           
================================================================================{Style.RESET}"""
    print(banner)


def format_duration(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}h {m:02d}m {s:02d}s"
    elif m > 0:
        return f"{m}m {s:02d}s"
    return f"{seconds:.1f}s"


class PipelineOrchestrator:
    def __init__(self):
        self.py_exec = sys.executable

    def run_step(self, script_rel_path: str, args: Optional[List[str]] = None, title: str = "") -> bool:
        """Executa um script Python em subprocesso isolado, garantindo liberação de memória e drivers."""
        script_path = os.path.join(BASE_DIR, script_rel_path)
        if not os.path.exists(script_path):
            print(f"{Style.FAIL}[!] Script não encontrado: {script_path}{Style.RESET}")
            return False

        cmd = [self.py_exec, script_path] + (args or [])
        display_title = title or f"Executando {script_rel_path}"

        print(f"\n{Style.BOLD}{Style.BLUE}>>> [ETAPA] {display_title}{Style.RESET}")
        print(f"{Style.DIM}    Comando: {' '.join(cmd)}{Style.RESET}\n")

        start_time = time.time()
        try:
            # Executa com streaming direto para stdout
            result = subprocess.run(cmd, cwd=BASE_DIR, check=False)
            elapsed = time.time() - start_time

            if result.returncode == 0:
                print(f"\n{Style.GREEN}[✓] Concluído com sucesso em {format_duration(elapsed)}{Style.RESET}")
                return True
            else:
                print(f"\n{Style.FAIL}[✗] Falha na etapa (Exit Code {result.returncode}) após {format_duration(elapsed)}{Style.RESET}")
                return False
        except Exception as e:
            elapsed = time.time() - start_time
            print(f"\n{Style.FAIL}[!] Erro de execução ({format_duration(elapsed)}): {e}{Style.RESET}")
            return False

    # -------------------------------------------------------------------------
    # COMANDOS DE STATUS E DASHBOARD
    # -------------------------------------------------------------------------
    def show_status(self):
        print_banner()
        print(f"\n{Style.BOLD}📊 STATUS DO ECOSSISTEMA DE DADOS:{Style.RESET}\n")
        st = get_pipeline_status()

        # 1. Banco de Dados
        db = st["database"]
        if db["exists"]:
            print(f"  {Style.GREEN}● Banco de Dados:{Style.RESET} scout.db ({db['size_formatted']})")
            print("    Tabelas no SQLite:")
            for t_name, count in db["tables"].items():
                print(f"      - {t_name:<30}: {Style.BOLD}{count:>7}{Style.RESET} registros")
        else:
            print(f"  {Style.WARNING}○ Banco de Dados: scout.db NÃO CRIADO{Style.RESET}")

        # 2. Scrapers
        print(f"\n  {Style.BOLD}● Armazenamento dos Scrapers (Dumps Brutos e Checkpoints):{Style.RESET}")
        for s_name, data in st["scrapers"].items():
            print(f"    - {s_name.upper():<14}: {Style.CYAN}{data['total_size_formatted']:>9}{Style.RESET} ({data['file_count']} arquivos)")
            if data["key_files"]:
                files_str = ", ".join(data["key_files"][:4])
                if len(data["key_files"]) > 4:
                    files_str += f" (+{len(data['key_files'])-4} arquivos)"
                print(f"      {Style.DIM}Arquivos: {files_str}{Style.RESET}")

        print(f"\n{Style.DIM}Dica: Para resetar os dados e recomeçar do zero, use: python main.py reset --force{Style.RESET}\n")

    # -------------------------------------------------------------------------
    # COMANDOS DE HIGIENIZAÇÃO (RESET)
    # -------------------------------------------------------------------------
    def reset(self, force: bool = False, db_only: bool = False, scrapers_only: bool = False):
        print_banner()
        if not force:
            print(f"{Style.WARNING}{Style.BOLD}ATENÇÃO:{Style.RESET} Esta ação irá apagar dados locais coletados.")
            confirm = input("Deseja realmente continuar? [s/N]: ").strip().lower()
            if confirm not in ['s', 'sim', 'y', 'yes']:
                print(f"{Style.BLUE}[*] Operação de reset cancelada pelo usuário.{Style.RESET}")
                return

        if db_only:
            reset_database()
        elif scrapers_only:
            reset_sofascore_data()
            reset_fbref_data()
            reset_transfermarkt_data()
            reset_whoscored_data()
            clean_locks_and_temps()
        else:
            reset_all_collected_data(reset_db=True)

    # -------------------------------------------------------------------------
    # SCRAPING POR FONTE
    # -------------------------------------------------------------------------
    def scrape_sofascore(self) -> bool:
        print(f"\n{Style.HEADER}{Style.BOLD}=== INICIANDO COLETA: SOFASCORE (FONTE PRIMÁRIA) ==={Style.RESET}")
        steps = [
            ("scrapers/sofascore/team_spider.py", "SofaScore: Mapeamento de Clubes nas 11 Ligas"),
            ("scrapers/sofascore/player_spider.py", "SofaScore: Extração de Jogadores Brasileiros nos Clubes"),
            ("scrapers/sofascore/stats_spider.py", "SofaScore: Extração de Estatísticas e Características"),
        ]
        for script, title in steps:
            if not self.run_step(script, title=title):
                return False
        return True

    def scrape_fbref(self) -> bool:
        print(f"\n{Style.HEADER}{Style.BOLD}=== INICIANDO COLETA: FBREF (MÉTRICAS EXCLUSIVAS) ==={Style.RESET}")
        steps = [
            ("scrapers/fbref/league_spider.py", "FBref: Mapeamento de Ligas e Clubes"),
            ("scrapers/fbref/player_spider.py", "FBref: Extração de Jogadores Brasileiros e Tabelas Exclusivas"),
        ]
        for script, title in steps:
            if not self.run_step(script, title=title):
                return False
        return True

    def scrape_transfermarkt(self) -> bool:
        print(f"\n{Style.HEADER}{Style.BOLD}=== INICIANDO COLETA: TRANSFERMARKT (VALOR DE MERCADO & DUPLA NACIONALIDADE) ==={Style.RESET}")
        steps = [
            ("scrapers/transfermarkt/teams_spider.py", "Transfermarkt: Mapeamento de Clubes nas 11 Ligas"),
            ("scrapers/transfermarkt/players_spider.py", "Transfermarkt: Extração de Brasileiros (Filtro 1ª Bandeira) & Valuation"),
        ]
        for script, title in steps:
            if not self.run_step(script, title=title):
                return False
        return True

    def scrape_whoscored(self) -> bool:
        print(f"\n{Style.HEADER}{Style.BOLD}=== INICIANDO COLETA: WHOSCORED (ESTILOS & CARACTERÍSTICAS TÁTICAS) ==={Style.RESET}")
        steps = [
            ("scrapers/whoscored/teams_spider.py", "WhoScored: Mapeamento de Clubes nas 11 Ligas"),
            ("scrapers/whoscored/club_and_players_spider.py", "WhoScored: Características dos Clubes & Identificação de Brasileiros"),
            ("scrapers/whoscored/player_details_spider.py", "WhoScored: Perfis Detalhados, Características & Histórico Opção 2"),
        ]
        for script, title in steps:
            if not self.run_step(script, title=title):
                return False
        return True

    def scrape_all(self) -> bool:
        print_banner()
        print(f"{Style.BOLD}Iniciando Scraping Global das 4 Fontes de Dados...{Style.RESET}")
        start = time.time()
        ok = (
            self.scrape_sofascore() and
            self.scrape_fbref() and
            self.scrape_transfermarkt() and
            self.scrape_whoscored()
        )
        elapsed = time.time() - start
        if ok:
            print(f"\n{Style.GREEN}{Style.BOLD}[✓] Coleta Global Finalizada com Sucesso em {format_duration(elapsed)}!{Style.RESET}")
        else:
            print(f"\n{Style.FAIL}{Style.BOLD}[✗] Coleta Global interrompida devido a falha em etapa.{Style.RESET}")
        return ok

    # -------------------------------------------------------------------------
    # CARGA NO BANCO DE DADOS (LOADERS)
    # -------------------------------------------------------------------------
    def load_source(self, source: str) -> bool:
        loaders = {
            "sofascore": ("load_sofascore.py", "Carga ETL: SofaScore -> scout.db"),
            "fbref": ("load_fbref.py", "Carga ETL: FBref -> scout.db"),
            "transfermarkt": ("load_transfermarkt.py", "Carga ETL: Transfermarkt -> scout.db"),
            "whoscored": ("load_whoscored.py", "Carga ETL: WhoScored -> scout.db"),
        }
        if source not in loaders:
            print(f"{Style.FAIL}[!] Fonte de carga inválida: {source}{Style.RESET}")
            return False

        script, title = loaders[source]
        return self.run_step(script, title=title)

    def load_all(self) -> bool:
        print_banner()
        print(f"{Style.BOLD}Iniciando Carga ETL das 4 Fontes no Banco de Dados...{Style.RESET}")
        for src in ["sofascore", "fbref", "transfermarkt", "whoscored"]:
            if not self.load_source(src):
                return False
        print(f"\n{Style.GREEN}{Style.BOLD}[✓] Todas as 4 fontes foram carregadas com sucesso no scout.db!{Style.RESET}")
        return True

    # -------------------------------------------------------------------------
    # RESOLUÇÃO DE IDENTIDADES (MATCHING)
    # -------------------------------------------------------------------------
    def match(self) -> bool:
        print_banner()
        print(f"{Style.BOLD}Iniciando Algoritmo de Reconciliação e Resolução de Entidades...{Style.RESET}")
        return self.run_step("match_ids.py", title="Resolução de Identidades (player_mapping)")

    # -------------------------------------------------------------------------
    # PIPELINE END-TO-END (RUN ALL)
    # -------------------------------------------------------------------------
    def run_all(self, reset_first: bool = False, force: bool = False) -> bool:
        print_banner()
        print(f"{Style.BOLD}🚀 EXECUTANDO PIPELINE END-TO-END COMPLETO{Style.RESET}\n")

        if reset_first:
            self.reset(force=force)

        # 1. Scraping das 4 fontes
        if not self.scrape_all():
            return False

        # 2. Carga no banco
        if not self.load_all():
            return False

        # 3. Cruzamento
        if not self.match():
            return False

        # 4. Status final
        self.show_status()
        print(f"\n{Style.GREEN}{Style.BOLD}✨ PIPELINE EXECUTADO COM SUCESSO DE PONTA A PONTA! ✨{Style.RESET}\n")
        return True

    # -------------------------------------------------------------------------
    # SERVIDOR FASTAPI & DASHBOARD WEB
    # -------------------------------------------------------------------------
    def start_api(self, host: str = "127.0.0.1", port: int = 8000, reload: bool = True, open_browser: bool = False):
        import threading
        import webbrowser

        print_banner()
        print(f"{Style.BOLD}Iniciando Plataforma de Inteligência e Scouting...{Style.RESET}")
        print(f"  {Style.GREEN}● Dashboard Visual:{Style.RESET} http://{host}:{port}/dashboard")
        print(f"  {Style.CYAN}● Documentação API:{Style.RESET} http://{host}:{port}/docs\n")

        if open_browser:
            def _open():
                time.sleep(1.8)
                webbrowser.open(f"http://{host}:{port}/dashboard")
            threading.Thread(target=_open, daemon=True).start()

        cmd = [self.py_exec, "-m", "uvicorn", "api.main:app", "--host", host, "--port", str(port)]
        if reload:
            cmd.append("--reload")
        try:
            subprocess.run(cmd, cwd=BASE_DIR)
        except KeyboardInterrupt:
            print(f"\n{Style.BLUE}[*] Servidor encerrado pelo usuário.{Style.RESET}")


def main():
    parser = argparse.ArgumentParser(
        description="Scout Data Scraper & Analytics - Pipeline Orchestrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="Comando a ser executado")

    # status
    subparsers.add_parser("status", help="Exibe o status do banco de dados e arquivos locais de coleta")

    # reset
    parser_reset = subparsers.add_parser("reset", help="Limpa coletas e/ou reinicializa o banco de dados")
    parser_reset.add_argument("--force", action="store_true", help="Não solicita confirmação interativa")
    parser_reset.add_argument("--db-only", action="store_true", help="Limpa apenas o banco de dados scout.db")
    parser_reset.add_argument("--scrapers-only", action="store_true", help="Limpa apenas os arquivos dos scrapers")

    # scrape
    parser_scrape = subparsers.add_parser("scrape", help="Executa a coleta de dados de uma ou todas as fontes")
    parser_scrape.add_argument(
        "source",
        choices=["all", "sofascore", "fbref", "transfermarkt", "whoscored"],
        help="Fonte alvo a ser coletada"
    )

    # load
    parser_load = subparsers.add_parser("load", help="Carrega os dados coletados no banco de dados scout.db")
    parser_load.add_argument(
        "source",
        choices=["all", "sofascore", "fbref", "transfermarkt", "whoscored"],
        help="Fonte de dados para carga no banco"
    )

    # match
    subparsers.add_parser("match", help="Executa o algoritmo de resolução e cruzamento de identidades")

    # run-all
    parser_run_all = subparsers.add_parser("run-all", help="Executa todo o pipeline de ponta a ponta")
    parser_run_all.add_argument("--reset", action="store_true", help="Executa a limpeza prévia antes da coleta")
    parser_run_all.add_argument("--force", action="store_true", help="Força a execução sem confirmações interativas")

    # api
    parser_api = subparsers.add_parser("api", help="Inicia o servidor FastAPI local")
    parser_api.add_argument("--host", default="127.0.0.1", help="Host para bind (padrão: 127.0.0.1)")
    parser_api.add_argument("--port", type=int, default=8000, help="Porta HTTP (padrão: 8000)")
    parser_api.add_argument("--no-reload", action="store_true", help="Desativa hot reload automático")

    # dashboard
    parser_dash = subparsers.add_parser("dashboard", help="Inicia o servidor e abre o Dashboard no navegador")
    parser_dash.add_argument("--host", default="127.0.0.1", help="Host para bind (padrão: 127.0.0.1)")
    parser_dash.add_argument("--port", type=int, default=8000, help="Porta HTTP (padrão: 8000)")
    parser_dash.add_argument("--no-reload", action="store_true", help="Desativa hot reload automático")

    args = parser.parse_args()
    orchestrator = PipelineOrchestrator()

    if not args.command or args.command == "status":
        orchestrator.show_status()
    elif args.command == "reset":
        orchestrator.reset(force=args.force, db_only=args.db_only, scrapers_only=args.scrapers_only)
    elif args.command == "scrape":
        if args.source == "all":
            orchestrator.scrape_all()
        elif args.source == "sofascore":
            orchestrator.scrape_sofascore()
        elif args.source == "fbref":
            orchestrator.scrape_fbref()
        elif args.source == "transfermarkt":
            orchestrator.scrape_transfermarkt()
        elif args.source == "whoscored":
            orchestrator.scrape_whoscored()
    elif args.command == "load":
        if args.source == "all":
            orchestrator.load_all()
        else:
            orchestrator.load_source(args.source)
    elif args.command == "match":
        orchestrator.match()
    elif args.command == "run-all":
        orchestrator.run_all(reset_first=args.reset, force=args.force)
    elif args.command == "api":
        orchestrator.start_api(host=args.host, port=args.port, reload=not args.no_reload)
    elif args.command == "dashboard":
        orchestrator.start_api(host=args.host, port=args.port, reload=not args.no_reload, open_browser=True)


if __name__ == "__main__":
    main()
