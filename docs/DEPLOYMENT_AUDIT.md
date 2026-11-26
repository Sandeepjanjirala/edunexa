# Deployment audit and validation — 2026-11-26

Work is on local branch `chore/deployment-reliability`. No commit, push or live
deployment was performed. Video Studio and other existing containers were not
modified. The developer's existing `.env` was not overwritten.

## Findings and changes

| Finding | Resolution |
|---|---|
| Manual migration/static/seed ordering; first-start `exec web` cannot work | `scripts/deploy.sh` builds/validates first, waits for dependencies, runs one-off migration/static jobs, then starts application services. |
| Historical `config` import and `packaging` errors | `PYTHONPATH=/app`, workdir, WSGI/Celery module paths and `packaging` were already correct. Retained them and validated the production image; no speculative dependency replacement. |
| Two deployment stacks with different environment locations | Explicit root Compose/env paths in the new VPS workflow; documented the separate legacy Caddy workflow. Existing Caddy scripts remain for their existing rehearsal. |
| Missing persistent media directory/volume | Owned `/app/media` in the image, Django MEDIA_ROOT/MEDIA_URL, shared named media volume. No insecure public media alias. |
| Redis configured to discard all queued state on recreation | Persistent volume, AOF every second, existing noeviction memory ceiling retained. Documented first-upgrade draining, redelivery and durability limitations. |
| No safe automated environment initialization | Exclusive-create initializer, generated secrets, mode 600, validation without shell sourcing, no credential overwrite. |
| No preflight or operation serialization | Ubuntu/tool/disk/RAM/DNS/env/Compose/port checks, project identity guard and flock for mutations. |
| Nginx example HTTP-only; SSL manual | Optional preview/apply helper with vhost snapshots, validation-before-reload, rollback, opt-in Certbot webroot and public/direct-origin HTTPS checks. |
| Existing seed command refuses a second run and prints passwords | Added `initialize_demo`: repeatable, no reset, refuses school data and suppresses password output. Existing seed behavior remains available for development. |
| Updates lack backup/version/rollback coordination | Clean-checkout gate, backup before fetch/fast-forward, pinned previous image, versioned builds, stopped-writer backup, explicit schema-compatible image rollback. |
| Backups default to Caddy; no media in that backup | New root-stack backups include DB/media/checksums/revision, private permissions and opt-in retention. Restore stages and verifies DB before transactional name swap, retaining old DB. |
| No unified final health status | SQL/Redis/container health/migrations/security/queued worker/static/local HTTP/public and origin TLS checks, resource/restart/OOM output. Non-200 HTTP is failure. |
| Missing VPS guide in this checkout | Created VPS runbook and this audit; README links exact commands and adoption instructions. |

## Architecture and safety

`scripts/lib.sh` supplies explicit Compose context, environment validation,
preflight, backups, deployment sequencing and health checks. Thin entrypoints
provide deploy/update/healthcheck/backup/restore/rollback; `scripts/nginx.sh` is a
separate explicit host operation. `scripts/env.py` creates/validates literal env
files without executing shell code. No migrations run inside Gunicorn, Worker or
Beat startup. Application services run as the existing non-root image user, now
with an init process and 90-second graceful shutdown allowance.

Database and Redis have no published ports. Web stays on `127.0.0.1:8002` by
default. Existing PostgreSQL volume naming and resource limits are retained.
No measured evidence justified increasing concurrency or memory limits. Logs
remain capped at five 10-MiB files per service. Build-time memory remains outside
runtime limits. Secret files, deployment state, backups and media are ignored by
Git and excluded from Docker build context.

The production image already collects static assets during build. The release
job additionally validates collection with production settings; runtime servers
serve the immutable assets in their own image through WhiteNoise. There is no
shared static volume that could accidentally retain a previous release's files.

## Tests actually executed

| Test | Result/evidence |
|---|---|
| Production image build | `docker build -t edunexa:reliability-test .` passed; dependency layer cached; image build collected 58 static files with 152 post-processing operations. This was not a fresh dependency-resolution audit. |
| Existing application tests on SQLite, before new test additions | 523 passed, 6 PostgreSQL-only skips, 1,193 subtests. |
| Full pytest suite with local PostgreSQL 17 | **549 passed, 1,196 subtests**, no skips; 354.15 seconds. Includes new env/demo tests and existing browser tests. One Django DB connection warning occurred while the isolated database became available; the suite completed successfully. |
| Environment tests independently | Six passed: generated env validation, byte-for-byte preservation on repeat init, missing secrets, duplicate assignments and shell-expression rejection. |
| New demo initialization tests | Three passed in the full suite: repeat preservation/no password output, real-school refusal and production-mode refusal. |
| Production Compose rehearsal | Passed with isolated project `edunexa-test-6a572c9d`, generated test credentials and loopback port 18092. Log: `.deploy/rehearsal.log` (local, ignored). |
| Real database behavior in rehearsal | Fresh migrations, repeat migrations, repeat demo initialization preserving sentinel user, pg_dump and restore into separate DB with sentinel assertion. |
| Restore swap SQL | CREATE DATABASE, ALLOW_CONNECTIONS false and both database renames in a transaction executed successfully on the isolated PostgreSQL server. Full host restore script remains staging verification. |
| Real service behavior in rehearsal | Gunicorn, Worker and Beat healthy; actual queued job completed; local health and CSS returned 200; restart recovery passed. |
| Real persistence in rehearsal | PostgreSQL sentinel, media sentinel and Redis key survived forced container recreation. |
| Shell validation | Bash parsing and ShellCheck passed. LF line endings verified after correcting a Windows write that introduced CRLF. |
| Mocked deployment fault tests | Unhealthy dependency and failed migration prevent application restart; repeated release performs one migration/backup per call. Foreign occupied port refused, current EduNexa binding accepted. |
| Mocked Nginx test | Failed `nginx -t` restored previous vhost bytes and removed the newly created enable symlink inside a disposable container. No real Nginx/ACME operation performed. |
| Mocked update/rollback tests | Dirty Git and failed backup prevent fetch; clean update reaches release; rollback requires explicit schema acknowledgment and performs no migration/restore. |
| Python lint/format | Ruff checks passed. |

Initial rehearsal attempts exposed two errors in the new test harness: a fixture
user lacked required email/role fields, and a static probe used Django admin CSS
although this app has no admin assets. Both were corrected before the passing
rehearsal. Temporary-directory permissions initially blocked five env tests;
rerunning with a workspace-local pytest temp directory passed. These failures
were not presented as deployment successes.

The rehearsal removes only its own containers/network, deliberately retaining
test volumes and backup artifacts. No global pruning or volume deletion ran.
CI now includes the Bash/fault tests and isolated VPS Compose rehearsal.

## Remaining limits and required VPS verification

- No live VPS access occurred. Run real Ubuntu preflight and the runbook's health
  checks after approving and publishing the changes.
- The entire Bash deploy/update flow was tested with mocked host/Git operations;
  real Docker service steps were tested separately. End-to-end Ubuntu shell
  deployment, real Git update, image rollback and `restore.sh` database swap need
  a staging-VPS rehearsal before production adoption. The real PostgreSQL restore
  drill verified archive restoration, not the complete host restore script.
- Nginx config generation/failure recovery was tested with mocks. Validate the
  candidate on the actual Nginx version before reload. Real Let's Encrypt issuance,
  DNS origin correctness, Cloudflare routing/526 handling and renewal dry-run
  remain pending. No Cloudflare API automation is claimed.
- Existing custom media inside containers must be exported before recreation.
  The repository currently processes CSV uploads without a persistent file model;
  adding a media volume cannot discover or recover files stored elsewhere.
- Existing nonpersistent Redis queues must be drained before first recreation.
  AOF cannot guarantee exactly-once tasks or recover a destroyed VPS/disk.
- DEMO_MODE retains the application's pre-existing nightly reset behavior for
  marked demo databases. Use a separate fresh database for real school data.
- Backup structure/checksum verification is not a complete restore guarantee.
  Copy backups off-host, test restoration regularly, and review media and queued
  task consistency before reopening after a restore.
- Beat's health check proves startup/schedule file presence, not execution of
  every scheduled job. Resource output is a snapshot, not performance/load testing.
- Floating base image tags and the existing packaging lower bound remain. Retain
  tested images; a future clean rebuild may resolve different artifacts.
- Verify Video Studio availability before/after adoption and review combined CPU,
  RAM, disk and log growth under representative traffic. No capacity claim is made.

## Files

Created: `scripts/{lib,deploy,update,healthcheck,backup,restore,rollback,nginx}.sh`,
`scripts/env.py`, `scripts/tests/{test_env.py,failures.sh,nginx_failure.sh,workflows.sh}`,
`apps/demo/management/commands/initialize_demo.py`,
`apps/demo/tests/test_initialize_demo.py`, `e2e/rehearse_vps.py`,
`docs/VPS_DEPLOYMENT.md`, and this report.

Modified: Dockerfile, root production Compose, production env template, base
Django media settings, Git/Docker ignores, README and CI workflow.

## References used

- [Docker Compose one-off run semantics](https://docs.docker.com/reference/cli/docker/compose/run/)
- [Docker production Compose guidance](https://docs.docker.com/compose/how-tos/production/)
- [Certbot webroot, renewal and hooks](https://eff-certbot.readthedocs.io/en/stable/using.html)
