from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.models import User

from .agent import AssistantBusy, AssistantUnavailable, ask
from .forms import QuestionForm
from .policies import can_use_assistant, may_ask

# The conversation lives in the session: the last KEEP exchanges are shown, and the last
# CONTEXT go to the model with a new question so it can follow up ("and her attendance?").
SESSION_KEY = "assistant"
KEEP = 20
CONTEXT = 6


@login_required
def assistant(request):
    """Ask a question. With htmx, only the new exchange is returned and added to the page;
    without JavaScript, the page reloads with the whole conversation."""
    if not can_use_assistant(request.user):
        raise Http404
    conversation = request.session.get(SESSION_KEY, [])
    form = QuestionForm(request.POST or None)
    if request.method == "POST" and not form.is_valid() and request.headers.get("HX-Request"):
        return HttpResponse(status=204)  # a blank question: nothing to add to the conversation
    if request.method == "POST" and form.is_valid():
        question, page = form.cleaned_data["question"], form.cleaned_data["page"]
        exchange = answer(request.user, question, conversation, page)
        if not exchange["failed"]:
            conversation = [*conversation, exchange][-KEEP:]
            request.session[SESSION_KEY] = conversation
        if request.headers.get("HX-Request"):
            return render(request, "assistant/_exchange.html", {"exchange": exchange})
        if exchange["failed"]:
            form.add_error("question", exchange["answer"])
        else:
            return redirect("assistant")
    return render(
        request, "assistant/assistant.html", {"title": "AI assistant", **chat(request, form)}
    )


@login_required
def panel(request):
    """The conversation in the panel that the "Ask AI" button opens beside any page. htmx loads
    it when the panel is first opened; `page` is the title of the page underneath."""
    if not can_use_assistant(request.user):
        raise Http404
    page = request.GET.get("page", "")[:120]
    return render(request, "assistant/_chat.html", chat(request, QuestionForm(), page))


def chat(request, form, page=""):
    """What the conversation template needs, on the assistant page and in the panel."""
    return {
        "form": form,
        "page": page,
        "conversation": request.session.get(SESSION_KEY, []),
        **starters(request.user, page),
    }


def starters(user, page=""):
    """What an empty conversation offers: the topics this role can ask about, and a few
    questions, starting with help for the page the panel was opened on."""
    if user.is_accountant:
        topics = "fees, payments and announcements"
        suggestions = ["How much is outstanding?", "Which invoices are most overdue?"]
    elif user.is_family:
        child = "my" if user.is_student else "my child's"
        topics = (
            "attendance, results, timetables, leave"
            + (", fees" if user.is_parent else "")
            + " and announcements"
        )
        suggestions = [f"How is {child} attendance this year?", f"How did {child} exams go?"]
        suggestions.append(
            "Do I have any fees due?" if user.is_parent else "What are my lessons tomorrow?"
        )
    else:
        topics = (
            "students, attendance, exams, leave"
            + (", fees" if user.is_finance else "")
            + (", timetables" if user.role == User.Role.TEACHER else "")
            + " and announcements"
        )
        suggestions = ["Who is below 75% attendance?", "What is waiting for me?"]
        if user.role == User.Role.TEACHER:
            suggestions.append("What are my lessons today?")
        if user.is_finance:
            suggestions.append("How much fee is outstanding?")
    if page:
        suggestions.insert(0, f"How do I use the {page} page?")
    return {"topics": topics, "suggestions": suggestions}


def answer(user, question, conversation, page=""):
    """One exchange: the question and the assistant's answer, or why there isn't one."""
    if not may_ask(user):
        reply, failed = "You've asked a lot of questions this hour. Please try again later.", True
    else:
        history = [(e["question"], e["answer"]) for e in conversation[-CONTEXT:]]
        try:
            reply, failed = ask(user, question, history, page), False
        except AssistantBusy:
            reply = "The assistant is busy with other questions. Please try again in a minute."
            failed = True
        except AssistantUnavailable:
            reply = "The assistant couldn't answer just now. Please try again in a moment."
            failed = True
    return {"question": question, "answer": reply, "failed": failed}


@login_required
@require_POST
def clear(request):
    request.session.pop(SESSION_KEY, None)
    if request.headers.get("HX-Request"):
        # The panel's "New conversation": it starts afresh in place, on the same page.
        page = request.POST.get("page", "")[:120]
        return render(request, "assistant/_chat.html", chat(request, QuestionForm(), page))
    return redirect("assistant")
