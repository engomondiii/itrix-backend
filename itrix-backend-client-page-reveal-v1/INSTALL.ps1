# itrix-backend - Conversation -> client-page reveal (states 3 -> 4) 2026-07-31
# ---------------------------------------------------------------------------
# WHAT THIS ADDS
# The conversation surface took anonymous visitors through the qualification band
# (ARRIVED -> IN_REVIEW -> DIAGNOSED) but stopped at DIAGNOSED. This package
# carries it the rest of the way: once the loop has closed AND the visitor gives a
# company + a valid email, the conversation creates a real Lead, advances to
# CLIENT_PAGE (state 4), mints the /c/<token> capability token exactly as the
# structured-form path does, and hands the visitor a link to their personalised
# page (plus a live reveal over the socket).
#
# RUN FROM THE ROOT OF THE itrix-backend REPO (the folder with manage.py):
#     powershell -ExecutionPolicy Bypass -File .\itrix-backend-client-page-reveal-v1\INSTALL.ps1
#
# It backs up every file it overwrites, refuses to run outside the repo root, and
# clears stale bytecode. NO new migration is required (the bridge reuses the
# existing Lead / ReviewSession / capability-token models).
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

# This package builds on the conversation-memory change (Thread.current_state). Warn
# if that is not present, since the reveal depends on the thread reaching DIAGNOSED.
if (-not (Select-String -Path "apps\conversations\models_thread.py" -Pattern "current_state" -Quiet -ErrorAction SilentlyContinue)) {
    Write-Warning "Thread.current_state not found - install itrix-backend-conversation-memory-v1 first. Continuing, but the reveal needs it."
}

$Stamp     = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupDir = ".client-page-reveal-v1-backup-$Stamp"
New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null

Write-Host "itrix-backend client-page reveal - install $Stamp"
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

foreach ($cacheRoot in @("apps\conversations", "apps\realtime")) {
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
Write-Host "  3. git commit -m 'Reveal client page from conversation (states 3 -> 4)'"
Write-Host "  4. git push"
Write-Host ""
Write-Host "  After deploy: a visitor who completes qualification and then gives a company"
Write-Host "  and email in the chat is taken to their personalised /c/<token> page."
Write-Host "  Requires ENABLE_ADAPTIVE_QUESTIONS=True (already set in your env)."
Write-Host ""
Write-Host "  Roll back by restoring from $BackupDir\ and deleting the two new files."
