"""Spider for fetching match betting odds from Flashscore.

Two parallel feeds, selected by the ``oddsType`` input (see ``ODDS_TYPES``):

* PREMATCH — ``pobtm`` (menu) + ``ope2`` (odds): the current and opening lines a
  bookmaker published before kick-off. Available whatever state the match is in.
* LIVE — ``lobtm`` (menu) + ``ole2`` (odds): in-play prices that move during the
  match, plus in-play-only markets such as NEXT_GOAL. Published only while a match
  is actually being played.

Request flow (the ``oce`` endpoint referenced by earlier versions is no longer active):

1. One GET to flashscore.com homepage → would supply a ``geolocation`` cookie for
   geo-aware menu requests. The site no longer sets one, so the GB/GB default is
   the normal path; the region actually used is logged once per run.
2. One menu request per match *per selected feed* → bookmaker list + available
   bet types for that feed.
3. One odds request per (match × feed × bookmaker × bet_type × bet_scope) → the
   odds for that combination.

Item assembly: each ``parse_odds`` callback writes into a spider-level dict
(``_match_store``) keyed by event_id, with markets keyed by (feed, bet_type,
bet_scope) so a live market never overwrites its pre-match twin. Two counters
decide when a match is done: ``menus_pending`` (menus still to answer) and
``pending`` (odds requests still outstanding). ``_maybe_finalize`` emits the item
only when both reach zero, so one feed finishing early cannot cut the other short.
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

# Live (in-play) counterparts of the pre-match pair above: same host, same auth
# (none), same parameters. lobtm lists the live markets, ole2 returns the prices.
LOBTM_URL = (
    "https://global.ds.lsapp.eu/odds/pq_graphql"
    "?_hash=lobtm&eventId={event_id}&projectId=2"
    "&geoIpCode={geo_code}&geoIpSubdivisionCode={geo_sub}"
)

OLE2_URL = (
    "https://global.ds.lsapp.eu/odds/pq_graphql"
    "?_hash=ole2&eventId={event_id}&bookmakerId={bookmaker_id}"
    "&betType={bet_type}&betScope={bet_scope}"
)

PREMATCH = "PREMATCH"
LIVE = "LIVE"

MENU_URL = {PREMATCH: POBTM_URL, LIVE: LOBTM_URL}
ODDS_URL = {PREMATCH: OPE2_URL, LIVE: OLE2_URL}
MENU_PATH = {
    PREMATCH: "data.getPrematchOddsBettingTypeMenu",
    LIVE: "data.getLiveOddsBettingTypeMenu",
}
# The live feed wraps the odds one level deeper than the pre-match feed, behind
# push-subscription metadata this Actor does not use.
ODDS_PATH = {
    PREMATCH: "data.findPrematchOddsForBookmaker",
    LIVE: "data.findLiveOddsForBookmaker.eventOddsOverview",
}

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
    """Convert an odds-overview dict into a list of odd-row dicts.

    Handles both feeds: the pre-match ``findPrematchOddsForBookmaker`` payload and the
    live ``findLiveOddsForBookmaker.eventOddsOverview`` payload, which share the same
    ``__typename`` shapes. Structure varies by __typename:
    - HOME_DRAW_AWAY / HOME_AWAY / DRAW_NO_BET  → {home, draw?, away}
    - OVER_UNDER / ASIAN_HANDICAP / EUROPEAN_HANDICAP → {opportunities[{...}]}
    - DOUBLE_CHANCE  → {homeOrDraw, awayOrDraw, noDraw}
    - BOTH_TEAMS_TO_SCORE → {yes, no}
    - NEXT_GOAL (live only) → {home, none, away}

    Both feeds publish ``change{type,previous}`` per selection, captured as
    ``change_direction`` / ``previous_odds``; it is null until a price moves.
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
        change = raw.get("change") or {}
        try:
            previous_v = float(change["previous"]) if change.get("previous") is not None else None
        except (ValueError, TypeError):
            previous_v = None
        return {
            "selection": sel,
            "odds": odds_v,
            "opening_odds": opening_v,
            "previous_odds": previous_v,
            "change_direction": change.get("type"),
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

    elif typename == "EventOddsOverviewNextGoal":
        # Live-only market: who scores the next goal, or nobody ("none").
        for sel, key in [("HOME", "home"), ("NONE", "none"), ("AWAY", "away")]:
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
        # Which feeds to read: PREMATCH, LIVE, or both.
        self._odds_types: list[str] = [PREMATCH]
        # Geo actually used to build the pobtm menu requests. Flashscore publishes a
        # different bookmaker set per region, so every "no odds" diagnostic names it.
        self._geo: tuple[str, str] = ("GB", "GB")
        # Per-match accumulator: {event_id: {pending: int, bm_acc: {bm_id: {name, markets}}, ...}}
        self._match_store: dict[str, dict] = {}

    async def start(self):
        """Scrapy 2.13+ async entry point.

        Do NOT delegate to ``super().start()``: its default implementation only yields
        requests built from ``start_urls`` (unused here), and Scrapy 2.19 dropped
        ``Spider.start_requests()`` altogether — so delegating emits no requests at all.
        Both entry points therefore share ``_initial_requests()``.
        """
        for request in self._initial_requests():
            yield request

    def start_requests(self):
        """Entry point for Scrapy < 2.13, kept so the spider runs on either version."""
        return self._initial_requests()

    def _initial_requests(self):
        self._bet_types_filter = self.settings.get("BET_TYPES_FILTER") or None
        self._odds_types = list(self.settings.get("ODDS_TYPES") or [PREMATCH])
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
                logger.info("geolocation cookie: %s -> code=%s sub=%s", raw, geo_code, geo_sub)
                break
        else:
            # flashscore.com sets no geolocation cookie, so this is the normal path,
            # not a fault. The region actually used is logged at INFO just below.
            logger.debug("No geolocation cookie in the response; using the default GB/GB region")

        yield from self._yield_match_requests(geo_code, geo_sub)

    def _yield_match_requests(self, geo_code: str, geo_sub: str):
        """Initialise per-match state and yield one pobtm request per match."""
        self._geo = (geo_code, geo_sub)
        logger.info(
            "Odds region: geoIpCode=%s geoIpSubdivisionCode=%s "
            "(the bookmakers Flashscore publishes depend on this region)",
            geo_code, geo_sub,
        )
        logger.info("Reading %s odds", " + ".join(t.lower() for t in self._odds_types))
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
                "menus_pending": len(self._odds_types),
            }
            for odds_type in self._odds_types:
                url = MENU_URL[odds_type].format(
                    event_id=event_id, geo_code=geo_code, geo_sub=geo_sub,
                )
                yield scrapy.Request(
                    url=url,
                    callback=self.parse_menu,
                    errback=self.errback_menu,
                    headers=BROWSER_HEADERS,
                    cb_kwargs={"event_id": event_id, "odds_type": odds_type},
                    dont_filter=True,
                )

    def parse_menu(self, response, event_id: str, odds_type: str):
        """Parse one odds menu; yield an odds request per bookmaker/betType/betScope."""
        store = self._match_store.get(event_id)
        if store is None:
            return

        feed = odds_type.lower()

        try:
            data = Jmes(response.text)
        except Exception as e:
            logger.warning("Failed to parse the %s odds menu for %s: %s", feed, event_id, e)
            store["menus_pending"] -= 1
            yield from self._maybe_finalize(event_id)
            return

        menu_path = MENU_PATH[odds_type]
        menu = data.select_dict(menu_path, default={})
        if not menu:
            logger.warning(
                "No %s odds menu returned for event_id=%s (geoIpCode=%s "
                "geoIpSubdivisionCode=%s): the match ID may be invalid, this region "
                "publishes no odds menu, or the match is not in that state right now",
                feed, event_id, *self._geo,
            )
            store["menus_pending"] -= 1
            yield from self._maybe_finalize(event_id)
            return

        # Build bookmaker name lookup
        for bm_entry in data.select_list(f"{menu_path}.settings.bookmakers", default=[]):
            bm = bm_entry.get("bookmaker") or {}
            bm_id = bm.get("id")
            if bm_id is not None:
                self._register_bookmaker(
                    store,
                    int(bm_id),
                    str(bm.get("name") or bm_id),
                    # Appearing in the live menu proves the bookmaker takes in-play
                    # bets; the pre-match menu states it outright.
                    odds_type == LIVE or bool(bm_entry.get("hasLiveBettingOffers")),
                )

        # Build list of (betType, betScope, [bookmaker_ids]) combos
        menu_items = data.select_list(f"{menu_path}.items", default=[])
        available_types = sorted({it.get("bettingType") for it in menu_items if it.get("bettingType")})
        offers_in_menu = sum(len(it.get("bookmakerIds") or []) for it in menu_items)

        odds_requests: list[dict] = []
        for item in menu_items:
            bet_type = item.get("bettingType") or ""
            bet_scope = item.get("bettingScope") or ""
            if not bet_type or not bet_scope:
                continue
            if self._bet_types_filter and bet_type not in self._bet_types_filter:
                continue
            for bm_id in (item.get("bookmakerIds") or []):
                odds_requests.append({
                    "event_id": event_id,
                    "bookmaker_id": int(bm_id),
                    "bet_type": bet_type,
                    "bet_scope": bet_scope,
                })

        # Account for this menu and ALL of its requests before yielding any of them:
        # the other feed's callbacks must never observe a zero counter while these
        # requests are still to come, or the item would be emitted early.
        store["menus_pending"] -= 1
        store["pending"] += len(odds_requests)

        if not odds_requests:
            self._log_no_markets(event_id, odds_type, available_types, offers_in_menu)
            yield from self._maybe_finalize(event_id)
            return

        for req in odds_requests:
            yield scrapy.Request(
                url=ODDS_URL[odds_type].format(**req),
                callback=self.parse_odds,
                errback=self.errback_ope2,
                headers=BROWSER_HEADERS,
                cb_kwargs=dict(req, odds_type=odds_type),
                dont_filter=True,
            )

    @staticmethod
    def _register_bookmaker(store: dict, bm_id: int, name: str, offers_live: bool) -> dict:
        """Create or update one bookmaker accumulator; never overwrites a known name."""
        entry = store["bm_acc"].setdefault(bm_id, {
            "name": name,
            "has_live_betting": False,
            "markets": {},
        })
        if offers_live:
            entry["has_live_betting"] = True
        return entry

    def _maybe_finalize(self, event_id: str):
        """Emit the item once every menu has answered and every odds request is done."""
        store = self._match_store.get(event_id)
        if store is None:
            return
        if store["pending"] <= 0 and store["menus_pending"] <= 0:
            yield from self._finalize(event_id)

    def _log_no_markets(self, event_id: str, odds_type: str, available_types: list[str],
                        offers_in_menu: int):
        """Explain WHY a match produced no odds requests.

        The three causes need different action from the caller, so each gets its own
        message: a region that publishes no bookmakers, a betTypes filter that matched
        nothing, or a menu that listed bet types but published no bookmaker offers.
        """
        geo_code, geo_sub = self._geo

        if offers_in_menu == 0:
            logger.warning(
                "No %s bookmaker offers for event_id=%s in region geoIpCode=%s "
                "geoIpSubdivisionCode=%s. Flashscore publishes bookmakers per region and "
                "validates against this run's exit IP, so odds visible in your own browser "
                "may be absent here.",
                odds_type.lower(), event_id, geo_code, geo_sub,
            )
            return

        if self._bet_types_filter:
            logger.warning(
                "betTypes filter matched no %s market for event_id=%s: requested %s, but "
                "this match offers only %s. Bet types differ by sport: football offers "
                "HOME_DRAW_AWAY, OVER_UNDER, BOTH_TEAMS_TO_SCORE and DOUBLE_CHANCE; basketball "
                "offers HOME_DRAW_AWAY, HOME_AWAY, OVER_UNDER and ASIAN_HANDICAP. "
                "Remove betTypes to return every market this match offers.",
                odds_type.lower(), event_id, sorted(self._bet_types_filter), available_types,
            )
            return

        logger.warning(
            "No %s odds markets for event_id=%s (geoIpCode=%s geoIpSubdivisionCode=%s); the "
            "menu listed %s but published no bookmaker offers.",
            odds_type.lower(), event_id, geo_code, geo_sub, available_types,
        )

    def parse_odds(self, response, event_id: str, bookmaker_id: int, bet_type: str,
                   bet_scope: str, odds_type: str):
        """Parse one odds response; emit the item once the match has no work left."""
        store = self._match_store.get(event_id)
        if store is None:
            return

        try:
            data = Jmes(response.text)
            fp = data.select_dict(ODDS_PATH[odds_type], default={})
        except Exception as e:
            logger.warning("%s odds parse error for %s bm=%s bt=%s/%s: %s",
                           odds_type.lower(), event_id, bookmaker_id, bet_type, bet_scope, e)
            fp = {}

        if fp:
            odds_rows = _parse_ope2_odds(fp)
            if odds_rows:
                bm_entry = self._register_bookmaker(store, bookmaker_id, str(bookmaker_id), False)
                # Keyed by feed too, so a live market never overwrites its pre-match twin.
                bm_entry["markets"][(odds_type, bet_type, bet_scope)] = {
                    "odds_type": odds_type,
                    "bet_type": bet_type,
                    "bet_scope": bet_scope,
                    "has_live_betting": bm_entry.get("has_live_betting", False),
                    "odds": odds_rows,
                }

        store["pending"] -= 1
        yield from self._maybe_finalize(event_id)

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
        odds_type = request.cb_kwargs.get("odds_type", PREMATCH)
        logger.warning("The %s odds menu failed for event_id=%s: %s",
                       odds_type.lower(), event_id, repr(failure.value))
        store = self._match_store.get(event_id)
        if store is not None:
            store["menus_pending"] -= 1
            yield from self._maybe_finalize(event_id)

    def errback_ope2(self, failure):
        request = failure.request
        event_id = request.cb_kwargs.get("event_id", "unknown")
        bet_type = request.cb_kwargs.get("bet_type", "?")
        bet_scope = request.cb_kwargs.get("bet_scope", "?")
        bm_id = request.cb_kwargs.get("bookmaker_id", "?")
        odds_type = request.cb_kwargs.get("odds_type", PREMATCH)
        logger.warning("A %s odds request failed for %s bm=%s bt=%s/%s: %s",
                       odds_type.lower(), event_id, bm_id, bet_type, bet_scope, repr(failure.value))
        store = self._match_store.get(event_id)
        if store is not None:
            store["pending"] -= 1
            yield from self._maybe_finalize(event_id)
