import pytest
from bot.config import Config


def env(monkeypatch):
    monkeypatch.setattr('bot.config.load_dotenv',lambda:None)
    for k,v in {'BOT_TOKEN':'123456:OFFLINE_TEST','ADMIN_ID':'99','DATABASE_URL':'postgresql://local/test',
                'OPENAI_API_KEY':'offline','TELEGRAM_WEBHOOK_SECRET':'w'*32,'CRON_SECRET':'c'*32,
                'PUBLIC_BASE_URL':'https://example.invalid','TIMEZONE':'Asia/Tashkent',
                'OPENAI_REASONING_EFFORT':'high','DATABASE_SSL':'true'}.items():
        monkeypatch.setenv(k,v)


def test_valid_config_defaults(monkeypatch):
    env(monkeypatch)
    cfg=Config.load()
    assert cfg.admin_id==99 and cfg.model=='gpt-5.6-sol' and cfg.database_ssl
    assert 'offline' not in repr(cfg) and 'w'*32 not in repr(cfg)


@pytest.mark.parametrize('name,value', [('ADMIN_ID',''),('ADMIN_ID','not-a-number'),('TELEGRAM_WEBHOOK_SECRET','short'),('CRON_SECRET','short'),('TIMEZONE','invalid/zone'),('PUBLIC_BASE_URL','http://insecure'),('DATABASE_URL','https://db'),('OPENAI_REASONING_EFFORT','low'),('DATABASE_SSL','maybe')])
def test_invalid_configuration_clear_errors(monkeypatch,name,value):
    env(monkeypatch)
    monkeypatch.setenv(name,value)
    with pytest.raises(RuntimeError) as exc: Config.load()
    assert name in str(exc.value)
