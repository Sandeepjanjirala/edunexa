# 15. An AI assistant that reads through the user's own scope

**Status:** Accepted, November 2026

## Context

People ask EduNexa the same questions every day: who is below 75% attendance, how did my child do, what is owed, what are my lessons tomorrow. The answers are already on several pages. An assistant that answers in plain language saves the clicking, but it must never become a way around EduNexa's access rules: a parent must not learn about another child by asking cleverly, and the model must not change anything.

## Decision

A new app, `apps.assistant`, in the top layer next to `reports`. Its page (`/assistant/`, "AI assistant" in the sidebar) is open to every role once `GEMINI_API_KEY` is set. Without a key, ordinary users cannot access it (404), while active system administrators can open a setup message from the sidebar or right-side panel. Missing configuration no longer silently hides the feature from the person who can restore it.

- **An "Ask AI" button on every page** opens the same conversation in a panel on the right (Ctrl+/ too; Esc closes it). htmx loads the panel's conversation when it is first opened, so pages cost nothing until then, and an open panel stays open on the next page. The panel sends the title of the page underneath with each question, so "how do I use this page?" has an answer. Without JavaScript the button is a link to the assistant page.

- **A LangGraph agent on Google Gemini** (`agent.py`). The graph is a loop: the model reads the question and either answers or asks for tools; their results go back to it. `ASSISTANT_MODEL` picks the model (`gemini-3.5-flash-lite` by default).
- **The tools are the access control** (`tools.py`). Each tool is built per question as a closure over the signed-in user and reads only through that user's selectors (`students(user)`, `exams(user)`, `invoices(user)` ...), the same ones the pages use. The model can't name another user, and an out-of-scope record looks exactly like one that doesn't exist. A role is offered only the tools it has use for: an accountant gets fees and announcements, a teacher no fees.
- **Read-only.** No tool writes. Asked to mark attendance or approve leave, the assistant names the page to use.
- **Tools run in the request's thread.** LangGraph's prebuilt `ToolNode` runs tool calls on a thread pool; Django's database connection belongs to the request's thread, and nothing would close a pool thread's connection. The graph's tools node calls them one after another instead.
- **The conversation lives in the session**: the last 20 exchanges are shown and the last 6 go with each new question, so follow-ups work. "New conversation" clears it. No model of its own stores it: it sits in Django's session (the `django_session` table) and goes when the session ends, after 8 hours at most.
- **Each person may ask `ASSISTANT_HOURLY_LIMIT` questions an hour** (30 by default), counted with the sign-in throttle's table: every question is a paid call to the model.
- **The page follows the rest of the front end**: a plain form that works without JavaScript, htmx to add each answer in place, no inline scripts, so the Content-Security-Policy is unchanged. Answers are printed as escaped plain text.

## Consequences

- A question, and the records the tools return to answer it, are sent to Google. The page says so. A school that may not send pupils' data to Google leaves `GEMINI_API_KEY` empty; the admin setup state sends no requests. `python manage.py check_assistant` explicitly tests the configured Gemini connection with one synthetic prompt and no school records. Provider errors are sanitized before logging or displaying them. The integration explicitly selects the Gemini Developer API rather than inferring Vertex AI from unrelated environment settings.
- Answers can be wrong; the page says to check anything important on its own page. The instructions tell the model to answer only from tool results and to treat text inside records (announcements, leave reasons) as data, not instructions. Because the tools are read-only and scoped, a misled model can only show the user what they could already see.
- Gemini's free tier allows only a few requests a minute per key, and each question takes two or three model calls. When the limit is reached the user is told the assistant is busy. A school using the assistant in earnest needs a paid key.
- Tests never call Gemini: they run the real graph and tools against a scripted fake model.
