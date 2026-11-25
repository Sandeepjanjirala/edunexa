import json
from unittest import mock

from django.test import override_settings
from django.urls import reverse
from langchain_core.exceptions import ModelRateLimitError
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, ToolMessage
from pydantic import Field

from apps.assistant.agent import AssistantBusy, AssistantUnavailable, ask, instructions
from apps.assistant.tools import tools_for
from apps.core.testing import PASSWORD, SchoolTestCase


class FakeModel(GenericFakeChatModel):
    """Answers with the scripted messages in turn, and keeps what it was sent each time."""

    seen: list = Field(default_factory=list)

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, *args, **kwargs):
        self.seen.append(messages)
        return super()._generate(messages, *args, **kwargs)


def scripted(*replies):
    return FakeModel(messages=iter(replies))


def call(tool_name, **args):
    return AIMessage(content="", tool_calls=[{"name": tool_name, "args": args, "id": tool_name}])


def run(user, tool_name, **args):
    """Call one of the user's tools as the model would; None if the user isn't offered it."""
    found = {t.name: t for t in tools_for(user)}
    return found[tool_name].invoke(args) if tool_name in found else None


class ToolScopeTests(SchoolTestCase):
    """The tools see exactly what the user could open in EduNexa."""

    def names(self, user):
        return {t.name for t in tools_for(user)}

    def test_each_role_is_offered_only_the_tools_it_has_use_for(self):
        self.assertIn("school_overview", self.names(self.teacher))
        self.assertNotIn("fees_overview", self.names(self.teacher))
        self.assertEqual(self.names(self.accountant), {"fees_overview", "latest_announcements"})
        self.assertIn("fees_overview", self.names(self.parent))
        self.assertNotIn("school_overview", self.names(self.parent))
        self.assertNotIn("fees_overview", self.names(self.e1.student.user))

    def test_staff_find_students_in_their_own_classes_only(self):
        found = json.loads(run(self.teacher, "find_students", name="alice"))
        self.assertEqual([s["student_id"] for s in found], [self.e1.student.pk])
        self.assertEqual(found[0]["class"], "9-A")
        self.assertEqual(json.loads(run(self.foreign_teacher, "find_students", name="alice")), [])

    def test_a_parent_finds_only_their_own_child(self):
        found = json.loads(run(self.parent, "find_students", name="bob"))
        self.assertEqual([s["name"] for s in found], ["alice"])

    def test_a_record_outside_the_users_scope_is_not_found(self):
        reply = run(self.parent, "student_record", student_id=self.e2.student.pk)
        self.assertEqual(reply, "No student with that id is in your records.")
        record = json.loads(run(self.parent, "student_record", student_id=self.e1.student.pk))
        self.assertEqual(record["name"], "alice")
        self.assertEqual(record["results"]["published_exams"], 0)

    def test_families_see_published_exams_only(self):
        self.assertEqual(json.loads(run(self.parent, "list_exams")), [])
        teacher_exams = {e["exam"] for e in json.loads(run(self.teacher, "list_exams"))}
        self.assertEqual(teacher_exams, {"Midterm", "Science test"})

    def test_fees_for_finance_staff_and_parents(self):
        self.assertEqual(json.loads(run(self.parent, "fees_overview"))["outstanding"], "₹0.00")
        self.assertEqual(json.loads(run(self.accountant, "fees_overview"))["billed"], "₹0.00")
        self.assertIsNone(run(self.teacher, "fees_overview"))


class AgentTests(SchoolTestCase):
    def test_the_model_answers_from_the_tool_results(self):
        model = scripted(call("find_students", name="alice"), "Alice is in 9-A.")
        with mock.patch("apps.assistant.agent.chat_model", return_value=model):
            answer = ask(self.teacher, "Which class is Alice in?", [("Hi", "Hello!")])
        self.assertEqual(answer, "Alice is in 9-A.")
        first, second = model.seen
        self.assertIn("teacher", first[0].content)  # the instructions name the role
        self.assertEqual(
            [m.content for m in first[1:]], ["Hi", "Hello!", "Which class is Alice in?"]
        )
        result = second[-1]
        self.assertIsInstance(result, ToolMessage)
        self.assertIn('"class": "9-A"', result.content)

    def test_a_made_up_tool_or_wrong_arguments_go_back_to_the_model(self):
        model = scripted(
            call("delete_student", student_id=1), call("student_record"), "I can't do that."
        )
        with mock.patch("apps.assistant.agent.chat_model", return_value=model):
            self.assertEqual(ask(self.teacher, "Delete Alice"), "I can't do that.")
        made_up, wrong = model.seen[1][-1], model.seen[2][-1]
        self.assertEqual(made_up.status, "error")
        self.assertIn("no tool called delete_student", made_up.content)
        self.assertEqual(wrong.status, "error")
        self.assertIn("student_id", wrong.content)

    def test_the_instructions_name_the_page_the_question_came_from(self):
        self.assertIn('They have the "Fees" page open.', instructions(self.parent, "Fees"))
        self.assertNotIn("page open", instructions(self.parent))

    def test_markdown_emphasis_is_removed(self):
        model = scripted("**Nothing** is due.")
        with mock.patch("apps.assistant.agent.chat_model", return_value=model):
            self.assertEqual(ask(self.parent, "Fees?"), "Nothing is due.")

    def test_model_failures_become_assistant_errors(self):
        for error, expected in (
            (ModelRateLimitError("quota"), AssistantBusy),
            (ConnectionError("offline"), AssistantUnavailable),
        ):
            with (
                self.subTest(error=error),
                mock.patch("apps.assistant.agent.chat_model", side_effect=error),
                self.assertLogs("apps.assistant.agent"),
                self.assertRaises(expected),
            ):
                ask(self.teacher, "Hello?")


@override_settings(GEMINI_API_KEY="test-key", ASSISTANT_HOURLY_LIMIT=30)
class AssistantPageTests(SchoolTestCase):
    url = reverse("assistant")

    def setUp(self):
        super().setUp()
        self.client.login(username="teacher", password=PASSWORD)

    def post(self, question, htmx=True, page="", **answer):
        headers = {"HX-Request": "true"} if htmx else {}
        data = {"question": question, "page": page}
        with mock.patch("apps.assistant.views.ask", **answer) as asked:
            response = self.client.post(self.url, data, headers=headers)
        return response, asked

    def test_switched_off_without_a_key(self):
        with override_settings(GEMINI_API_KEY=""):
            self.assertEqual(self.client.get(self.url).status_code, 404)
            self.assertNotContains(self.client.get(reverse("dashboard")), 'href="/assistant/"')
        self.assertContains(self.client.get(reverse("dashboard")), 'href="/assistant/"')

    def test_every_page_but_the_assistant_page_has_the_ask_ai_panel(self):
        self.assertContains(self.client.get(reverse("dashboard")), 'id="assistant-panel"')
        self.assertNotContains(self.client.get(self.url), 'id="assistant-panel"')
        with override_settings(GEMINI_API_KEY=""):
            self.assertNotContains(self.client.get(reverse("dashboard")), "data-assistant-open")
            panel = self.client.get(reverse("assistant_panel"))
            self.assertEqual(panel.status_code, 404)

    def test_the_panel_carries_the_conversation_and_knows_the_page(self):
        panel = self.client.get(reverse("assistant_panel"), {"page": "Daily attendance"})
        self.assertTemplateUsed(panel, "assistant/_chat.html")
        self.assertContains(panel, "How do I use the Daily attendance page?")
        self.assertContains(panel, 'name="page" value="Daily attendance"', count=2)
        _, asked = self.post("Who is absent?", page="Daily attendance", return_value="Nobody.")
        asked.assert_called_once_with(self.teacher, "Who is absent?", [], "Daily attendance")
        self.assertContains(self.client.get(reverse("assistant_panel")), "Nobody.")

    def test_the_empty_page_offers_questions_for_the_role(self):
        response = self.client.get(self.url)
        self.assertContains(response, "What are my lessons today?")
        self.assertNotContains(response, "New conversation")

    def test_htmx_adds_the_exchange_and_the_conversation_carries_on(self):
        response, asked = self.post("Who is absent?", return_value="Nobody.")
        self.assertTemplateUsed(response, "assistant/_exchange.html")
        self.assertContains(response, "Who is absent?")
        self.assertContains(response, "Nobody.")
        asked.assert_called_once_with(self.teacher, "Who is absent?", [], "")
        _, asked = self.post("And yesterday?", return_value="Alice.")
        asked.assert_called_once_with(
            self.teacher, "And yesterday?", [("Who is absent?", "Nobody.")], ""
        )
        page = self.client.get(self.url)
        self.assertContains(page, "Nobody.")
        self.assertContains(page, "New conversation")

    def test_without_javascript_the_page_reloads(self):
        response, _ = self.post("Who is absent?", htmx=False, return_value="Nobody.")
        self.assertRedirects(response, self.url)
        response, _ = self.post("Again?", htmx=False, side_effect=AssistantUnavailable)
        self.assertContains(response, "couldn&#x27;t answer just now")

    def test_a_failed_answer_is_shown_but_not_kept(self):
        response, _ = self.post("Who is absent?", side_effect=AssistantBusy)
        self.assertContains(response, "is-failed")
        self.assertContains(response, "busy with other questions")
        self.assertNotContains(self.client.get(self.url), "Who is absent?")

    def test_a_blank_question_adds_nothing(self):
        response, asked = self.post("   ")
        self.assertEqual(response.status_code, 204)
        asked.assert_not_called()

    @override_settings(ASSISTANT_HOURLY_LIMIT=1)
    def test_questions_are_limited_per_hour(self):
        self.post("One?", return_value="Yes.")
        response, asked = self.post("Two?", return_value="Yes.")
        asked.assert_not_called()
        self.assertContains(response, "a lot of questions this hour")

    def test_a_new_conversation_forgets_the_old_one(self):
        self.post("Who is absent?", return_value="Nobody.")
        self.assertEqual(self.client.get(reverse("assistant_clear")).status_code, 405)
        self.assertRedirects(self.client.post(reverse("assistant_clear")), self.url)
        self.assertNotContains(self.client.get(self.url), "Nobody.")

    def test_the_panel_starts_a_new_conversation_in_place(self):
        self.post("Who is absent?", return_value="Nobody.")
        response = self.client.post(
            reverse("assistant_clear"), {"page": "Fees"}, headers={"HX-Request": "true"}
        )
        self.assertTemplateUsed(response, "assistant/_chat.html")
        self.assertContains(response, "How do I use the Fees page?")
        self.assertNotContains(response, "Nobody.")
