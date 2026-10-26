"""Configurações centrais (caminhos, banco de dados e diretórios)."""
import os
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, '.env'))

DB_PATH = os.getenv("DB_PATH", os.path.join(BASE_DIR, 'scout.db'))
DB_URL = os.getenv("DATABASE_URL", f"sqlite:///{DB_PATH}")

# Diretórios de dados brutos e checkpoints dos scrapers
FBREF_DATA_DIR = os.path.join(BASE_DIR, 'scrapers', 'fbref', 'data')
SOFASCORE_DATA_DIR = os.path.join(BASE_DIR, 'data', 'sofascore')
TRANSFERMARKT_DATA_DIR = os.path.join(BASE_DIR, 'scrapers', 'transfermarkt', 'data')
WHOSCORED_DATA_DIR = os.path.join(BASE_DIR, 'scrapers', 'whoscored', 'data')
