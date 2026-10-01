import logging
from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

log = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


def _make_engine(url: str):
    kwargs = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(url, **kwargs)


engine = _make_engine(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class CatalogBase(DeclarativeBase):
    """Tables of the separate FlowAccount catalog database (products, product sets)."""


def _catalog_engine(url: str):
    if url.startswith("sqlite:///") and not url.startswith("sqlite:///:memory:"):
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    return _make_engine(url)


catalog_engine = _catalog_engine(get_settings().catalog_database_url)
CatalogSession = sessionmaker(bind=catalog_engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    from app import models  # noqa: F401  (register tables)

    Base.metadata.create_all(engine)
    _add_missing_columns(Base, engine)
    init_catalog_db()


def init_catalog_db() -> None:
    from app import catalog_models  # noqa: F401  (register tables)

    CatalogBase.metadata.create_all(catalog_engine)
    _add_missing_columns(CatalogBase, catalog_engine)
    _move_catalog_from_main_db()


_CATALOG_TABLES = ("products", "product_sets", "product_set_items")  # parents first


def _move_catalog_from_main_db() -> None:
    """Copy products and sets saved before the catalog had its own file, once (the old tables are left as they were)."""
    old = inspect(engine)
    if not old.has_table("product_sets") or engine.url == catalog_engine.url:
        return
    with catalog_engine.begin() as dst:
        if dst.execute(text("SELECT COUNT(*) FROM product_sets")).scalar() or dst.execute(text("SELECT COUNT(*) FROM products")).scalar():
            return  # already moved, or the catalog has its own data
        new_columns = {t: {c["name"] for c in inspect(catalog_engine).get_columns(t)} for t in _CATALOG_TABLES}
        moved = 0
        with engine.connect() as src:
            for table in _CATALOG_TABLES:
                if not old.has_table(table):
                    continue
                for row in src.execute(text(f"SELECT * FROM {table}")).mappings():
                    values = {k: v for k, v in row.items() if k in new_columns[table]}
                    cols = ", ".join(values)
                    dst.execute(text(f"INSERT INTO {table} ({cols}) VALUES ({', '.join(':' + c for c in values)})"), values)
                    moved += 1
        if moved:
            log.info("moved %d product/set rows into the catalog database %s", moved, catalog_engine.url)


def _add_missing_columns(base: type[DeclarativeBase], bind) -> None:
    """Tiny forward-only migration: add columns that newer code defines to existing tables.

    create_all() only creates missing tables, so databases made by an older version
    would otherwise lack new columns. Adds nullable columns and ones with a server_default.
    """
    inspector = inspect(bind)
    with bind.begin() as conn:
        for table in base.metadata.sorted_tables:
            if not inspector.has_table(table.name):
                continue
            existing = {c["name"] for c in inspector.get_columns(table.name)}
            for col in table.columns:
                if col.name in existing:
                    continue
                col_type = col.type.compile(dialect=bind.dialect)
                if col.server_default is not None:
                    extra = f"DEFAULT {col.server_default.arg} NOT NULL"
                elif col.nullable:
                    extra = ""
                else:
                    continue  # can't add a required column without a default
                conn.execute(text(f"ALTER TABLE {table.name} ADD COLUMN {col.name} {col_type} {extra}".rstrip()))
                log.info("added column %s.%s", table.name, col.name)


def get_catalog_db() -> Iterator[Session]:
    db = CatalogSession()
    try:
        yield db
    finally:
        db.close()


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
