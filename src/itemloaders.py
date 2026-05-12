"""Scrapy item loader module.

Defines item loaders with appropriate input/output processors for each field.

Key rules:
- Scalar string fields use TakeFirst() output processor (default).
- The ``bookmakers`` field uses Identity() because it receives a fully-built list
  via a single add_value() call. Identity() is NOT applied to scalar fields —
  doing so would wrap the value in an extra list.
"""

from __future__ import annotations

from itemloaders import ItemLoader
from itemloaders.processors import Identity, MapCompose, TakeFirst

from src.items import MatchOddsItem


class MatchOddsItemLoader(ItemLoader):
    default_item_class = MatchOddsItem

    # Strings: strip surrounding whitespace on input, take first value on output.
    default_input_processor = MapCompose(str.strip)
    default_output_processor = TakeFirst()

    # ``bookmakers`` is a list of dicts assembled entirely in the spider and
    # passed as a single add_value() call.
    # Identity() on INPUT prevents MapCompose(str.strip) from trying to apply
    # str.strip to the list-of-dicts (which would raise ValueError).
    # Identity() on OUTPUT preserves the list as-is (do NOT use TakeFirst() —
    # it would unwrap the list to a single dict).
    bookmakers_in = Identity()
    bookmakers_out = Identity()
