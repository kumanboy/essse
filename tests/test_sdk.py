import json
from types import SimpleNamespace
import httpx
from openai import AsyncOpenAI
from bot.services.essay_checker import EssayChecker
from bot.services.results import INTRO,totals
from unittest.mock import AsyncMock
import pytest


async def test_installed_sdk_serializes_responses_request():
    result=INTRO+'\n\nSTOP NATIJA:\n\nSabab: 100 so‘zdan kam\n\n'+totals(2)
    captured=[]
    def respond(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200,json={
            'id':'resp_offline','object':'response','created_at':1700000000,'status':'completed',
            'model':'gpt-5.6-sol','output':[{'id':'msg_offline','type':'message','role':'assistant','status':'completed',
                'content':[{'type':'output_text','text':result,'annotations':[]}]}],
            'parallel_tool_calls':False,'tools':[],'tool_choice':'auto',
        })
    async with AsyncOpenAI(api_key='offline-test',http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond))) as client:
        config=SimpleNamespace(model='gpt-5.6-sol',reasoning_effort='high')
        assert await EssayChecker(client,config).check('Mavzu','qisqa esse')==result
    assert captured[0]['reasoning']=={'effort':'high'}
    assert captured[0]['max_output_tokens']==16000
    assert captured[0]['model']=='gpt-5.6-sol'


@pytest.mark.parametrize('status,text',[('incomplete','partial'),('completed',''),('completed','wrong format')])
async def test_incomplete_empty_malformed_rejected(status,text):
    client=SimpleNamespace(responses=SimpleNamespace(create=AsyncMock(return_value=SimpleNamespace(status=status,output_text=text))))
    config=SimpleNamespace(model='gpt-5.6-sol',reasoning_effort='high')
    with pytest.raises(ValueError): await EssayChecker(client,config).check('Mavzu','so‘z '*100)
