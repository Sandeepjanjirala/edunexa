"""jQuery integration with real HTMX, CSP and browser APIs; external services are stubbed."""

import re
from datetime import timedelta
from unittest.mock import patch
from urllib.parse import parse_qs

from django.test import override_settings
from django.urls import reverse

from apps.assistant.agent import AssistantUnavailable
from apps.fees.models import FeeHead, FeePlan, PaymentOrder
from apps.fees.services import issue_invoices, save_fee_plan
from e2e.browser.test_browser import BrowserTestCase, expect


class JQueryInteractionTests(BrowserTestCase):
    def test_cancel_prevents_htmx_request_even_after_content_replacement(self):
        page = self.open_as(self.admin, "/")
        requests = []

        def record(route):
            requests.append(route.request)
            route.fulfill(status=200, content_type="text/html", body="<span>Confirmed once</span>")

        page.route("**/jquery-confirm-probe/", record)
        page.evaluate("""() => {
            const container = document.createElement('section');
            container.id = 'confirm-probe';
            container.innerHTML = '<form data-confirm="First prompt" hx-post="/jquery-confirm-probe/" hx-target="#confirm-probe"><button type="submit">Confirm probe</button></form>';
            document.getElementById('main').prepend(container);
            htmx.process(container);
        }""")
        page.once("dialog", lambda dialog: dialog.dismiss())
        page.get_by_role("button", name="Confirm probe").click()
        page.wait_for_timeout(150)  # Prove a canceled request was not sent asynchronously.
        self.assertEqual(requests, [])
        page.evaluate(
            "document.querySelector('#confirm-probe form').setAttribute('data-confirm', 'Updated prompt')"
        )
        messages = []

        def accept(dialog):
            messages.append(dialog.message)
            dialog.accept()

        page.once("dialog", accept)
        page.get_by_role("button", name="Confirm probe").click()
        expect(page.locator("#confirm-probe")).to_have_text("Confirmed once")
        self.assertEqual(messages, ["Updated prompt"])
        self.assertEqual(len(requests), 1)
        self.assert_not_reloaded(page)

    def test_theme_updates_all_toggles_and_works_with_storage_blocked(self):
        page = self.open_as(self.admin, "/")
        self.context.add_init_script("""Object.defineProperty(window, 'localStorage', {
            get() { throw new DOMException('Blocked', 'SecurityError'); }
        });""")
        page.reload()
        page.evaluate("""() => {
            const button = document.createElement('button');
            button.setAttribute('data-theme-toggle', '');
            button.textContent = 'Extra theme switch';
            document.getElementById('main').prepend(button);
        }""")
        page.get_by_role("button", name="Extra theme switch").click()
        expect(page.locator("html")).to_have_attribute("data-theme", "dark")
        self.assertEqual(page.locator("[data-theme-toggle][aria-pressed='true']").count(), 2)
        page.locator("[data-theme-toggle]").first.click()
        expect(page.locator("html")).to_have_attribute("data-theme", "light")
        self.assertEqual(page.locator("[data-theme-toggle][aria-pressed='false']").count(), 2)

    def test_print_on_a_newly_inserted_control(self):
        page = self.open_as(self.admin, "/")
        page.evaluate("""() => {
            window.printCalls = 0;
            window.print = () => { window.printCalls += 1; };
            const button = document.createElement('button');
            button.setAttribute('data-print', '');
            button.textContent = 'Print probe';
            document.getElementById('main').prepend(button);
        }""")
        page.get_by_role("button", name="Print probe").click()
        self.assertEqual(page.evaluate("window.printCalls"), 1)

    def test_attendance_plain_form_still_works_without_javascript(self):
        page = self.open_as(
            self.teacher,
            f"/attendance/?classroom={self.c.pk}&date={self.today.isoformat()}",
            java_script_enabled=False,
        )
        page.locator(f"label.status-P:has(input[name='status_{self.e1.pk}'])").click()
        page.locator(f"label.status-P:has(input[name='status_{self.e2.pk}'])").click()
        page.get_by_role("button", name="Save daily attendance").click()
        expect(page.get_by_text("Daily attendance saved.")).to_be_visible()


@override_settings(GEMINI_API_KEY="browser-test-only")
class JQueryAssistantTests(BrowserTestCase):
    @override_settings(GEMINI_API_KEY="")
    def test_missing_key_keeps_setup_panel_visible_to_system_admin_on_phone(self):
        page = self.open_as(self.root, "/", viewport={"width": 390, "height": 844})
        launcher = page.locator("[data-assistant-open]")
        launcher.click()
        expect(page.get_by_role("heading", name="Connect your AI assistant")).to_be_visible()
        expect(page.locator("#assistant-panel textarea")).to_have_count(0)
        self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth - innerWidth"), 0)
        page.keyboard.press("Escape")
        expect(page.locator("#assistant-panel")).to_be_hidden()
        expect(launcher).to_be_focused()

    def test_enter_shift_enter_and_composition_after_panel_swap(self):
        with patch("apps.assistant.views.ask", return_value="A safe test answer") as ask:
            page = self.open_as(self.admin, "/")
            page.locator("[data-assistant-open]").click()
            box = page.locator(".assistant-composer textarea")
            expect(box).to_be_visible()
            box.fill("A question")
            box.press("Shift+Enter")
            expect(box).to_have_value("A question\n")
            page.evaluate("""() => document.querySelector('.assistant-composer textarea').dispatchEvent(
                new KeyboardEvent('keydown', {key: 'Enter', isComposing: true, bubbles: true, cancelable: true})
            )""")
            page.wait_for_timeout(100)
            ask.assert_not_called()
            box.press("Enter")
            expect(page.locator("[data-answer]")).to_have_text("A safe test answer")
            expect(box).to_have_value("")
            expect(box).to_be_focused()
            self.assertEqual(ask.call_count, 1)
            self.assert_not_reloaded(page)
            page.get_by_role("button", name="New conversation").click()
            expect(page.locator("[data-answer]")).to_have_count(0)
            box.fill("A second question")
            box.press("Enter")
            expect(page.locator("[data-answer]")).to_have_text("A safe test answer")
            expect(box).to_have_value("")
            self.assertEqual(ask.call_count, 2)  # No duplicate handlers after a replacement.

    def test_failed_answer_keeps_question_and_clipboard_denial_is_handled(self):
        with patch("apps.assistant.views.ask", side_effect=AssistantUnavailable):
            page = self.open_as(self.admin, reverse("assistant"))
            box = page.locator(".assistant-composer textarea")
            box.fill("Keep this question")
            box.press("Enter")
            expect(page.locator(".assistant-exchange.is-failed")).to_be_visible()
            expect(box).to_have_value("Keep this question")
        with patch("apps.assistant.views.ask", return_value="Literal <answer> & text"):
            box.press("Enter")
            expect(page.locator("[data-copy]")).to_have_count(1)
            page.evaluate("""() => {
                window.copyAttempts = 0;
                Object.defineProperty(navigator, 'clipboard', {configurable: true, value: {
                    writeText: () => { window.copyAttempts++; return Promise.reject(new Error('Denied')); }
                }});
            }""")
            page.locator("[data-copy]").click()
            page.wait_for_function("window.copyAttempts === 1")
            expect(page.locator("[data-copy]")).not_to_have_class(re.compile(r"\bis-copied\b"))
            page.evaluate(
                "navigator.clipboard.writeText = text => { window.copiedText = text; return Promise.resolve(); }"
            )
            page.locator("[data-copy]").click()
            page.wait_for_function(
                "document.querySelector('[data-copy]').classList.contains('is-copied')"
            )
            self.assertEqual(page.evaluate("window.copiedText"), "Literal <answer> & text")

    def test_panel_reopens_after_navigation_and_escape_restores_focus(self):
        page = self.open_as(self.admin, "/")
        page.keyboard.press("Control+/")
        expect(page.locator(".assistant-composer textarea")).to_be_visible()
        page.reload()
        expect(page.locator(".assistant-composer textarea")).to_be_visible()
        expect(page.locator("[data-assistant-open]")).to_have_attribute("aria-expanded", "true")
        page.keyboard.press("Escape")
        expect(page.locator("#assistant-panel")).to_be_hidden()
        expect(page.locator("[data-assistant-open]")).to_be_focused()
        page.reload()
        expect(page.locator("#assistant-panel")).to_be_hidden()


class JQueryCheckoutTests(BrowserTestCase):
    def test_sdk_callback_posts_ids_and_csrf_without_external_payment(self):
        # Use the actual checkout view/template and script with a local SDK stub.
        tuition = FeeHead.objects.create(branch=self.a, name="Tuition", code="tuition")
        plan = save_fee_plan(
            self.admin,
            FeePlan(branch=self.a, year=self.year, grade=self.grade9),
            {tuition: 100000},
        )
        invoices, _ = issue_invoices(
            self.accountant, plan, "Checkout test", self.today + timedelta(days=14)
        )
        invoice = next(invoice for invoice in invoices if invoice.student_id == self.e1.student_id)
        order = PaymentOrder.objects.create(
            invoice=invoice,
            created_by=self.parent,
            gateway="razorpay",
            gateway_order_id="order_browser",
            amount_paise=invoice.total_paise,
        )
        page = self.open_as(self.parent, "/")
        page.route(
            "https://checkout.razorpay.com/v1/checkout.js",
            lambda route: route.fulfill(
                content_type="application/javascript",
                body="window.Razorpay = function(options) { this.open = function() { window.checkoutOptions = options; }; };",
            ),
        )
        posted = []

        def callback(route):
            posted.append(parse_qs(route.request.post_data))
            route.fulfill(status=200, content_type="text/html", body="Payment callback received")

        page.route("**" + reverse("razorpay_callback", args=[order.pk]), callback)
        page.goto(self.live_server_url + reverse("checkout", args=[order.pk]))
        page.locator("[data-razorpay-open]").click()
        page.wait_for_function("window.checkoutOptions")
        self.assertEqual(posted, [])  # Opening or dismissing the provider does not post a payment.
        page.evaluate(
            "window.checkoutOptions.handler({razorpay_payment_id: 'pay_browser', razorpay_signature: 'signature_browser'})"
        )
        expect(page.locator("body")).to_have_text("Payment callback received")
        self.assertEqual(len(posted), 1)
        self.assertEqual(posted[0]["razorpay_payment_id"], ["pay_browser"])
        self.assertEqual(posted[0]["razorpay_signature"], ["signature_browser"])
        self.assertTrue(posted[0]["csrfmiddlewaretoken"][0])
