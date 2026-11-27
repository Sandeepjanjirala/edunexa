# EduNexa on a shared Ubuntu VPS

This guide uses **docker-compose.prod.yml + scripts/**, host Nginx, Certbot and
Cloudflare Full (strict). The separate `deploy/compose.production.yaml` and
`deploy/backup.sh` belong to the alternative Caddy installation. Do not mix those
commands with this stack or start Caddy on a server where Nginx owns 80/443.

The scripts target Ubuntu 22.04 or newer. Commands below run from the repository
root as the deployment user unless `sudo` is shown. They do not install packages,
change Cloudflare, change other applications or publish database/cache ports.
Updates have a maintenance window; this is **not zero downtime**.

## Already deployed: update from GitHub main

In your VPS SSH terminal, enter the **existing repository folder** that contains
`docker-compose.prod.yml` and your production `.env`. Replace the example path
below with your actual folder. Keep the terminal connected until the command
reports success.

```bash
cd /path/to/existing/edunexa
git status --short
bash scripts/update.sh origin/main
```

The status should be empty. The explicit `origin/main` argument also works with
the earlier updater. It takes a backup before advancing the checkout, fetches
main, builds the image, backs up again with writers stopped, migrates, collects
static files, restarts web/Celery/scheduler and verifies health including HTTPS.
The updater handles the Git fetch and fast-forward itself. Your existing `.env`,
Compose project and database volume stay in place; working Nginx/SSL configuration
needs no changes for a UI update.

After it reports success:

```bash
docker compose --env-file .env -f docker-compose.prod.yml ps
git rev-parse --short=12 HEAD
cat .deploy/deployed-revision
```

Open the website and use **Ctrl+F5** to load the new theme. Future updates use
`bash scripts/update.sh`; it now defaults to `origin/main`. Run
`bash scripts/update.sh --help` for usage without starting a deployment.

If Git reports local edits or commits absent from GitHub, the updater stops;
preserve and reconcile them before retrying. If deployment fails, inspect the
scoped logs below and retry the same update command after fixing the cause. A
retry still runs deployment even if the checkout is already current. The
`.deploy/deployed-revision` file records the last successful deployment;
`.deploy/before-revision` records the checkout before the most recent attempt.

```bash
docker compose --env-file .env -f docker-compose.prod.yml logs --tail 100 web worker beat
```

If `scripts/update.sh` does not exist in the deployed checkout, complete
[adoption of the existing installation](#adopting-this-on-the-already-deployed-vps)
first, including a backup using the current stack before fetching new code. These
commands apply to the host-Nginx stack, not the separate Caddy installation.

## Prerequisites and shared-server safety

Have the administrator install Docker Engine, the Compose v2 plugin (with
`up --wait --wait-timeout` support), Nginx, Certbot, Python **3**, Git, curl,
OpenSSL, util-linux and iproute2 using the host's approved installation procedure.
Give the deployment user Docker access (equivalent to root privileges).
The scripts stop with actionable errors if prerequisites are missing; they never
install or upgrade shared services themselves.

Reserve a unique Compose project name and a free loopback port. Defaults are
`edunexa` and `127.0.0.1:8002`. Keep Video Studio's project, ports, Nginx files and
volumes unchanged. Check before proceeding:

```bash
docker compose version
docker ps --format 'table {{.Names}}\t{{.Ports}}'
sudo ss -ltnp
free -m
df -h .
sudo nginx -t
certbot --version
```

Allow public inbound 80 and 443 using your existing firewall policy. Never open
5432, 6379 or 8002 publicly. Budget at least 3 GiB free disk and 512 MiB currently
available RAM; the script warns below 2 GiB available. These are preflight floors,
not guarantees that a build will fit alongside Video Studio.

## First installation

Replace `REPOSITORY_URL` with your repository URL and review the approved revision.

```bash
git clone REPOSITORY_URL edunexa
cd edunexa
python3 scripts/env.py init .env --domain edunexa.sandeepwebsolutions.in --port 8002
chmod 600 .env
nano .env
```

Initialization generates random Django and URL-safe database secrets. It refuses
to overwrite any existing file. Set `EMAIL_HOST` and your SMTP credentials for real
production; leave `DEMO_MODE=0`. The template sets HTTPS hosts/origins, proxy trust,
secure production settings and the resource defaults. `DEBUG=False` is enforced
by Django production settings regardless of the environment.

The env parser accepts literal `KEY=value` lines, optionally quoted, without
shell expansion, duplicate keys or multiline values. It never executes `.env`.
PostgreSQL passwords must be URL-safe (`A-Z a-z 0-9 _ -`, at least 16 characters)
because Compose places them in the database URL. If existing credentials fail
validation, stop and plan a coordinated credential change; do not regenerate
them or simply edit the password of an initialized database.

```bash
# First start before the HTTPS vhost exists:
bash scripts/deploy.sh --local-only
```

Without `.env`, `deploy.sh` creates a private template and stops so you can
configure SMTP. It never overwrites an existing environment. `--local-only`
explicitly skips public and origin HTTPS verification; it is not a production
sign-off. Subsequent normal deployments use `bash scripts/deploy.sh`.

For a **new, disposable demonstration database**, initialize instead with:

```bash
python3 scripts/env.py init .env --domain edunexa.sandeepwebsolutions.in --port 8002 --demo
bash scripts/deploy.sh --seed-demo --local-only
```

Do not run initialization twice; if `.env` exists, review it manually. Seeding is
opt-in, refuses existing school data, keeps an existing demo unchanged and never
prints demo passwords. Use the demo role-login page. **The existing application
enables nightly resets in DEMO_MODE=1 for a database bearing its demo marker.**
Never reuse a demo database for real school records. Real production starts with
an empty database and an administrator created interactively:

```bash
docker compose --env-file .env -f docker-compose.prod.yml exec web python manage.py createsuperuser
```

## Cloudflare DNS, Nginx and SSL

In Cloudflare, create the domain's A record pointing at the VPS public IPv4.
Only add an AAAA record if IPv6 routing, firewall and Nginx listeners are configured;
the generated vhost listens on IPv4. The scripts do not change DNS or Cloudflare.
Keep SSL/TLS mode **Full (strict)**. For initial HTTP-01 issuance, DNS-only mode is
the simplest option until the origin certificate is installed. Ensure Cloudflare
redirect/WAF rules do not intercept `/.well-known/acme-challenge/`.

Preview the generated configuration without changing host files:

```bash
bash scripts/nginx.sh
cat .deploy/nginx.conf
```

After reviewing it, explicitly authorize installation and, if needed, ACME
registration/certificate issuance (replace the contact email):

```bash
sudo bash scripts/nginx.sh --apply --obtain-certificate --email admin@example.com
bash scripts/healthcheck.sh
```

This only manages `/etc/nginx/sites-available/edunexa-DOMAIN.conf` and its matching
enabled symlink. It refuses unmanaged files or a domain found in another enabled
vhost. It checks the existing Nginx configuration first, takes a private snapshot,
validates each change before reload and restores its previous vhost on failure.
It does not disable any other site. An existing valid matching Let's Encrypt
certificate is reused. Issuance uses Certbot webroot, not the Nginx plugin, so
Certbot cannot rewrite unrelated vhosts. A certificate obtained successfully is
retained even if a later health check fails.

Existing installations with a working custom Nginx/SSL configuration should keep
it; `deploy.sh` does not need to run `nginx.sh`. Certbot lineages with a `-0001`
suffix or Cloudflare Origin CA certificates require manual configuration review.
The direct-origin health check expects a public trusted chain (Let's Encrypt),
not Cloudflare's private Origin CA trust model.

Set `UPLOAD_LIMIT=10m` in `.env` if changing the proxy upload limit; application
validation still applies its own size limits. The proxy overwrites
`X-Forwarded-Proto`, uses 65-second I/O timeouts and forwards to loopback only.
It does not publish uploaded media: private school files need authorized Django
download views, not a public Nginx alias.

Verify certificate-specific renewal and the existing scheduler manually:

```bash
sudo certbot renew --cert-name edunexa.sandeepwebsolutions.in --dry-run
systemctl list-timers --all | grep -E 'certbot|renew'
sudo openssl x509 -in /etc/letsencrypt/live/edunexa.sandeepwebsolutions.in/fullchain.pem -noout -dates -subject
```

New issuance stores a deploy hook to validate and reload Nginx after renewal.
For reused certificates, inspect their existing renewal hook and timer/cron;
these are not silently rewritten. The helper warns if it cannot find a known
timer. Do not claim renewal is working until the dry run succeeds.

Cloudflare **526** means origin TLS validation failed. Check expiry, hostname,
full chain, matching key and the certificate served for the domain's SNI:

```bash
curl --fail --resolve edunexa.sandeepwebsolutions.in:443:127.0.0.1 https://edunexa.sandeepwebsolutions.in/health/
curl --fail https://edunexa.sandeepwebsolutions.in/health/
sudo nginx -t
```

The first command bypasses Cloudflare; the second tests the public route. Fix the
origin certificate instead of weakening Full (strict). Do not use `curl -k` to
declare a successful verification.

## Updating

For subsequent published releases, use a clean checkout. The default target is
`origin/main`, including when the local branch has no configured upstream:

```bash
bash scripts/update.sh
# Or choose an already approved remote revision explicitly:
bash scripts/update.sh origin/main
```

The update checks Git status, records HEAD, creates a verified backup, fetches
origin and resolves the intended revision to a commit. It refuses local commits
absent from that target, then fast-forwards to that exact commit. It then builds
and validates the image, stops web/worker/beat, waits for dependencies, creates
another backup with writers stopped, runs migrations and static collection in
one-off containers, and recreates application services. The image contains its
own collected static files; each one-off collection verifies production settings
without depending on a running web container. Workers do not run migrations.

A nonblocking operation lock prevents simultaneous deployment/update/backup/
restore/rollback. Versioned image tags and the previous image ID are retained in
`.deploy/`; no automatic image pruning occurs. `update.sh` invokes the newly
fetched deployment functions, so review deployment-script changes before updates.
For reproducibility, use approved immutable revisions and retain the built image;
base image tags and `packaging>=23.2` remain mutable dependencies.

## Backups, restore and rollback

```bash
bash scripts/backup.sh
```

Backups are private timestamped directories under `.deploy/backups/`, with a
PostgreSQL custom-format dump, media tarball, checksums and Git revision. The
script verifies archive readability, not every database constraint or future
restore compatibility. Copy them encrypted to another host/storage location and
perform restore drills. Optional `BACKUP_RETENTION_DAYS=14` prunes only complete
local backup sets; default `0` retains everything. Monitor disk growth.

Online backups may span concurrent media changes. Updates take a second backup
after stopping application writers. For other coordinated snapshots, stop the
application services first and leave PostgreSQL running. Redis is deliberately
not part of a database backup: replaying tasks against historical data needs
application-level review.

Restore is an explicit maintenance operation. Replace the example path with a
real backup directory:

```bash
bash scripts/restore.sh /opt/edunexa/.deploy/backups/TIMESTAMP --replace-database
```

The script verifies checksums, restores into a unique staging database before
changing the live database, stops application writers, backs up the current state,
and transactionally renames databases. It retains the replaced database with
connections disabled. It intentionally leaves application services stopped and
does not automatically migrate or restore media. Failed staging databases are
also retained for inspection.

Review the backup's revision, current migration compatibility, queued Celery
tasks and media before reopening. To merge the media backup back into the volume
after reviewing its paths (this can overwrite same-named files):

```bash
tar -tzf /opt/edunexa/.deploy/backups/TIMESTAMP/media.tar.gz
docker compose --env-file .env -f docker-compose.prod.yml run --rm -T --no-deps web tar -C /app/media -xzf - < /opt/edunexa/.deploy/backups/TIMESTAMP/media.tar.gz
```

Do not blindly purge Redis or run old queued tasks against restored data. Choose
the compatible application image deliberately, then use the deployment workflow
to apply reviewed forward migrations and restart. If restoring a matching old
schema/image without migrations, set the chosen image explicitly:

```bash
export EDUNEXA_IMAGE="$(cat .deploy/image)"
docker compose --env-file .env -f docker-compose.prod.yml up -d --no-deps --wait --wait-timeout 180 web worker beat
bash scripts/healthcheck.sh
```

For an application-only rollback, **first verify that the previous image works
with the current database schema**, then:

```bash
bash scripts/rollback.sh --schema-compatible
```

It restores the recorded previous image only, without Git reset, reverse
migrations, database restore or dependency recreation. It retains the current
schema. An incompatible schema requires a reviewed recovery plan and possibly an
explicit database restore; restoring loses writes made after the backup.

After any failed deployment, inspect `.deploy/latest-backup`,
`.deploy/previous-image`, `.deploy/before-revision` and scoped logs. A failure after
migration starts may leave services stopped. Fix the cause and rerun deployment,
or use the compatible-image rollback above. No automatic schema reversal occurs.

## Adopting this on the already-deployed VPS

Use this section when adopting the automation for the first time on an existing
installation. No live VPS changes were made during implementation.

1. Schedule a maintenance window and take an off-host database backup using the
   current installation. Record the current image ID and Git revision.
2. Identify the current Compose project and its **actual** PostgreSQL volume:

   ```bash
   docker compose --env-file .env -f docker-compose.prod.yml ps
   docker inspect "$(docker compose --env-file .env -f docker-compose.prod.yml ps -q db)" --format '{{json .Mounts}}'
   git rev-parse HEAD
   ```

3. Keep the same repository location, `.env`, project name, database name and
   `postgres_data` volume. Never rename the project as an upgrade technique: that
   creates a different volume. Keep the current password and secret key. Set
   `COMPOSE_PROJECT_NAME` in the existing `.env` to the recorded name if needed.
4. Fetch/check out the approved revision using your normal reviewed workflow.
   Preserve any local edits first. Run `chmod 600 .env`, add only missing template
   keys and run `python3 scripts/env.py validate .env`. Do not copy the template
   over the existing file. Keep the current working Nginx and certificate.
5. This release adds `/app/media` persistence. The current repository has no
   persisted upload model; CSV uploads are processed on receipt. If your running
   installation/customization has files inside a container, copy them out before
   recreation and explicitly migrate them into the new volume. Mounting an empty
   volume would otherwise hide files in that path.
6. Before the first Redis recreation, stop producers and allow existing workers
   to drain pending jobs. The previous Redis configuration has no persistence;
   recreating it can lose queued tasks. Review active/reserved/scheduled tasks.
7. Deploy and verify:

   ```bash
   bash scripts/backup.sh
   bash scripts/deploy.sh
   bash scripts/healthcheck.sh
   ```

8. Check school records, logins, file workflows and scheduled jobs manually. Check
   Video Studio's URL and containers before and after. Do not enable demo seeding
   on a real school database. Verify renewal as above.

## Enable or restore the right-side AI assistant

The LangGraph/Gemini assistant is already included. Every signed-in role gets an
**Ask AI** button at the bottom right when `GEMINI_API_KEY` is configured in the
running web service. The chat uses the same access restrictions as the ERP.
An active system administrator sees a setup message if the key is missing.

In the existing VPS repository, edit the production environment privately:

```bash
nano .env
```

Set `GEMINI_API_KEY` to your own key; keep it out of Git and screenshots.
`ASSISTANT_MODEL` defaults to `gemini-3.5-flash-lite`. Pulling source code does not
copy your computer's `.env` to the VPS. Apply this code release using the updater
above. If you only changed the key after deploying the current release, reload
the web container using the already-deployed image:

```bash
export EDUNEXA_IMAGE="$(cat .deploy/image)"
docker compose --env-file .env -f docker-compose.prod.yml up -d --no-deps --force-recreate --wait --wait-timeout 180 web
docker compose --env-file .env -f docker-compose.prod.yml exec -T web python manage.py check_assistant
```

This image reference exists after using `scripts/deploy.sh` or `scripts/update.sh`;
older installations should complete the adoption steps first. A plain container
restart does not load edited Compose environment values. The connection check
makes one small Gemini request with synthetic text and prints no credentials or
school records. A failure names key/access, model, quota or connectivity checks
without exposing provider exception contents.

Refresh the website, click **Ask AI** (or **Ctrl+/**), enter a question and press
Enter. Shift+Enter adds a line. The panel keeps the current conversation while
you navigate; **New conversation** clears it. For local development, set the key
in the root `.env`, restart Django and run `python manage.py check_assistant`.

## Operations and limitations

```bash
bash scripts/healthcheck.sh
docker compose --env-file .env -f docker-compose.prod.yml ps
docker compose --env-file .env -f docker-compose.prod.yml logs --tail 100 web worker beat
docker compose --env-file .env -f docker-compose.prod.yml exec -T web python manage.py showmigrations
docker compose --env-file .env -f docker-compose.prod.yml exec -T worker celery -A config inspect active
```

Health checks cover SQL, Redis, container health, migration state, Django security
checks, an actual queued worker job, local HTTP/static, public HTTPS and direct
origin TLS. Restart counts, OOM flags, CPU/RAM snapshots and disk usage are shown.
Beat health establishes process startup/schedule creation, not proof that every
periodic task executes on time. Check job outcomes and logs for that guarantee.

Defaults stay at two Gunicorn workers, one Celery worker process, and memory
limits of 512/768/192/512/256 MiB for web/worker/beat/PostgreSQL/Redis. Logs rotate
at 10 MiB with five files per service. This is not a measured performance target;
observe both applications before adjusting limits. Build memory is not constrained
by runtime limits. Multiple services can contend for the single CPU.

Redis now uses AOF with `everysec`, a persistent volume and `noeviction` at 128 MiB.
Power loss can still lose roughly a second of writes; full Redis can reject jobs.
Late acknowledgment/prefetch-one settings already existed. Delivery is at least
once, not exactly once: crashes can redeliver tasks, and tasks need idempotency.
Redis persistence is not an off-host backup or a reconciliation system.

Common errors:

| Error | Action |
|---|---|
| `No module named config` | Use the repository Dockerfile, `/app` workdir and `PYTHONPATH=/app`; rebuild the approved image. |
| Missing `packaging` | It is already in base requirements; run a clean image build if an old image is still deployed. |
| Host `python` not found | Host commands use `python3`; application commands run `python` inside containers. |
| `web` is not running | Migrations use `compose run --rm -T --no-deps`, never first-start `exec`. |
| Compose wrong project/env | Run from repo root with explicit production file and preserve the existing project name. |
| Port occupied | Stop and identify its owner; do not stop unrelated applications. Choose a different port if needed. |
| DB unhealthy/migration failed | Inspect scoped DB/app logs and backup; fix the cause, never reset volumes. |
| Nginx validation failed | Helper restores its prior config; inspect `sudo nginx -t`. |
| Public works, direct TLS fails | Check origin chain/SNI/expiry; Cloudflare may mask origin problems. |
| Static health 404 | Rebuild image and verify WhiteNoise/static collection; do not add a development static server. |

Never run volume deletion, global pruning or destructive database resets as a
deployment fix. Secrets, media and `.deploy/` are excluded from Git and builds.
Application logs can still contain personal data; protect access to them.

## Validation

See [DEPLOYMENT_AUDIT.md](DEPLOYMENT_AUDIT.md) for the actual local test results
and VPS-only checks still pending. Reproduce the isolated Docker rehearsal:

```bash
docker build -t edunexa:reliability-test .
python3 e2e/rehearse_vps.py
```

It uses a unique project and generated environment, loopback port 18092, and
retains test volumes/archives for inspection. Do not run it where 18092 is occupied.
It never removes production volumes. The shell fault tests use mocks, not a real
Nginx reload or a live ACME request.
