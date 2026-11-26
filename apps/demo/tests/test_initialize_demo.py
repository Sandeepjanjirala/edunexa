from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from apps.accounts.models import User
from apps.organization.models import Organization


@override_settings(DEMO_MODE=True, DEMO_SIZE="small")
class InitializeDemoTests(TestCase):
    def test_repeat_keeps_data_and_does_not_log_password(self):
        output = StringIO()
        call_command("initialize_demo", stdout=output)
        User.objects.create_superuser("keep-me", "keep@example.invalid", "test-only")
        count = User.objects.count()
        call_command("initialize_demo", stdout=output)
        self.assertEqual(User.objects.count(), count)
        self.assertTrue(User.objects.filter(username="keep-me").exists())
        self.assertNotIn("Demo password", output.getvalue())

    def test_existing_school_is_never_seeded(self):
        Organization.objects.create(name="Real school")
        with self.assertRaises(CommandError):
            call_command("initialize_demo")
        self.assertEqual(Organization.objects.get().name, "Real school")

    @override_settings(DEMO_MODE=False)
    def test_production_refused(self):
        with self.assertRaises(CommandError):
            call_command("initialize_demo")
