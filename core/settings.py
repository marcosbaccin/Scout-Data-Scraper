"""Configurações centrais (caminhos, banco de dados e diretórios)."""
import os
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, '.env'))

env_db = os.getenv("DB_PATH")
# Prioridade: 1) DB_PATH do ambiente (se existir o arquivo); 2) /data/scout.db (volume docker); 3) scout.db local
if env_db and os.path.exists(env_db):
    DB_PATH = env_db
elif os.path.exists('/data/scout.db'):
    DB_PATH = '/data/scout.db'
elif os.path.exists(os.path.join(BASE_DIR, 'scout.db')):
    DB_PATH = os.path.join(BASE_DIR, 'scout.db')
else:
    DB_PATH = env_db or os.path.join(BASE_DIR, 'scout.db')

DB_URL = os.getenv("DATABASE_URL", f"sqlite:///{DB_PATH}")

# Diretórios de dados brutos e checkpoints dos scrapers
FBREF_DATA_DIR = os.path.join(BASE_DIR, 'scrapers', 'fbref', 'data')
SOFASCORE_DATA_DIR = os.path.join(BASE_DIR, 'data', 'sofascore')
TRANSFERMARKT_DATA_DIR = os.path.join(BASE_DIR, 'scrapers', 'transfermarkt', 'data')
WHOSCORED_DATA_DIR = os.path.join(BASE_DIR, 'scrapers', 'whoscored', 'data')
