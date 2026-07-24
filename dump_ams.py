"""Quick script to dump raw MARS API response so we can see field names.
Run from your terminal: uv run python dump_ams.py
"""
import httpx
import os
import json
from dotenv import load_dotenv

load_dotenv()
key = os.environ["MARS_API_KEY"]

# Try lastReports=5 to get more rows — lastReports=1 may only return the header.
resp = httpx.get(
    "https://marsapi.ams.usda.gov/services/v1.2/reports/2390",
    params={"lastReports": 5},
    auth=(key, ""),
    timeout=30,
)
print(f"HTTP {resp.status_code}")
data = resp.json()

stats = data.get("stats", {})
print(f"stats: {json.dumps(stats, indent=2)}")
print(f"reportSections: {data.get('reportSections')}")
print(f"num results: {len(data.get('results', []))}")
print()

# Print first 3 result rows in full so we can see every field name
for i, row in enumerate(data.get("results", [])[:3]):
    print(f"===== ROW {i} =====")
    print(json.dumps(row, indent=2))
    print()

# Save full response to a fixture file
with open("tests/fixtures/ams_2390_raw.json", "w") as f:
    json.dump(data, f, indent=2)
print(f"Full response saved to tests/fixtures/ams_2390_raw.json")
