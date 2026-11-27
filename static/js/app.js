// jQuery enhancements. Deferred so the document is parsed, but installed before htmx starts.
// Delegated handlers also cover elements inserted by htmx, without rebinding on every swap.
(function ($) {
  "use strict";

  const $document = $(document);
  const $root = $(document.documentElement);
  const $sidebar = $("#sidebar");
  const $menuButton = $("#menu-toggle");

  if ($sidebar.length && $menuButton.length) {
    const mobileNavigation = window.matchMedia("(max-width: 860px)");
    const $backdrop = $("[data-nav-backdrop]");
    const $closeButton = $sidebar.find("[data-nav-close]");
    let backgroundState = [];
    const setMenuOpen = (open, restoreFocus = true) => {
      open = open && mobileNavigation.matches;
      const wasOpen = $sidebar.hasClass("open");
      $sidebar.toggleClass("open", open).prop("inert", mobileNavigation.matches && !open);
      $menuButton.attr("aria-expanded", String(open));
      $backdrop.prop("hidden", !open);
      $(document.body).toggleClass("nav-open", open);
      if (open) {
        $sidebar.attr({ role: "dialog", "aria-modal": "true", "aria-label": "Navigation" });
        if (!wasOpen) {
          backgroundState = $(".shell, .skip-link, .assistant-launcher, #assistant-panel").toArray()
            .map((element) => ({ element, inert: element.inert }));
          backgroundState.forEach(({ element }) => { element.inert = true; });
          $closeButton.trigger("focus");
        }
      } else {
        $sidebar.removeAttr("role aria-modal aria-label");
        backgroundState.forEach(({ element, inert }) => { element.inert = inert; });
        backgroundState = [];
        if (wasOpen && restoreFocus) $menuButton.trigger("focus");
      }
    };
    $menuButton.on("click.edunexa", () => setMenuOpen(!$sidebar.hasClass("open")));
    $closeButton.add($backdrop).on("click.edunexa", () => setMenuOpen(false));
    $document.on("keydown.edunexaMenu", (event) => {
      if (!$sidebar.hasClass("open")) return;
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopImmediatePropagation();
        setMenuOpen(false);
      } else if (event.key === "Tab") {
        const $focusable = $sidebar.find("a[href], button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex='0']")
          .filter(":visible");
        const first = $focusable[0];
        const last = $focusable[$focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          $(last).trigger("focus");
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          $(first).trigger("focus");
        }
      }
    });
    $(mobileNavigation).on("change.edunexaNav", () => {
      const focusWasInside = $.contains($sidebar[0], document.activeElement);
      setMenuOpen(false, false);
      if (mobileNavigation.matches && focusWasInside) $menuButton.trigger("focus");
    });
    setMenuOpen(false, false);
  }

  $document.on("keydown.edunexaSearch", (event) => {
    if ($sidebar.hasClass("open")) return;
    const $search = $("#global-search");
    if ($search.length && (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      $search.trigger("focus");
    }
  });

  // jQuery's .on() only listens during bubbling. Confirmation must run in capture before
  // htmx's form-level submit handler can send a request. Keep this small native bridge.
  document.addEventListener("submit", (event) => {
    const $form = $(event.target).closest("form[data-confirm]");
    if ($form.length && !window.confirm($form.attr("data-confirm"))) {
      event.preventDefault();
      event.stopImmediatePropagation();
    }
  }, true);

  $document.on("click.edunexaPrint", "[data-print]", () => window.print());

  const currentTheme = () => ($root.attr("data-theme") === "dark" ? "dark" : "light");
  const syncThemeButtons = () => {
    $("[data-theme-toggle]").attr("aria-pressed", String(currentTheme() === "dark"));
  };
  syncThemeButtons();
  $document.on("click.edunexaTheme", "[data-theme-toggle]", () => {
    const next = currentTheme() === "dark" ? "light" : "dark";
    $root.attr("data-theme", next);
    try {
      window.localStorage.setItem("edunexa-theme", next);
    } catch (error) {
      // Storage blocked: the theme still changes for this page view.
    }
    syncThemeButtons();
  });

  const assistantBox = () => $(".assistant-composer textarea").first();
  $document.on("keydown.edunexaAssistant", ".assistant-composer textarea", function (event) {
    // isComposing is a native KeyboardEvent field, not a normalized jQuery field.
    if (event.key === "Enter" && !event.shiftKey && !event.originalEvent?.isComposing) {
      event.preventDefault();
      // Native requestSubmit preserves validation and lets htmx receive a real submit event.
      $(this).prop("form").requestSubmit();
    }
  });

  $document.on("htmx:afterSettle.edunexa", (event) => {
    syncThemeButtons();
    const swapped = $(event.target).attr("id");
    if (swapped !== "conversation" && swapped !== "assistant-panel-body") return;
    const $box = assistantBox();
    const $latest = $("#conversation").children().last();
    if (swapped === "conversation" && $latest.length && !$latest.hasClass("is-failed")) {
      $box.val("");
    }
    $latest[0]?.scrollIntoView({ block: "nearest" });
    const usingPanel = $(document.activeElement).closest("#assistant-panel").length;
    if (swapped === "conversation" || usingPanel) $box.trigger("focus");
  });

  $document.on("click.edunexaCopy", "[data-copy]", function () {
    if (!navigator.clipboard) return;
    const $button = $(this);
    const $answer = $button.closest(".assistant-answer").find("[data-answer]");
    if (!$answer.length) return;
    // Clipboard access can be denied even on HTTPS; keep the answer available for manual copy.
    Promise.resolve().then(() => navigator.clipboard.writeText($answer.text())).then(() => {
      $button.addClass("is-copied");
      window.setTimeout(() => $button.removeClass("is-copied"), 1500);
    }).catch(() => {});
  });

  const $panel = $("#assistant-panel");
  const $launcher = $("[data-assistant-open]");
  if ($panel.length && $launcher.length) {
    const $closeButton = $panel.find("[data-assistant-close]");
    const setPanelOpen = (open) => {
      $panel.prop("hidden", !open);
      $(document.body).toggleClass("assistant-open", open);
      $launcher.attr("aria-expanded", String(open));
      try {
        window.sessionStorage.setItem("edunexa-assistant", open ? "open" : "");
      } catch (error) {
        // Storage blocked: the panel just won't reopen on the next page.
      }
      // htmx listens with native events; jQuery .trigger() would not reach that listener.
      if (open) document.body.dispatchEvent(new Event("assistant-open"));
    };
    const toggle = () => {
      const open = $panel.prop("hidden");
      setPanelOpen(open);
      if (open) {
        const $box = assistantBox();
        ($box.length ? $box : $closeButton).trigger("focus");
      } else {
        $launcher.trigger("focus");
      }
    };
    $launcher.on("click.edunexa", (event) => {
      event.preventDefault();
      toggle();
    });
    $closeButton.on("click.edunexa", toggle);
    $document.on("keydown.edunexaPanel", (event) => {
      if ($sidebar.hasClass("open")) return;
      if ((event.ctrlKey || event.metaKey) && event.key === "/") {
        event.preventDefault();
        toggle();
      } else if (event.key === "Escape" && !$panel.prop("hidden")) {
        toggle();
      }
    });
    let reopen = false;
    try {
      reopen = window.sessionStorage.getItem("edunexa-assistant") === "open";
    } catch (error) {
      // Storage blocked: start closed.
    }
    if (reopen) $document.one("htmx:load.edunexa", () => setPanelOpen(true));
  }
})(jQuery);
