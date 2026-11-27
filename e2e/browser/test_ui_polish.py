"""ERP presentation and navigation regressions in the real browser, with no external services."""

import os
from datetime import timedelta
from pathlib import Path
from time import monotonic

from django.conf import settings
from django.test import override_settings
from django.urls import reverse

from apps.attendance.services import save_register
from apps.fees.models import FeeHead, FeePlan
from apps.fees.services import issue_invoices, save_fee_plan
from e2e.browser.test_browser import BrowserTestCase, expect


@override_settings(GEMINI_API_KEY="browser-test-only")
class WorkspacePresentationTests(BrowserTestCase):
    def capture(self, page, name):
        """Opt-in artifacts for visual review; only test fixture data is captured."""
        if os.environ.get("EDUNEXA_UI_SHOTS") == "1":
            directory = Path(settings.BASE_DIR, ".deploy", "ui-previews")
            directory.mkdir(parents=True, exist_ok=True)
            page.screenshot(
                path=str(directory / f"{name}.png"),
                full_page=name != "mobile-navigation",
                animations="disabled",
            )

    def wait_for_chart(self, page, expression):
        # Poll through DevTools: Playwright's in-page wait_for_function re-evaluates strings
        # on animation frames, which the real CSP forbids when the first check isn't ready.
        deadline = monotonic() + 5
        while monotonic() < deadline:
            if page.evaluate(expression):
                return
            page.wait_for_timeout(50)
        self.fail(f"Chart state did not settle: {expression}")

    def seed_attendance(self):
        save_register(self.teacher, self.c, self.today, {self.e1.pk: "P", self.e2.pk: "A"}, 0)

    def test_mobile_navigation_keyboard_backdrop_and_focus_restoration(self):
        page = self.open_as(self.admin, "/", viewport={"width": 390, "height": 844})
        sidebar = page.locator("#sidebar")
        menu = page.locator("#menu-toggle")
        expect(sidebar).to_have_js_property("inert", True)
        menu.click()
        expect(sidebar).to_have_attribute("role", "dialog")
        expect(sidebar).to_have_attribute("aria-modal", "true")
        expect(page.locator(".shell")).to_have_js_property("inert", True)
        expect(page.locator("[data-nav-close]")).to_be_focused()
        self.capture(page, "mobile-navigation")
        # Tab and Shift+Tab wrap inside the drawer, including the brand link.
        first = sidebar.locator("a.brand")
        last = sidebar.locator(".nav a").last
        last.focus()
        page.keyboard.press("Tab")
        expect(first).to_be_focused()
        page.keyboard.press("Shift+Tab")
        expect(last).to_be_focused()
        page.keyboard.press("Control+k")
        expect(last).to_be_focused()
        page.keyboard.press("Control+/")
        expect(page.locator("#assistant-panel")).to_be_hidden()
        page.keyboard.press("Escape")
        expect(menu).to_be_focused()
        expect(menu).to_have_attribute("aria-expanded", "false")
        expect(sidebar).to_have_js_property("inert", True)
        expect(page.locator(".shell")).to_have_js_property("inert", False)
        expect(page.locator("[data-nav-backdrop]")).to_be_hidden()
        menu.click()
        page.locator("[data-nav-backdrop]").click(position={"x": 370, "y": 300})
        expect(menu).to_be_focused()
        expect(menu).to_have_attribute("aria-expanded", "false")
        menu.click()
        page.locator("[data-nav-close]").click()
        expect(menu).to_be_focused()

    def test_navigation_resize_restores_background_and_sidebar_access(self):
        page = self.open_as(self.admin, "/", viewport={"width": 390, "height": 844})
        page.locator(".skip-link").evaluate("element => { element.inert = true; }")
        page.locator("#menu-toggle").click()
        page.set_viewport_size({"width": 1366, "height": 900})
        expect(page.locator("#sidebar")).to_have_class("sidebar")
        expect(page.locator("#sidebar")).to_have_js_property("inert", False)
        expect(page.locator(".shell")).to_have_js_property("inert", False)
        # A pre-existing inert state belongs to its owner and must survive closing the drawer.
        expect(page.locator(".skip-link")).to_have_js_property("inert", True)
        self.assertIsNone(page.locator("#sidebar").get_attribute("aria-modal"))
        expect(page.locator("[data-nav-backdrop]")).to_be_hidden()
        self.assertEqual(
            page.locator("body").evaluate("element => getComputedStyle(element).overflow"),
            "visible",
        )
        page.locator("#sidebar .nav a").first.focus()
        page.set_viewport_size({"width": 390, "height": 844})
        expect(page.locator("#menu-toggle")).to_be_focused()
        expect(page.locator("#sidebar")).to_have_js_property("inert", True)
        page.locator("#menu-toggle").click()
        page.locator("#sidebar").get_by_role("link", name="Students", exact=True).click()
        expect(page.get_by_role("heading", name="Students", exact=True)).to_be_visible()
        expect(page.locator(".shell")).to_have_js_property("inert", False)

    def test_reduced_motion_disables_css_and_canvas_animation_and_tracks_changes(self):
        self.seed_attendance()
        page = self.open_as(self.root, "/", reduced_motion="reduce")
        animations = """() => ['attendance-trend', 'branch-comparison'].map(
            id => Chart.getChart(document.getElementById(id)).options.animation
        )"""
        self.wait_for_chart(page, "Boolean(window.Chart && Chart.getChart('branch-comparison'))")
        self.assertEqual(page.evaluate(animations), [False, False])
        self.assertEqual(
            page.locator(".page-header").evaluate("e => getComputedStyle(e).animationName"), "none"
        )
        page.set_viewport_size({"width": 390, "height": 844})
        page.locator("#menu-toggle").click()
        self.assertEqual(
            page.locator("#sidebar").evaluate("e => getComputedStyle(e).transitionDuration"), "0s"
        )
        expect(page.locator("[data-nav-close]")).to_be_focused()
        page.keyboard.press("Escape")
        page.emulate_media(reduced_motion="no-preference")
        self.wait_for_chart(
            page, "Chart.getChart('attendance-trend').options.animation.duration === 220"
        )
        page.emulate_media(reduced_motion="reduce")
        self.wait_for_chart(page, "Chart.getChart('attendance-trend').options.animation === false")
        self.assertEqual(page.evaluate(animations), [False, False])
        expect(page.locator(".page-header")).to_be_visible()
        self.assertEqual(
            page.locator(".page-header").evaluate("e => getComputedStyle(e).opacity"), "1"
        )

    def test_workspaces_fit_narrow_screens_in_both_themes(self):
        self.seed_attendance()
        tuition = FeeHead.objects.create(branch=self.a, name="Tuition", code="tuition")
        plan = save_fee_plan(
            self.admin,
            FeePlan(branch=self.a, year=self.year, grade=self.grade9),
            {tuition: 12500000},
        )
        issue_invoices(self.accountant, plan, "Term tuition", self.today + timedelta(days=14))
        page = self.open_as(self.root, "/", reduced_motion="reduce")
        paths = {
            "dashboard": "/",
            "students": reverse("students"),
            "student-form": reverse("student_create"),
            "attendance": f"/attendance/?classroom={self.c.pk}&date={self.today.isoformat()}",
            "timetable": f"/timetable/{self.c.pk}/",
        }
        # 683 px also represents the available CSS width at 200% zoom on a 1366 px display.
        for width in (320, 390, 683, 1366):
            page.set_viewport_size({"width": width, "height": 900})
            for theme in ("light", "dark"):
                for name, path in paths.items():
                    with self.subTest(width=width, theme=theme, page=name):
                        page.goto(self.live_server_url + path)
                        if page.locator("html").get_attribute("data-theme") != theme:
                            page.locator("[data-theme-toggle]").click()
                        expect(page.locator("h1")).to_be_visible()
                        self.assertLessEqual(
                            page.evaluate(
                                "document.documentElement.scrollWidth - window.innerWidth"
                            ),
                            0,
                            "the whole page scrolls sideways; tables should scroll inside their container",
                        )
                        if width == 1366 and name in ("dashboard", "students", "student-form"):
                            self.capture(page, f"{name}-{theme}")
                        elif width == 390 and name in ("dashboard", "attendance"):
                            self.capture(page, f"{name}-mobile-{theme}")

    def test_navigation_links_work_on_mobile_without_javascript(self):
        page = self.open_as(
            self.admin, "/", java_script_enabled=False, viewport={"width": 390, "height": 844}
        )
        expect(page.locator("#sidebar")).to_be_visible()
        expect(page.locator("[data-nav-close]")).to_be_hidden()
        page.locator("#sidebar").get_by_role("link", name="Students", exact=True).click()
        expect(page.get_by_role("heading", name="Students", exact=True)).to_be_visible()

    def test_printing_uses_light_surfaces_and_hides_navigation(self):
        page = self.open_as(self.admin, "/")
        page.locator("[data-theme-toggle]").click()
        page.emulate_media(media="print")
        expect(page.locator("#sidebar")).to_be_hidden()
        expect(page.locator(".topbar")).to_be_hidden()
        expect(page.locator(".page-header")).to_be_visible()
        self.assertEqual(
            page.locator("body").evaluate("e => getComputedStyle(e).backgroundColor"),
            "rgb(255, 255, 255)",
        )
        self.assertEqual(
            page.locator(".page-header").evaluate("e => getComputedStyle(e).animationName"), "none"
        )
