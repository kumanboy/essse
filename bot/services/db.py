import ssl
import asyncpg


async def create_pool(config):
    return await asyncpg.create_pool(
        config.database_url, min_size=1, max_size=5, command_timeout=30,
        ssl=ssl.create_default_context() if config.database_ssl else False,
        statement_cache_size=0,
    )
