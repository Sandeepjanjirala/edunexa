"""Isolated production Compose rehearsal. Never uses the developer's .env or stack.

Run after building edunexa:reliability-test. Leaves test volumes for inspection;
removes only this rehearsal's containers/network, without deleting volumes.
"""

import os
import secrets
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    project = "edunexa-test-" + secrets.token_hex(4)
    folder = ROOT / ".deploy" / project
    folder.mkdir(parents=True)
    env_file = folder / ".env"
    subprocess.run(
        [
            sys.executable,
            "scripts/env.py",
            "init",
            str(env_file),
            "--demo",
            "--port",
            "18092",
            "--domain",
            "test.example.com",
        ],
        cwd=ROOT,
        check=True,
    )
    with env_file.open("a") as stream:
        stream.write("\nDEMO_SIZE=small\nEDUNEXA_IMAGE=edunexa:reliability-test\n")
    env = os.environ.copy()
    env.update(
        EDUNEXA_ENV_FILE=str(env_file),
        COMPOSE_PROJECT_NAME=project,
        EDUNEXA_IMAGE="edunexa:reliability-test",
    )
    command = [
        "docker",
        "compose",
        "--project-directory",
        str(ROOT),
        "--env-file",
        str(env_file),
        "-p",
        project,
        "-f",
        str(ROOT / "docker-compose.prod.yml"),
    ]

    def dc(*args, **kwargs):
        return subprocess.run([*command, *args], env=env, cwd=ROOT, check=True, **kwargs)

    def manage(*args):
        dc("run", "--rm", "-T", "--no-deps", "web", "python", "manage.py", *args)

    def shell(code):
        manage("shell", "-c", code)

    try:
        dc("config", "--quiet")
        dc("up", "-d", "--wait", "--wait-timeout", "180", "db", "redis")
        manage("check", "--deploy", "--fail-level", "WARNING")
        manage("migrate", "--noinput")
        manage("migrate", "--noinput")
        manage("initialize_demo")
        shell(
            "from apps.accounts.models import User; User.objects.create_superuser('persistence-sentinel', 'sentinel@example.invalid', 'test-only')"
        )
        manage("initialize_demo")
        shell(
            "from apps.accounts.models import User; assert User.objects.filter(username='persistence-sentinel').exists()"
        )
        dc(
            "run",
            "--rm",
            "-T",
            "--no-deps",
            "web",
            "python",
            "-c",
            "from pathlib import Path; Path('/app/media/sentinel').write_text('persistent')",
        )
        dc("up", "-d", "--no-deps", "--wait", "--wait-timeout", "180", "web", "worker", "beat")
        dc("exec", "-T", "web", "python", "manage.py", "check_jobs", "--timeout", "30")
        for path in ("/health/", "/static/css/base.css"):
            request = urllib.request.Request(
                "http://127.0.0.1:18092" + path,
                headers={"Host": "test.example.com", "X-Forwarded-Proto": "https"},
            )
            with urllib.request.urlopen(request, timeout=15) as response:
                assert response.status == 200
        with (folder / "database.dump").open("wb") as stream:
            dc(
                "exec",
                "-T",
                "db",
                "pg_dump",
                "-U",
                "edunexa",
                "-d",
                "edunexa",
                "-Fc",
                stdout=stream,
            )
        dc("exec", "-T", "db", "createdb", "-U", "edunexa", "restore_drill")
        with (folder / "database.dump").open("rb") as stream:
            dc(
                "exec",
                "-T",
                "db",
                "pg_restore",
                "-U",
                "edunexa",
                "-d",
                "restore_drill",
                "--exit-on-error",
                stdin=stream,
            )
        dc(
            "exec",
            "-T",
            "db",
            "psql",
            "-U",
            "edunexa",
            "-d",
            "restore_drill",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM accounts_user WHERE username='persistence-sentinel') THEN RAISE EXCEPTION 'missing sentinel'; END IF; END $$;",
        )
        dc("exec", "-T", "redis", "redis-cli", "SET", "rehearsal-persistence", "yes")
        time.sleep(2)  # Allow Redis everysec AOF to flush before recreation.
        dc("stop", "web", "worker", "beat")
        dc("up", "-d", "--force-recreate", "--wait", "--wait-timeout", "180", "db", "redis")
        dc(
            "up",
            "-d",
            "--no-deps",
            "--force-recreate",
            "--wait",
            "--wait-timeout",
            "180",
            "web",
            "worker",
            "beat",
        )
        shell(
            "from apps.accounts.models import User; assert User.objects.filter(username='persistence-sentinel').exists()"
        )
        dc(
            "exec",
            "-T",
            "web",
            "python",
            "-c",
            "from pathlib import Path; assert Path('/app/media/sentinel').read_text() == 'persistent'",
        )
        result = dc(
            "exec",
            "-T",
            "redis",
            "redis-cli",
            "GET",
            "rehearsal-persistence",
            capture_output=True,
            text=True,
        )
        assert result.stdout.strip() == "yes"
        dc("restart", "web", "worker", "beat")
        dc("up", "-d", "--wait", "--wait-timeout", "180")
        dc("exec", "-T", "web", "python", "manage.py", "check_jobs", "--timeout", "30")
        print(
            f"PASS: production migrations, repeat seed, HTTP/static, worker, restart, DB/media/Redis persistence and restore drill. Project: {project}"
        )
    finally:
        dc("down")  # Deliberately retains volumes; never down -v.
        print(f"Artifacts: {folder}; test volumes retained under {project}_*.")


if __name__ == "__main__":
    main()
