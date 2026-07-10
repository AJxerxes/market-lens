"""
Brute-force discover the PTR (Periodic Transaction Report) index name for House financial disclosures.
The lobbying endpoint is confirmed: POST app-pub-pri-elastic.azurewebsites.net/search with index='lobbying-disclosures'.
Try likely index names on the same endpoint.
"""
import json
import requests

def discover_ptr_index():
    url = "https://app-pub-pri-elastic.azurewebsites.net/search"
    headers = {
        "Content-Type": "application/json",
        "Origin": "https://disclosures.house.gov",
        "Referer": "https://disclosures.house.gov/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
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
    ]

    base_payload = {
        "term": "",
        "aggregations": [],
        "filters": [],
        "size": 3,
        "sort": [{"_score": True}],
    }

    for index_name in index_candidates:
        payload = {**base_payload, "index": index_name}
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=10)
            status = resp.status_code
            if status == 200:
                try:
                    data = resp.json()
                    hits = data.get("filteredHits", [])
                    total = data.get("hitsTotal", 0)
                    if hits and total > 0:
                        print(f"\n✓ FOUND DATA: index='{index_name}' | total={total}")
                        print(f"  First record keys: {list(hits[0].keys())}")
                        print(f"  First record: {json.dumps(hits[0], default=str)[:400]}")
                    else:
                        print(f"  index='{index_name}': 200 but empty ({total} total)")
                except Exception:
                    print(f"  index='{index_name}': 200 but not JSON — {resp.text[:100]}")
            else:
                print(f"  index='{index_name}': {status}")
        except Exception as e:
            print(f"  index='{index_name}': ERROR {e}")


if __name__ == "__main__":
    discover_ptr_index()
