"""
Simple file structure verification (no imports needed)
Run this first to verify Phase 1 files are in place.
"""
from pathlib import Path

def check_files():
    """Verify all Phase 1 files exist."""
    root = Path(__file__).parent
    
    files = {
        "Core": [
            "market_lens/__init__.py",
            "market_lens/config.py",
        ],
        "Database": [
            "market_lens/database/__init__.py",
            "market_lens/database/models.py",
            "market_lens/database/seed.py",
            "market_lens/database/watchlist.py",
        ],
        "Packages": [
            "market_lens/ingestion/__init__.py",
            "market_lens/processing/__init__.py",
            "market_lens/analysis/__init__.py",
            "market_lens/agent/__init__.py",
            "market_lens/alerts/__init__.py",
            "market_lens/recommendation/__init__.py",
        ],
        "Config": [
            "requirements.txt",
            ".env.example",
            ".gitignore",
        ],
        "Documentation": [
            "README.md",
            "QUICKSTART.md",
            "PHASE1_COMPLETE.md",
            "docs/NSSM_SETUP.md",
        ],
        "Tests": [
            "test_phase1.py",
            "verify_files.py",
        ],
    }
    
    print("=" * 70)
    print(" " * 20 + "PHASE 1 FILE VERIFICATION")
    print("=" * 70)
    
    all_good = True
    
    for category, file_list in files.items():
        print(f"\n{category}:")
        for file_path in file_list:
            full_path = root / file_path
            if full_path.exists():
                size = full_path.stat().st_size
                print(f"  ✓ {file_path:50} ({size:,} bytes)")
            else:
                print(f"  ✗ {file_path:50} MISSING")
                all_good = False
    
    print("\n" + "=" * 70)
    if all_good:
        print("✓ ALL FILES PRESENT")
        print("=" * 70)
        print("\nNext steps:")
        print("  1. Create virtual environment: python -m venv venv")
        print("  2. Activate: .\\venv\\Scripts\\activate")
        print("  3. Install dependencies: pip install -r requirements.txt")
        print("  4. Copy .env.example to .env and configure")
        print("  5. Create PostgreSQL database 'market_lens'")
        print("  6. Run: python -m market_lens.database.seed")
        print("  7. Run: python test_phase1.py")
        return 0
    else:
        print("✗ SOME FILES MISSING")
        print("=" * 70)
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(check_files())
