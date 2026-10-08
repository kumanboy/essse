import asyncio
import logging
from aiogram.exceptions import TelegramRetryAfter, TelegramForbiddenError, TelegramBadRequest, TelegramNetworkError, TelegramServerError
from openai import APIStatusError, APIConnectionError, APITimeoutError

log = logging.getLogger(__name__)


class Workers:
    def __init__(self, jobs, checker, bot, inbox):
        self.jobs, self.checker, self.bot, self.inbox = jobs, checker, bot, inbox
        self.tasks = []
        self.wakeup = asyncio.Event()

    async def evaluate_one(self):
        job = await self.jobs.claim_evaluation()
        if not job:
            return False
        log.info("evaluation_started job=%s", job["id"])
        try:
            async with asyncio.timeout(360):
                text = await self.checker.check(job["topic"], job["essay_text"])
            await self.jobs.complete(job, text)
        except asyncio.CancelledError:
            raise  # Lease recovery handles interrupted attempts.
        except APIStatusError as exc:
            permanent = exc.status_code not in {408, 409, 429} and exc.status_code < 500
            await self.jobs.evaluation_error(job, permanent, f"api_status_{exc.status_code}")
        except (APIConnectionError, APITimeoutError, TimeoutError, ValueError) as exc:
            await self.jobs.evaluation_error(job, False, type(exc).__name__)
        except Exception as exc:
            await self.jobs.evaluation_error(job, False, type(exc).__name__)
        return True

    async def deliver_one(self):
        part = await self.jobs.claim_delivery()
        if not part:
            return False
        try:
            # No automatic HTTP retries: uncertain delivery must never be replayed.
            sent = await self.bot.send_message(part["chat_id"], part["text"], parse_mode=None, request_timeout=30)
        except TelegramRetryAfter as exc:
            await self.jobs.delivery_error(part, retry_after=exc.retry_after + 1)
        except (TelegramForbiddenError, TelegramBadRequest):
            await self.jobs.delivery_error(part)
        except (TelegramNetworkError, TelegramServerError, TimeoutError):
            await self.jobs.delivery_error(part, uncertain=True)
        else:
            # If DB recording fails after send, the reserved part stays 'sending'.
            # Recovery marks it uncertain instead of resending it.
            await self.jobs.delivered(part, sent.message_id)
        return True

    async def loop(self, name, operation, interval=2):
        while True:
            try:
                worked = await operation()
                if worked:
                    continue
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.error("worker_error worker=%s error_type=%s", name, type(exc).__name__)
            try:
                await asyncio.wait_for(self.wakeup.wait(), timeout=interval)
                self.wakeup.clear()
            except TimeoutError:
                pass

    async def start(self):
        await self.jobs.recover()
        for name, op in [("inbox-1", self.inbox.process_one), ("inbox-2", self.inbox.process_one),
                         ("evaluation-1", self.evaluate_one), ("evaluation-2", self.evaluate_one),
                         ("delivery", self.deliver_one)]:
            self.tasks.append(asyncio.create_task(self.loop(name, op), name=name))
        self.tasks.append(asyncio.create_task(self.loop("recovery", self.jobs.recover, 30)))

    async def close(self):
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
