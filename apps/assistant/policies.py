from django.conf import settings

from apps.accounts.throttling import throttle


def can_use_assistant(user):
    """Everyone signed in, once a Gemini key is configured. The tools decide what each role sees."""
    return bool(settings.GEMINI_API_KEY) and user.is_authenticated and user.is_active


def may_ask(user):
    """Count a question against the user's hourly limit; False once it is used up."""
    allowed, _ = throttle("assistant", str(user.pk), settings.ASSISTANT_HOURLY_LIMIT, minutes=60)
    return allowed
