# itrix-backend - Instant client-page reveal from conversation 2026-07-31
# ---------------------------------------------------------------------------
# WHAT THIS FIXES
# The conversation reached DIAGNOSED ("Reflection") and then STOPPED: the AI said
# "the Assessment Team will be in touch" and no personalised page appeared, even
# after the visitor gave their company. Two faults caused this:
#
#   1. The reveal trigger read only the CURRENT message and demanded BOTH a company
#      AND an email in that one message. Real visitors split it ("my name is X and my
#      email is Y" ... then "our company is Z"), so the two never coincided and the
#      reveal never fired.
#      FIX: contact is now accumulated across ALL turns, and an EMAIL ALONE reveals
#      the page (company is captured when present but never required).
#
#   2. The AI had no idea an instant page exists, so it did the generic-concierge
#      thing and promised a human follow-up — contradicting the page.
#      FIX: when the page is revealed, the AI is told to hand it over in its own
#      words and NOT promise the team will be in touch. The /c/<token> link is also
#      appended to the reply as a transport-independent guarantee.
#
# RUN FROM THE ROOT OF THE itrix-backend REPO (the folder with manage.py):
#     powershell -ExecutionPolicy Bypass -File .\itrix-backend-instant-client-page-v1\INSTALL.ps1
#
# Backs up every file it overwrites, refuses to run outside the repo root, clears
# stale bytecode. NO new migration (reuses existing Lead / ReviewSession / token).
# ---------------------------------------------------------------------------

$ErrorActionPreference = "Stop"

$ScriptDir  = Split-Path -LiteralPath $MyInvocation.MyCommand.Path -Parent
$PayloadDir = Join-Path -Path $ScriptDir -ChildPath "payload"

if (-not (Test-Path -LiteralPath "manage.py")) {
    Write-Error "Run this from the itrix-backend repo root (the folder with manage.py). You are in: $((Get-Location).Path)"
    exit 1
}
if (-not (Test-Path -LiteralPath "apps\conversations")) {
    Write-Error "This does not look like itrix-backend (apps\conversations is missing). Refusing to run."
    exit 1
}
if (-not (Test-Path -LiteralPath $PayloadDir)) {
    Write-Error "payload\ not found next to INSTALL.ps1. Unzip the package first, then run from the repo root."
    exit 1
}

# Depends on the conversation-memory change (Thread.current_state + the state loop).
if (-not (Select-String -Path "apps\conversations\models_thread.py" -Pattern "current_state" -Quiet -ErrorAction SilentlyContinue)) {
    Write-Warning "Thread.current_state not found - install the conversation-memory package first. Continuing, but the reveal needs the thread to reach DIAGNOSED."
}

$Stamp     = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupDir = ".instant-client-page-v1-backup-$Stamp"
New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null

Write-Host "itrix-backend instant client-page reveal - install $Stamp"
Write-Host "Backups -> $BackupDir\"
Write-Host ""

$PayloadRoot = (Resolve-Path -LiteralPath $PayloadDir).Path
$Updated = 0; $Added = 0
Get-ChildItem -LiteralPath $PayloadDir -Recurse -File | ForEach-Object {
    $rel = $_.FullName.Substring($PayloadRoot.Length + 1)
    $dst = Join-Path -Path (Get-Location).Path -ChildPath $rel

    if (Test-Path -LiteralPath $dst) {
        $b = Join-Path -Path $BackupDir -ChildPath $rel
        New-Item -ItemType Directory -Force -Path (Split-Path -LiteralPath $b -Parent) | Out-Null
        Copy-Item -LiteralPath $dst -Destination $b -Force
        $action = "updated"; $script:Updated++
    } else {
        $action = "added  "; $script:Added++
    }

    New-Item -ItemType Directory -Force -Path (Split-Path -LiteralPath $dst -Parent) | Out-Null
    Copy-Item -LiteralPath $_.FullName -Destination $dst -Force
    if (-not (Test-Path -LiteralPath $dst)) { Write-Error "Failed to write $rel"; exit 1 }
    Write-Host "  $action  $rel"
}

foreach ($cacheRoot in @("apps\conversations", "apps\realtime", "apps\agents")) {
    if (Test-Path -LiteralPath $cacheRoot) {
        Get-ChildItem -LiteralPath $cacheRoot -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
            ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction SilentlyContinue }
    }
}

Write-Host ""
Write-Host "Done. $Updated file(s) updated, $Added added, 0 removed. No migration required."
Write-Host ""
Write-Host "NEXT STEPS:"
Write-Host "  1. Verify:  python manage.py check"
Write-Host "              python -m pytest tests/test_conversations/test_client_page_reveal.py"
Write-Host "  2. git add -A"
Write-Host "  3. git commit -m 'Instant client-page reveal from conversation'"
Write-Host "  4. git push"
Write-Host ""
Write-Host "  After deploy: a visitor who completes the review and gives an email is taken"
Write-Host "  to their personalised /c/<token> page, and the AI hands it over directly"
Write-Host "  instead of saying the team will be in touch."
Write-Host "  Requires ENABLE_ADAPTIVE_QUESTIONS=True (already set in your env)."
Write-Host ""
Write-Host "  Roll back by restoring from $BackupDir\ and deleting the two new files"
Write-Host "  (apps\conversations\services\reveal_bridge.py and the test)."
