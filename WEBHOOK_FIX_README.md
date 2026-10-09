# Telegram webhook serialization fix (October 2026)

## Problem

The Render log showed:

`pydantic_core.PydanticSerializationError: Unable to serialize unknown type: <class 'aiogram.client.default.Default'>`

`bot/services/inbox.py` attempted to JSON-serialize an `aiogram.types.Update` with
`update.model_dump_json(exclude_none=True)`. Some received Telegram objects contain
framework-internal `Default` placeholders, which are not JSON serializable.
The `/telegram/webhook` endpoint consequently returned a server error and never
inserted the message into `telegram_updates`.

## Fix

- `bot/main.py`: Parse and validate the incoming Telegram JSON while preserving its
  original dictionary; pass it along with the validated Update to the inbox.
- `bot/services/inbox.py`: Insert JSON constructed from the **original wire dictionary**
  instead of serializing the aiogram model. This preserves Unicode and received fields.
- `bot/services/inbox.py`: On replay, validate the stored update with
  `context={"bot": self.bot}` so aiogram need not model-dump it again to mount bot context.
- Added and adjusted regression tests in `tests/`.

## Deploy

1. Commit/push the updated code to the branch Render deploys (or deploy the ZIP code).
2. Verify deployment completes and `/health` responds with `{"status":"ok"}`.
3. Send `/start` and `📝 Esse tekshirish` to the bot.
4. In Render logs, look for `POST /telegram/webhook ... 200 OK` and no
   `PydanticSerializationError`.
5. In Neon SQL editor check fresh updates:

```sql
SELECT update_id, status, attempt_count,
       created_at AT TIME ZONE 'Asia/Tashkent' AS received_time
FROM telegram_updates
ORDER BY update_id DESC LIMIT 10;
```

Do not reset the Telegram webhook with `drop_pending_updates=true` unless you
intentionally want to discard queued messages. Existing `set_webhook` uses false.

## Validation caveat

The fixed Python files were checked for syntax in the sandbox. Runtime testing
against aiogram and PostgreSQL requires the project's pinned dependencies and a
separate test database. No production database or live Telegram bot was modified.
