import asyncio
import os
import sys
from urllib.parse import urlparse

import pytest
from sqlalchemy import text
from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

test_db_url = os.environ.get("TEST_DATABASE_URL")
if not test_db_url:
    raise RuntimeError(
        "TEST_DATABASE_URL environment variable must be set to run the test suite. "
        "Never run tests against the dev database."
    )

parsed = urlparse(test_db_url)
db_name = parsed.path.lstrip("/").lower()
if "test" not in db_name and "test" not in test_db_url.lower():
    raise RuntimeError(
        f"Safety assertion failed: TEST_DATABASE_URL '{test_db_url}' (database name "
        f"'{db_name}') must contain 'test'. Refusing to run tests against a non-test database."
    )

os.environ["DATABASE_URL"] = test_db_url

from backend.app import database as db_mod  # noqa: E402
import backend.app.models as backend  # noqa: E402  (register all models)
from backend.app.database import Base  # noqa: E402

db_mod.engine = create_async_engine(test_db_url, echo=False, future=True, poolclass=NullPool)
db_mod.AsyncSessionLocal = async_sessionmaker(
    bind=db_mod.engine, class_=AsyncSession, expire_on_commit=False, autocommit=False, autoflush=False
)

engine = db_mod.engine

assert "test" in (engine.url.database or "").lower(), (
    f"Safety violation: test engine database '{engine.url.database}' does not contain 'test'!"
)
assert (engine.url.database or "").lower() != "candidly ai", (
    "Safety violation: test engine is pointed at production/dev database 'Candidly AI'!"
)


@pytest.fixture(scope="session", autouse=True)
def setup_test_database_schema():
    """Create schema in the test database at session start and drop at session end."""
    assert "test" in (engine.url.database or "").lower(), "Safety violation in setup_test_database_schema"

    async def _init_schema():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_init_schema())
    yield

    async def _teardown_schema():
        """DROP SCHEMA public CASCADE;"""
        async with engine.begin() as conn:
            if engine.dialect.name == "postgresql":
                await conn.execute(text("DROP SCHEMA public CASCADE;"))
                await conn.execute(text("CREATE SCHEMA public;"))
            else:
                await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()

    asyncio.run(_teardown_schema())


@pytest.fixture(autouse=True)
def clean_test_database_after_test():
    """Per-test cleanup fixture that truncates test database tables without deleting by department."""
    yield

    assert "test" in (engine.url.database or "").lower(), (
        f"Refusing to clean non-test database: {engine.url.database}"
    )

    async def _truncate_all_tables():
        """ TRUNCATE ... RESTART IDENTITY CASCADE;"""
        async with engine.begin() as conn:
            if engine.dialect.name == "postgresql":
                table_names = [f'"{t.name}"' for t in Base.metadata.tables.values()]
                sql = f"TRUNCATE TABLE {', '.join(table_names)} RESTART IDENTITY CASCADE;"
                await conn.execute(text(sql))
            else:
                for table in reversed(Base.metadata.sorted_tables):
                    await conn.execute(table.delete())

    asyncio.run(_truncate_all_tables())
