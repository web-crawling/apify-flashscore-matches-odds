"""Scrapy item pipelines module.

Module defines Scrapy item pipelines for scraped data.

For detailed information on creating and utilizing item pipelines, refer to:
http://doc.scrapy.org/en/latest/topics/item-pipeline.html
"""
# ruff: noqa: ARG002, D102

from __future__ import annotations

from typing import TYPE_CHECKING

from scrapy.exceptions import DropItem

if TYPE_CHECKING:
    from scrapy import Spider

    from .items import MatchOddsItem


class NullStripPipeline:
    """Strip None values from top-level item fields before Apify dataset push.

    The Apify dataset schema rejects ``null`` values for typed fields. Absent fields
    are valid; null fields are not. This pipeline removes any top-level field whose
    value is None so the schema validator does not reject the item.

    Note: nested None values inside the ``bookmakers`` list (e.g. ``opening_odds: null``)
    are inside dicts, not top-level item fields, and are not affected by this pipeline.
    """

    def process_item(self, item: MatchOddsItem, spider: Spider) -> MatchOddsItem:
        null_keys = [k for k, v in item.items() if v is None]
        for key in null_keys:
            del item[key]
        return item


class LimitItemsNumberPipeline:
    """Enforce the ``maxItems`` input cap.

    Reads ``CLOSESPIDER_ITEMCOUNT`` from Scrapy settings (set from the ``maxItems``
    Actor input in ``main.py``) and drops items once the limit is reached.
    """

    def __init__(self) -> None:
        self.items_scraped_count = 0

    def process_item(self, item: MatchOddsItem, spider: Spider) -> MatchOddsItem:
        self.items_scraped_count += 1

        items_limit = spider.settings.get('CLOSESPIDER_ITEMCOUNT')
        if items_limit and self.items_scraped_count > items_limit:
            raise DropItem(f'Strict limit reached: Exceeded {items_limit} items.')

        return item
