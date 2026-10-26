"""Engine, sessão e inicialização do banco único `scout.db`."""
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from core.models import Base
from core.settings import DB_URL
from core.views import VIEWS

engine = create_engine(DB_URL)


@event.listens_for(engine, "connect")
def _enable_sqlite_fk(dbapi_connection, _):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(bind=engine)


def init_db():
    """Cria as tabelas (se não existirem) e recria as views de métricas derivadas."""
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        for name, select_sql in VIEWS.items():
            conn.execute(text(f"DROP VIEW IF EXISTS {name}"))
            conn.execute(text(f"CREATE VIEW {name} AS {select_sql}"))


def get_session():
    init_db()
    return SessionLocal()
