from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from aiogram.exceptions import TelegramRetryAfter, TelegramNetworkError
from aiogram.methods import SendMessage
from bot.services.workers import Workers
from openai import APIStatusError
import httpx
import asyncio


async def test_delivery_same_saved_chat_and_record():
    part={'chat_id':101,'text':'Complete result'}
    jobs=SimpleNamespace(claim_delivery=AsyncMock(return_value=part),delivered=AsyncMock(),delivery_error=AsyncMock())
    bot=SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(message_id=7)))
    workers=Workers(jobs,None,bot,None)
    assert await workers.deliver_one()
    bot.send_message.assert_awaited_once_with(101,'Complete result',parse_mode=None,request_timeout=30)
    jobs.delivered.assert_awaited_once_with(part,7)


@pytest.mark.parametrize('error,expected',[
    (TelegramRetryAfter(method=SendMessage(chat_id=101,text='x'),message='retry',retry_after=4),{'retry_after':5}),
    (TelegramNetworkError(method=SendMessage(chat_id=101,text='x'),message='timeout'),{'uncertain':True}),
])
async def test_delivery_error_classification(error,expected):
    part={'chat_id':101,'text':'Result'}
    jobs=SimpleNamespace(claim_delivery=AsyncMock(return_value=part),delivered=AsyncMock(),delivery_error=AsyncMock())
    bot=SimpleNamespace(send_message=AsyncMock(side_effect=error))
    await Workers(jobs,None,bot,None).deliver_one()
    jobs.delivered.assert_not_called()
    jobs.delivery_error.assert_awaited_once_with(part,**expected)


async def test_bad_evaluation_never_saved():
    job={'id':1,'topic':'topic','essay_text':'text'}
    jobs=SimpleNamespace(claim_evaluation=AsyncMock(return_value=job),complete=AsyncMock(),evaluation_error=AsyncMock())
    checker=SimpleNamespace(check=AsyncMock(side_effect=ValueError('malformed')))
    await Workers(jobs,checker,None,None).evaluate_one()
    jobs.complete.assert_not_called()
    jobs.evaluation_error.assert_awaited_once_with(job,False,'ValueError')


@pytest.mark.parametrize('code,permanent',[(401,True),(400,True),(429,False),(500,False)])
async def test_api_failure_classification(code,permanent):
    job={'id':1,'topic':'topic','essay_text':'text'}
    response=httpx.Response(code,request=httpx.Request('POST','https://offline.invalid'))
    error=APIStatusError('offline',response=response,body=None)
    jobs=SimpleNamespace(claim_evaluation=AsyncMock(return_value=job),complete=AsyncMock(),evaluation_error=AsyncMock())
    checker=SimpleNamespace(check=AsyncMock(side_effect=error))
    await Workers(jobs,checker,None,None).evaluate_one()
    jobs.evaluation_error.assert_awaited_once_with(job,permanent,f'api_status_{code}')


async def test_shutdown_cancels_inflight_evaluation():
    started=asyncio.Event()
    stopped=asyncio.Event()
    async def check(*args):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()
    job={'id':1,'topic':'topic','essay_text':'text'}
    jobs=SimpleNamespace(claim_evaluation=AsyncMock(return_value=job),complete=AsyncMock(),evaluation_error=AsyncMock())
    workers=Workers(jobs,SimpleNamespace(check=check),None,None)
    workers.tasks=[asyncio.create_task(workers.evaluate_one())]
    await started.wait()
    await workers.close()
    assert stopped.is_set() and workers.tasks[0].cancelled()
    jobs.complete.assert_not_called()
    jobs.evaluation_error.assert_not_called()
