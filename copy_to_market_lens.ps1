# Copy Market Lens Phase 1 files to C:\Users\User\Downloads\DuoWeave\Market Lens
# Copies ONLY Market Lens project files (not node_modules, 1st Interation, etc.)

$Source = "C:\Users\User\.cursor\worktrees\Market_Lens\avi"
$Dest   = "C:\Users\User\Downloads\DuoWeave\Market Lens"

Write-Host "Copying Market Lens project to DuoWeave..." -ForegroundColor Cyan
Write-Host "  From: $Source"
Write-Host "  To:   $Dest"
Write-Host ""

if (-not (Test-Path $Dest)) {
    New-Item -ItemType Directory -Path $Dest -Force | Out-Null
    Write-Host "Created destination folder." -ForegroundColor Yellow
}

# Copy only Market Lens items (no node_modules, no other repo folders)
$items = @(
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

foreach ($item in $items) {
    $srcPath = Join-Path $Source $item
    if (Test-Path $srcPath) {
        $destPath = Join-Path $Dest $item
        Copy-Item -Path $srcPath -Destination $destPath -Recurse -Force -ErrorAction SilentlyContinue
        Write-Host "  Copied: $item" -ForegroundColor Gray
    }
}

Write-Host ""
Write-Host "Copy complete. Contents of destination:" -ForegroundColor Green
Get-ChildItem -Path $Dest -Name | ForEach-Object { Write-Host "  $_" }
Write-Host ""
Write-Host "Done. Open folder: $Dest" -ForegroundColor Green
