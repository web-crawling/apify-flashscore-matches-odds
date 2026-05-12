"""Verify the output structure of a real actor run in detail."""
import json
import os
import shutil
import subprocess
from pathlib import Path

ACTOR_DIR = Path(__file__).parent.parent.resolve()
VENV_PYTHON = ACTOR_DIR / ".venv" / "Scripts" / "python.exe"
STORAGE_DIR = ACTOR_DIR / "storage"
KV_DIR = STORAGE_DIR / "key_value_stores" / "default"
DATASET_DIR = STORAGE_DIR / "datasets" / "default"


def clear_and_run(input_data):
    if STORAGE_DIR.exists():
        shutil.rmtree(STORAGE_DIR)
    KV_DIR.mkdir(parents=True, exist_ok=True)
    (KV_DIR / "INPUT.json").write_text(json.dumps(input_data))
    env = os.environ.copy()
    result = subprocess.run(
        [str(VENV_PYTHON), "-m", "src"],
        cwd=str(ACTOR_DIR), env=env, capture_output=True, text=True, timeout=90
    )
    items = []
    if DATASET_DIR.exists():
        for f in sorted(DATASET_DIR.glob("[0-9]*.json")):
            items.append(json.loads(f.read_text()))
    return result, items


print("Running football URL test for detailed validation...")
_, items = clear_and_run({
    "startUrls": [{"url": "https://www.flashscore.com/match/football/arsenal-hA1Zm19f/west-ham-Cxq57r8g/?mid=8Cxbx9Wh"}]
})

assert len(items) == 1, f"Expected 1 item, got {len(items)}"
item = items[0]

print("\n=== Top-level fields ===")
print(f"match_id: {item['match_id']!r} (type: {type(item['match_id']).__name__})")
print(f"match_url: {item['match_url']!r}")
print(f"sport: {item.get('sport')!r}")
print(f"scraped_at: {item['scraped_at']!r}")
print(f"home_team present: {'home_team' in item}")
print(f"away_team present: {'away_team' in item}")
print(f"bookmakers: list of {len(item['bookmakers'])} bookmakers")

print("\n=== scraped_at ISO 8601 check ===")
from datetime import datetime
sat = item["scraped_at"]
# Should be like 2026-05-11T15:18:55.849125+00:00
try:
    parsed = datetime.fromisoformat(sat)
    print(f"  PASS: {sat!r} parses OK, tzinfo={parsed.tzinfo}")
except Exception as e:
    print(f"  FAIL: {e}")

print("\n=== bookmakers[] structure ===")
for i, bm in enumerate(item["bookmakers"]):
    print(f"  bookmaker {i+1}: id={bm['bookmaker_id']!r} (type: {type(bm['bookmaker_id']).__name__}), name={bm['bookmaker_name']!r}, markets={len(bm['markets'])}")
    assert isinstance(bm["bookmaker_id"], int), f"bookmaker_id not int: {bm['bookmaker_id']!r}"
    assert isinstance(bm["bookmaker_name"], str) and bm["bookmaker_name"], "bookmaker_name empty"
    assert isinstance(bm["markets"], list) and len(bm["markets"]) > 0, "markets empty"

print("\n=== Sample market ===")
bm0 = item["bookmakers"][0]
mkt0 = bm0["markets"][0]
print(f"  bet_type: {mkt0['bet_type']!r} (type: {type(mkt0['bet_type']).__name__})")
print(f"  bet_scope: {mkt0['bet_scope']!r} (type: {type(mkt0['bet_scope']).__name__})")
print(f"  has_live_betting: {mkt0['has_live_betting']!r} (type: {type(mkt0['has_live_betting']).__name__})")
print(f"  odds: {len(mkt0['odds'])} entries")
assert isinstance(mkt0["has_live_betting"], bool), "has_live_betting not bool"

print("\n=== Sample odds entries ===")
for odd in mkt0["odds"][:3]:
    print(f"  selection={odd.get('selection')!r}, odds={odd.get('odds')!r} ({type(odd.get('odds')).__name__}), "
          f"opening_odds={odd.get('opening_odds')!r}, handicap={odd.get('handicap')!r}, "
          f"is_active={odd.get('is_active')!r} ({type(odd.get('is_active')).__name__})")
    assert isinstance(odd.get("odds"), float), f"odds not float: {odd.get('odds')!r}"
    assert isinstance(odd.get("is_active"), bool), f"is_active not bool: {odd.get('is_active')!r}"
    assert "opening_odds" in odd, "opening_odds key absent"
    assert "handicap" in odd, "handicap key absent"
    assert "selection" in odd and odd["selection"], "selection missing"

# Check opening_odds presence
has_opening = any(
    odd.get("opening_odds") is not None
    for bm in item["bookmakers"]
    for mkt in bm["markets"]
    for odd in mkt["odds"]
)
print(f"\n=== opening_odds: at least one non-null: {has_opening} ===")
assert has_opening, "No opening_odds found in any odd"

# Check handicap on OVER_UNDER
ou_markets = [
    (bm, mkt)
    for bm in item["bookmakers"]
    for mkt in bm["markets"]
    if mkt["bet_type"] == "OVER_UNDER"
]
if ou_markets:
    bm, mkt = ou_markets[0]
    has_handicap = any(odd.get("handicap") is not None for odd in mkt["odds"])
    print(f"=== OVER_UNDER handicap (bm={bm['bookmaker_name']}): has non-null handicap: {has_handicap} ===")
    assert has_handicap, "OVER_UNDER should have handicap values"
    print(f"  sample: {mkt['odds'][0]}")

print("\n=== ALL STRUCTURE CHECKS PASSED ===")
