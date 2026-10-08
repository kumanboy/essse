# Esse bot — Render + Supabase

Uzbek essay checking using aiogram 3, FastAPI, asyncpg and the OpenAI Responses API. The application retains the original `bot/` package structure and Telegram membership helper design. Payment, balance, free-try, voice and administrator-review workflows are removed.

## Behavior

`/start` → subscription links → Telegram membership verification → menu → topic (include situation text if supplied) → essay text → persistent acceptance → evaluation → stored result → delivery to that same private chat **no earlier than 600 seconds after database acceptance**.

The five normal menu items are essay checking, course, template, sample essays and help. Product/contact information remains available when essay checking is closed. Only `ADMIN_ID` sees the extra admin button. Every admin handler and settings mutation also checks authorization server-side.

Instagram is a follow link; it is not technically verified. Telegram uses `getChatMember`, which requires the bot to be an administrator in the channel for reliable checks of other users. See the [Telegram Bot API](https://core.telegram.org/bots/api#getchatmember).

The supplied rubric is preserved byte-for-byte in `bot/prompts/rubric.txt`. It is sent in full, with an additional content-boundary instruction. Topic and essay are JSON-encoded untrusted content. The application validates exact criterion names and score values, arithmetic, all 49 lookup entries, five recommendations, required closing, and STOP formatting. Invalid/incomplete output is retried, never delivered as a grade. Semantic accuracy still depends on the evaluator; textual injection defenses cannot provide a mathematical guarantee.

The configured default is `gpt-5.6-sol` with `high` reasoning and 16,000 output tokens, including reasoning. These are compatible with the [official model documentation](https://developers.openai.com/api/docs/models/gpt-5.6-sol) and [Responses reasoning guide](https://developers.openai.com/api/docs/guides/reasoning). Account access and live behavior must be checked with your API key during deployment. No live paid API request was made during preparation.

## Persistence and recovery

All operational state lives in PostgreSQL:

- `bot_settings`: singleton schedule, timezone, enabled state, updater audit fields.
- `telegram_updates`: durable webhook inbox, update-ID deduplication, ordered handling per user. Payload is erased after successful handling or final handler failure; ID tombstones remain.
- `fsm_state`: topic/essay draft and admin input states, saved through an aiogram storage adapter.
- `essay_jobs`: content, status, result, timestamps, attempts and fenced evaluation lease.
- `delivery_parts`: acceptance, result parts and failure notices, with individual delivery checkpoints.

The webhook commits to the inbox before acknowledging Telegram. Two short handler workers consume updates; two evaluation workers process different jobs concurrently. A separate delivery loop sends results and notices. Recovery runs at startup and periodically. The tick endpoint wakes these loops, including when an inbound request wakes a sleeping Render service.

Evaluation claims use `FOR UPDATE SKIP LOCKED`, a UUID fencing token and an eight-minute lease. API calls are bounded to six minutes. Three total evaluation attempts are allowed, with persisted backoff. Expired claims can be recovered; an obsolete worker cannot overwrite a later claim. Persisted ready results are not evaluated again. A crash after OpenAI completes but before the result commits can require another API call.

The database enforces one active job per user through a partial unique index. Final acceptance takes a settings lock and checks database time, so a user who began before closing cannot submit after closing. Disabling intake does not cancel already accepted jobs or their deliveries.

### Delivery guarantee and unavoidable limitation

Normal operation, concurrent worker cycles, restarts before delivery, and completed multipart checkpoints are deduplicated. Each part is reserved in PostgreSQL **before** sending. A result part is eligible only when `send_after <= database time`.

Telegram `sendMessage` has no client-supplied idempotency key and cannot join a PostgreSQL transaction. If a send times out or the process dies between Telegram accepting it and the database recording its message ID, the application cannot determine whether it arrived. Both loss-free and duplicate-free delivery cannot be guaranteed across that boundary.

This implementation prioritizes the requested **no duplicate results** rule: uncertain parts are retained as `uncertain` and are not automatically resent. The job becomes `failed`, retains its result, releases the user's submission slot and queues a generic failure notice. A crash immediately before sending can therefore leave a result undelivered. There is no routine admin approval or forwarding step. Check uncertain rows during operations; do not blindly reset them to pending. Definitive Telegram rate-limit refusals are retried up to five attempts; blocked chats/bad requests fail, while network and server errors are treated as ambiguous. Failure notices can themselves be undeliverable if the user blocked the bot.

Interactive menu replies may repeat if a handler succeeds remotely but its transaction rolls back. Essay acceptance and result messages use the durable outbox. Draft changes and inbox completion commit together; essay creation is separately idempotent by source update ID.

## Deployment — no source edits required

### 1. GitHub

Extract the project and push its contents to a new private repository. Commit source, migrations, requirements, `.env.example`, Docker files and tests. Do not commit `.env`, tokens, database passwords or generated caches. Existing archive-local database credentials were removed; rotate the old database password if it was used beyond disposable local development.

### 2. Supabase database

Create a Supabase project. In SQL Editor run **`migrations/001_persistent_workflow.sql`** once. It can be rerun safely. It creates new tables without dropping or altering legacy payment/voice tables. Historical legacy data remains untouched and is not used by the new application. Back it up and retire it separately only after deciding your retention policy.

Use a dedicated database for this bot, or verify that these new table names do not already represent another application. The migration does not attempt to reconcile unrelated pre-existing tables with the same names.

From Supabase **Connect**, copy the **Session pooler** PostgreSQL URI (commonly port 5432). Put the actual database password into the URI, URL-encoding special characters. Set it as `DATABASE_URL` in Render. The backend connection must own these tables or have appropriate privileges and RLS bypass; do not use the anonymous API key or a browser-facing Supabase client. RLS is enabled on all new tables with no public policies. No browser/Data API access is needed.

`DATABASE_SSL=true` is the production default. TLS verifies the server certificate using system trusted CAs. Do not disable it in production. `DATABASE_SSL=false` exists only for isolated local PostgreSQL tests. There is one pool per app process, 1–5 connections, and no statement cache. Use one Uvicorn process on the small Render instance.

### 3. Telegram and OpenAI

Create/use the bot through BotFather; copy its token into Render `BOT_TOKEN`. Add the bot as an administrator of `@sardortoshmuhammad_onatili`. Set `ADMIN_ID` to your numeric personal Telegram user ID, not a channel ID. Users must initiate the private bot chat before receiving messages.

Create an OpenAI project API key, enable billing/model access, and set `OPENAI_API_KEY`. Configure account spend limits appropriate to the expected usage. The bot does not charge users, but evaluator API usage still incurs provider cost.

### 4. Render Web Service

Connect the GitHub repository, choose Python, and use Python 3.11. The included `render.yaml` can create the service. Direct manual configuration is also supported:

| Setting | Value |
|---|---|
| Build command | `pip install -r requirements.lock` |
| Start command | `uvicorn bot.main:app --host 0.0.0.0 --port $PORT` |
| Health check | `/health` |
| Telegram endpoint | `POST /telegram/webhook` |
| Recovery endpoint | `POST /internal/jobs/tick` |

`requirements.lock` contains tested exact dependency versions. `requirements.txt` states the compatible direct dependency ranges for future upgrades. Retest before refreshing the lock.

Set these required environment variables:

| Variable | Meaning |
|---|---|
| `BOT_TOKEN` | BotFather token |
| `ADMIN_ID` | Positive personal Telegram ID |
| `DATABASE_URL` | Supabase Session pooler PostgreSQL URI |
| `OPENAI_API_KEY` | Project API key |
| `PUBLIC_BASE_URL` | HTTPS Render origin, e.g. `https://your-service.onrender.com` |
| `TELEGRAM_WEBHOOK_SECRET` | 32–256 random characters from letters, digits, `_`, `-` |
| `CRON_SECRET` | Independent random secret, at least 32 characters |

Optional defaults: `OPENAI_MODEL=gpt-5.6-sol`, `OPENAI_REASONING_EFFORT=high`, `CHANNEL_USERNAME=@sardortoshmuhammad_onatili`, `TIMEZONE=Asia/Tashkent`, `DATABASE_SSL=true`. Render supplies `PORT`; local default example is 8000. Only `high`, `xhigh`, and `max` reasoning are accepted to prevent accidentally downgrading grading to low reasoning. Verify model support before changing them.

Generate each secret separately with `python -c "import secrets; print(secrets.token_urlsafe(32))"` and paste it into the environment UI. Do not commit the output. Blueprint-generated secrets are also suitable.

After Render assigns the URL, set `PUBLIC_BASE_URL` to that origin and redeploy. An initial deploy without required settings fails with a configuration error; it will succeed after the values are set. No source modification is necessary.

### 5. Webhook setup

Startup calls `setWebhook` automatically using the configured HTTPS origin and secret. It requests only messages/callbacks, keeps pending updates, and sets one webhook connection to preserve intake ordering. It does not start long polling. Do not delete the webhook on shutdown; the next instance uses the same endpoint. Stop the old polling deployment before starting this service with the same token.

Requests without the correct `X-Telegram-Bot-Api-Secret-Token` header receive 403. Invalid or oversized bodies are rejected. The URL does not contain the bot token. Health is unauthenticated and reveals only readiness. Tick requires `Authorization: Bearer <CRON_SECRET>` and returns no job contents.

### 6. Supabase Cron

Enable `pg_cron` and `pg_net` using the Supabase dashboard. In **Vault**, create `esse_bot_base_url` with your Render origin (no trailing slash) and `esse_bot_cron_secret` with the same value as Render `CRON_SECRET`. Then run **`scripts/supabase_cron.sql`**. It schedules a protected tick every minute and reads secrets from Vault rather than committed SQL. Supabase documents this pattern in its [scheduling guide](https://supabase.com/docs/guides/functions/schedule-functions).

Monitor `cron.job_run_details` and `net._http_response` for failures without sharing authorization headers. A cold start may outlast the HTTP timeout; subsequent scheduled requests retry. The endpoint wakes durable workers rather than keeping the HTTP request open for grading.

Render Free can sleep after 15 minutes without inbound traffic, and its filesystem is ephemeral. See [Render Free documentation](https://render.com/docs/free). Cron improves responsiveness but is not a timing SLA. Delivery can occur later than ten minutes during sleep, outages, quota exhaustion or slow evaluation. It must never occur earlier. For dependable latency use an always-running plan; PostgreSQL remains the recovery source on every plan.

### 7. Admin configuration

Open the private bot chat as `ADMIN_ID`, use `/admin` or the hidden admin button. Start the global promotional period or enter a local start date, edit duration (1–365 days), opening/closing hours, timezone and enabled state. All changes persist immediately.

The default promotion duration is 3 × 24 hours. The start button resets `access_start` to database time, using the currently configured duration. It does not enable a disabled service; use the separate enable control. A future start blocks intake until that start. With no start configured, the daily schedule applies. Default hours are 13:00 inclusive to 23:00 exclusive in Asia/Tashkent. Overnight intervals are supported; equal opening/closing times are rejected. The initial `TIMEZONE` env setting only initializes untouched defaults; saved admin settings take precedence thereafter.

### 8. Docker and local development

`docker compose up --build` starts the same ASGI application with `.env` and connects to `DATABASE_URL`. The image runs as a non-root user. Docker is optional; native Render builds work directly.

For local development:

```sh
python -m venv .venv
# Activate the environment using your operating system's command.
pip install -r requirements.lock
pip install -r requirements-dev.txt
python -m compileall -q bot tests
python -m pytest -q
```

To run PostgreSQL integration tests, set `TEST_DATABASE_URL` to an **isolated disposable test database** where the test role may create schemas. Each test creates and drops a randomly named schema; production schemas are never truncated. Without that variable the database tests report skips. Use an HTTPS development tunnel and a separate bot token for local webhook testing.

## Validation and operations

See `TEST_PLAN.md` for all requested A–AA acceptance scenarios and the live deployment checks. `IMPLEMENTATION_REPORT.md` records executed tests, file changes and limitations.

Logs contain job IDs, safe event names and exception types; never essay content, API keys, raw API errors or database credentials. A failed job releases its user slot. Inspect `essay_jobs.error_message`, job ages and `delivery_parts.status` for operational failures. No essay/result is sent to the admin by default.

Data retention is not silently imposed: essays and results persist until the operator applies a chosen retention policy. Remove old completed records and their parts according to that policy; keep records needed for active jobs and delivery reconciliation. Purge abandoned drafts as appropriate. Back up the database. Existing user-menu commands configured manually in BotFather are external state: remove obsolete public payment/admin commands there before launch.
