#!/usr/bin/env bash
#
# itriX Backend v6.0 — PHASE 3 INSTALLER (FINAL)
# Customer-first NBA · inline cards · analytics · retention · rails retirement
#
# USAGE
#   Put this zip in the ROOT of itrix-backend, unzip it, and run:
#
#       bash itrix-backend-v6-phase3/INSTALL.sh
#
# WHAT IT DOES
#   1. GUARD    refuses to run without Phases 1 and 2 installed
#   2. BACKUP   timestamped copy of every file it will touch
#   3. INSTALL  50 files into place
#   4. VERIFY   Django check, migration drift, the retired contracts
#   5. REPORT   what to run next
#
# ── PHASE 3 IS NOT PURELY ADDITIVE ───────────────────────────────────────────
# Unlike Phases 1 and 2, this one REMOVES things. Read this before you run it:
#
#   * The deprecated ENGAGED and CLIENT journey states are DROPPED (migration 0005).
#     They survived exactly one release as aliases. Stale rows still READ correctly
#     via normalize_state(), but nothing can write them any more.
#
#   * left_rail / right_rail are RETIRED. They were emitted as empty stubs through
#     Phases 1-2, giving both frontends a full release to migrate. A client that still
#     SENDS them now receives 400.
#
#   * tier and scoreBreakdown are REMOVED from the PUBLIC result page. They were being
#     served to unidentified visitors, which is a §10.5 breach.
#
# CONFIRM YOUR FRONTENDS NO LONGER READ left_rail / right_rail BEFORE DEPLOYING.

set -euo pipefail

PKG_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(pwd)"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="${REPO_ROOT}/.v6-phase3-backup-${STAMP}"

BOLD=$'\033[1m'; RED=$'\033[31m'; GRN=$'\033[32m'; YLW=$'\033[33m'; DIM=$'\033[2m'; RST=$'\033[0m'

head1() { printf '\n%s%s%s\n' "$BOLD" "$*" "$RST"; }
ok()   { printf '  %s✓%s %s\n' "$GRN" "$RST" "$*"; }
warn() { printf '  %s!%s %s\n' "$YLW" "$RST" "$*"; }
die()  { printf '\n  %s✗ %s%s\n\n' "$RED" "$*" "$RST" >&2; exit 1; }

# ─────────────────────────────────────────────────────────────────────────────
head1 "1/5  GUARD"
# ─────────────────────────────────────────────────────────────────────────────
[[ -f "${REPO_ROOT}/manage.py" ]] || die "No manage.py here. Run from the itrix-backend root."
[[ -f "${PKG_DIR}/MANIFEST_INSTALL.txt" ]] || die "MANIFEST_INSTALL.txt missing — package incomplete."
[[ -d "${PKG_DIR}/files" ]] || die "files/ missing — package incomplete."

for required in \
  "apps/journey/constants.py" \
  "apps/journey/services/shell.py" \
  "apps/customer_success/models.py" \
  "apps/attachments/models.py" \
  "apps/agents/services/stop_rule.py" \
  "apps/journey/services/artifacts.py"
do
  [[ -f "${REPO_ROOT}/${required}" ]] || die "Phases 1-2 are not both installed (missing ${required})."
done
ok "Phases 1 and 2 confirmed"

# Migration 0003 must already have converted the bulk of the ENGAGED rows. 0005 sweeps
# stragglers, but running it without 0003 would classify the WHOLE population late.
if [[ ! -f "${REPO_ROOT}/apps/journey/migrations/0003_migrate_engaged_split.py" ]]; then
  die "journey/0003 is missing — run the Phase 1 migration before Phase 3."
fi
ok "journey/0003 present (the ENGAGED split has a home)"

printf '\n  %sPhase 3 REMOVES the deprecated ENGAGED/CLIENT states and the rails stubs.%s\n' "$BOLD" "$RST"
printf '  %sConfirm both frontends no longer read left_rail / right_rail.%s\n' "$DIM" "$RST"
read -r -p "  Have your frontends migrated off the rails contract? [y/N] " reply
[[ "${reply}" =~ ^[Yy]$ ]] || die "Aborted. Migrate the frontends first, then re-run."

if command -v git >/dev/null 2>&1 && git -C "${REPO_ROOT}" rev-parse --git-dir >/dev/null 2>&1; then
  if [[ -n "$(git -C "${REPO_ROOT}" status --porcelain)" ]]; then
    warn "Your working tree has uncommitted changes."
    read -r -p "  Continue? [y/N] " reply
    [[ "${reply}" =~ ^[Yy]$ ]] || die "Aborted by user. Nothing was changed."
  else
    ok "git working tree is clean"
  fi
fi

# ─────────────────────────────────────────────────────────────────────────────
head1 "2/5  BACKUP"
# ─────────────────────────────────────────────────────────────────────────────
mkdir -p "${BACKUP_DIR}"
backed_up=0
while IFS= read -r rel; do
  [[ -z "${rel}" ]] && continue
  if [[ -f "${REPO_ROOT}/${rel}" ]]; then
    mkdir -p "${BACKUP_DIR}/$(dirname "${rel}")"
    cp -p "${REPO_ROOT}/${rel}" "${BACKUP_DIR}/${rel}"
    backed_up=$((backed_up + 1))
  fi
done < "${PKG_DIR}/MANIFEST_INSTALL.txt"
ok "${backed_up} existing file(s) backed up"
printf '  %s%s%s\n' "$DIM" "${BACKUP_DIR}" "$RST"
printf '  %sRestore with: cp -a "%s"/. "%s"/%s\n' "$DIM" "${BACKUP_DIR}" "${REPO_ROOT}" "$RST"
printf '  %sNote: a code restore does NOT undo migration 0005 — use%s\n' "$DIM" "$RST"
printf '  %s      python manage.py migrate journey 0004%s\n' "$DIM" "$RST"

# ─────────────────────────────────────────────────────────────────────────────
head1 "3/5  INSTALL"
# ─────────────────────────────────────────────────────────────────────────────
installed=0
while IFS= read -r rel; do
  [[ -z "${rel}" ]] && continue
  src="${PKG_DIR}/files/${rel}"
  [[ -f "${src}" ]] || die "Package is missing ${rel} — refusing a partial install."
  mkdir -p "${REPO_ROOT}/$(dirname "${rel}")"
  cp -p "${src}" "${REPO_ROOT}/${rel}"
  installed=$((installed + 1))
done < "${PKG_DIR}/MANIFEST_INSTALL.txt"
ok "${installed} file(s) installed"

# ─────────────────────────────────────────────────────────────────────────────
head1 "4/5  VERIFY"
# ─────────────────────────────────────────────────────────────────────────────
PY="${PYTHON:-python3}"
command -v "${PY}" >/dev/null 2>&1 || die "python3 not found. Set PYTHON=/path/to/python and re-run."
verify_failed=0

if "${PY}" -c "import django" >/dev/null 2>&1; then
  if DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-itrix.settings.development}" \
     "${PY}" manage.py check >/tmp/v6p3check.log 2>&1; then
    ok "manage.py check — no issues"
  else
    warn "manage.py check reported problems:"
    sed 's/^/      /' /tmp/v6p3check.log | tail -20
    verify_failed=1
  fi

  if DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-itrix.settings.development}" \
     "${PY}" manage.py makemigrations --check --dry-run >/tmp/v6p3mig.log 2>&1; then
    ok "no un-generated model changes (migration set is complete)"
  else
    warn "makemigrations --check found drift:"
    sed 's/^/      /' /tmp/v6p3mig.log | tail -12
    verify_failed=1
  fi
else
  warn "Django not importable here — skipping the Django checks."
fi

missing=0
for f in apps/governance/services/nba_precedence.py apps/journey/services/cards.py \
         apps/conversations/services/retention.py \
         apps/analytics/services/customer_health.py \
         apps/analytics/services/stream_metrics.py \
         apps/journey/migrations/0005_drop_engaged_alias.py \
         apps/conversations/management/commands/purge_anonymous_threads.py
do
  [[ -f "${REPO_ROOT}/${f}" ]] || { warn "MISSING after install: ${f}"; missing=1; }
done
[[ "${missing}" == "0" ]] && ok "key Phase 3 modules present" || verify_failed=1

# The two retirements, asserted on the installed source.
if grep -q "deprecated_rail_stub" "${REPO_ROOT}/apps/conversations/serializers_thread.py" 2>/dev/null; then
  warn "the rails deprecation stub is still present"
  verify_failed=1
else
  ok "rails contract retired (left_rail / right_rail removed)"
fi

if grep -qE '^\s+ENGAGED = "ENGAGED"' "${REPO_ROOT}/apps/journey/models.py" 2>/dev/null; then
  warn "the deprecated ENGAGED member is still in the enum"
  verify_failed=1
else
  ok "ENGAGED / CLIENT dropped from the journey enum"
fi

# ─────────────────────────────────────────────────────────────────────────────
head1 "5/5  NEXT STEPS"
# ─────────────────────────────────────────────────────────────────────────────
cat <<'NEXT'
  1. MIGRATE — three migrations. journey/0005 SWEEPS any straggler ENGAGED row
     before narrowing the vocabulary, so run the report first if you want to see
     what it will touch:

         python manage.py journey_migration_report --detail
         python manage.py migrate

  2. RUN THE TESTS:

         pytest -q                      # expect 731 passed

  3. TURN THE RULE ON. Everything else is already live; this is the last flag:

         ENABLE_CUSTOMER_FIRST_NBA=True

     With it OFF the highest-weighted candidate wins (pre-Phase-3 behaviour), so
     the flag is genuinely reversible. With it ON, support and outcome actions
     provably outrank expansion on BOTH surfaces.

  4. FINALISE THE PHASE 1-2 FLAGS. Phase 3 assumes they are on:

         ENABLE_TEN_STATE_JOURNEY=True
         ENABLE_CONVERSATION_SURFACE=True
         ENABLE_ANONYMOUS_STREAMING=True
         ENABLE_CUSTOMER_SUCCESS=True
         CUSTOMER_CONTRACT_TIER_ENABLED=True
         ENABLE_ATTACHMENTS=True
         ENABLE_ADAPTIVE_QUESTIONS=True

  5. START CELERY BEAT. The schedules are registered in code, but beat has to be
     running for retention to happen. Retention is a PRIVACY OBLIGATION:

         celery -A tasks.celery beat --loglevel=info

     Scheduled: nightly health recompute · SLA sweep every 15 min · nightly
     attachment purge · nightly anonymous-thread expiry.

  6. VERIFY RETENTION at any time, with or without a broker:

         python manage.py purge_anonymous_threads --report
         python manage.py purge_anonymous_threads --verify
         python scripts/purge_attachments.py --verify

  7. NEW COCKPIT ENDPOINTS (team-JWT only):

         /api/v1/analytics/customers/      health board
         /api/v1/analytics/support/        queue depth, SLA, ageing
         /api/v1/analytics/outcomes/       outcome distribution
         /api/v1/analytics/conversations/  depth, loop productivity, abandonment
         /api/v1/analytics/attachments/    volume, extraction, quarantine
         /api/v1/analytics/streaming/      guard halts + THE DRIFT SIGNAL
         /api/v1/cockpit/customers|threads|attachments|streaming/

  A NOTE ON THE DRIFT SIGNAL. /analytics/streaming/ reports whether the guard-hit
  rate is RISING, not just its total. A rising rate is retrieval or prompt drift,
  not noise — if it climbs, check what changed in retrieval or the system prompt.
NEXT

if [[ "${verify_failed}" == "1" ]]; then
  printf '\n  %s! Verification reported problems. Review them before migrating.%s\n\n' "$YLW" "$RST"
  exit 1
fi

printf '\n  %s✓ Phase 3 installed and verified. The backend is complete.%s\n\n' "$GRN" "$RST"
