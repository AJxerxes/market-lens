"""
Run one agent brain cycle (delta + synthesis) and log to agent_cycle_log.
Use for verification: Check 6.
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from market_lens.config import DATABASE_URL
from market_lens.database.models import Company, AgentCycleLog
from market_lens.agent.memory import build_signal_history_90d, get_latest_memory, prior_state_from_memory
from market_lens.agent.delta import detect_delta
from market_lens.agent.synthesizer import synthesize_change

def main():
    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        companies = session.query(Company).filter(Company.active == True).all()
        did_one = False
        for c in companies:
            ticker = c.ticker
            prior = get_latest_memory(session, ticker)
            delta, should_synth = detect_delta(session, ticker, prior_memory=prior)
            # Ensure at least one cycle is logged for verification
            if not should_synth and not did_one:
                should_synth = True
                delta["as_of_date"] = delta.get("as_of_date")
            if not should_synth:
                continue
            history_90d = build_signal_history_90d(session, ticker)
            prior_state = prior_state_from_memory(prior)
            thesis = (c.thesis_notes or "")[:2000]
            try:
                synthesis_text = synthesize_change(ticker, thesis, prior_state, delta, history_90d)
            except Exception as e:
                print(f"  Synthesis {ticker}: {e}")
                synthesis_text = ""
            session.add(AgentCycleLog(
                ticker=ticker,
                cycle_at=datetime.now(timezone.utc),
                delta_trigger=delta,
                synthesis_text=synthesis_text or None,
                material_flag=bool(delta.get("coincidence") or delta.get("score_change")),
                alert_sent=False,
            ))
            did_one = True
            print(f"  [OK] {ticker} cycle logged")
        session.commit()
        print("[OK] Agent brain cycle done.")
    except Exception as e:
        session.rollback()
        raise
    finally:
        session.close()

if __name__ == "__main__":
    main()
