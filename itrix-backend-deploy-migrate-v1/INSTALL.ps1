# itrix-backend - Run migrations on deploy (fixes the production 500) 2026-07-31
# ---------------------------------------------------------------------------
# WHAT THIS FIXES
# The production 500 on /api/threads was NOT a code bug - it was a deploy bug.
# The image started the server directly with no migration step (no release
# command anywhere), so the conversation-memory migration that adds
# Thread.current_state / Thread.questions_asked never ran on Railway. The code
# expected the new columns; the database did not have them; every thread create
# 500'd, and the frontend fell back to a local "thr_local_..." id.
#
# This package makes migrations run automatically on every deploy, via a small
# start.sh entrypoint the Dockerfile now calls. It also updates the Procfile web
# process to migrate first. Deploying this heals the current 500 (the migration
# runs on boot) AND prevents the whole class of "schema drift" problem going forward.
#
# RUN FROM THE ROOT OF THE itrix-backend REPO (the folder with manage.py):
#     powershell -ExecutionPolicy Bypass -File .\itrix-backend-deploy-migrate-v1\INSTALL.ps1
#
# It backs up Dockerfile + Procfile before overwriting, and refuses to run outside
# the repo root. It does not run anything - you just commit and push afterwards.
# ---------------------------------------------------------------------------

$ErrorActionPreference = "Stop"

$ScriptDir  = Split-Path -LiteralPath $MyInvocation.MyCommand.Path -Parent
$PayloadDir = Join-Path -Path $ScriptDir -ChildPath "payload"

if (-not (Test-Path -LiteralPath "manage.py")) {
    Write-Error "Run this from the itrix-backend repo root (the folder with manage.py). You are in: $((Get-Location).Path)"
    exit 1
}
if (-not (Test-Path -LiteralPath "Dockerfile")) {
    Write-Error "No Dockerfile here - this does not look like the itrix-backend repo root. Refusing to run."
    exit 1
}
if (-not (Test-Path -LiteralPath $PayloadDir)) {
    Write-Error "payload\ not found next to INSTALL.ps1. Unzip the package first, then run from the repo root."
    exit 1
}

$Stamp     = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupDir = ".deploy-migrate-v1-backup-$Stamp"
New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null

Write-Host "itrix-backend deploy-migration fix - install $Stamp"
Write-Host "Backups -> $BackupDir\"
Write-Host ""

$PayloadRoot = (Resolve-Path -LiteralPath $PayloadDir).Path
Get-ChildItem -LiteralPath $PayloadDir -Recurse -File | ForEach-Object {
    $rel = $_.FullName.Substring($PayloadRoot.Length + 1)
    $dst = Join-Path -Path (Get-Location).Path -ChildPath $rel

    if (Test-Path -LiteralPath $dst) {
        $b = Join-Path -Path $BackupDir -ChildPath $rel
        New-Item -ItemType Directory -Force -Path (Split-Path -LiteralPath $b -Parent) | Out-Null
        Copy-Item -LiteralPath $dst -Destination $b -Force
        $action = "updated"
    } else {
        $action = "added  "
    }

    # Copy-Item copies bytes verbatim, so start.sh keeps its LF line endings - which
    # matters: a shell script with CRLF fails on Linux with "bad interpreter".
    Copy-Item -LiteralPath $_.FullName -Destination $dst -Force
    if (-not (Test-Path -LiteralPath $dst)) { Write-Error "Failed to write $rel"; exit 1 }
    Write-Host "  $action  $rel"
}

Write-Host ""
Write-Host "Done. start.sh added; Dockerfile + Procfile updated to migrate on deploy."
Write-Host ""
Write-Host "IMPORTANT - do NOT let Git rewrite start.sh to CRLF:"
Write-Host "  A .gitattributes rule is included (gitattributes-append.txt) that forces"
Write-Host "  start.sh to LF. Append it to your .gitattributes (or copy the file in) so"
Write-Host "  the script stays LF when committed from Windows. If start.sh ends up CRLF,"
Write-Host "  the container fails at boot with 'bad interpreter: /usr/bin/env sh^M'."
Write-Host ""
Write-Host "NEXT STEPS:"
Write-Host "  1. (append .gitattributes rule)  Get-Content gitattributes-append.txt | Add-Content .gitattributes"
Write-Host "  2. git add -A"
Write-Host "  3. git commit -m 'Run DB migrations on deploy (fix production 500)'"
Write-Host "  4. git push"
Write-Host ""
Write-Host "  On the next Railway deploy, start.sh runs 'migrate --noinput' before the"
Write-Host "  server starts, which applies the pending conversation-memory migration and"
Write-Host "  clears the 500. Watch the deploy logs for '[start] running database migrations'."
Write-Host ""
Write-Host "  Roll back by restoring Dockerfile + Procfile from $BackupDir\ and deleting start.sh."
