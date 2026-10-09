"""Regression test: never serialize Pydantic/aiogram Default placeholders."""
import json
from unittest.mock import AsyncMock
from aiogram.types import Update
from bot.services.inbox import Inbox


async def test_receive_stores_original_telegram_json_without_model_dump(monkeypatch):
    raw = {
        'update_id': 672405334,
        'message': {
            'message_id': 15,
            'date': 1700000000,
            'chat': {'id': 101, 'type': 'private'},
            'from': {'id': 101, 'is_bot': False, 'first_name': 'Test'},
            'text': '📝 Esse tekshirish',
            # Raw Telegram JSON can contain nested optional data.
            'link_preview_options': {'is_disabled': False},
        },
    }
    update = Update.model_validate(raw)

    def broken_serializer(*args, **kwargs):
        raise AssertionError('model_dump_json must not be called for webhook updates')
    monkeypatch.setattr(Update, 'model_dump_json', broken_serializer)

    pool = AsyncMock()
    await Inbox(pool, None, None).receive(update, raw)
    pool.execute.assert_awaited_once()
    query, update_id, user_id, serialized = pool.execute.await_args.args
    assert 'ON CONFLICT DO NOTHING' in query
    assert update_id == raw['update_id']
    assert user_id == 101
    assert json.loads(serialized) == raw
