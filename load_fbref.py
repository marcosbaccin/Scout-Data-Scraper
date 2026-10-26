"""
FBref Data Loader
Carrega os dados processados e estruturados do FBref para o banco de dados scout.db.
Utiliza pipelines.cleaner para executar a normalização das estatísticas exclusivas.
"""
from pipelines.cleaner import process_players

if __name__ == "__main__":
    process_players()
