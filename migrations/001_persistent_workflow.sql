BEGIN;
CREATE TABLE IF NOT EXISTS bot_settings (
 id integer PRIMARY KEY CHECK (id=1),
 access_start timestamptz,
 free_access_days integer NOT NULL DEFAULT 3 CHECK (free_access_days BETWEEN 1 AND 365),
 daily_open_time time NOT NULL DEFAULT '13:00',
 daily_close_time time NOT NULL DEFAULT '23:00',
 timezone text NOT NULL DEFAULT 'Asia/Tashkent',
 bot_enabled boolean NOT NULL DEFAULT true,
 updated_at timestamptz NOT NULL DEFAULT now(), updated_by bigint,
 CHECK (daily_open_time <> daily_close_time)
);
INSERT INTO bot_settings(id) VALUES (1) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS essay_jobs (
 id bigserial PRIMARY KEY, user_id bigint NOT NULL, chat_id bigint NOT NULL,
 source_update_id bigint NOT NULL UNIQUE,
 topic text NOT NULL, essay_text text NOT NULL,
 submitted_at timestamptz NOT NULL DEFAULT now(),
 send_after timestamptz NOT NULL DEFAULT (now() + interval '10 minutes'),
 evaluation_started_at timestamptz, evaluation_completed_at timestamptz,
 result_text text, status text NOT NULL DEFAULT 'pending'
 CHECK (status IN ('pending','processing','ready','sending','sent','failed')),
 sent_at timestamptz, error_message text,
 attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
 lease_token uuid, lease_until timestamptz,
 next_attempt_at timestamptz NOT NULL DEFAULT now(),
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 CHECK (chat_id=user_id),
 CHECK (send_after >= submitted_at + interval '10 minutes'),
 CHECK (status NOT IN ('ready','sending','sent') OR result_text IS NOT NULL),
 CHECK (status <> 'sent' OR sent_at IS NOT NULL)
);
CREATE UNIQUE INDEX IF NOT EXISTS essay_one_active_user ON essay_jobs(user_id)
 WHERE status IN ('pending','processing','ready','sending');
CREATE INDEX IF NOT EXISTS essay_claim_idx ON essay_jobs(status,next_attempt_at);
CREATE INDEX IF NOT EXISTS essay_due_idx ON essay_jobs(status,send_after) WHERE sent_at IS NULL;
CREATE TABLE IF NOT EXISTS delivery_parts (
 id bigserial PRIMARY KEY, job_id bigint NOT NULL REFERENCES essay_jobs(id),
 kind text NOT NULL CHECK(kind IN ('result','failure','acceptance')),
 part_no integer NOT NULL, text text NOT NULL,
 status text NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','sending','sent','uncertain','failed')),
 attempt_count integer NOT NULL DEFAULT 0,
 next_attempt_at timestamptz NOT NULL DEFAULT now(),
 lease_token uuid, lease_until timestamptz, telegram_message_id bigint,
 UNIQUE(job_id,kind,part_no)
);
CREATE INDEX IF NOT EXISTS delivery_due_idx ON delivery_parts(status,next_attempt_at);
CREATE TABLE IF NOT EXISTS telegram_updates (
 update_id bigint PRIMARY KEY, user_id bigint NOT NULL, payload jsonb,
 status text NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','done','failed')),
 attempt_count integer NOT NULL DEFAULT 0, next_attempt_at timestamptz NOT NULL DEFAULT now(),
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS update_claim_idx ON telegram_updates(status,next_attempt_at,update_id);
CREATE INDEX IF NOT EXISTS update_user_idx ON telegram_updates(user_id,update_id);
CREATE TABLE IF NOT EXISTS fsm_state (
 key text PRIMARY KEY, state text, data jsonb NOT NULL DEFAULT '{}',
 updated_at timestamptz NOT NULL DEFAULT now()
);
-- These tables are backend-only. No public Supabase Data API access.
ALTER TABLE bot_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE essay_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE delivery_parts ENABLE ROW LEVEL SECURITY;
ALTER TABLE telegram_updates ENABLE ROW LEVEL SECURITY;
ALTER TABLE fsm_state ENABLE ROW LEVEL SECURITY;
COMMIT;
