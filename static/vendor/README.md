# Vendored front-end libraries

Served from our own static files (no CDN), so the Content-Security-Policy stays `script-src 'self'`.
Each file is the package's own published file, checked against the hash jsDelivr publishes for it
(`https://data.jsdelivr.com/v1/packages/npm/<package>@<version>?structure=flat`).

| Library | Version | File | SHA-256 (base64) | Licence |
|---|---|---|---|---|
| [jQuery](https://jquery.com/) | 4.1.0 | `jquery/jquery.min.js` (npm `dist/jquery.min.js`) | `hjRvPkFLO1JGZFMXGrzdpG6TlsHDyjp4PQeqLWRcMzk=` | MIT, `jquery/LICENSE.txt` |
| jQuery source map | 4.1.0 | `jquery/jquery.min.map` (npm `dist/jquery.min.map`) | `+B6DTeF7Dgc6qvcn1tBVnCi6FdXZ+e85Dvkwn97HHKY=` | MIT |
| jQuery license | 4.1.0 | `jquery/LICENSE.txt` | `1Nuevm8p9RaOrEWtcT8FViOsXQ3NW6ktoj1lCuASAg0=` | MIT |
| [Chart.js](https://www.chartjs.org/) | 4.4.7 | `chartjs/chart.umd.js` (npm `dist/chart.umd.js`) | `KBLLiCX9xXRp6y97sFXpQpJE5ZmSBRHuR36ChJm2Mss=` | MIT, `chartjs/LICENSE.md` |
| Chart.js source map | 4.4.7 | `chartjs/chart.umd.js.map` (npm `dist/chart.umd.js.map`) | `Krbm0H/MWcRw8rXE35fKKmuKigz0GNBWTpykrG/4vP0=` | MIT |
| [htmx](https://htmx.org/) | 2.0.4 | `htmx/htmx.min.js` (npm `htmx.org`, `dist/htmx.min.js`; no source map comment) | `4gndpcgjVHnzFm3vx3UOHbzVpcGAi3eS/C5nM3aPtEc=` | 0BSD, `htmx/LICENSE` (`09JFb3ZBTyRWEEZg69Za/xwEzXlmuUK9q9Y/PNsxajg=`) |

htmx is configured in `templates/base.html` (`htmx-config` meta tag) with `allowEval: false`, `allowScriptTags: false` and `includeIndicatorStyles: false`, and EduNexa never uses `hx-on` or `js:` expressions, so the CSP needs neither `unsafe-eval` nor inline scripts.

jQuery is pinned and served locally on every HTML page using `base.html`, including sign-in.
It loads synchronously before `theme.js` so saved themes apply before first paint; the other
application scripts remain deferred. This adds a roughly 79 KB uncompressed asset (cached by
the browser and compressed by production static storage). There is no runtime CDN request.
The official [4.1.0 release](https://blog.jquery.com/2026/11/17/jquery-4-1-0-and-3-8-0-released-passing-the-torch/)
was verified against jsDelivr's package metadata when vendored. No jQuery Migrate plugin is
needed: this code uses current `.on()`, `.attr()`, `.prop()`, `.val()` and `.text()` APIs.

Keep each library's source map: production's static storage follows the `sourceMappingURL` comment at the end of the script, and `collectstatic` fails if the map is missing (`apps/core/tests/test_static_build.py` checks this).

To upgrade: download the new version's file from `https://cdn.jsdelivr.net/npm/<package>@<version>/<path>`,
compare its hash with the published one, then update this table.
