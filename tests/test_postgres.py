import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from pathlib import Path
from datetime import time
import pytest
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.base import StorageKey
from aiogram.types import Update
from bot.services.jobs import Jobs, ActiveJob, ServiceClosed
from bot.services.access import AccessService
from bot.services.storage import PostgresStorage
from bot.services.inbox import Inbox
from bot.handlers import user, admin
from bot.states import EssayStates

pytestmark=pytest.mark.integration


async def new_job(jobs,uid=101,update=1):
    return await jobs.submit(uid,uid,'Mavzu','so‘z '*100,update)


async def accept(jobs):
    part=await jobs.claim_delivery()
    assert part['kind']=='acceptance'
    await jobs.delivered(part,100)


async def due(pool,job_id):
    await pool.execute("UPDATE essay_jobs SET submitted_at=now()-interval '11 minutes',send_after=now()-interval '1 minute' WHERE id=$1",job_id)


async def test_migration_idempotent_and_unique_concurrent_submission(pool):
    await pool.execute(Path('migrations/001_persistent_workflow.sql').read_text())
    jobs=Jobs(pool)
    result=await asyncio.gather(new_job(jobs,update=1),new_job(jobs,update=2),return_exceptions=True)
    assert sum(isinstance(x,ActiveJob) for x in result)==1
    assert await jobs.active(101)
    row=await pool.fetchrow('SELECT * FROM essay_jobs')
    assert (row['send_after']-row['submitted_at']).total_seconds()>=600
    # Replayed webhook cannot create a second job even after completion.
    assert (await new_job(jobs,update=row['source_update_id']))['id']==row['id']


async def test_final_access_check_and_settings_persistence(pool):
    jobs=Jobs(pool)
    access=AccessService(pool,99)
    await access.update(99,bot_enabled=False,daily_open_time=time(14),free_access_days=4)
    with pytest.raises(ServiceClosed): await new_job(jobs)
    second=AccessService(pool,99)
    assert (await second.get_settings())['daily_open_time']==time(14)
    with pytest.raises(PermissionError): await second.update(100,bot_enabled=True)
    with pytest.raises(ValueError): await second.update(99,daily_close_time=time(14))


async def test_early_ready_restart_then_due_single_claim(pool):
    jobs=Jobs(pool)
    original=await new_job(jobs)
    await accept(jobs)
    claimed=await jobs.claim_evaluation()
    await jobs.complete(claimed,'Result')
    assert await jobs.claim_delivery() is None
    restarted=Jobs(pool)
    await restarted.recover()
    assert await restarted.claim_evaluation() is None
    assert await restarted.claim_delivery() is None
    await due(pool,original['id'])
    claims=await asyncio.gather(restarted.claim_delivery(),jobs.claim_delivery())
    assert sum(x is not None for x in claims)==1
    part=next(x for x in claims if x)
    assert part['chat_id']==101
    await restarted.delivered(part,123)
    assert not await jobs.active(101)
    assert await pool.fetchval('SELECT status FROM essay_jobs')=='sent'
    assert await jobs.claim_delivery() is None


async def test_late_ready_delivers_immediately(pool):
    jobs=Jobs(pool)
    job=await new_job(jobs)
    await accept(jobs)
    await due(pool,job['id'])
    assert await jobs.claim_delivery() is None
    await jobs.complete(await jobs.claim_evaluation(),'Late result')
    assert (await jobs.claim_delivery())['kind']=='result'


async def test_stale_processing_and_fenced_old_worker(pool):
    jobs=Jobs(pool)
    await new_job(jobs)
    old=await jobs.claim_evaluation()
    assert await jobs.claim_evaluation() is None
    await pool.execute("UPDATE essay_jobs SET lease_until=now()-interval '1 second'")
    await jobs.recover()
    fresh=await jobs.claim_evaluation()
    assert fresh['attempt_count']==2
    await jobs.complete(old,'Stale result')
    assert await pool.fetchval('SELECT result_text FROM essay_jobs') is None
    await jobs.complete(fresh,'Fresh result')
    assert await pool.fetchval('SELECT result_text FROM essay_jobs')=='Fresh result'


async def test_failures_release_user_and_notify(pool):
    jobs=Jobs(pool)
    await new_job(jobs)
    await accept(jobs)
    for _ in range(3):
        claim=await jobs.claim_evaluation()
        await jobs.evaluation_error(claim,False,'timeout')
        await pool.execute('UPDATE essay_jobs SET next_attempt_at=now()')
    assert not await jobs.active(101)
    assert await pool.fetchval('SELECT status FROM essay_jobs')=='failed'
    notice=await jobs.claim_delivery()
    assert notice['kind']=='failure'
    await new_job(jobs,update=2)


async def test_stale_send_is_not_replayed(pool):
    jobs=Jobs(pool)
    job=await new_job(jobs)
    await accept(jobs)
    await jobs.complete(await jobs.claim_evaluation(),'Result')
    await due(pool,job['id'])
    part=await jobs.claim_delivery()
    await pool.execute("UPDATE delivery_parts SET lease_until=now()-interval '1 second' WHERE id=$1",part['id'])
    await jobs.recover()
    assert await pool.fetchval('SELECT status FROM delivery_parts WHERE id=$1',part['id'])=='uncertain'
    assert not await jobs.active(101)
    assert (await jobs.claim_delivery())['kind']=='failure'


async def test_multipart_checkpoints_and_rate_limit(pool):
    jobs=Jobs(pool)
    job=await new_job(jobs)
    await accept(jobs)
    await jobs.complete(await jobs.claim_evaluation(),'A'*3000+'\n\n'+'B'*3000)
    await due(pool,job['id'])
    first=await jobs.claim_delivery()
    assert await jobs.claim_delivery() is None
    await jobs.delivery_error(first,retry_after=1)
    assert await jobs.claim_delivery() is None
    await pool.execute('UPDATE delivery_parts SET next_attempt_at=now()')
    first=await jobs.claim_delivery()
    await jobs.delivered(first,200)
    second=await Jobs(pool).claim_delivery()
    assert second['part_no']==1
    await jobs.delivered(second,201)
    assert await pool.fetchval('SELECT status FROM essay_jobs')=='sent'


async def test_storage_survives_new_instance(pool):
    key=StorageKey(bot_id=123,chat_id=101,user_id=101)
    storage=PostgresStorage(pool)
    await storage.set_state(key,EssayStates.waiting_for_essay)
    await storage.set_data(key,{'topic':'Saqlangan mavzu'})
    restart=PostgresStorage(pool)
    assert await restart.get_state(key)==EssayStates.waiting_for_essay.state
    assert (await restart.get_data(key))['topic']=='Saqlangan mavzu'


def update(uid,number,text):
    return Update.model_validate({'update_id':number,'message':{'message_id':number,'date':1700000000,'chat':{'id':uid,'type':'private'},'from':{'id':uid,'is_bot':False,'first_name':'Test'},'text':text}})


def dispatcher(pool,bot,subscribed=True):
    cfg=SimpleNamespace(admin_id=99,channel_username='@channel')
    dp=Dispatcher(storage=PostgresStorage(pool),config=cfg,jobs=Jobs(pool),
                  access=AccessService(pool,99),subscription=SimpleNamespace(allowed=AsyncMock(return_value=subscribed)))
    dp.include_router(admin.build_router())
    dp.include_router(user.build_router())
    return dp


async def test_real_dispatch_fsm_inbox_duplicate_and_submission(pool):
    bot=Bot('123456:TEST_TOKEN_FOR_OFFLINE_TESTS')
    bot.session.make_request=AsyncMock(return_value=True)
    inbox=Inbox(pool,dispatcher(pool,bot),bot)
    for number,text in enumerate(['📝 Esse tekshirish','Mavzu','qisqa esse'],1):
        event=update(101,number,text)
        await inbox.receive(event)
        await inbox.receive(event)
        assert await inbox.process_one()
        assert not await inbox.process_one()
    assert await pool.fetchval('SELECT count(*) FROM essay_jobs')==1
    assert await pool.fetchval('SELECT essay_text FROM essay_jobs')=='qisqa esse'
    assert await pool.fetchval('SELECT count(*) FROM telegram_updates WHERE payload IS NOT NULL')==0
    assert await pool.fetchval('SELECT state FROM fsm_state') is None
    await bot.session.close()


async def test_no_subscription_no_job(pool):
    bot=Bot('123456:TEST_TOKEN_FOR_OFFLINE_TESTS')
    bot.session.make_request=AsyncMock(return_value=True)
    inbox=Inbox(pool,dispatcher(pool,bot,False),bot)
    await inbox.receive(update(101,1,'📝 Esse tekshirish'))
    await inbox.process_one()
    assert await pool.fetchval('SELECT count(*) FROM essay_jobs')==0
    assert await pool.fetchval('SELECT count(*) FROM fsm_state')==0
    await bot.session.close()


async def test_forged_admin_callback_and_command(pool):
    bot=Bot('123456:TEST_TOKEN_FOR_OFFLINE_TESTS')
    bot.session.make_request=AsyncMock(return_value=True)
    inbox=Inbox(pool,dispatcher(pool,bot),bot)
    await inbox.receive(update(101,1,'/admin'))
    await inbox.process_one()
    assert bot.session.make_request.call_count==0
    event=Update.model_validate({'update_id':2,'callback_query':{'id':'abc','from':{'id':101,'is_bot':False,'first_name':'Test'},'chat_instance':'abc','data':'admin:off','message':{'message_id':1,'date':1700000000,'chat':{'id':101,'type':'private'},'text':'fake'}}})
    await inbox.receive(event)
    await inbox.process_one()
    assert await pool.fetchval('SELECT bot_enabled FROM bot_settings')
    assert await pool.fetchval('SELECT updated_by FROM bot_settings') is None
    await bot.session.close()
