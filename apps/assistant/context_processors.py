from .policies import can_use_assistant, can_view_assistant


def assistant(request):
    """Show chat when connected, and a setup state for system administrators otherwise."""
    return {
        "can_use_assistant": can_use_assistant(request.user),
        "can_view_assistant": can_view_assistant(request.user),
    }
