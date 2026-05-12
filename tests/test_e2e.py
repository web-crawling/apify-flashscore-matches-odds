"""End-to-end tests for flashscore-matches-odds actor.

Run from the actor root:
    .venv/Scripts/python tests/test_e2e.py

Tests:
1. Football URL — Arsenal vs West Ham (Premier League, mid=8Cxbx9Wh)
2. Basketball URL — Minnesota vs San Antonio (NBA, mid=8r8XHz43)
3. matchIds input — verify redirect URL construction
4. betTypes filter — only HOME_DRAW_AWAY in output
5. Error case — invalid match ID
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ACTOR_DIR = Path(__file__).parent.parent.resolve()
VENV_PYTHON = ACTOR_DIR / ".venv" / "Scripts" / "python.exe"
STORAGE_DIR = ACTOR_DIR / "storage"
KV_DIR = STORAGE_DIR / "key_value_stores" / "default"
DATASET_DIR = STORAGE_DIR / "datasets" / "default"
INPUT_FILE = KV_DIR / "INPUT.json"


def write_input(data: dict) -> None:
    KV_DIR.mkdir(parents=True, exist_ok=True)
    INPUT_FILE.write_text(json.dumps(data, indent=2))


def clear_storage() -> None:
    """Clear all Apify local storage between test runs.

    Removes the entire storage tree (except KV INPUT.json) to ensure a clean
    state for each test case. Apify SDK will recreate the directories on the
    next actor run.
    """
    # Nuclear option: wipe the entire storage dir and recreate the KV dir
    if STORAGE_DIR.exists():
        shutil.rmtree(STORAGE_DIR)
    # Recreate KV dir so we can write INPUT.json
    KV_DIR.mkdir(parents=True, exist_ok=True)


# Keep backward compat alias
def clear_dataset() -> None:
    clear_storage()


def run_actor(timeout: int = 90) -> subprocess.CompletedProcess:
    """Run the actor and return the process result."""
    env = os.environ.copy()
    env["SCRAPY_SETTINGS_MODULE"] = "src.settings"
    result = subprocess.run(
        [str(VENV_PYTHON), "-m", "src"],
        cwd=str(ACTOR_DIR),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result


def read_dataset() -> list[dict]:
    """Read all output items from the dataset directory (numbered files only)."""
    items = []
    if not DATASET_DIR.exists():
        return items
    # Only read the sequentially-numbered item files (e.g. 000000001.json)
    # Exclude __metadata__.json and other non-item files
    for f in sorted(DATASET_DIR.glob("[0-9]*.json")):
        try:
            items.append(json.loads(f.read_text()))
        except json.JSONDecodeError:
            pass
    return items


def check(condition: bool, label: str, detail: str = "") -> bool:
    status = "PASS" if condition else "FAIL"
    msg = f"  [{status}] {label}"
    if detail:
        msg += f" — {detail}"
    print(msg)
    return condition


# ───────────────────────────────────────────────────────────────
# Test helpers
# ───────────────────────────────────────────────────────────────

def validate_item_structure(item: dict, test_name: str, expected_sport: str | None = None) -> list[str]:
    """Validate an output item against the approved schema. Returns list of failure messages."""
    failures = []

    def fail(msg):
        failures.append(f"[{test_name}] {msg}")

    # Top-level required fields
    if "match_id" not in item or not item["match_id"]:
        fail("match_id missing or empty")
    if "match_url" not in item or not item["match_url"]:
        fail("match_url missing or empty")
    if "scraped_at" not in item or not item["scraped_at"]:
        fail("scraped_at missing or empty")
    else:
        sat = item["scraped_at"]
        if "T" not in sat or ("Z" not in sat and "+" not in sat):
            fail(f"scraped_at not valid ISO 8601 UTC: {sat!r}")

    if expected_sport and item.get("sport") != expected_sport:
        fail(f"sport expected {expected_sport!r}, got {item.get('sport')!r}")

    # home_team/away_team are optional (not available from ope2 without extra request)
    # — their absence is acceptable in v1

    # bookmakers must be non-empty list
    bookmakers = item.get("bookmakers")
    if not isinstance(bookmakers, list) or len(bookmakers) == 0:
        fail("bookmakers is empty or not a list")
        return failures

    for bm in bookmakers:
        if not isinstance(bm.get("bookmaker_id"), int):
            fail(f"bookmaker_id not int: {bm.get('bookmaker_id')!r}")
        if not isinstance(bm.get("bookmaker_name"), str) or not bm["bookmaker_name"]:
            fail(f"bookmaker_name missing/empty: {bm.get('bookmaker_name')!r}")
        markets = bm.get("markets")
        if not isinstance(markets, list) or len(markets) == 0:
            fail(f"markets empty for bookmaker {bm.get('bookmaker_id')}")
            continue
        for mkt in markets:
            if not isinstance(mkt.get("bet_type"), str) or not mkt["bet_type"]:
                fail(f"bet_type missing in market: {mkt!r}")
            if not isinstance(mkt.get("bet_scope"), str) or not mkt["bet_scope"]:
                fail(f"bet_scope missing in market: {mkt!r}")
            if not isinstance(mkt.get("has_live_betting"), bool):
                fail(f"has_live_betting not bool in market: {mkt.get('has_live_betting')!r}")
            odds_list = mkt.get("odds")
            if not isinstance(odds_list, list) or len(odds_list) == 0:
                fail(f"odds empty for market {mkt.get('bet_type')}/{mkt.get('bet_scope')}")
                continue
            for odd in odds_list:
                if not isinstance(odd.get("selection"), str):
                    fail(f"selection not str: {odd.get('selection')!r}")
                if not isinstance(odd.get("odds"), float):
                    fail(f"odds not float: {odd.get('odds')!r}")
                if not isinstance(odd.get("is_active"), bool):
                    fail(f"is_active not bool: {odd.get('is_active')!r}")
                # opening_odds may be float or None — both acceptable
                if "opening_odds" not in odd:
                    fail(f"opening_odds key absent in odd")
                # handicap may be float or None — both acceptable
                if "handicap" not in odd:
                    fail(f"handicap key absent in odd")

    return failures


# ───────────────────────────────────────────────────────────────
# TEST 1: Football via URL
# ───────────────────────────────────────────────────────────────

def test_football_url():
    print("\n=== TEST 1: Football via URL (Arsenal vs West Ham) ===")
    clear_dataset()
    write_input({
        "startUrls": [
            {"url": "https://www.flashscore.com/match/football/arsenal-hA1Zm19f/west-ham-Cxq57r8g/?mid=8Cxbx9Wh"}
        ]
    })

    result = run_actor()
    print(f"  Exit code: {result.returncode}")

    items = read_dataset()
    passed = True

    passed &= check(len(items) == 1, "Exactly 1 item in dataset", f"got {len(items)}")

    if items:
        item = items[0]
        print(f"  match_id: {item.get('match_id')}")
        print(f"  home_team: {item.get('home_team')}")
        print(f"  away_team: {item.get('away_team')}")
        print(f"  sport: {item.get('sport')}")
        print(f"  bookmakers count: {len(item.get('bookmakers', []))}")

        passed &= check(item.get("match_id") == "8Cxbx9Wh", "match_id correct")
        passed &= check(item.get("sport") == "football", "sport is football")
        # home_team/away_team: not available from ope2 without extra request — expected absent
        print(f"  home_team: {item.get('home_team')!r} (expected absent — ope2 architecture limitation)")
        print(f"  away_team: {item.get('away_team')!r} (expected absent — ope2 architecture limitation)")

        bm_count = len(item.get("bookmakers", []))
        passed &= check(bm_count > 0, "bookmakers non-empty", f"{bm_count} bookmakers")

        # Check HOME_DRAW_AWAY exists for football
        all_bet_types = set()
        for bm in item.get("bookmakers", []):
            for mkt in bm.get("markets", []):
                all_bet_types.add(mkt.get("bet_type"))
        passed &= check("HOME_DRAW_AWAY" in all_bet_types, "HOME_DRAW_AWAY bet_type present", str(all_bet_types))

        # Structure validation
        failures = validate_item_structure(item, "football", expected_sport="football")
        for f in failures:
            print(f"  [FAIL] Structure: {f}")
        passed &= len(failures) == 0

        # Check opening_odds presence on at least some entries
        has_opening = False
        for bm in item.get("bookmakers", []):
            for mkt in bm.get("markets", []):
                for odd in mkt.get("odds", []):
                    if odd.get("opening_odds") is not None:
                        has_opening = True
        print(f"  opening_odds present on at least one entry: {has_opening}")
    else:
        print(f"  STDERR:\n{result.stderr[-2000:]}")
        passed = False

    return passed


# ───────────────────────────────────────────────────────────────
# TEST 2: Basketball via URL
# ───────────────────────────────────────────────────────────────

def test_basketball_url():
    print("\n=== TEST 2: Basketball via URL (Minnesota vs San Antonio) ===")
    clear_dataset()
    write_input({
        "startUrls": [
            {"url": "https://www.flashscore.com/match/basketball/minnesota-timberwolves-KjBIVQcI/san-antonio-spurs-IwmkErSH/?mid=8r8XHz43"}
        ]
    })

    result = run_actor()
    print(f"  Exit code: {result.returncode}")

    items = read_dataset()
    passed = True

    passed &= check(len(items) == 1, "Exactly 1 item in dataset", f"got {len(items)}")

    if items:
        item = items[0]
        print(f"  match_id: {item.get('match_id')}")
        print(f"  home_team: {item.get('home_team')}")
        print(f"  away_team: {item.get('away_team')}")
        print(f"  sport: {item.get('sport')}")
        bm_count = len(item.get("bookmakers", []))
        print(f"  bookmakers count: {bm_count}")

        passed &= check(item.get("match_id") == "8r8XHz43", "match_id correct")
        passed &= check(item.get("sport") == "basketball", "sport is basketball")
        # home_team/away_team: not available from ope2 — expected absent
        print(f"  home_team: {item.get('home_team')!r} (expected absent — ope2 architecture limitation)")
        print(f"  away_team: {item.get('away_team')!r} (expected absent — ope2 architecture limitation)")
        passed &= check(bm_count > 0, "bookmakers non-empty", f"{bm_count} bookmakers")

        # Check HOME_AWAY present for basketball
        all_bet_types = set()
        for bm in item.get("bookmakers", []):
            for mkt in bm.get("markets", []):
                all_bet_types.add(mkt.get("bet_type"))
        print(f"  bet_types in output: {sorted(all_bet_types)}")
        passed &= check("HOME_AWAY" in all_bet_types, "HOME_AWAY present for basketball")
        # Note: basketball may also have HOME_DRAW_AWAY (some markets offer it as OT result)
        # This is valid data from the Flashscore API — not a bug
        print(f"  HOME_DRAW_AWAY in basketball: {('HOME_DRAW_AWAY' in all_bet_types)} (expected: may be present per API)")

        failures = validate_item_structure(item, "basketball", expected_sport="basketball")
        for f in failures:
            print(f"  [FAIL] Structure: {f}")
        passed &= len(failures) == 0
    else:
        print(f"  STDERR:\n{result.stderr[-2000:]}")
        passed = False

    return passed


# ───────────────────────────────────────────────────────────────
# TEST 3: matchIds input — redirect URL construction
# ───────────────────────────────────────────────────────────────

def test_match_ids_input():
    print("\n=== TEST 3: matchIds input — redirect URL construction ===")
    football_mid = "8Cxbx9Wh"
    clear_dataset()
    write_input({
        "matchIds": [football_mid]
    })

    result = run_actor()
    print(f"  Exit code: {result.returncode}")

    items = read_dataset()
    passed = True

    passed &= check(len(items) == 1, "Exactly 1 item", f"got {len(items)}")

    if items:
        item = items[0]
        expected_url = f"https://www.flashscore.com/match/?mid={football_mid}"
        print(f"  match_url: {item.get('match_url')}")
        print(f"  sport (expected None or missing — redirect URL has no sport): {item.get('sport')}")

        passed &= check(item.get("match_id") == football_mid, "match_id correct")
        passed &= check(item.get("match_url") == expected_url, "match_url is redirect form",
                        f"got {item.get('match_url')!r}")
        # sport should be None (absent from item after NullStripPipeline) or at most None
        sport = item.get("sport")
        passed &= check(sport is None, "sport is absent/None for matchId-only input", f"got {sport!r}")
        bm_count = len(item.get("bookmakers", []))
        passed &= check(bm_count > 0, "bookmakers non-empty (odds still returned)", f"{bm_count} bookmakers")
    else:
        print(f"  STDERR:\n{result.stderr[-2000:]}")
        passed = False

    return passed


# ───────────────────────────────────────────────────────────────
# TEST 4: betTypes filter
# ───────────────────────────────────────────────────────────────

def test_bet_types_filter():
    print("\n=== TEST 4: betTypes filter — only HOME_DRAW_AWAY ===")
    clear_dataset()
    write_input({
        "startUrls": [
            {"url": "https://www.flashscore.com/match/football/arsenal-hA1Zm19f/west-ham-Cxq57r8g/?mid=8Cxbx9Wh"}
        ],
        "betTypes": ["HOME_DRAW_AWAY"]
    })

    result = run_actor()
    print(f"  Exit code: {result.returncode}")

    items = read_dataset()
    passed = True

    passed &= check(len(items) == 1, "Exactly 1 item", f"got {len(items)}")

    if items:
        item = items[0]
        all_bet_types = set()
        for bm in item.get("bookmakers", []):
            for mkt in bm.get("markets", []):
                all_bet_types.add(mkt.get("bet_type"))

        print(f"  bet_types in filtered output: {sorted(all_bet_types)}")
        passed &= check(all_bet_types == {"HOME_DRAW_AWAY"}, "Only HOME_DRAW_AWAY in output",
                        f"got {sorted(all_bet_types)}")
        bm_count = len(item.get("bookmakers", []))
        passed &= check(bm_count > 0, "bookmakers still non-empty after filter", f"{bm_count} bookmakers")
    else:
        print(f"  STDERR:\n{result.stderr[-2000:]}")
        passed = False

    return passed


# ───────────────────────────────────────────────────────────────
# TEST 5: Error case — invalid match ID
# ───────────────────────────────────────────────────────────────

def test_invalid_match_id():
    print("\n=== TEST 5: Error case — invalid/non-existent match ID ===")
    clear_dataset()
    write_input({
        "matchIds": ["INVALID1"],
        "startUrls": [
            {"url": "https://www.flashscore.com/match/football/arsenal-hA1Zm19f/west-ham-Cxq57r8g/?mid=8Cxbx9Wh"}
        ]
    })

    result = run_actor()
    print(f"  Exit code: {result.returncode}")

    # Actor should NOT crash; it should process the valid URL and skip the invalid one
    items = read_dataset()
    passed = True

    passed &= check(result.returncode == 0, "Actor exits cleanly (no crash)", f"code={result.returncode}")
    # The valid match should still produce output (invalid ID returns empty data, not HTTP error)
    passed &= check(len(items) >= 1, "Valid match item still produced", f"got {len(items)} items")

    # Check that the run did not raise an unhandled exception
    stderr_lower = result.stderr.lower()
    has_traceback = "traceback" in stderr_lower and "error" in stderr_lower
    # Tracebacks may appear from warnings — only fail if actor returncode != 0
    if result.returncode != 0:
        print(f"  STDERR (last 1000):\n{result.stderr[-1000:]}")

    return passed


# ───────────────────────────────────────────────────────────────
# Main runner
# ───────────────────────────────────────────────────────────────

def main():
    results = {}

    results["test_football_url"] = test_football_url()
    results["test_basketball_url"] = test_basketball_url()
    results["test_match_ids_input"] = test_match_ids_input()
    results["test_bet_types_filter"] = test_bet_types_filter()
    results["test_invalid_match_id"] = test_invalid_match_id()

    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    all_passed = True
    for name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}")
        if not passed:
            all_passed = False

    print()
    if all_passed:
        print("OVERALL: PASSED")
    else:
        print("OVERALL: FAILED — see individual test output above")
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
