# Acceptance coverage and deployment checks

Automated tests use real PostgreSQL for transactions, migrations, constraints and recovery. Telegram and OpenAI interactions are mocked, including serialization through the installed OpenAI SDK. They do not establish actual grading quality, channel privileges, model access or cloud networking.

Run `python -m pytest -q`. Set `TEST_DATABASE_URL` to an isolated test database to execute the integration suite. Schema cleanup in tests is limited to a random `test_<UUID>` schema created by that test.

| Case | Expected result | Coverage / live follow-up |
|---|---|---|
| A | Unsubscribed user blocked | Membership status tests and real dispatcher test with denied subscription; verify actual channel in staging |
| B | Promotion permits 03:00 | Exact 72-hour business test |
| C | Expired promotion, 12:59 closed | Parametrized boundary test |
| D | 13:00 open | Parametrized boundary test |
| E | 22:59 open | Parametrized boundary test |
| F | 23:00 closed | Parametrized boundary test |
| G | Normal menu has no admin control | Exact menu test |
| H | Admin menu includes panel | Exact menu test |
| I | Forged admin request rejected | Real dispatcher callback/command integration test and service guard test |
| J | Start promotion persists | Admin settings persistence; exercise start callback live |
| K | Hours change without redeploy | Database settings persistence and access boundary tests; exercise edit conversation live |
| L | Ready at minute 1 waits until minute 10 | Database early-ready/restart test verifies claim is blocked; clock advanced with test-only SQL |
| M | Ready at minute 7 waits until minute 10 | Same readiness-independent database eligibility check; staged test at minute 7 |
| N | Ready at minute 13 delivers then | Database late-ready test |
| O | Restart at minute 5 preserves pending/processing work | New Jobs instance, expired lease recovery and old-worker fencing tests; terminate staging instance once |
| P | Ready result survives restart before due time | Early-ready/restart test |
| Q | Restart after due time delivers saved result | Early-ready/restart and late-ready tests |
| R | Two worker cycles claim once | Concurrent PostgreSQL delivery claim test; uncertain-send behavior tested separately |
| S | One active essay enforced | Concurrent insert and partial unique constraint test |
| T | Failure releases user and notifies | Three-attempt PostgreSQL failure test plus durable failure notice check |
| U | Short essay gets official STOP format | Dispatcher accepts short essay; all STOP format tests; real SDK serialization mock |
| V | Injection is untrusted input | JSON-boundary and full-rubric request tests; adversarial live grading must still be evaluated |
| W | Twelve scores, exact sum and lookup, five recommendations, closing | Valid/invalid result tests and all 49 matrix entries compared to supplied rubric |
| X | Complete long result delivered in parts | Unicode split completeness and multipart checkpoint tests |
| Y | Course copy and contact | Product content test |
| Z | Template copy and contact | Product content test |
| AA | 20-topic sample collection and contact | Product content test |

Additional tests cover configuration validation, secret-safe representations, HTTP endpoint authorization, oversized bodies, startup/shutdown cleanup, permanent/temporary delivery behavior, malformed evaluator output and persistent FSM storage.

## Staging deployment sequence

1. Use a separate bot, channel and database. Apply the migration, configure environment variables and deploy. Confirm `/health` returns `{"status":"ok"}`.
2. Verify Telegram's webhook configuration through your secure Bot API tooling: correct URL, no pending errors, no token logged. Test missing/wrong webhook secret (403) and missing/wrong tick bearer (403).
3. Check a nonmember, a member and the configured admin. Confirm Instagram opens the requested profile without claiming technical verification.
4. Start the global promotion; submit a topic plus a short essay. Confirm immediate acceptance, a persisted job, official STOP output and no result before 600 seconds after `submitted_at`.
5. Submit a normal essay and inspect the actual rubric quality. Verify model billing/access, expected Uzbek wording, result length, no extra sections and no arithmetic discrepancies.
6. Submit an adversarial essay asking to ignore the rubric. Confirm it is graded as content. Automated request-boundary tests alone cannot prove model resistance.
7. Restart before evaluation, during evaluation, after ready and after the due time. Observe DB states and final delivery. Do not change production timestamps to speed up this check.
8. Configure expired promotion and the hour boundaries. Start at 22:58 and submit after 23:00; expect rejection. Toggle service off and confirm product/help content still works and previously accepted work still finishes.
9. Trigger a Telegram rate limit in a controlled mock/staging harness, not by flooding users. Check backoff/checkpoints. Simulate the send/commit crash window: expect `uncertain`, preserved result, failed job and no automatic duplicate resend.
10. Enable Supabase Cron, let the service become idle, and inspect recovery on the next tick. Check Vault values and HTTP responses. Cold starts may delay delivery beyond ten minutes.
11. Remove any old BotFather public commands, stop the legacy polling service and rotate any formerly used archive-local database password before switching the production token.

Cloud deployment, Docker image execution, real Telegram delivery, actual OpenAI grading, Instagram authentication and Supabase Cron execution require the operator's environment and are not claimed as executed preparation tests.
