"""Deployment-only, repeatable initialization without reset or password output."""

import io

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User
from apps.demo.models import DemoMarker
from apps.organization.models import Organization


class Command(BaseCommand):
    help = "Initialize an empty demo database, or leave an existing demo untouched."

    def handle(self, **options):
        if not settings.DEMO_MODE:
            raise CommandError("Requires DEMO_MODE=1; never seed a real production database.")
        if DemoMarker.objects.exists():
            self.stdout.write("Existing demo retained; no reset performed.")
            return
        if User.objects.exists() or Organization.objects.exists():
            raise CommandError("Existing school data detected; initialization refused.")
        call_command("seed_demo", size=settings.DEMO_SIZE, stdout=io.StringIO())
        self.stdout.write("Demo initialized. Use the demo role-login page; no passwords logged.")
