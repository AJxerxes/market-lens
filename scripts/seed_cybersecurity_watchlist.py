"""
Seed watchlist with AI/automotive cybersecurity tickers and thesis notes.
Run from project root: python -m scripts.seed_cybersecurity_watchlist
Or: cd Market Lens && venv\Scripts\python -m scripts.seed_cybersecurity_watchlist
"""
import sys
from pathlib import Path

# Ensure project root on path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from market_lens.database.watchlist import WatchlistManager

PYTHON_TICKERS = [
    # AI Cybersecurity plays
    ("S", "SentinelOne — AI-native endpoint security, CrowdStrike competitor with lower valuation. Watch: ARR growth, gross margin expansion, path to profitability."),
    ("ZS", "Zscaler — zero trust network access. Thesis: as AI agents make autonomous API calls across enterprise networks, zero trust becomes mandatory architecture. Watch: platform consolidation deals, federal contracts."),
    ("PANW", "Palo Alto Networks — incumbent security platform. Platformization strategy and AI SOC automation. Watch: platformization revenue mix, billings growth."),
    ("FTNT", "Fortinet — cheaper valuation than peers, strong OT/ICS security. Thesis: AI touching physical infrastructure expands their addressable market. Watch: OT segment revenue."),
    ("TENB", "Tenable — vulnerability management. Thesis: AI accelerates software development and vulnerability introduction simultaneously. Watch: cloud exposure management adoption."),
    ("VRNS", "Varonis — data security and insider threat detection. Thesis: AI systems require broad enterprise data access creating new insider threat and data exfiltration surface. Watch: SaaS transition progress."),
    ("CALX", "Calix — broadband network security and management platform. Thesis: AI traffic explosion travels over networks broadband providers need AI-native management. Lynch observation: unglamorous but essential picks and shovels."),
    ("IOT", "Samsara — physical operations AI and security. Thesis: AI moving into trucks factories job sites creates new physical security category. Lynch observation: dashcams visible on commercial trucks nationwide. Check windshields of commercial vehicles on highways."),
    ("NET", "Cloudflare — network security and edge computing. Lynch observation: user has direct personal experience using Cloudflare for websites and understands the business model from the inside including their entropy-based security architecture. Strong natural edge here over typical retail investor."),
    # Automotive cybersecurity — AV and connected vehicle plays
    ("NXPI", "NXP Semiconductors — chips inside vehicles handling secure communications encrypted key management and hardware security modules. Every major automaker uses NXP silicon including Waymo Tesla GM SuperCruise. Pure picks and shovels play — sells to everyone regardless of who wins the AV race. Watch: automotive segment revenue growth, design win announcements, EV content per vehicle increases."),
    ("APTV", "Aptiv — electrical architecture and software systems inside vehicles. Essentially the nervous system supplier to the auto industry. As cars become software-defined Aptiv sits at the intersection of hardware and cybersecurity. Spun out of Delphi. Watch: software and services revenue mix, autonomous driving partnerships, margin expansion as software content grows."),
    ("CTTAF", "Continental AG — German automotive supplier deeply embedded in vehicle cybersecurity and ADAS systems. OTC listed in US so liquidity is limited but exposure to every major automaker globally. Watch: OTC liquidity before sizing, software division separation plans, AV contract wins."),
]


def main():
    wl = WatchlistManager()
    try:
        for ticker, thesis in PYTHON_TICKERS:
            result = wl.add_ticker(ticker, thesis_notes=thesis, force=True)
            status = result.get("status", "?")
            msg = result.get("message") or result.get("error", str(result))
            print(f"  {ticker}: {status} — {msg}")
    finally:
        if getattr(wl, "_owns_session", True) and wl.session:
            wl.session.close()
    print("Done.")


if __name__ == "__main__":
    main()
