<#
.SYNOPSIS
    Archives historical OmniCapital / early Compass / monolithic HYDRA development files
    into archive/legacy/ while preserving git history where possible.

.DESCRIPTION
    Moves old versioned scripts (omnicapital_v*, compass_v*, HYDRA_ALGORITHM_COMPLETE, etc.)
    and obvious cruft (old experiment results, the giant 'nul' file, etc.) out of the
    repository root.

    This cleans up the repo root so it only contains:
    - Active project code (hydra_screener_local/, hydra_backtest/, etc.)
    - Current supporting compass_* tools (non-v* versions)
    - Documentation, tests, data sources, state, etc.

    The script defaults to DRY-RUN for safety.

.PARAMETER DryRun
    When present (default), only prints what would be done. No files are moved.

.PARAMETER Force
    When present, actually performs the moves (use after reviewing a dry run).

.EXAMPLE
    # Preview
    .\scripts\cleanup-legacy.ps1

    # Actually do it
    .\scripts\cleanup-legacy.ps1 -Force

.NOTES
    - Uses git mv for tracked files (preserves history).
    - Regular Move-Item for untracked files.
    - The giant 'nul' file is deleted rather than moved (1.2 GB device-name artifact).
    - A README.md is already present in archive/legacy/ (or will be created).
#>
[CmdletBinding()]
param(
    [switch]$DryRun = $true,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$repoRoot = (git rev-parse --show-toplevel 2>$null)
if (-not $repoRoot) {
    $repoRoot = $PSScriptRoot | Split-Path -Parent
}
Set-Location $repoRoot

Write-Host "=== HYDRA Legacy Cleanup ===" -ForegroundColor Cyan
Write-Host "Repo root: $repoRoot" -ForegroundColor Gray
if ($DryRun -and -not $Force) {
    Write-Host "MODE: DRY RUN (no changes will be made)" -ForegroundColor Yellow
} else {
    Write-Host "MODE: LIVE (files will be moved)" -ForegroundColor Red
}

# Define legacy patterns to archive (root level only)
$legacyGlobs = @(
    'omnicapital_*.py',
    'omnicapital_v*.py',
    'omnicapital*.log',
    'omnicapital*.json',
    'omnicapital_state*.json',
    'OMNICAPITAL_*',
    'HYDRA_ALGORITHM_COMPLETE.py',
    'test_hold6.py',
    'results_exp*.pkl',
    'compass_v*.py',
    'COMPASS_V8_FOR_REVIEW.py',
    'compass_v8_*.py',
    'compass_v83_*.py',
    'compass_v9_*.py',
    'omnicapital_vortex*.py'
)

# Collect candidate files (only direct children of root, not recursive)
$filesToMove = @()
foreach ($glob in $legacyGlobs) {
    $matches = Get-ChildItem -File -Filter $glob -ErrorAction SilentlyContinue
    $filesToMove += $matches
}

# Also explicitly add 'nul' if it exists (special case)
$nulFile = Get-Item -LiteralPath '.\nul' -ErrorAction SilentlyContinue
if ($nulFile) {
    $filesToMove += $nulFile
}

# Deduplicate
$filesToMove = $filesToMove | Sort-Object FullName -Unique

if ($filesToMove.Count -eq 0) {
    Write-Host "No legacy files matched. Nothing to do." -ForegroundColor Green
    exit 0
}

Write-Host "`nFound $($filesToMove.Count) legacy files to archive:" -ForegroundColor Yellow
$filesToMove | ForEach-Object { "  $($_.Name)" }

# Categorize destinations
$archiveRoot = Join-Path $repoRoot 'archive\legacy'
$categories = @{
    'omnicapital'       = @()
    'compass'           = @()
    'experiment-results' = @()
    'cruft'             = @()
}

foreach ($f in $filesToMove) {
    $name = $f.Name.ToLower()
    if ($name -eq 'nul') {
        $categories['cruft'] += $f
    }
    elseif ($name -match 'results_exp|test_hold') {
        $categories['experiment-results'] += $f
    }
    elseif ($name -match 'compass_v|compass_v8|compass_v83|compass_v9|compass_v8_for_review') {
        $categories['compass'] += $f
    }
    else {
        $categories['omnicapital'] += $f
    }
}

# Ensure category directories exist
$categories.Keys | ForEach-Object {
    $dir = Join-Path $archiveRoot $_
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
}

# Perform moves
$moved = @()
$deleted = @()

foreach ($category in $categories.Keys) {
    $destDir = Join-Path $archiveRoot $category
    foreach ($file in $categories[$category]) {
        $src = $file.FullName
        $dest = Join-Path $destDir $file.Name

        if ($file.Name -eq 'nul') {
            # Special handling for the giant nul artifact
            if ($DryRun -and -not $Force) {
                Write-Host "[DRY] Would DELETE (not move) huge nul file: $($file.Name) ($([math]::Round($file.Length/1MB,1)) MB)" -ForegroundColor Magenta
            } else {
                Write-Host "DELETING huge nul file: $($file.Name)" -ForegroundColor Red
                Remove-Item -LiteralPath $src -Force
                $deleted += $file.Name
            }
            continue
        }

        # Check if tracked by git
        $isTracked = $false
        git ls-files --error-unmatch -- "$($file.Name)" 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { $isTracked = $true }

        if ($DryRun -and -not $Force) {
            if ($isTracked) {
                Write-Host "[DRY] git mv  $($file.Name) -> archive/legacy/$category/" -ForegroundColor Gray
            } else {
                Write-Host "[DRY] Move-Item $($file.Name) -> archive/legacy/$category/" -ForegroundColor Gray
            }
        } else {
            if ($isTracked) {
                Write-Host "git mv  $($file.Name) -> archive/legacy/$category/" -ForegroundColor Green
                git mv -- "$($file.Name)" "$dest"
            } else {
                Write-Host "Move-Item $($file.Name) -> archive/legacy/$category/" -ForegroundColor Green
                Move-Item -Path $src -Destination $dest -Force
            }
            $moved += $file.Name
        }
    }
}

# Create/update a small manifest for this run (if live)
if (-not ($DryRun -and -not $Force)) {
    $manifest = @"
Legacy archival run: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
Moved files: $($moved.Count)
Deleted (nul): $($deleted.Count)

See archive/legacy/README.md for full context.
"@
    $manifest | Out-File -FilePath (Join-Path $archiveRoot "ARCHIVAL_RUN_$(Get-Date -Format 'yyyyMMdd-HHmm').txt") -Encoding utf8
}

Write-Host "`n=== Summary ===" -ForegroundColor Cyan
if ($DryRun -and -not $Force) {
    Write-Host "This was a DRY RUN. No files were changed." -ForegroundColor Yellow
    Write-Host "Re-run with -Force to perform the actual moves:" -ForegroundColor Yellow
    Write-Host "    .\scripts\cleanup-legacy.ps1 -Force" -ForegroundColor White
} else {
    Write-Host "Moved: $($moved.Count) files" -ForegroundColor Green
    Write-Host "Deleted: $($deleted.Count) files (nul artifact)" -ForegroundColor Green
    Write-Host "`nNext steps:" -ForegroundColor Cyan
    Write-Host "  git add archive/" -ForegroundColor White
    Write-Host "  git status" -ForegroundColor White
    Write-Host "  git commit -m 'chore: archive historical omnicapital/compass v* development artifacts'" -ForegroundColor White
}

Write-Host "`nArchive location: $archiveRoot" -ForegroundColor Gray
Write-Host "See archive/legacy/README.md for documentation of these historical files." -ForegroundColor Gray
