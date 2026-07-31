# itrix-backend - Instant Client-Page Reveal From Conversation

Makes the personalised client page appear as soon as the visitor finishes the
review and gives an email — instead of the conversation stalling at "Reflection"
with the AI promising that "the Assessment Team will be in touch."

## The two faults this fixes

Your screenshots showed the conversation reaching DIAGNOSED ("Reflection"), the
visitor giving their name, email, and even their company — and still no page, with
the AI ending on "we will be in touch shortly." Two stacked faults caused this:

### Fault 1 — the trigger read one message and required company + email together

The reveal read only the **current turn** and demanded **both** a company and an
email in that single message. But real visitors split their details across turns:

- one turn: *"My name is Fidel Omondi and my email is engomondiii@gmail.com"*
  (email, no company)
- a later turn: *"Our company is GPSLAB"* (company, no email)

Neither message had both, so the gate failed every time and the reveal never fired.

**Fix:** contact is now **accumulated across every visitor turn**, so details given
in different messages combine. And the trigger is **email-anchored** — a valid email
alone reveals the page; a company is captured when present but never blocks it.

### Fault 2 — the AI didn't know the page exists

The "Assessment Team will be in touch" wording was never a template — the AI
generated it, because nothing told it a personalised page can be produced instantly.
So it behaved like a generic intake concierge and promised a human follow-up, which
contradicted the whole point.

**Fix:** when the page is revealed, the concierge is given a direct instruction to
hand the page over in its own words and **not** promise the team will be in touch or
ask to "close the intake." The `/c/<token>` link is also appended to the reply as a
transport-independent guarantee, and the reveal is broadcast to the thread's socket
group so the surface can navigate live.

## How the fix flows

1. Visitor describes the problem -> AI reviews and asks follow-ups (memory).
2. Enough covered -> loop closes -> DIAGNOSED.
3. Visitor gives an email (with or without a name/company, in one message or
   several) -> the bridge accumulates contact, creates a `conversation` Lead,
   advances to CLIENT_PAGE, and mints the client-page token.
4. The AI is told the page is ready and hands over the `/c/<token>` link in its own
   voice; the link is also appended to the reply. The state chip becomes
   "Client page."

## Files in this change set

New (2):
- `apps/conversations/services/reveal_bridge.py` - the corrected bridge:
  accumulate-across-turns contact extraction, email-anchored reveal, Lead creation,
  thread claim, token mint, thread-group broadcast.
- `tests/test_conversations/test_client_page_reveal.py` - 11 tests, including the
  exact "contact split across turns" production failure.

Modified (5):
- `apps/conversations/services/qualification.py` - runs the reveal check on every
  turn (after the band logic), and stashes the outcome for the reply.
- `apps/conversations/services/conversation_context.py` - passes the reveal fact
  into the agent context so the AI can present the page.
- `apps/agents/services/concierge.py` - injects the "hand over the page, do not
  promise human follow-up" directive when a reveal fired.
- `apps/conversations/views_thread.py` - HTTP path appends the /c/<token> link and
  suppresses the next-question suggestion once revealed.
- `apps/realtime/consumers/review.py` - WebSocket path does the same.

**No new migration** - reuses the existing Lead, ReviewSession, and capability-token
models.

## How to install

Unzip inside the root of your `itrix-backend` repo (the folder with `manage.py`):

```powershell
powershell -ExecutionPolicy Bypass -File .\itrix-backend-instant-client-page-v1\INSTALL.ps1
python manage.py check
git add -A
git commit -m "Instant client-page reveal from conversation"
git push
```

## Prerequisite

Builds on the conversation-memory package (adds `Thread.current_state` and the state
loop), which is already in your repo. Requires `ENABLE_ADAPTIVE_QUESTIONS=True`
(already set in your Railway env) so the loop reaches DIAGNOSED.

## Verification performed

- **The exact production failure reproduced and fixed:** email in one turn, company
  in another -> the page now reveals (previously it never did). Verified both
  orderings (email-first and company-first).
- **Email-alone reveals** the page; no company required.
- End-to-end: thread reaches DIAGNOSED -> the email turn creates a `conversation`
  Lead, advances to CLIENT_PAGE, and produces a `/c/<token>` link.
- The minted token **verifies** as a valid `client_page` token bound to the lead.
- The **AI directive** is present in the prompt when a reveal fires (with the link
  and the "do not say the team will be in touch" prohibition) and absent otherwise.
- Name extraction cleaned up ("Fidel Omondi", not "Fidel Omondi and").
- Gating: no reveal before DIAGNOSED, none without an email, idempotent (no second
  lead on a later turn).
- Full backend suite: **977 passed, 0 failed** (966 baseline + 11 new),
  re-confirmed after CRLF normalisation. Zero regressions.
- `python manage.py check` clean; `makemigrations --check` -> "No changes detected".
- All shipped files verified pure CRLF, matching the repo.

## Optional follow-up (not in this package)

For the most seamless "instant" feel, the frontend can **auto-navigate** to
`/c/<token>` on the `journey.reveal` socket event (the `RevealGate` + socket
infrastructure already exists on the web app), so the visitor is *taken* to their
page rather than clicking a link. This package guarantees the link + live reveal
event; the auto-navigation is a small frontend change if you want it.
