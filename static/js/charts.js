// Dashboard charts. The numbers come from a <script type="application/json"> block written by
// the server (json_script), so no inline script runs and the CSP stays "script-src 'self'".
// Colours come from the design tokens, so the charts are drawn again when the theme changes.
(function ($) {
  "use strict";

  var $source = $("#dashboard-charts");
  if (!$source.length || typeof Chart === "undefined") {
    return;
  }
  var data = JSON.parse($source.text());
  var charts = [];
  var motionPreference = window.matchMedia("(prefers-reduced-motion: reduce)");

  function draw() {
    charts.forEach(function (chart) { chart.destroy(); });
    charts = [];
    var $root = $(document.documentElement);
    function token(name) {
      return $root.css(name).trim();
    }

    Chart.defaults.font.family = token("--font-sans");
    Chart.defaults.color = token("--color-text-muted");
    var grid = token("--color-border");
    var percent = {
      min: 0,
      max: 100,
      grid: { color: grid },
      ticks: { callback: function (value) { return value + "%"; } }
    };

    var trend = $("#attendance-trend")[0];
    if (trend && data.trend && data.trend.length) {
      charts.push(new Chart(trend, {
        type: "line",
        data: {
          labels: data.trend.map(function (point) { return point.label; }),
          datasets: [{
            label: "Attendance",
            data: data.trend.map(function (point) { return point.rate; }),
            borderColor: token("--color-primary"),
            backgroundColor: token("--color-primary-soft"),
            fill: true,
            tension: 0.3,
            pointRadius: 2,
            spanGaps: true
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          animation: motionPreference.matches ? false : { duration: 220, easing: "easeOutQuad" },
          scales: { y: percent, x: { grid: { display: false } } },
          plugins: { legend: { display: false } }
        }
      }));
    }

    var branches = $("#branch-comparison")[0];
    if (branches && data.branches && data.branches.length) {
      charts.push(new Chart(branches, {
        type: "bar",
        data: {
          labels: data.branches.map(function (row) { return row.branch; }),
          datasets: [{
            label: "Attendance, last 30 days",
            data: data.branches.map(function (row) { return row.rate; }),
            backgroundColor: token("--color-accent"),
            borderRadius: 6,
            maxBarThickness: 48
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          animation: motionPreference.matches ? false : { duration: 220, easing: "easeOutQuad" },
          scales: { y: percent, x: { grid: { display: false } } },
          plugins: { legend: { display: false } }
        }
      }));
    }
  }

  draw();
  // Canvas animation must respect the same preference as the CSS, including live changes.
  $(motionPreference).on("change.edunexaCharts", draw);
  // The theme toggle sets data-theme on <html>.
  new MutationObserver(draw).observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["data-theme"]
  });
})(jQuery);
