from .policies import can_use_assistant


def assistant(request):
    """Whether the sidebar shows the assistant."""
    return {"can_use_assistant": can_use_assistant(request.user)}
