import requests
import json


def discover_house_ptr_index():
    url = "https://app-pub-pri-elastic.azurewebsites.net/search"
    headers = {
        "Content-Type": "application/json",
        "Origin": "https://disclosures.house.gov",
        "Referer": "https://disclosures.house.gov/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    index_candidates = [
        "financial-disclosures",
        "financial-disclosure",
        "ptr-disclosures",
        "ptr",
        "house-ptr",
        "periodic-transaction-reports",
        "periodic-transactions",
        "stock-disclosures",
        "fd-ptr",
        "member-financial-disclosures",
        "annual-disclosures",
        "annual-financial-disclosures",
        "candidate-disclosures",
        "house-financial-disclosures",
        "house-disclosures",
        "disclosures",
        "member-disclosures",
        "stock-act",
        "stock-act-disclosures",
        "ethics-disclosures",
    ]

    print(f"Testing {len(index_candidates)} index names...\n")

    for index_name in index_candidates:
        payload = {"index": index_name, "size": 3, "from": 0}
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=10)
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    hits = data.get('filteredHits', [])
                    total = data.get('hitsTotal', 0)
                    if total and total > 0:
                        print(f"FOUND DATA: index='{index_name}' | total={total}")
                        if hits:
                            print(f"  Keys: {list(hits[0].keys())}")
                            source = hits[0].get('_source', hits[0])
                            print(f"  Sample: {json.dumps(source, default=str)[:300]}")
                    else:
                        print(f"  '{index_name}': 200 but empty (total={total})")
                except Exception as e:
                    print(f"  '{index_name}': 200 but parse error — {e}")
            else:
                print(f"  '{index_name}': {resp.status_code}")
        except Exception as e:
            print(f"  '{index_name}': ERROR — {e}")


discover_house_ptr_index()
