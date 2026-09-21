# Changelog

## v1.3 (2026-09-21)

**`oddsType` now defaults to `both`**

- A run with no `oddsType` set now returns the pre-match lines **and**, while a match
  is being played, the in-play prices. Previously the default was `prematch`, so live
  odds had to be asked for explicitly.
- Nothing is removed by this change: the pre-match markets a run returned before are
  still returned. A match that has kicked off simply returns additional markets tagged
  `odds_type: "LIVE"`. In-play prices appear at kick-off and Flashscore keeps them
  after the match ends, so completed matches carry them too; only matches that have
  not started yet return pre-match markets alone.
- **If you match on `bet_type` alone, key on `odds_type` as well.** During a live
  match the same `bet_type` now appears once per feed. Set `oddsType: "prematch"` to
  restore exactly the previous behaviour.

## v1.2 (2026-09-21)

**Live in-play odds**

- New `oddsType` input: `prematch` (default, unchanged behaviour), `live`, or `both`.
  Live odds are the in-play prices that move during a match, read from Flashscore's
  live odds feed. Previously the Actor only ever returned pre-match odds, despite
  the listing describing live odds.
- Live football adds the `NEXT_GOAL` market (who scores next, including a `NONE`
  outcome for no further goal), and `ASIAN_HANDICAP` in-play.
- Every market now carries `odds_type` (`PREMATCH` or `LIVE`), so a run with
  `oddsType: "both"` keeps the two feeds distinguishable.
- Every selection now carries `change_direction` (`UP`/`DOWN`) and `previous_odds`,
  the latest price move and the price it moved from. Both feeds publish this; it is
  null until a price moves. This is the data the line-movement use case needs.
- Documentation corrected: the price is $0.005 per result ($5 per 1,000), previously
  stated as $1 per 1,000; the output tables and examples now include `odds_type`,
  `previous_odds` and `change_direction`; and the "empty result" FAQ now describes
  what actually happens - the `bookmakers` key is omitted rather than returned as an
  empty array, with a log line naming which cause applies.

## v1.1 (2026-09-21)

**Fixes a match returning no odds without saying why**

- A `betTypes` filter naming only bet types the match's sport does not publish no longer
  fails silently. Bet types differ by sport - football publishes HOME_DRAW_AWAY,
  OVER_UNDER, BOTH_TEAMS_TO_SCORE and DOUBLE_CHANCE, while basketball publishes
  HOME_DRAW_AWAY, HOME_AWAY, OVER_UNDER and ASIAN_HANDICAP - so filtering a football
  match to ASIAN_HANDICAP matched nothing and returned the match with no odds. The run
  log now names what you asked for and what the match actually offers.
- `betTypes` is now a multi-select of valid values in the Console, and each option says
  which sport publishes it.
- The single ambiguous "empty menu or all filtered" log line is split into three distinct
  warnings: a region that publishes no bookmakers, a `betTypes` filter that matched
  nothing, and a menu that listed bet types but published no offers. The resolved odds
  region (`geoIpCode`) is logged once per run.
- `has_live_betting` now reports whether the bookmaker offers in-play betting on the
  match, read from the Flashscore odds menu. It was previously hardcoded to `false`.
- Fixed the spider emitting no requests at all on Scrapy 2.13+, which removed
  `Spider.start_requests()`; the Actor now runs on both old and new Scrapy.
- Pinned `crawlee<1.10.1`: with `apify` 4.0.2 the newer release makes `import apify.scrapy`
  raise `TypeError`, which would break the Actor on its next rebuild.
- Documentation corrected: the odds returned are current and opening **pre-match** odds,
  not live in-play prices.

## v1.0 (2026-05-11)

**Initial release**

- Extract betting odds from Flashscore for football and basketball matches
- Bookmaker-level odds with nested markets and selections (HOME_DRAW_AWAY, OVER_UNDER, ASIAN_HANDICAP, DRAW_NO_BET, DOUBLE_CHANCE, EUROPEAN_HANDICAP, BOTH_TEAMS_TO_SCORE)
- Opening odds and current odds per selection for line movement analysis
- Accept match URLs or match IDs (compatible with Flashscore Extractor `match_id` output)
- Filter by bet type via `betTypes` parameter
- Cap output with `maxItems` parameter
