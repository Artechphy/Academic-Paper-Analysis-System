"""Use an isolated migrated PostgreSQL schema or an in-memory SQLite database."""

import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import JSON, MetaData, create_engine, event, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db.base import Base
from app.db.seed import seed_builtin_templates
from app.db.session import get_db
from app.main import app


def _install_sqlite_schema(engine):
    metadata = MetaData()
    for original in Base.metadata.sorted_tables:
        table = original.to_metadata(metadata)
        for column in table.columns:
            if isinstance(column.type, JSONB):
                column.type = JSON(none_as_null=column.type.none_as_null)
                if column.server_default is not None:
                    column.server_default.arg = text(str(column.server_default.arg).removesuffix("::jsonb"))
        for index in table.indexes:
            predicate = index.dialect_options["postgresql"].get("where")
            if predicate is not None:
                index.dialect_options["sqlite"]["where"] = predicate
    metadata.create_all(engine)

    with engine.begin() as connection:
        for event_name, affected in (
            ("INSERT", "NEW.batch_id"),
            ("UPDATE", "OLD.batch_id, NEW.batch_id"),
            ("DELETE", "OLD.batch_id"),
        ):
            connection.exec_driver_sql(f"""
                CREATE TRIGGER sync_check_batch_counts_{event_name.lower()}
                AFTER {event_name} ON check_runs
                BEGIN
                    UPDATE check_batches
                    SET (total_count, pass_count, fail_count, error_count) = (
                        SELECT COUNT(*),
                               COUNT(*) FILTER (WHERE verdict = 'pass'),
                               COUNT(*) FILTER (WHERE verdict = 'fail'),
                               COUNT(*) FILTER (WHERE verdict = 'error')
                        FROM check_runs
                        WHERE batch_id = check_batches.id
                    )
                    WHERE id IN ({affected});
                END
            """)
        connection.exec_driver_sql("""
            CREATE VIEW v_batch_summary AS
            SELECT batch.id AS batch_id,
                   batch.name, batch.rule_set_id, batch.status, batch.created_at, batch.completed_at,
                   batch.total_count, batch.pass_count, batch.fail_count, batch.error_count,
                   COALESCE(1.0 * batch.pass_count / NULLIF(batch.total_count, 0), 0) AS pass_rate,
                   ROUND(AVG(run.score), 2) AS avg_score,
                   ROUND(AVG(run.duration_ms), 2) AS avg_duration_ms
            FROM check_batches AS batch
            LEFT JOIN check_runs AS run ON run.batch_id = batch.id
            GROUP BY batch.id
        """)
        connection.exec_driver_sql("""
            CREATE VIEW v_rule_violation_stats AS
            SELECT violation.rule_code,
                   MIN(violation.rule_name) AS rule_name,
                   MIN(violation.category) AS category,
                   COUNT(*) AS violation_count,
                   COUNT(DISTINCT run.paper_id) AS affected_paper_count,
                   1.0 * COUNT(*) / SUM(COUNT(*)) OVER () AS violation_ratio,
                   DENSE_RANK() OVER (ORDER BY COUNT(*) DESC) AS violation_rank
            FROM check_violations AS violation
            LEFT JOIN check_runs AS run ON run.id = violation.check_run_id
            GROUP BY violation.rule_code
        """)


@pytest.fixture
def db_engine():
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        engine = create_engine(
            "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
        )

        @event.listens_for(engine, "connect")
        def enforce_foreign_keys(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")

        try:
            _install_sqlite_schema(engine)
            yield engine
        finally:
            engine.dispose()
        return

    url = make_url(database_url)
    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+psycopg")
    schema = f"test_api_{uuid4().hex}"
    admin = create_engine(url)
    try:
        with admin.begin() as connection:
            connection.exec_driver_sql(f"CREATE SCHEMA {schema}")
        engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
        try:
            config = Config(Path(__file__).resolve().parents[1] / "alembic.ini")
            with engine.begin() as connection:
                config.attributes["connection"] = connection
                command.upgrade(config, "head")
            yield engine
        finally:
            engine.dispose()
            with admin.begin() as connection:
                connection.exec_driver_sql(f"DROP SCHEMA {schema} CASCADE")
    finally:
        admin.dispose()


@pytest.fixture
def db_sessions(db_engine):
    sessions = sessionmaker(db_engine, expire_on_commit=False)
    with sessions.begin() as session:
        seed_builtin_templates(session)
    return sessions


@pytest.fixture
def client(db_sessions, tmp_path, monkeypatch):
    def override_db():
        with db_sessions() as session:
            yield session

    monkeypatch.setattr(settings, "storage_dir", tmp_path / "storage")
    monkeypatch.setitem(app.dependency_overrides, get_db, override_db)
    with TestClient(app) as test_client:
        yield test_client
