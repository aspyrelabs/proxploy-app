from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from proxploy.config import Settings


def make_engine(settings: Settings):
    engine = create_engine(settings.db_url)
    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _rec):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()
    return engine


def make_sessionmaker(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)


def run_migrations(settings: Settings) -> None:
    cfg = AlembicConfig()
    cfg.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    # Alembic stores this in a ConfigParser, which treats "%" as interpolation
    # syntax. A Postgres DSN whose password contains "%": ordinary for a
    # generated password: otherwise fails at startup with
    # `ValueError: invalid interpolation syntax in '<the whole DSN>'`, printing
    # the password in the traceback. Escaping is alembic's documented answer and
    # incidentally makes such a password work at all.
    cfg.set_main_option("sqlalchemy.url", settings.db_url.replace("%", "%%"))
    command.upgrade(cfg, "head")
