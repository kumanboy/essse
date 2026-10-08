import os
from pathlib import Path
from uuid import uuid4
import asyncpg
import pytest_asyncio
import pytest


@pytest_asyncio.fixture
async def pool():
    url=os.getenv('TEST_DATABASE_URL')
    if not url:
        pytest.skip('TEST_DATABASE_URL is not set; PostgreSQL integration test skipped')
    # Each test owns a separate schema; never truncate an existing database.
    schema='test_'+uuid4().hex
    admin=await asyncpg.connect(url)
    await admin.execute(f'CREATE SCHEMA {schema}')
    pool=await asyncpg.create_pool(url,min_size=1,max_size=8,server_settings={'search_path':schema})
    migration=Path('migrations/001_persistent_workflow.sql').read_text(encoding='utf-8')
    await pool.execute(migration)
    await pool.execute("UPDATE bot_settings SET access_start=now()-interval '1 hour'")
    try:
        yield pool
    finally:
        await pool.close()
        await admin.execute(f'DROP SCHEMA {schema} CASCADE')
        await admin.close()
