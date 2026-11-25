// Small progressive enhancements. Every page also works with JavaScript turned off.

// Mobile navigation drawer.
const sidebar = document.getElementById("sidebar");
const menuButton = document.getElementById("menu-toggle");
if (sidebar && menuButton) {
  const setOpen = (open) => {
    sidebar.classList.toggle("open", open);
    menuButton.setAttribute("aria-expanded", String(open));
  };
  menuButton.addEventListener("click", () => setOpen(!sidebar.classList.contains("open")));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") setOpen(false);
  });
}

// Ctrl+K (Cmd+K on a Mac) jumps to the global search in the top bar.
const globalSearch = document.getElementById("global-search");
if (globalSearch) {
  document.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      globalSearch.focus();
      globalSearch.select();
    }
  });
}

// Ask before actions with lasting effects, such as publishing results or deactivating accounts.
// Listened for on the document, so forms that htmx swaps in later are covered too.
document.addEventListener(
  "submit",
  (event) => {
    const form = event.target.closest("form[data-confirm]");
    if (form && !window.confirm(form.dataset.confirm)) event.preventDefault();
  },
  true,
);

// Print / Save as PDF for student reports.
document.addEventListener("click", (event) => {
  if (event.target.closest("[data-print]")) window.print();
});

// Light/dark toggle. The choice is remembered in this browser only.
const root = document.documentElement;
const prefersDark = window.matchMedia("(prefers-color-scheme: dark)");
const currentTheme = () => root.dataset.theme || (prefersDark.matches ? "dark" : "light");
document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
  const sync = () => button.setAttribute("aria-pressed", String(currentTheme() === "dark"));
  sync();
  prefersDark.addEventListener("change", sync);
  button.addEventListener("click", () => {
    const next = currentTheme() === "dark" ? "light" : "dark";
    root.dataset.theme = next;
    try {
      window.localStorage.setItem("edunexa-theme", next);
    } catch (error) {
      // Storage blocked: the theme still changes for this page view.
    }
    sync();
  });
});

// The AI assistant: Enter sends the question (Shift+Enter starts a new line). When an answer
// arrives, the box is cleared for the next question, unless the assistant couldn't answer, and
// the answer is scrolled into view. Listened for on the document: the panel's conversation
// arrives later, by htmx.
const assistantBox = () => document.querySelector(".assistant-composer textarea");
document.addEventListener("keydown", (event) => {
  const box = event.target.closest?.(".assistant-composer textarea");
  if (box && event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    box.form.requestSubmit();
  }
});
// htmx fires these on the element it swapped into: the conversation list, or the whole panel
// when it loads or starts a new conversation.
document.addEventListener("htmx:afterSettle", (event) => {
  const swapped = event.target.id;
  if (swapped !== "conversation" && swapped !== "assistant-panel-body") return;
  const box = assistantBox();
  const latest = document.getElementById("conversation")?.lastElementChild;
  if (swapped === "conversation" && box && latest && !latest.classList.contains("is-failed")) {
    box.value = "";
  }
  latest?.scrollIntoView({ block: "nearest" });
  // A panel that reopened by itself on a new page leaves the focus where the page put it.
  const usingPanel = document.activeElement?.closest("#assistant-panel");
  if (swapped === "conversation" || usingPanel) box?.focus();
});

// Copy an answer.
document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-copy]");
  if (!button || !navigator.clipboard) return;
  const answer = button.closest(".assistant-answer").querySelector("[data-answer]");
  navigator.clipboard.writeText(answer.textContent).then(() => {
    button.classList.add("is-copied");
    setTimeout(() => button.classList.remove("is-copied"), 1500);
  });
});

// The "Ask AI" button opens the assistant in a panel on the right of any page (Ctrl+/ or Cmd+/
// too); Esc or the close button shuts it. An open panel stays open on the next page.
const assistantPanel = document.getElementById("assistant-panel");
const assistantLauncher = document.querySelector("[data-assistant-open]");
if (assistantPanel && assistantLauncher) {
  const remember = (open) => {
    try {
      window.sessionStorage.setItem("edunexa-assistant", open ? "open" : "");
    } catch (error) {
      // Storage blocked: the panel just won't reopen on the next page.
    }
  };
  const setPanelOpen = (open) => {
    assistantPanel.hidden = !open;
    document.body.classList.toggle("assistant-open", open);
    assistantLauncher.setAttribute("aria-expanded", String(open));
    remember(open);
    if (open) document.body.dispatchEvent(new Event("assistant-open")); // htmx loads it once
  };
  const closeButton = assistantPanel.querySelector("[data-assistant-close]");
  const toggle = () => {
    const open = assistantPanel.hidden;
    setPanelOpen(open);
    // Until the conversation has loaded, the close button holds the focus; the box takes it then.
    if (open) (assistantBox() ?? closeButton).focus();
    else assistantLauncher.focus();
  };
  assistantLauncher.addEventListener("click", (event) => {
    event.preventDefault();
    toggle();
  });
  closeButton.addEventListener("click", toggle);
  document.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "/") {
      event.preventDefault();
      toggle();
    } else if (event.key === "Escape" && !assistantPanel.hidden) {
      toggle();
    }
  });
  let reopen = false;
  try {
    reopen = window.sessionStorage.getItem("edunexa-assistant") === "open";
  } catch (error) {
    // Storage blocked: start closed.
  }
  // htmx is deferred too, but loads after this file: wait for it before asking it to load.
  if (reopen) document.addEventListener("htmx:load", () => setPanelOpen(true), { once: true });
}
