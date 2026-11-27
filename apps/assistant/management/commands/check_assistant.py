"""Check the configured Gemini connection without sending school records or logging secrets."""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from langchain_core.exceptions import (
    ModelAuthenticationError,
    ModelNotFoundError,
    ModelPermissionDeniedError,
    ModelRateLimitError,
)

from apps.assistant.agent import chat_model


class Command(BaseCommand):
    help = "Verify the Gemini key and model with one short request; no school data is sent."
    requires_system_checks = []

    def handle(self, *args, **options):
        if not (settings.GEMINI_API_KEY or "").strip():
            raise CommandError("Set GEMINI_API_KEY in the server environment and restart web.")
        try:
            reply = chat_model().invoke(
                "Connection test. Reply only with OK.", timeout=20, max_retries=0
            )
            if not reply.text.strip():
                raise CommandError("Gemini returned an empty answer; check ASSISTANT_MODEL.")
        except (ModelAuthenticationError, ModelPermissionDeniedError):
            raise CommandError(
                "Gemini rejected the credentials or access. Check the key and project permissions."
            ) from None
        except ModelNotFoundError:
            raise CommandError(
                "The configured ASSISTANT_MODEL is unavailable for this key."
            ) from None
        except ModelRateLimitError:
            raise CommandError(
                "Gemini quota or rate limit reached. Check the project's quota and billing."
            ) from None
        except CommandError:
            raise
        except Exception as error:
            # Never expose provider exception strings: they may include credentials or URLs.
            raise CommandError(
                f"Gemini connection failed ({type(error).__name__}). "
                "Check the key, model, quota and outbound HTTPS access."
            ) from None
        self.stdout.write(
            self.style.SUCCESS("Gemini connection verified. No school data was sent.")
        )
