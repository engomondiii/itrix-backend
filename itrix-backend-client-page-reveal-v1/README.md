# itrix-backend - Conversation to Client-Page Reveal (states 3 -> 4)

Carries the conversational surface past DIAGNOSED to the personalised client page
the visitor is meant to receive.

## The problem this fixes

The earlier conversation-memory fix took anonymous visitors through the
qualification band: ARRIVED (1) -> IN_REVIEW (2) -> DIAGNOSED (3). But it stopped
at DIAGNOSED. The custom "pitch room" is **State 4 (CLIENT_PAGE)**, reached by the
`reveal_client_page` transition, which mints the `/c/<token>` capability token.

That transition — and the Lead it needs — only ever existed in the **old
structured-form path** (`review.qualification_processor`), which scores Q1-Q9
answers and creates a Lead. The conversation produces neither, and every transition
past DIAGNOSED requires a Lead. So the conversation completed qualification,
collected the visitor's company and email in prose, and then just sat at DIAGNOSED
("we'll prepare a briefing") — the page was never generated.

## What changed

A new bridge wires the conversation to the **existing** reveal machinery — it does
not duplicate it. When a thread has (a) reached DIAGNOSED and (b) captured a company
+ a valid email, the bridge:

1. creates a real Lead from the thread (`lead_source=conversation`, honest
   exploratory defaults — no fabricated Q1-Q9 score),
2. attaches the captured contact,
3. claims the anonymous thread onto that Lead so the conversation continues as the
   same thread (turns/artifacts preserved),
4. fires the existing `reveal_client_page` transition (3 -> 4), minting the
   client-page token exactly as the form path does,
5. broadcasts the reveal to the **thread's** socket group (the anonymous visitor is
   subscribed there, not to a lead group) for live navigation, AND appends the
   `/c/<token>` link to the reply so it works even without realtime.

### Design choices

- **Trigger: DIAGNOSED + contact.** The page is the delivered value, so it is only
  revealed after the review has actually happened and the visitor has shown intent
  by giving contact details — matching the form path, where the page is revealed
  only after qualification completes.
- **Both link + live reveal**, so the visitor reaches the page whether or not the
  socket delivered the event.
- **Honest defaults** (general route, exploratory tier, score 0) rather than
  inventing a qualification score the conversation never produced. The operator sees
  a `conversation`-sourced Lead in the cockpit and can enrich it.

## Files in this change set

New (2):
- `apps/conversations/services/reveal_bridge.py` - the bridge: contact extraction,
  Lead creation, thread claim, and the client-page reveal.
- `tests/test_conversations/test_client_page_reveal.py` - 9 tests.

Modified (3):
- `apps/conversations/services/qualification.py` - runs the reveal check on every
  turn (after the band logic), so DIAGNOSED + contact triggers the reveal.
- `apps/conversations/views_thread.py` - HTTP path appends the /c/<token> link to
  the reply when a reveal occurred.
- `apps/realtime/consumers/review.py` - WebSocket path does the same.

**No new migration** - the bridge reuses the existing Lead, ReviewSession, and
capability-token models.

## How to install

Unzip inside the root of your `itrix-backend` repo (the folder with `manage.py`):

```powershell
powershell -ExecutionPolicy Bypass -File .\itrix-backend-client-page-reveal-v1\INSTALL.ps1
python manage.py check
git add -A
git commit -m "Reveal client page from conversation (states 3 -> 4)"
git push
```

## Prerequisite

This builds on `itrix-backend-conversation-memory-v1` (which added
`Thread.current_state` and the state/loop machinery). Install that first if it is
not already in the repo. Also requires `ENABLE_ADAPTIVE_QUESTIONS=True` (already set
in your Railway env) so the loop reaches DIAGNOSED.

## The visitor experience after this

1. Visitor describes their problem -> the AI reviews and asks follow-ups (memory
   fix).
2. Once enough is covered, the loop closes -> DIAGNOSED (reflection delivered).
3. The AI invites them to take the first step; the visitor gives their company and
   email.
4. The conversation creates their Lead, advances to CLIENT_PAGE, and replies with a
   link to their personalised /c/<token> page - which the frontend already renders
   (`src/app/c/[token]/page.tsx`).

## Verification performed

- Full end-to-end through the real `/api/threads` + `/turns` endpoints: thread
  reaches DIAGNOSED, the contact turn creates a Lead, advances to CLIENT_PAGE, and
  the reply contains a `/c/<token>` link.
- The minted token **verifies** as a valid `client_page` token at state
  CLIENT_PAGE, bound to the created lead - so the `/c/<token>` page accepts it.
- Reveal gating tested: no reveal before DIAGNOSED, no reveal without contact,
  idempotent (no second lead on a second contact turn).
- Contact extraction tested, including rejecting malformed emails.
- Full backend suite: **975 passed, 0 failed** (966 baseline + 9 new), re-confirmed
  after CRLF normalisation. Zero regressions.
- `python manage.py check` clean; `makemigrations --check` reports "No changes
  detected".
- All shipped files verified CRLF, matching the repo.

## Note on tier/routing

Conversation-created Leads use exploratory defaults rather than a computed Q1-Q9
score. If you later want conversation Leads scored/tiered like form submissions,
that is a follow-up: it needs a mapping from conversation coverage to a score, which
is a product decision. This package keeps it honest rather than inventing numbers.
