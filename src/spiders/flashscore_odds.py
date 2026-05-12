"""Spider for fetching match betting odds from Flashscore.

Request flow (revised after API investigation — oce endpoint is no longer active):

1. One GET to flashscore.com homepage → acquires the ``geolocation`` cookie used
   to build geo-aware ``pobtm`` menu requests.
2. One ``pobtm`` request per match → returns bookmaker list + available bet types.
3. One ``ope2`` request per (match × bookmaker × bet_type × bet_scope) → returns
   the actual odds for that combination.

Item assembly: each ``parse_odds`` callback writes into a spider-level dict
(``_match_store``) keyed by event_id. When the final ope2 response for a match
arrives, the item is yielded. A counter (``pending``) tracks how many ope2 requests
are still outstanding for each match.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from urllib.parse import urlparse, unquote

import scrapy

from src.helpers.jmes import Jmes
from src.itemloaders import MatchOddsItemLoader

logger = logging.getLogger(__name__)

FS_HOME = "https://www.flashscore.com/"

POBTM_URL = (
    "https://global.ds.lsapp.eu/odds/pq_graphql"
    "?_hash=pobtm&eventId={event_id}&projectId=2"
    "&geoIpCode={geo_code}&geoIpSubdivisionCode={geo_sub}"
)

OPE2_URL = (
    "https://global.ds.lsapp.eu/odds/pq_graphql"
    "?_hash=ope2&eventId={event_id}&bookmakerId={bookmaker_id}"
    "&betType={bet_type}&betScope={bet_scope}"
)

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.flashscore.com/",
    "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not.A/Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
}


def _extract_sport_from_url(match_url: str | None) -> str | None:
    if not match_url:
        return None
    try:
        path = urlparse(match_url).path
        parts = [p for p in path.split("/") if p]
        if len(parts) >= 2 and parts[0] == "match":
            candidate = parts[1]
            if not candidate.startswith("?"):
                return candidate
    except Exception:
        pass
    return None


def _parse_geo_cookie(cookie_value: str) -> tuple[str, str]:
    """Parse the ``geolocation`` cookie into (geoIpCode, geoIpSubdivisionCode).

    Cookie format: ``CC;S`` where CC=country, S=subdivision letter.
    e.g. ``RO;B`` → (``RO``, ``ROB``)
    """
    decoded = unquote(cookie_value)
    parts = decoded.split(";")
    country = parts[0].strip() if parts else "GB"
    subdivision = parts[1].strip() if len(parts) > 1 else ""
    geo_sub = f"{country}{subdivision}" if subdivision else country
    return country, geo_sub


def _parse_ope2_odds(fp_data: dict) -> list[dict]:
    """Convert a ``findPrematchOddsForBookmaker`` dict into a list of odd-row dicts.

    Response structure varies by __typename:
    - HOME_DRAW_AWAY / HOME_AWAY / DRAW_NO_BET  → {home, draw?, away}
    - OVER_UNDER / ASIAN_HANDICAP / EUROPEAN_HANDICAP → {opportunities[{...}]}
    - DOUBLE_CHANCE  → {homeOrDraw, awayOrDraw, noDraw}
    - BOTH_TEAMS_TO_SCORE → {yes, no}
    """

    def _item(sel: str, raw: dict, handicap_dict: dict | None = None) -> dict:
        try:
            odds_v = float(raw["value"]) if raw.get("value") is not None else None
        except (ValueError, TypeError):
            odds_v = None
        try:
            opening_v = float(raw["opening"]) if raw.get("opening") is not None else None
        except (ValueError, TypeError):
            opening_v = None
        hv = None
        if isinstance(handicap_dict, dict):
            try:
                hv = float(handicap_dict["value"]) if handicap_dict.get("value") is not None else None
            except (ValueError, TypeError):
                hv = None
        return {
            "selection": sel,
            "odds": odds_v,
            "opening_odds": opening_v,
            "handicap": hv,
            "is_active": bool(raw.get("active")),
        }

    rows: list[dict] = []
    typename = fp_data.get("__typename", "")

    if typename in ("EventOddsOverviewHomeDrawAway",):
        for sel, key in [("HOME", "home"), ("DRAW", "draw"), ("AWAY", "away")]:
            if key in fp_data:
                rows.append(_item(sel, fp_data[key]))

    elif typename in ("EventOddsOverviewHomeAway", "EventOddsOverviewDrawNoBet"):
        for sel, key in [("HOME", "home"), ("AWAY", "away")]:
            if key in fp_data:
                rows.append(_item(sel, fp_data[key]))

    elif typename == "EventOddsOverviewDoubleChance":
        mapping = [("HOME_OR_DRAW", "homeOrDraw"), ("AWAY_OR_DRAW", "awayOrDraw"), ("NO_DRAW", "noDraw")]
        for sel, key in mapping:
            if key in fp_data:
                rows.append(_item(sel, fp_data[key]))

    elif typename == "EventOddsOverviewBothTeamsToScore":
        for sel, key in [("YES", "yes"), ("NO", "no")]:
            if key in fp_data:
                rows.append(_item(sel, fp_data[key]))

    elif typename in (
        "EventOddsOverviewOverUnder",
        "EventOddsOverviewAsianHandicap",
        "EventOddsOverviewEuropeanHandicap",
    ):
        for opp in fp_data.get("opportunities") or []:
            hc = opp.get("handicap")
            if "over" in opp:
                rows.append(_item("OVER", opp["over"], hc))
                if "under" in opp:
                    rows.append(_item("UNDER", opp["under"], hc))
            elif "home" in opp:
                rows.append(_item("HOME", opp["home"], hc))
                if "away" in opp:
                    rows.append(_item("AWAY", opp["away"], hc))

    return rows


class FlashscoreOddsSpider(scrapy.Spider):
    name = "flashscore_odds"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._bet_types_filter: set[str] | None = None
        # Per-match accumulator: {event_id: {pending: int, bm_acc: {bm_id: {name, markets}}, ...}}
        self._match_store: dict[str, dict] = {}

    async def start(self):
        """Scrapy 2.13+ async entry point — delegates to start_requests() for compatibility."""
        async for item in super().start():
            yield item

    def start_requests(self):
        self._bet_types_filter = self.settings.get("BET_TYPES_FILTER") or None
        # Homepage request to pick up the geolocation cookie
        yield scrapy.Request(
            url=FS_HOME,
            callback=self.parse_home,
            errback=self.errback_home,
            headers=BROWSER_HEADERS,
            dont_filter=True,
        )

    def parse_home(self, response):
        """Read geolocation cookie; yield one pobtm request per match."""
        geo_code, geo_sub = "GB", "GB"

        for ck in response.headers.getlist("Set-Cookie"):
            ck_str = ck.decode("utf-8", errors="ignore") if isinstance(ck, bytes) else str(ck)
            if "geolocation=" in ck_str:
                start = ck_str.find("geolocation=") + len("geolocation=")
                end = ck_str.find(";", start)
                raw = ck_str[start:end] if end != -1 else ck_str[start:]
                geo_code, geo_sub = _parse_geo_cookie(raw)
                logger.info("geolocation cookie: %s → code=%s sub=%s", raw, geo_code, geo_sub)
                break
        else:
            logger.warning("geolocation not found in Set-Cookie; using default GB/GB")

        yield from self._yield_match_requests(geo_code, geo_sub)

    def _yield_match_requests(self, geo_code: str, geo_sub: str):
        """Initialise per-match state and yield one pobtm request per match."""
        odds_requests = self.settings.get("ODDS_REQUESTS", [])
        for req_info in odds_requests:
            event_id = req_info["event_id"]
            match_url = req_info.get("match_url")
            sport = _extract_sport_from_url(match_url)
            self._match_store[event_id] = {
                "match_id": event_id,
                "match_url": match_url,
                "sport": sport,
                "bm_acc": {},
                "pending": 0,
            }
            url = POBTM_URL.format(event_id=event_id, geo_code=geo_code, geo_sub=geo_sub)
            yield scrapy.Request(
                url=url,
                callback=self.parse_menu,
                errback=self.errback_menu,
                headers=BROWSER_HEADERS,
                cb_kwargs={"event_id": event_id},
                dont_filter=True,
            )

    def parse_menu(self, response, event_id: str):
        """Parse pobtm menu; yield ope2 requests for each bookmaker×betType×betScope."""
        store = self._match_store.get(event_id)
        if store is None:
            return

        try:
            data = Jmes(response.text)
        except Exception as e:
            logger.warning("Failed to parse pobtm for %s: %s", event_id, e)
            yield from self._finalize(event_id)
            return

        menu = data.select_dict("data.getPrematchOddsBettingTypeMenu", default={})
        if not menu:
            logger.info("No odds menu for event_id=%s — may be invalid match ID", event_id)
            yield from self._finalize(event_id)
            return

        # Build bookmaker name lookup
        for bm_entry in data.select_list("data.getPrematchOddsBettingTypeMenu.settings.bookmakers", default=[]):
            bm = bm_entry.get("bookmaker") or {}
            bm_id = bm.get("id")
            if bm_id is not None:
                bm_id_int = int(bm_id)
                store["bm_acc"].setdefault(bm_id_int, {
                    "name": str(bm.get("name") or bm_id),
                    "markets": {},
                })

        # Build list of (betType, betScope, [bookmaker_ids]) combos
        ope2_requests: list[dict] = []
        for item in data.select_list("data.getPrematchOddsBettingTypeMenu.items", default=[]):
            bet_type = item.get("bettingType") or ""
            bet_scope = item.get("bettingScope") or ""
            if not bet_type or not bet_scope:
                continue
            if self._bet_types_filter and bet_type not in self._bet_types_filter:
                continue
            for bm_id in (item.get("bookmakerIds") or []):
                ope2_requests.append({
                    "event_id": event_id,
                    "bookmaker_id": int(bm_id),
                    "bet_type": bet_type,
                    "bet_scope": bet_scope,
                })

        if not ope2_requests:
            logger.info("No ope2 requests for event_id=%s (empty menu or all filtered)", event_id)
            yield from self._finalize(event_id)
            return

        store["pending"] = len(ope2_requests)

        for req in ope2_requests:
            yield scrapy.Request(
                url=OPE2_URL.format(**req),
                callback=self.parse_odds,
                errback=self.errback_ope2,
                headers=BROWSER_HEADERS,
                cb_kwargs=req,
                dont_filter=True,
            )

    def parse_odds(self, response, event_id: str, bookmaker_id: int, bet_type: str, bet_scope: str):
        """Parse one ope2 response; yield item when all ope2 requests for the match complete."""
        store = self._match_store.get(event_id)
        if store is None:
            return

        try:
            data = Jmes(response.text)
            fp = data.select_dict("data.findPrematchOddsForBookmaker", default={})
        except Exception as e:
            logger.warning("ope2 parse error for %s bm=%s bt=%s/%s: %s",
                           event_id, bookmaker_id, bet_type, bet_scope, e)
            fp = {}

        if fp:
            odds_rows = _parse_ope2_odds(fp)
            if odds_rows:
                bm_entry = store["bm_acc"].get(bookmaker_id)
                if bm_entry is None:
                    bm_entry = {"name": str(bookmaker_id), "markets": {}}
                    store["bm_acc"][bookmaker_id] = bm_entry
                bm_entry["markets"][(bet_type, bet_scope)] = {
                    "bet_type": bet_type,
                    "bet_scope": bet_scope,
                    "has_live_betting": False,
                    "odds": odds_rows,
                }

        store["pending"] -= 1
        if store["pending"] <= 0:
            yield from self._finalize(event_id)

    def _finalize(self, event_id: str):
        """Build and yield the MatchOddsItem for a match."""
        store = self._match_store.pop(event_id, None)
        if store is None:
            return

        bookmakers_list: list[dict] = []
        for bm_id, bm_data in store["bm_acc"].items():
            markets = list(bm_data["markets"].values())
            if not markets:
                continue
            bookmakers_list.append({
                "bookmaker_id": bm_id,
                "bookmaker_name": bm_data["name"],
                "markets": markets,
            })

        loader = MatchOddsItemLoader()
        loader.add_value("match_id", store["match_id"])
        loader.add_value("match_url", store["match_url"])
        loader.add_value("sport", store.get("sport"))
        loader.add_value("scraped_at", datetime.now(tz=timezone.utc).isoformat())
        loader.add_value("bookmakers", bookmakers_list)
        # home_team / away_team: not available from ope2 without extra request — omit
        yield loader.load_item()

    def errback_home(self, failure):
        logger.warning("Homepage request failed; falling back to default geo GB/GB: %s", repr(failure.value))
        yield from self._yield_match_requests("GB", "GB")

    def errback_menu(self, failure):
        request = failure.request
        event_id = request.cb_kwargs.get("event_id", "unknown")
        logger.warning("pobtm failed for event_id=%s: %s", event_id, repr(failure.value))
        yield from self._finalize(event_id)

    def errback_ope2(self, failure):
        request = failure.request
        event_id = request.cb_kwargs.get("event_id", "unknown")
        bet_type = request.cb_kwargs.get("bet_type", "?")
        bet_scope = request.cb_kwargs.get("bet_scope", "?")
        bm_id = request.cb_kwargs.get("bookmaker_id", "?")
        logger.warning("ope2 failed for %s bm=%s bt=%s/%s: %s",
                       event_id, bm_id, bet_type, bet_scope, repr(failure.value))
        store = self._match_store.get(event_id)
        if store is not None:
            store["pending"] -= 1
            if store["pending"] <= 0:
                yield from self._finalize(event_id)
