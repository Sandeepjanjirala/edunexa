"""Read deployment dotenv without executing shell code; never print secret values."""

import argparse
import os
import re
import secrets
import sys
from pathlib import Path


def read_env(path):
    values = {}
    for number, raw in enumerate(Path(path).read_text().splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            raise ValueError(f"Invalid .env assignment at line {number}")
        if key in values:
            raise ValueError(f"Duplicate .env key: {key}")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if "$" in value or "`" in value or "\x00" in value:
            raise ValueError(f"Use literal values without interpolation for {key}")
        values[key] = value
    return values


def validate(values):
    required = (
        "DJANGO_SECRET_KEY",
        "POSTGRES_PASSWORD",
        "SITE_DOMAIN",
        "SITE_URL",
        "ALLOWED_HOSTS",
        "CSRF_TRUSTED_ORIGINS",
        "DEMO_MODE",
    )
    for key in required:
        if not values.get(key):
            raise ValueError(f"Set {key} in the production .env")
    domain = values["SITE_DOMAIN"]
    if (
        not re.fullmatch(r"(?=.{1,253}$)[a-z0-9]+(?:[a-z0-9.-]*[a-z0-9])?", domain)
        or "." not in domain
    ):
        raise ValueError("SITE_DOMAIN must be a lowercase DNS hostname")
    if len(values["DJANGO_SECRET_KEY"]) < 50:
        raise ValueError("DJANGO_SECRET_KEY must contain at least 50 characters")
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,}", values["POSTGRES_PASSWORD"]):
        raise ValueError(
            "POSTGRES_PASSWORD must be URL-safe and at least 16 characters; do not change an existing DB password blindly"
        )
    if values["SITE_URL"] != f"https://{domain}":
        raise ValueError("SITE_URL must be https://SITE_DOMAIN")
    if domain not in values["ALLOWED_HOSTS"].split(",") or f"https://{domain}" not in values[
        "CSRF_TRUSTED_ORIGINS"
    ].split(","):
        raise ValueError(
            "Include SITE_DOMAIN in ALLOWED_HOSTS and its HTTPS URL in CSRF_TRUSTED_ORIGINS"
        )
    if values["DEMO_MODE"] not in ("0", "1"):
        raise ValueError("DEMO_MODE must be 0 or 1")
    if values["DEMO_MODE"] == "0" and not values.get("EMAIL_HOST"):
        raise ValueError("Set EMAIL_HOST for real production email")
    if (
        not values.get("PORT", "8002").isdigit()
        or not 1024 <= int(values.get("PORT", "8002")) <= 65535
    ):
        raise ValueError("PORT must be 1024..65535")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", values.get("COMPOSE_PROJECT_NAME", "edunexa")):
        raise ValueError("Invalid COMPOSE_PROJECT_NAME")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("init", "validate", "export"))
    parser.add_argument("path", type=Path)
    parser.add_argument("--domain", default="edunexa.sandeepwebsolutions.in")
    parser.add_argument("--port", default="8002")
    parser.add_argument("--demo", action="store_true")
    args = parser.parse_args()
    if args.action == "init":
        template = Path(__file__).resolve().parents[1] / ".env.production.example"
        text = template.read_text().replace("edunexa.sandeepwebsolutions.in", args.domain)
        text = text.replace("PORT=8002", f"PORT={args.port}")
        text = text.replace(
            "DJANGO_SECRET_KEY=\n", f"DJANGO_SECRET_KEY={secrets.token_urlsafe(60)}\n"
        )
        text = text.replace(
            "POSTGRES_PASSWORD=\n", f"POSTGRES_PASSWORD={secrets.token_urlsafe(32)}\n"
        )
        text = text.replace("DEMO_MODE=0", f"DEMO_MODE={int(args.demo)}")
        # O_EXCL prevents both accidental overwrite and concurrent initialization races.
        fd = os.open(args.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", newline="\n") as stream:
            stream.write(text)
        print("Created private environment file; configure SMTP before real production deployment.")
        return
    values = read_env(args.path)
    validate(values)
    if args.action == "export":
        for key, value in values.items():
            sys.stdout.buffer.write(f"{key}={value}".encode() + b"\0")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError) as error:
        sys.exit(str(error))
