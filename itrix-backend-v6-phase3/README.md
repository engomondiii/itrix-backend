# itriX Backend v6.0 — Phase 3 (FINAL)

Customer-first NBA · inline cards · analytics · retention · rails retirement.

**By the end of this phase the backend is complete and production-ready.**

## Install

```bash
unzip itrix-backend-v6-phase3.zip
bash itrix-backend-v6-phase3/INSTALL.sh
```

Guards on Phases 1-2, backs up, installs 50 files, verifies both retirements.
Does **not** migrate.

## Validation

| Check | Result |
|---|---|
| Full test suite | **731 passed, 0 failed** (from 628) |
| New tests | **103** |
| `manage.py check` / `--deploy` | no issues |
| `makemigrations --check` | no drift |
| Install on pristine Phase-2 checkout | **byte-identical** |
| Migrations on installed result | all three apply |

## ⚠ Phase 3 is NOT purely additive

Unlike Phases 1-2, this one **removes** things. Read before deploying:

- **`ENGAGED` and `CLIENT` journey states are dropped** (migration 0005). They survived
  exactly one release as aliases. Stale rows still *read* correctly via
  `normalize_state()`, but nothing can write them.
- **`left_rail` / `right_rail` are retired.** Emitted as empty stubs through Phases 1-2,
  giving both frontends a full release to migrate. A client that still *sends* them now
  receives 400 — naming the field, so the frontend author knows what to change.
- **`tier` and `scoreBreakdown` removed from the PUBLIC result page** — see below.

**Confirm your frontends no longer read the rails fields before deploying.** The
installer asks.

## A real leak the contract test found

`tests/contract/test_client_plane_field_allowlist.py` sweeps *every* serializer in the
codebase rather than trusting per-app tests. It found `ResultPageSerializer` — mounted
`AllowAny` and listed in `public_groups` — exposing `tier` and `scoreBreakdown`.

An unidentified visitor could read the tier we had assigned them and the breakdown of how
we scored them. That is precisely what §4 forbids:

> Personalization means the framing, the emphasis and the chosen pathway are tailored.
> It **never** means telling the visitor what we think we know about them.

Removed. The page's *content* is still tailored by tier and score; the visitor is no
longer shown the machinery. Two existing tests asserted the old shape — they were pinning
the leak, and have been updated.

## One rule, two surfaces

`nba_precedence` is called by **both** `PortalNextBestActionView` and
`CockpitNextActionView`. §11.1: a customer and an operator can never see contradictory
guidance. If the rule were implemented twice they would drift, and the first symptom would
be a customer being sold to while their operator was looking at an unresolved outage.

The suppression reason goes to the operator only. A customer does not need to be told we
decided not to sell to them today.

## Fail-safe, not fail-open

- `_default_action` **manufactures** a support action if condition 1 holds and none was
  offered — the rule never falls through to commercial.
- Every signal in `collect_signals` fails to the *suppressing* value. An unavailable
  health service must not read as a healthy customer.
- Migration 0005 **sweeps stragglers before** narrowing the vocabulary — a rolling deploy
  can write a fresh `ENGAGED` row between 0003 and 0005, and that window is real.

## The drift signal

`/analytics/streaming/` reports whether the guard-hit rate is **rising**, not just its
total, and states the interpretation rule inline. §6.4: a rising rate is retrieval or
prompt drift, not noise. A number without its rule gets read as "the guard is working
well".
