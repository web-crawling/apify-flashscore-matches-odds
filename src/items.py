"""Scrapy item models module.

Module defines Scrapy item models for scraped data. Items represent structured data
extracted by spiders.

For detailed information on creating and utilizing items, refer to the official documentation:
https://docs.scrapy.org/en/latest/topics/items.html
"""

from __future__ import annotations

import scrapy


class MatchOddsItem(scrapy.Item):
    """Represents betting odds for a single Flashscore match.

    One item is produced per input match. Bookmakers, markets, and individual
    odds selections are nested within the ``bookmakers`` list field.

    All fields declared here must also be present in .actor/dataset_schema.json.
    """

    match_id = scrapy.Field()    # str — Flashscore event ID
    match_url = scrapy.Field()   # str — canonical or redirect match URL
    home_team = scrapy.Field()   # str or None — home team display name
    away_team = scrapy.Field()   # str or None — away team display name
    sport = scrapy.Field()       # str or None — sport slug from URL path (e.g. "football")
    scraped_at = scrapy.Field()  # str ISO 8601 UTC — timestamp when odds were fetched
    bookmakers = scrapy.Field()  # list[dict] — fully-built before add_value; see output schema
