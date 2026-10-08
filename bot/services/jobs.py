import logging
from datetime import timedelta
from uuid import uuid4
import asyncpg
from bot.services.access import is_available
from bot.services.results import split_result

log = logging.getLogger(__name__)
ACTIVE = ("pending", "processing", "ready", "sending")
ACCEPTED = "✅ Essengiz qabul qilindi.\n\nEssengiz UZBMB baholash mezonlari asosida batafsil tekshirilmoqda.\n\n⏳ Tekshiruv natijasi 10 daqiqadan so‘ng, tekshiruv yakunlangach, ushbu chatga avtomatik yuboriladi."
FAILURE = "⚠️ Esseni tekshirishda texnik nosozlik yuz berdi.\n\nIltimos, birozdan so‘ng qayta urinib ko‘ring."


def send_after(submitted_at):
    if submitted_at.tzinfo is None:
        raise ValueError("Timezone required")
    return submitted_at + timedelta(minutes=10)


class ServiceClosed(Exception):
    pass


class ActiveJob(Exception):
    pass


class Jobs:
    def __init__(self, pool):
        self.pool = pool

    async def active(self, user_id: int) -> bool:
        return await self.pool.fetchval("SELECT EXISTS(SELECT 1 FROM essay_jobs WHERE user_id=$1 AND status=ANY($2::text[]))", user_id, list(ACTIVE))

    async def submit(self, user_id: int, chat_id: int, topic: str, essay: str, update_id: int):
        if user_id != chat_id:
            raise ValueError("Private chats only")
        try:
            async with self.pool.acquire() as conn, conn.transaction():
                previous = await conn.fetchrow("SELECT * FROM essay_jobs WHERE source_update_id=$1", update_id)
                if previous:
                    return previous
                # Serialize schedule changes against the final acceptance check.
                settings = await conn.fetchrow("SELECT *, clock_timestamp() AS db_now FROM bot_settings WHERE id=1 FOR SHARE")
                if not is_available(settings, settings["db_now"]):
                    log.info("access_denied user=%s", user_id)
                    raise ServiceClosed()
                job = await conn.fetchrow("""INSERT INTO essay_jobs(user_id,chat_id,topic,essay_text,source_update_id,submitted_at,send_after)
                    VALUES($1,$2,$3,$4,$5,clock_timestamp(),clock_timestamp()+interval '10 minutes') RETURNING *""",
                    user_id, chat_id, topic, essay, update_id)
                await conn.execute("INSERT INTO delivery_parts(job_id,kind,part_no,text) VALUES($1,'acceptance',0,$2)", job["id"], ACCEPTED)
                log.info("essay_submitted job=%s", job["id"])
                return job
        except asyncpg.UniqueViolationError:
            raise ActiveJob() from None

    async def recover(self):
        async with self.pool.acquire() as conn, conn.transaction():
            await conn.execute("""UPDATE essay_jobs SET status=CASE WHEN result_text IS NULL THEN 'pending' ELSE 'ready' END,
                lease_token=NULL, lease_until=NULL, updated_at=now()
                WHERE status='processing' AND lease_until < now()""")
            # A send may have reached Telegram. Never blindly replay an uncertain send.
            stale = await conn.fetch("""UPDATE delivery_parts SET status='uncertain'
                WHERE status='sending' AND lease_until < now() RETURNING job_id,kind""")
            for row in stale:
                if row["kind"] == "result":
                    await self._fail(conn, row["job_id"], "delivery_outcome_unknown")
            exhausted = await conn.fetch("SELECT id FROM essay_jobs WHERE status='pending' AND attempt_count>=3 FOR UPDATE SKIP LOCKED")
            for row in exhausted:
                await self._fail(conn, row["id"], "evaluation_attempts_exhausted")

    async def _fail(self, conn, job_id, reason):
        await conn.execute("UPDATE essay_jobs SET status='failed',error_message=$2,lease_token=NULL,lease_until=NULL,updated_at=now() WHERE id=$1 AND status<>'sent'", job_id, reason)
        await conn.execute("UPDATE delivery_parts SET status='failed' WHERE job_id=$1 AND kind='result' AND status='pending'", job_id)
        await conn.execute("""INSERT INTO delivery_parts(job_id,kind,part_no,text) VALUES($1,'failure',0,$2)
            ON CONFLICT DO NOTHING""", job_id, FAILURE)

    async def claim_evaluation(self):
        token = uuid4()
        return await self.pool.fetchrow("""WITH candidate AS (
            SELECT id FROM essay_jobs WHERE status='pending' AND attempt_count<3 AND next_attempt_at<=now()
            ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1)
            UPDATE essay_jobs j SET status='processing', attempt_count=attempt_count+1,
            evaluation_started_at=now(), lease_token=$1, lease_until=now()+interval '8 minutes', updated_at=now()
            FROM candidate c WHERE j.id=c.id RETURNING j.*""", token)

    async def complete(self, job, text):
        async with self.pool.acquire() as conn, conn.transaction():
            updated = await conn.fetchval("""UPDATE essay_jobs SET result_text=$3,status='ready',evaluation_completed_at=now(),
                lease_until=NULL,lease_token=NULL,updated_at=now() WHERE id=$1 AND lease_token=$2 AND status='processing' RETURNING id""",
                job["id"], job["lease_token"], text)
            if updated:
                for index, part in enumerate(split_result(text)):
                    await conn.execute("""INSERT INTO delivery_parts(job_id,kind,part_no,text)
                        VALUES($1,'result',$2,$3) ON CONFLICT DO NOTHING""", job["id"], index, part)
                log.info("evaluation_completed job=%s", job["id"])

    async def evaluation_error(self, job, permanent: bool, reason: str):
        async with self.pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow("SELECT * FROM essay_jobs WHERE id=$1 AND lease_token=$2 AND status='processing' FOR UPDATE", job["id"], job["lease_token"])
            if not row:
                return
            if permanent or row["attempt_count"] >= 3:
                await self._fail(conn, job["id"], reason)
                log.warning("evaluation_failed job=%s reason=%s", job["id"], reason)
            else:
                await conn.execute("""UPDATE essay_jobs SET status='pending',lease_token=NULL,lease_until=NULL,error_message=$2,
                    next_attempt_at=now()+$3*interval '1 second',updated_at=now() WHERE id=$1""",
                    job["id"], reason, 30 * 2 ** row["attempt_count"])

    async def claim_delivery(self):
        async with self.pool.acquire() as conn, conn.transaction():
            part = await conn.fetchrow("""SELECT d.*,j.chat_id FROM delivery_parts d JOIN essay_jobs j ON j.id=d.job_id
                WHERE d.status='pending' AND d.next_attempt_at<=now()
                AND (d.kind<>'result' OR (j.status IN ('ready','sending') AND j.send_after<=clock_timestamp() AND j.sent_at IS NULL))
                AND NOT EXISTS(SELECT 1 FROM delivery_parts earlier WHERE earlier.job_id=d.job_id
                    AND earlier.kind=d.kind AND earlier.part_no<d.part_no AND earlier.status<>'sent')
                ORDER BY CASE d.kind WHEN 'acceptance' THEN 0 WHEN 'failure' THEN 1 ELSE 2 END,d.id
                FOR UPDATE OF d SKIP LOCKED LIMIT 1""")
            if not part:
                return None
            token = uuid4()
            await conn.execute("""UPDATE delivery_parts SET status='sending',attempt_count=attempt_count+1,
                lease_token=$2,lease_until=now()+interval '2 minutes' WHERE id=$1""", part["id"], token)
            if part["kind"] == "result":
                await conn.execute("UPDATE essay_jobs SET status='sending',updated_at=now() WHERE id=$1", part["job_id"])
            return dict(part) | {"lease_token": token, "attempt_count": part["attempt_count"] + 1}

    async def delivered(self, part, message_id):
        async with self.pool.acquire() as conn, conn.transaction():
            changed = await conn.fetchval("""UPDATE delivery_parts SET status='sent',telegram_message_id=$3,lease_until=NULL
                WHERE id=$1 AND lease_token=$2 AND status='sending' RETURNING id""", part["id"], part["lease_token"], message_id)
            if changed and part["kind"] == "result":
                await conn.execute("""UPDATE essay_jobs SET status='sent',sent_at=now(),updated_at=now()
                    WHERE id=$1 AND status='sending' AND NOT EXISTS(
                    SELECT 1 FROM delivery_parts WHERE job_id=$1 AND kind='result' AND status<>'sent')""", part["job_id"])
            log.info("message_sent job=%s kind=%s part=%s", part["job_id"], part["kind"], part["part_no"])

    async def delivery_error(self, part, *, retry_after=None, uncertain=False):
        async with self.pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow("SELECT id FROM delivery_parts WHERE id=$1 AND lease_token=$2 AND status='sending' FOR UPDATE", part["id"], part["lease_token"])
            if not row:
                return
            retry = retry_after is not None and part["attempt_count"] < 5
            status = "pending" if retry else "uncertain" if uncertain else "failed"
            await conn.execute("""UPDATE delivery_parts SET status=$2,lease_until=NULL,
                next_attempt_at=now()+$3*interval '1 second' WHERE id=$1""", part["id"], status, float(retry_after or 0))
            if not retry and part["kind"] == "result":
                await self._fail(conn, part["job_id"], "delivery_outcome_unknown" if uncertain else "delivery_failed")
            log.warning("delivery_%s job=%s part=%s", status, part["job_id"], part["part_no"])
