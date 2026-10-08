-- Run AFTER enabling pg_cron and pg_net in Supabase Dashboard.
-- Add these secrets through the Vault UI first:
-- esse_bot_base_url: HTTPS Render origin, no trailing slash
-- esse_bot_cron_secret: same secret as Render CRON_SECRET
-- This file deliberately contains no secret values.
SELECT cron.schedule('esse-bot-tick', '* * * * *', $job$
 SELECT net.http_post(
   url := (SELECT decrypted_secret FROM vault.decrypted_secrets WHERE name='esse_bot_base_url') || '/internal/jobs/tick',
   headers := jsonb_build_object('Content-Type','application/json','Authorization',
       'Bearer ' || (SELECT decrypted_secret FROM vault.decrypted_secrets WHERE name='esse_bot_cron_secret')),
   body := '{}'::jsonb,
   timeout_milliseconds := 5000
 );
$job$);
