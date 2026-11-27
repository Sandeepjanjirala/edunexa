// Apply a saved light/dark choice before the page paints, so there is no flash of the wrong theme.
// Loaded in <head> without `defer` on purpose. Without a saved choice, the page is light.
(function ($) {
  "use strict";
  const $root = $(document.documentElement);
  // Scripts run: forms that htmx saves on change can hide their fallback Save buttons.
  $root.addClass("js");
  try {
    var saved = window.localStorage.getItem("edunexa-theme");
    if (saved === "light" || saved === "dark") {
      $root.attr("data-theme", saved);
    }
  } catch (error) {
    // Storage can be blocked (private windows); the page stays light.
  }
})(jQuery);
