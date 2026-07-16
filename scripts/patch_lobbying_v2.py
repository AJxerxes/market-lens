"""Patch ingest_lobbying_registrations: _source mapping + 2-year skip. Run from repo root."""
path = "market_lens/ingestion/congress_tracker.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

old_loop = '''            # Diagnostic: print first raw hit once so we can see actual field names
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

                        if not registrant_name or not client_name:
                            skipped += 1
                            continue

                        if not registration_id:
                            skipped += 1
                            continue

                        existing = session.query(LobbyingRegistration).filter_by(
                            registration_id=registration_id
                        ).first()

                        if existing:
                            skipped += 1
                            continue

                        report_year_int = int(report_year) if str(report_year).isdigit() else current_year
                        filing_date_val = date(report_year_int, 1, 1)
                        reg = LobbyingRegistration(
                            registration_id=registration_id,
                            filing_id=filing_id,
                            registrant_name=registrant_name,
                            client_name=client_name,
                            filing_date=filing_date_val,
                            covered_officials=None,
                            sector_keywords=None,
                            lobbying_activities={"report_type": report_type_str, "lobbyist_names": lobbyist_names},
                            committee_match=False,
                            flagged=False,
                            senate_id=senate_id or None,
                            source="house_clerk_elastic"
                        )
                        session.add(reg)
                        inserted += 1

                    except Exception as e:
                        print(f"[Lobbying] Row error: {hit.get('_id', 'unknown')} — {e}")
                        skipped += 1
                        continue'''

new_loop = '''            session = _get_session()
            try:
                for hit in hits:
                    try:
                        filing_id = str(hit.get("_id", ""))
                        registration_id = filing_id

                        if not filing_id:
                            skipped += 1
                            continue

                        source = hit.get("_source", {})

                        # Registrant name
                        registrant = source.get("registrant", {})
                        registrant_name = (
                            registrant.get("name")
                            or registrant.get("organizationName")
                            or f"{registrant.get('firstName', '')} {registrant.get('lastName', '')}".strip()
                        ).strip()

                        # Client name
                        client = source.get("client", {})
                        client_name = (client.get("name") or "").strip()

                        # Report type
                        report_type_obj = source.get("reportType", {})
                        if isinstance(report_type_obj, dict):
                            report_type_str = report_type_obj.get("description") or report_type_obj.get("name") or ""
                        else:
                            report_type_str = str(report_type_obj)

                        # Year — skip records older than 2 years
                        report_year = source.get("reportYear", str(current_year))
                        report_year_int = int(report_year) if str(report_year).isdigit() else 0
                        if report_year_int < current_year - 1:
                            skipped += 1
                            continue

                        # Senate ID
                        senate_id = source.get("senateId", "")

                        # Lobbyists
                        lobbyists = source.get("lobbyists", [])
                        lobbyist_names = ", ".join([
                            l.get("fullName") or f"{l.get('firstName', '')} {l.get('lastName', '')}".strip()
                            for l in lobbyists if isinstance(l, dict)
                        ])

                        # Issue areas as sector keywords (store as list for JSON column)
                        issue_areas = source.get("issueAreaCodes", [])
                        sector_keywords = [
                            i.get("description", "") for i in issue_areas if isinstance(i, dict) and i.get("description")
                        ]

                        if not registrant_name or not client_name:
                            skipped += 1
                            continue

                        existing = session.query(LobbyingRegistration).filter_by(
                            registration_id=registration_id
                        ).first()

                        if existing:
                            skipped += 1
                            continue

                        filing_date_val = date(report_year_int, 1, 1)
                        reg = LobbyingRegistration(
                            registration_id=registration_id,
                            registrant_name=registrant_name,
                            client_name=client_name,
                            filing_date=filing_date_val,
                            covered_officials=None,
                            sector_keywords=sector_keywords or None,
                            lobbying_activities={
                                "report_type": report_type_str,
                                "lobbyist_names": lobbyist_names,
                                "senate_id": senate_id,
                                "source": "house_clerk_elastic",
                            },
                            committee_match=False,
                            flagged=False,
                        )
                        session.add(reg)
                        inserted += 1

                    except Exception as e:
                        print(f"[Lobbying] Row error: {hit.get('_id', 'unknown')} — {e}")
                        skipped += 1
                        continue'''

if old_loop not in content:
    print("OLD block not found")
    raise SystemExit(1)
content = content.replace(old_loop, new_loop, 1)
with open(path, "w", encoding="utf-8") as f:
    f.write(content)
print("Patched: lobbying _source mapping + 2-year skip")
