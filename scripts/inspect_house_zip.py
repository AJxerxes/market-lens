import requests
import zipfile
import io


headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}


for year in ["2025", "2026"]:
    url = f"https://disclosures-clerk.house.gov/public_disc/financial-pdfs/{year}FD.zip"
    print(f"\n=== {year} zip ===")
    resp = requests.get(url, headers=headers, timeout=30)
    print(f"Status: {resp.status_code} | Size: {len(resp.content)} bytes")
    if resp.status_code == 200:
        z = zipfile.ZipFile(io.BytesIO(resp.content))
        names = z.namelist()
        print(f"Files in zip: {len(names)}")
        for n in names[:10]:
            print(f"  {n}")
        xml_files = [n for n in names if n.lower().endswith(".xml")]
        if xml_files:
            first_xml = z.read(xml_files[0]).decode("utf-8", errors="replace")
            print(f"\nFirst XML: {xml_files[0]}")
            print(f"Preview:\n{first_xml[:1000]}")

