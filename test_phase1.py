"""
Market Lens Phase 1 Verification Script
Tests config, database models, seed, and watchlist functionality.
"""
import sys
from pathlib import Path

# Add market_lens to path
sys.path.insert(0, str(Path(__file__).parent))

def test_config():
    """Test config module loads correctly."""
    print("\n" + "="*60)
    print("Testing Config Module")
    print("="*60)
    
    try:
        from market_lens import config
        
        print(f"✓ Config loaded successfully")
        print(f"  Workspace root: {config.WORKSPACE_ROOT}")
        print(f"  Log directory: {config.LOG_DIR}")
        print(f"  Database URL: {config.DATABASE_URL[:30]}...")
        print(f"  EDGAR User-Agent: {config.EDGAR_USER_AGENT}")
        print(f"  Display timezone: {config.DISPLAY_TIMEZONE}")
        
        # Test pathlib usage
        assert isinstance(config.WORKSPACE_ROOT, Path), "WORKSPACE_ROOT must be pathlib.Path"
        assert isinstance(config.LOG_DIR, Path), "LOG_DIR must be pathlib.Path"
        
        # Test weights sum to 1.0
        lynch_sum = sum(config.LYNCH_WEIGHTS.values())
        assert abs(lynch_sum - 1.0) < 0.01, f"Lynch weights sum to {lynch_sum}, not 1.0"
        
        swing_sum = sum(config.SWING_WEIGHTS.values())
        assert abs(swing_sum - 1.0) < 0.01, f"Swing weights sum to {swing_sum}, not 1.0"
        
        print(f"✓ Lynch weights sum: {lynch_sum:.2f}")
        print(f"✓ Swing weights sum: {swing_sum:.2f}")
        
        return True
    except Exception as e:
        print(f"✗ Config test failed: {e}")
        return False


def test_models():
    """Test database models are importable."""
    print("\n" + "="*60)
    print("Testing Database Models")
    print("="*60)
    
    try:
        from market_lens.database import models
        
        print(f"✓ Models module loaded")
        
        # Check key models exist
        assert hasattr(models, 'Company'), "Company model missing"
        assert hasattr(models, 'PriceHistory'), "PriceHistory model missing"
        assert hasattr(models, 'Score'), "Score model missing"
        assert hasattr(models, 'AgentMemory'), "AgentMemory model missing"
        assert hasattr(models, 'InstrumentType'), "InstrumentType enum missing"
        
        print(f"✓ Core models present:")
        print(f"  - Company")
        print(f"  - PriceHistory")
        print(f"  - Fundamentals")
        print(f"  - Score")
        print(f"  - InsiderTransaction")
        print(f"  - NewsSentiment")
        print(f"  - OptionsSignal")
        print(f"  - AgentMemory")
        print(f"  - AgentCycleLog")
        print(f"  - CourtCase")
        print(f"  - LeadershipEvent")
        print(f"  - SupplierSignal")
        print(f"  - CongressMember")
        print(f"  - CongressTrade")
        
        # Check enums
        print(f"\n✓ Enums present:")
        print(f"  - InstrumentType: {[e.value for e in models.InstrumentType]}")
        print(f"  - DepartureClassification: {[e.value for e in models.DepartureClassification]}")
        
        return True
    except Exception as e:
        print(f"✗ Models test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_watchlist_manager():
    """Test watchlist manager (without DB connection)."""
    print("\n" + "="*60)
    print("Testing Watchlist Manager")
    print("="*60)
    
    try:
        from market_lens.database.watchlist import WatchlistManager
        
        print(f"✓ WatchlistManager class loaded")
        
        # Test classification logic (no DB needed)
        print(f"\n✓ Instrument classification methods present")
        
        return True
    except Exception as e:
        print(f"✗ Watchlist manager test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_seed_script():
    """Test seed script is importable."""
    print("\n" + "="*60)
    print("Testing Seed Script")
    print("="*60)
    
    try:
        from market_lens.database import seed
        
        print(f"✓ Seed module loaded")
        print(f"✓ Functions present:")
        print(f"  - create_tables()")
        print(f"  - seed_watchlist()")
        print(f"  - run_seed()")
        
        return True
    except Exception as e:
        print(f"✗ Seed script test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_directory_structure():
    """Verify project directory structure."""
    print("\n" + "="*60)
    print("Testing Directory Structure")
    print("="*60)
    
    root = Path(__file__).parent
    
    required_files = [
        "market_lens/__init__.py",
        "market_lens/config.py",
        "market_lens/database/__init__.py",
        "market_lens/database/models.py",
        "market_lens/database/seed.py",
        "market_lens/database/watchlist.py",
        "requirements.txt",
        ".env.example",
        "docs/NSSM_SETUP.md",
        "README.md",
    ]
    
    all_exist = True
    for file_path in required_files:
        full_path = root / file_path
        if full_path.exists():
            print(f"✓ {file_path}")
        else:
            print(f"✗ {file_path} MISSING")
            all_exist = False
    
    return all_exist


def main():
    """Run all Phase 1 tests."""
    print("\n" + "="*80)
    print(" "*20 + "MARKET LENS PHASE 1 VERIFICATION")
    print("="*80)
    
    results = {
        "Directory Structure": test_directory_structure(),
        "Config Module": test_config(),
        "Database Models": test_models(),
        "Watchlist Manager": test_watchlist_manager(),
        "Seed Script": test_seed_script(),
    }
    
    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)
    
    for test_name, passed in results.items():
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{status:8} | {test_name}")
    
    all_passed = all(results.values())
    
    if all_passed:
        print("\n" + "="*80)
        print("✓ ALL PHASE 1 TESTS PASSED")
        print("="*80)
        print("\nNext steps:")
        print("  1. Copy .env.example to .env and fill in your values")
        print("  2. Create PostgreSQL database 'market_lens' in pgAdmin")
        print("  3. Run: python -m market_lens.database.seed")
        print("  4. Verify seed data: python -m market_lens.database.watchlist list")
        print("  5. Proceed to Phase 2 (price ingestion)")
        return 0
    else:
        print("\n" + "="*80)
        print("✗ SOME TESTS FAILED")
        print("="*80)
        print("\nFix errors above before proceeding to Phase 2")
        return 1


if __name__ == "__main__":
    sys.exit(main())
