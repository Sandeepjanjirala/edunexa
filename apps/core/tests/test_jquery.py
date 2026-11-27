"""Pinned jQuery assets and dependency ordering on both public and signed-in pages."""

import base64
import hashlib
from pathlib import Path

from django.conf import settings
from django.urls import reverse

from apps.core.testing import SchoolTestCase


class JQueryTests(SchoolTestCase):
    def test_vendor_assets_match_documented_hashes(self):
        vendor = Path(settings.BASE_DIR, "static", "vendor")
        documentation = (vendor / "README.md").read_text(encoding="utf-8")
        for filename in ("jquery.min.js", "jquery.min.map", "LICENSE.txt"):
            with self.subTest(filename=filename):
                digest = hashlib.sha256((vendor / "jquery" / filename).read_bytes()).digest()
                self.assertIn(base64.b64encode(digest).decode(), documentation)

    def test_dependency_order_and_csp_for_public_and_authenticated_pages(self):
        for logged_in in (False, True):
            with self.subTest(logged_in=logged_in):
                if logged_in:
                    self.client.force_login(self.admin)
                response = self.client.get(reverse("dashboard" if logged_in else "login"))
                self.assertEqual(response.status_code, 200)
                html = response.content.decode()
                self.assertEqual(html.count("vendor/jquery/jquery.min.js"), 1)
                jquery = html.index("vendor/jquery/jquery.min.js")
                theme = html.index("js/theme.js")
                app = html.index("js/app.js")
                self.assertLess(jquery, theme)
                self.assertLess(theme, app)
                self.assertIn('<script src="/static/vendor/jquery/jquery.min.js">', html)
                self.assertIn("script-src 'self';", response["Content-Security-Policy"])
                self.assertNotIn("unsafe-inline", response["Content-Security-Policy"])
                self.assertNotIn("unsafe-eval", response["Content-Security-Policy"])
                if logged_in:
                    self.assertLess(app, html.index("vendor/htmx/htmx.min.js"))
