# UNDO: Remove wrongly copied items from DuoWeave\Market Lens
# THEN: Copy ONLY Market Lens project files (no node_modules, no 1st Interation, etc.)

$Dest = "C:\Users\User\Downloads\DuoWeave\Market Lens"
$Source = "C:\Users\User\.cursor\worktrees\Market_Lens\avi"

Write-Host "=== STEP 1: Removing wrongly copied folders ===" -ForegroundColor Red
$toRemove = @(
    "node_modules",
    "1st Interation",
    "presentation",
    "website",
    "backups",
    "work",
    "YinYang",
    "ios app version"
)
foreach ($name in $toRemove) {
    $path = Join-Path $Dest $name
    if (Test-Path $path) {
        Remove-Item -Path $path -Recurse -Force -ErrorAction SilentlyContinue
        Write-Host "  Removed: $name" -ForegroundColor Yellow
    }
}

# Remove zip files and other non-Market-Lens files that may have been copied
$fileJunk = @("Web-App-main.zip", "YinYang.zip", "copy_to_market_lens.ps1")
foreach ($name in $fileJunk) {
    $path = Join-Path $Dest $name
    if (Test-Path $path) {
        Remove-Item -Path $path -Force -ErrorAction SilentlyContinue
        Write-Host "  Removed file: $name" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "=== STEP 2: Copying ONLY Market Lens project files ===" -ForegroundColor Green

$marketLensItems = @(
    "market_lens",
    "docs",
    "README.md",
    "QUICKSTART.md",
    "PHASE1_COMPLETE.md",
    "requirements.txt",
    ".env.example",
    ".gitignore",
    "test_phase1.py",
    "verify_files.py"
)

foreach ($item in $marketLensItems) {
    $srcPath = Join-Path $Source $item
    if (Test-Path $srcPath) {
        $destPath = Join-Path $Dest $item
        Copy-Item -Path $srcPath -Destination $destPath -Recurse -Force -ErrorAction Stop
        Write-Host "  Copied: $item" -ForegroundColor Cyan
    }
}

Write-Host ""
Write-Host "Done. Only Market Lens files are now in: $Dest" -ForegroundColor Green
Get-ChildItem -Path $Dest -Name | ForEach-Object { Write-Host "  $_" }
