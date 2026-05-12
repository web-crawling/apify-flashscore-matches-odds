"""Module defines the main entry point for the Apify Actor.

Reads Actor input, validates it, normalises the list of matches to scrape, and
executes the Scrapy spider via CrawlerRunner.

Input parameters:
- startUrls:  list of Flashscore match URLs (conditional, at least one of startUrls/matchIds required)
- matchIds:   list of Flashscore event IDs (conditional, at least one of startUrls/matchIds required)
- betTypes:   list of bet-type enum strings to filter output (optional; omit for all)
- geoIpCode:  ISO 3166-1 alpha-2 country code for bookmaker availability (default "GB")
- maxItems:   maximum number of output items/matches (optional)
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from apify import Actor
from apify.scrapy import apply_apify_settings
from scrapy.crawler import CrawlerRunner
from scrapy.utils.defer import deferred_to_future

from .spiders.flashscore_odds import FlashscoreOddsSpider


def _extract_event_id_from_url(url: str) -> str | None:
    """Return the event ID embedded in a Flashscore match URL.

    Tries the ``mid`` query parameter first; if absent, falls back to the last
    non-empty path segment (e.g. ``/match/football/team-ID1/team-ID2/ID`` would
    yield ``ID``).
    """
    parsed = urlparse(url)

    # Prefer the explicit ?mid= query parameter.
    qs = parse_qs(parsed.query)
    if 'mid' in qs:
        return qs['mid'][0]

    # Fall back to the last non-empty path segment.
    segments = [seg for seg in parsed.path.split('/') if seg]
    if segments:
        return segments[-1]

    return None


async def main() -> None:
    """Apify Actor main coroutine for executing the Scrapy spider."""
    async with Actor:
        actor_input = await Actor.get_input() or {}

        start_urls: list = actor_input.get('startUrls') or []
        match_ids: list = actor_input.get('matchIds') or []
        bet_types: list = actor_input.get('betTypes') or []
        geo_ip_code: str = actor_input.get('geoIpCode') or 'GB'
        max_items: int | None = actor_input.get('maxItems')

        # Validation: at least one of startUrls or matchIds must be provided.
        if not start_urls and not match_ids:
            await Actor.fail(
                status_message='Input validation error: at least one of "startUrls" or "matchIds" must be provided.'
            )
            return

        # Normalise input into a list of (event_id, match_url) tuples.
        # Use a dict keyed by event_id to deduplicate across both inputs.
        seen: dict[str, str] = {}

        # Process startUrls — extract event_id from URL.
        for entry in start_urls:
            # Apify requestListSources entries may be dicts with a 'url' key or plain strings.
            url = entry.get('url') if isinstance(entry, dict) else str(entry)
            if not url:
                continue
            event_id = _extract_event_id_from_url(url)
            if not event_id:
                Actor.log.warning(f'Could not extract event ID from URL: {url!r} — skipping')
                continue
            if event_id not in seen:
                seen[event_id] = url  # preserve original URL as match_url

        # Process matchIds — construct a redirect URL; no extra HTTP request needed.
        for raw_id in match_ids:
            event_id = str(raw_id).strip()
            if not event_id:
                continue
            if event_id not in seen:
                seen[event_id] = f'https://www.flashscore.com/match/?mid={event_id}'

        if not seen:
            await Actor.fail(
                status_message='No valid match URLs or match IDs could be parsed from the input.'
            )
            return

        # Build the final list of request dicts expected by the spider.
        # Each dict has: event_id, match_url, geo_ip_code.
        odds_requests: list[dict] = [
            {'event_id': event_id, 'match_url': match_url, 'geo_ip_code': geo_ip_code}
            for event_id, match_url in seen.items()
        ]

        settings = apply_apify_settings()

        # Pass the match list and filter params to the spider via settings.
        settings.set('ODDS_REQUESTS', odds_requests)
        # BET_TYPES_FILTER: pass a set (or None) so the spider can use `in` checks efficiently.
        settings.set('BET_TYPES_FILTER', set(bet_types) if bet_types else None)

        # Apply the maxItems cap via Scrapy's CLOSESPIDER_ITEMCOUNT.
        if max_items:
            settings.set('CLOSESPIDER_ITEMCOUNT', max_items)

        crawler_runner = CrawlerRunner(settings)
        crawl_deferred = crawler_runner.crawl(FlashscoreOddsSpider)
        await deferred_to_future(crawl_deferred)
