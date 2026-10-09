import asyncio
import json
import logging
from aiogram.types import Update
from bot.services.storage import fsm_connection

log = logging.getLogger(__name__)


class Inbox:
    def __init__(self, pool, dispatcher, bot):
        self.pool, self.dispatcher, self.bot = pool, dispatcher, bot

    async def receive(self, update: Update, raw_update: dict):
        event = update.message or update.callback_query
        if event is None or event.from_user is None:
            return
        message = update.message or update.callback_query.message
        if message is None or message.chat.type != "private" or message.chat.id != event.from_user.id:
            return
        await self.pool.execute("""INSERT INTO telegram_updates(update_id,user_id,payload)
            VALUES($1,$2,$3::jsonb) ON CONFLICT DO NOTHING""",
            update.update_id, event.from_user.id,
            json.dumps(raw_update, ensure_ascii=False))
        log.debug("webhook_received update=%s", update.update_id)

    async def process_one(self):
        # Hold a row lock through the short handler, not through evaluation.
        # Earlier pending updates prevent another worker overtaking the same user.
        update_id = None
        try:
            async with self.pool.acquire() as conn, conn.transaction():
                row = await conn.fetchrow("""SELECT u.* FROM telegram_updates u
                    WHERE u.status='pending' AND u.next_attempt_at<=now()
                    AND NOT EXISTS (SELECT 1 FROM telegram_updates earlier
                        WHERE earlier.user_id=u.user_id AND earlier.update_id<u.update_id
                        AND earlier.status='pending')
                    ORDER BY u.update_id FOR UPDATE SKIP LOCKED LIMIT 1""")
                if not row:
                    return False
                update_id = row["update_id"]
                token = fsm_connection.set(conn)
                try:
                    # Bind the bot during validation, so aiogram's dispatcher
                    # does not re-serialize the Update to mount bot context.
                    update = Update.model_validate(json.loads(row["payload"]), context={"bot": self.bot})
                    async with asyncio.timeout(60):
                        await self.dispatcher.feed_update(self.bot, update)
                    await conn.execute("UPDATE telegram_updates SET status='done',payload=NULL WHERE update_id=$1", update_id)
                finally:
                    fsm_connection.reset(token)
            return True
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if update_id is None:
                raise
            # Transaction rollback keeps draft state coherent with a replayed update.
            await self.pool.execute("""UPDATE telegram_updates SET attempt_count=attempt_count+1,
                status=CASE WHEN attempt_count>=4 THEN 'failed' ELSE 'pending' END,
                payload=CASE WHEN attempt_count>=4 THEN NULL ELSE payload END,
                next_attempt_at=now()+interval '30 seconds' WHERE update_id=$1 AND status='pending'""", update_id)
            log.warning("update_retry update=%s error_type=%s", update_id, type(exc).__name__)
            return True
