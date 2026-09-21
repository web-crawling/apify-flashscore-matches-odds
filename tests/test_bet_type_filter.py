"""Offline regression tests for the odds feeds and the "no odds" diagnostics.

Covers two defects and one new feature:

* the field report - a ``betTypes`` filter naming only bet types the match's sport
  does not publish silently produced a match item with no odds and one ambiguous
  log line ("empty menu or all filtered");
* ``has_live_betting`` was hardcoded ``false``;
* the live (in-play) odds feed, which reads ``lobtm``/``ole2`` alongside the
  pre-match ``pobtm``/``ope2`` pair.

Every case runs against saved fixtures (real trimmed responses captured from the
live API) - no network - and asserts *differentially*: the same filter must behave
differently on football vs basketball, ``has_live_betting`` must follow its source
in both directions, and pre-match vs live must produce distinguishable markets.

Run from the actor root:
    .venv/Scripts/python tests/test_bet_type_filter.py
"""

from __future__ import annotations

import contextlib
import copy
import json
import logging
import sys
from pathlib import Path

from scrapy.http import Request, TextResponse
from scrapy.settings import Settings

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.spiders.flashscore_odds import LIVE, PREMATCH, FlashscoreOddsSpider  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
EVENT_ID = "GYoluT5L"

FOOTBALL_TYPES = {"HOME_DRAW_AWAY", "OVER_UNDER", "BOTH_TEAMS_TO_SCORE", "DOUBLE_CHANCE"}
BASKETBALL_TYPES = {"HOME_DRAW_AWAY", "HOME_AWAY", "OVER_UNDER", "ASIAN_HANDICAP"}

failures: list[str] = []


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}{' - ' + detail if detail else ''}")
        failures.append(label)


class LogCapture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    def text(self, level: int | None = None) -> str:
        return "\n".join(r.getMessage() for r in self.records
                         if level is None or r.levelno == level)


def make_spider(bet_types=None, odds_types=(PREMATCH,), geo=("GB", "GB")):
    """Build a spider with its match store seeded, as _yield_match_requests leaves it."""
    spider = FlashscoreOddsSpider()
    spider.settings = Settings({
        "ODDS_REQUESTS": [{"event_id": EVENT_ID,
                           "match_url": f"https://www.flashscore.com/match/?mid={EVENT_ID}"}],
        "BET_TYPES_FILTER": bet_types,
        "ODDS_TYPES": list(odds_types),
    })
    list(spider.start_requests())
    menu_requests = list(spider._yield_match_requests(*geo))
    return spider, menu_requests


def response_for(doc: dict, url: str = "https://global.ds.lsapp.eu/odds/pq_graphql") -> TextResponse:
    return TextResponse(url=url, body=json.dumps(doc).encode("utf-8"),
                        encoding="utf-8", request=Request(url))


@contextlib.contextmanager
def capturing():
    """Capture spider log records, including those emitted while seeding the store."""
    capture = LogCapture()
    logger = logging.getLogger("src.spiders.flashscore_odds")
    logger.addHandler(capture)
    logger.setLevel(logging.INFO)
    try:
        yield capture
    finally:
        logger.removeHandler(capture)


def feed_menu(spider, doc, odds_type):
    """Deliver one menu response; returns the odds requests it produced."""
    with capturing() as capture:
        out = list(spider.parse_menu(response_for(doc), event_id=EVENT_ID, odds_type=odds_type))
    return out, capture


def run_menu(menu_doc, bet_types=None, geo=("GB", "GB"), odds_type=PREMATCH):
    with capturing() as capture:
        spider, _ = make_spider(bet_types, (odds_type,), geo)
        out = list(spider.parse_menu(response_for(menu_doc), event_id=EVENT_ID, odds_type=odds_type))
    return spider, out, capture


def odds_requests(out) -> list:
    return [r for r in out if isinstance(r, Request) and "_hash=" in r.url]


def items(out) -> list:
    return [o for o in out if not isinstance(o, Request)]


# --------------------------------------------------------------------------- #
def test_fixtures_show_sport_specific_bet_types() -> None:
    print("\n[1] fixtures confirm bet types are sport-specific")
    football = {i["bettingType"]
                for i in load("pobtm_football.json")["data"]["getPrematchOddsBettingTypeMenu"]["items"]}
    basketball = {i["bettingType"]
                  for i in load("pobtm_basketball.json")["data"]["getPrematchOddsBettingTypeMenu"]["items"]}
    check("football pre-match menu matches the documented set", football == FOOTBALL_TYPES, str(football))
    check("basketball pre-match menu matches the documented set", basketball == BASKETBALL_TYPES, str(basketball))
    check("ASIAN_HANDICAP is not a football pre-match market",
          "ASIAN_HANDICAP" in basketball and "ASIAN_HANDICAP" not in football)


def test_no_filter_yields_requests() -> None:
    print("\n[2] no betTypes filter -> odds requests generated, no warning")
    _, out, logs = run_menu(load("pobtm_football.json"), None)
    check("odds requests generated", len(odds_requests(out)) > 0, f"got {len(odds_requests(out))}")
    check("no warning logged", logs.text(logging.WARNING) == "", logs.text(logging.WARNING))
    check("resolved geo logged at INFO", "geoIpCode=GB" in logs.text(logging.INFO))


def test_asian_handicap_on_football_is_explained() -> None:
    print("\n[3] betTypes=[ASIAN_HANDICAP] on FOOTBALL -> explained, not silent")
    _, out, logs = run_menu(load("pobtm_football.json"), {"ASIAN_HANDICAP"})
    warning = logs.text(logging.WARNING)
    check("no odds requests (the reported symptom)", odds_requests(out) == [])
    check("a WARNING is raised", warning != "")
    check("warning blames the betTypes filter", "betTypes filter matched no" in warning, warning)
    check("warning names what was requested", "ASIAN_HANDICAP" in warning)
    check("warning names what the match offers", "BOTH_TEAMS_TO_SCORE" in warning, warning)
    check("warning is not the old ambiguous text", "empty menu or all filtered" not in warning)


def test_same_filter_works_on_basketball() -> None:
    print("\n[4] betTypes=[ASIAN_HANDICAP] on BASKETBALL -> requests ARE generated")
    _, out, logs = run_menu(load("pobtm_basketball.json"), {"ASIAN_HANDICAP"})
    check("odds requests generated for basketball", len(odds_requests(out)) > 0)
    check("no filter warning for basketball",
          "betTypes filter matched no" not in logs.text(logging.WARNING))


def test_zero_offer_menu_names_the_region() -> None:
    print("\n[5] menu with no bookmaker offers -> region named, not blamed on filter")
    doc = copy.deepcopy(load("pobtm_football.json"))
    for item in doc["data"]["getPrematchOddsBettingTypeMenu"]["items"]:
        item["bookmakerIds"] = []
    _, out, logs = run_menu(doc, None, geo=("ES", "ES"))
    warning = logs.text(logging.WARNING)
    check("no odds requests", odds_requests(out) == [])
    check("warning names the region", "geoIpCode=ES" in warning, warning)
    check("warning explains bookmakers are regional", "region" in warning.lower())
    check("warning does not blame betTypes", "betTypes filter matched no" not in warning)


def test_absent_menu_names_the_region() -> None:
    print("\n[6] null menu -> region named alongside the invalid-ID hint")
    doc = {"data": {"getPrematchOddsBettingTypeMenu": None}}
    _, out, logs = run_menu(doc, None, geo=("HU", "HU"))
    warning = logs.text(logging.WARNING)
    check("no odds requests", odds_requests(out) == [])
    check("warning names the region", "geoIpCode=HU" in warning, warning)
    check("warning mentions the match ID may be invalid", "match ID may be invalid" in warning)


def _market_flag(live_offers: bool) -> bool:
    doc = copy.deepcopy(load("pobtm_football.json"))
    bookmakers = doc["data"]["getPrematchOddsBettingTypeMenu"]["settings"]["bookmakers"]
    bookmakers[0]["hasLiveBettingOffers"] = live_offers
    bm_id = bookmakers[0]["bookmaker"]["id"]
    spider, _, _ = run_menu(doc, {"HOME_DRAW_AWAY"})
    list(spider.parse_odds(response_for(load("ope2_home_draw_away.json")), event_id=EVENT_ID,
                           bookmaker_id=bm_id, bet_type="HOME_DRAW_AWAY",
                           bet_scope="FULL_TIME", odds_type=PREMATCH))
    markets = spider._match_store[EVENT_ID]["bm_acc"][bm_id]["markets"]
    return markets[(PREMATCH, "HOME_DRAW_AWAY", "FULL_TIME")]["has_live_betting"]


def test_has_live_betting_is_sourced_both_ways() -> None:
    print("\n[7] has_live_betting follows hasLiveBettingOffers (both poles)")
    off, on = _market_flag(False), _market_flag(True)
    check("False when the bookmaker offers no in-play betting", off is False, repr(off))
    check("True when the bookmaker does offer in-play betting", on is True, repr(on))
    check("the field is differential, not hardcoded", off != on)


def test_odds_are_still_parsed() -> None:
    print("\n[8] pre-match odds rows still parse")
    doc = load("pobtm_football.json")
    bm_id = doc["data"]["getPrematchOddsBettingTypeMenu"]["settings"]["bookmakers"][0]["bookmaker"]["id"]
    spider, _, _ = run_menu(doc, {"HOME_DRAW_AWAY"})
    list(spider.parse_odds(response_for(load("ope2_home_draw_away.json")), event_id=EVENT_ID,
                           bookmaker_id=bm_id, bet_type="HOME_DRAW_AWAY",
                           bet_scope="FULL_TIME", odds_type=PREMATCH))
    market = spider._match_store[EVENT_ID]["bm_acc"][bm_id]["markets"][(PREMATCH, "HOME_DRAW_AWAY", "FULL_TIME")]
    selections = {row["selection"] for row in market["odds"]}
    check("HOME/DRAW/AWAY selections parsed", {"HOME", "DRAW", "AWAY"} <= selections, str(selections))
    check("odds values are numeric", all(isinstance(r["odds"], float) for r in market["odds"]))
    check("market is tagged PREMATCH", market["odds_type"] == PREMATCH)


# --------------------------------------------------------------------------- live
def test_live_menu_is_read() -> None:
    print("\n[9] live menu (lobtm) produces live odds requests")
    _, out, logs = run_menu(load("lobtm_football.json"), None, odds_type=LIVE)
    reqs = odds_requests(out)
    check("live odds requests generated", len(reqs) > 0, f"got {len(reqs)}")
    check("requests target the live endpoint", all("_hash=ole2" in r.url for r in reqs),
          reqs[0].url if reqs else "")
    check("no warning", logs.text(logging.WARNING) == "", logs.text(logging.WARNING))


def test_next_goal_is_parsed() -> None:
    print("\n[10] NEXT_GOAL (live-only market) parses, including the NONE outcome")
    spider, _, _ = run_menu(load("lobtm_football.json"), {"NEXT_GOAL"}, odds_type=LIVE)
    bm_id = load("lobtm_football.json")["data"]["getLiveOddsBettingTypeMenu"]["settings"]["bookmakers"][0]["bookmaker"]["id"]
    list(spider.parse_odds(response_for(load("ole2_next_goal.json")), event_id=EVENT_ID,
                           bookmaker_id=bm_id, bet_type="NEXT_GOAL",
                           bet_scope="FULL_TIME", odds_type=LIVE))
    market = spider._match_store[EVENT_ID]["bm_acc"][bm_id]["markets"][(LIVE, "NEXT_GOAL", "FULL_TIME")]
    selections = {row["selection"] for row in market["odds"]}
    check("HOME/NONE/AWAY selections parsed", {"HOME", "NONE", "AWAY"} == selections, str(selections))
    check("NONE is the string 'NONE', never a null", "NONE" in selections and None not in selections)
    check("market is tagged LIVE", market["odds_type"] == LIVE)


def test_every_live_shape_parses() -> None:
    print("\n[11] every captured live market shape yields odds rows")
    from src.spiders.flashscore_odds import _parse_ope2_odds
    for name, bet_type in (("ole2_home_draw_away.json", "HOME_DRAW_AWAY"),
                           ("ole2_over_under.json", "OVER_UNDER"),
                           ("ole2_asian_handicap.json", "ASIAN_HANDICAP"),
                           ("ole2_home_away.json", "HOME_AWAY"),
                           ("ole2_next_goal.json", "NEXT_GOAL")):
        payload = load(name)["data"]["findLiveOddsForBookmaker"]["eventOddsOverview"]
        rows = _parse_ope2_odds(payload)
        check(f"{bet_type} yields odds rows", len(rows) > 0, f"{payload.get('__typename')} -> 0 rows")


def test_price_movement_is_captured_differentially() -> None:
    """Both feeds publish movement; it is null only until a price actually moves."""
    print("\n[12] change_direction/previous_odds captured from both feeds, null when unmoved")
    from src.spiders.flashscore_odds import _parse_ope2_odds
    feeds = {
        "live": _parse_ope2_odds(
            load("ole2_home_draw_away.json")["data"]["findLiveOddsForBookmaker"]["eventOddsOverview"]),
        "pre-match": _parse_ope2_odds(
            load("ope2_home_draw_away.json")["data"]["findPrematchOddsForBookmaker"]),
    }
    for label, rows in feeds.items():
        moved = [r for r in rows if r["change_direction"] in ("UP", "DOWN")]
        check(f"{label} rows capture a price move", len(moved) > 0,
              str([r["change_direction"] for r in rows]))
        check(f"{label} moved rows carry the previous price",
              all(isinstance(r["previous_odds"], float) for r in moved))

    # The differential: within one payload, an unmoved price must stay null rather
    # than inheriting the neighbouring selection's movement.
    unmoved = [r for r in feeds["pre-match"] if r["change_direction"] is None]
    check("an unmoved price yields null movement, not a stale value",
          len(unmoved) > 0 and all(r["previous_odds"] is None for r in unmoved),
          str([(r["selection"], r["change_direction"], r["previous_odds"]) for r in feeds["pre-match"]]))


def test_both_feeds_interleaved_emit_exactly_one_item() -> None:
    """The completion counter must survive menus and odds arriving out of order."""
    print("\n[13] oddsType=both, interleaved -> exactly one item, markets from both feeds")
    spider, menu_reqs = make_spider({"HOME_DRAW_AWAY"}, (PREMATCH, LIVE))
    check("one menu request per feed", len(menu_reqs) == 2, f"got {len(menu_reqs)}")

    emitted = []

    # 1. pre-match menu arrives and ALL its odds come back first.
    out, _ = feed_menu(spider, load("pobtm_football.json"), PREMATCH)
    pre_reqs = odds_requests(out)
    check("pre-match menu produced requests", len(pre_reqs) > 0)
    for r in pre_reqs:
        emitted += items(list(spider.parse_odds(
            response_for(load("ope2_home_draw_away.json")), **r.cb_kwargs)))

    check("NO item emitted while the live menu is still outstanding", emitted == [],
          f"{len(emitted)} item(s) emitted early")

    # 2. live menu arrives late, with its own odds.
    out, _ = feed_menu(spider, load("lobtm_football.json"), LIVE)
    live_reqs = odds_requests(out)
    check("live menu produced requests", len(live_reqs) > 0)
    for r in live_reqs:
        emitted += items(list(spider.parse_odds(
            response_for(load("ole2_home_draw_away.json")), **r.cb_kwargs)))

    check("exactly one item emitted overall", len(emitted) == 1, f"{len(emitted)} items")
    if len(emitted) != 1:
        return
    bookmakers = emitted[0]["bookmakers"]
    feeds = {m["odds_type"] for b in bookmakers for m in b["markets"]}
    check("item carries markets from BOTH feeds", feeds == {PREMATCH, LIVE}, str(feeds))
    check("live market did not overwrite its pre-match twin",
          sum(1 for b in bookmakers for m in b["markets"]) == len(pre_reqs) + len(live_reqs),
          f"{sum(1 for b in bookmakers for m in b['markets'])} markets")


def test_prematch_only_is_unchanged_by_default() -> None:
    print("\n[14] default (no oddsType) still reads pre-match only")
    spider, menu_reqs = make_spider(None)
    check("one menu request", len(menu_reqs) == 1, f"got {len(menu_reqs)}")
    check("it is the pre-match menu", "_hash=pobtm" in menu_reqs[0].url, menu_reqs[0].url)
    check("spider defaults to PREMATCH", spider._odds_types == [PREMATCH], str(spider._odds_types))


def main() -> int:
    for test in (
        test_fixtures_show_sport_specific_bet_types,
        test_no_filter_yields_requests,
        test_asian_handicap_on_football_is_explained,
        test_same_filter_works_on_basketball,
        test_zero_offer_menu_names_the_region,
        test_absent_menu_names_the_region,
        test_has_live_betting_is_sourced_both_ways,
        test_odds_are_still_parsed,
        test_live_menu_is_read,
        test_next_goal_is_parsed,
        test_every_live_shape_parses,
        test_price_movement_is_captured_differentially,
        test_both_feeds_interleaved_emit_exactly_one_item,
        test_prematch_only_is_unchanged_by_default,
    ):
        test()

    print("\n" + "=" * 60)
    if failures:
        print(f"FAILED ({len(failures)}): " + "; ".join(failures))
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
