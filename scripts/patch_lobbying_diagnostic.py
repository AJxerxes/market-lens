"""One-off patch: add first-hit diagnostic and fix _source/lobbyist mapping in congress_tracker.py"""
path = "market_lens/ingestion/congress_tracker.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

old = '''            data = resp.json()
            hits = data.get("filteredHits", [])
            total = data.get("hitsTotal", 0)
            print(f"[Lobbying] Page {page_num}: {len(hits)} records (total: {total})")

            if not hits:
                break

            session = _get_session()
            try:
                for hit in hits:
                    try:
                        # Support both flat hit and _source-wrapped response
                        src = hit.get("_source") or hit
                        filing_id = str(hit.get("_id") or "")
                        registration_id = filing_id or ""
                        registrant_name = (src.get("registrantName") or (src.get("registrant") or {}).get("name") or (src.get("registrant") or {}).get("organizationName") or "").strip()
                        client_name = (src.get("clientName") or (src.get("client") or {}).get("name") or "").strip()
                        report_type = src.get("reportType", "")
                        if isinstance(report_type, dict):
                            report_type_str = report_type.get("description", "") or report_type.get("name", "") or ""
                        else:
                            report_type_str = str(report_type or "")
                        report_year = src.get("reportYear", current_year)
                        senate_id = str(src.get("senateId") or "")
                        lobbyist_names = src.get("lobbyistNames") or src.get("lobbyists") or []
                        if not isinstance(lobbyist_names, list):
                            lobbyist_names = [str(lobbyist_names)] if lobbyist_names else []
'''

new = '''            data = resp.json()
            hits = data.get("filteredHits", [])
            total = data.get("hitsTotal", 0)
            print(f"[Lobbying] Page {page_num}: {len(hits)} records (total: {total})")

            if not hits:
                break

            # Diagnostic: print first raw hit once so we can see actual field names
            if page_num == 0 and hits:
                import json as _json
                print("FIRST HIT FULL STRUCTURE:")
                print(_json.dumps(hits[0], indent=2, default=str))

            session = _get_session()
            try:
                for hit in hits:
                    try:
                        # API returns hit with _id at top level and _source containing the document
                        src = hit.get("_source") or hit
                        filing_id = str(hit.get("_id") or "")
                        registration_id = filing_id or ""
                        registrant = src.get("registrant") or {}
                        registrant_name = (registrant.get("name") or registrant.get("organizationName") or src.get("registrantName") or "").strip()
                        client = src.get("client") or {}
                        client_name = (client.get("name") or src.get("clientName") or "").strip()
                        report_type = src.get("reportType", "")
                        if isinstance(report_type, dict):
                            report_type_str = report_type.get("description", "") or report_type.get("name", "") or ""
                        else:
                            report_type_str = str(report_type or "")
                        report_year = src.get("reportYear", current_year)
                        senate_id = str(src.get("senateId") or "")
                        lobbyists_raw = src.get("lobbyists") or src.get("lobbyistNames") or []
                        if not isinstance(lobbyists_raw, list):
                            lobbyists_raw = [lobbyists_raw] if lobbyists_raw else []
                        lobbyist_names = []
                        for lob in lobbyists_raw:
                            if isinstance(lob, dict):
                                lobbyist_names.append(lob.get("fullName") or lob.get("name") or "")
                            else:
                                lobbyist_names.append(str(lob))
                        lobbyist_names = [n for n in lobbyist_names if n]
'''

if old not in content:
    print("OLD block not found - file may already be patched or different")
    raise SystemExit(1)
content = content.replace(old, new, 1)
with open(path, "w", encoding="utf-8") as f:
    f.write(content)
print("Patched congress_tracker.py: diagnostic + _source/lobbyist mapping")
