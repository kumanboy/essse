import json
from contextvars import ContextVar
from aiogram.fsm.storage.base import BaseStorage, DefaultKeyBuilder, StorageKey
from aiogram.fsm.state import State

fsm_connection = ContextVar("fsm_connection", default=None)


class PostgresStorage(BaseStorage):
    """Draft-only FSM; essay processing lives in essay_jobs."""
    def __init__(self, pool):
        self.pool = pool
        self.keys = DefaultKeyBuilder(with_bot_id=True, with_destiny=True)

    @property
    def db(self):
        return fsm_connection.get() or self.pool

    async def set_state(self, key: StorageKey, state=None):
        value = state.state if isinstance(state, State) else state
        await self.db.execute("""INSERT INTO fsm_state(key,state) VALUES($1,$2)
            ON CONFLICT(key) DO UPDATE SET state=$2, updated_at=now()""", self.keys.build(key), value)

    async def get_state(self, key: StorageKey):
        return await self.db.fetchval("SELECT state FROM fsm_state WHERE key=$1", self.keys.build(key))

    async def set_data(self, key: StorageKey, data):
        await self.db.execute("""INSERT INTO fsm_state(key,data) VALUES($1,$2::jsonb)
            ON CONFLICT(key) DO UPDATE SET data=$2::jsonb, updated_at=now()""",
            self.keys.build(key), json.dumps(data, ensure_ascii=False))

    async def get_data(self, key: StorageKey):
        value = await self.db.fetchval("SELECT data FROM fsm_state WHERE key=$1", self.keys.build(key))
        return json.loads(value) if value else {}

    async def close(self):
        pass  # Pool belongs to application lifespan.
