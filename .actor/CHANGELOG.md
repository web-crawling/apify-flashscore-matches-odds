# Changelog

## v1.0 (2026-05-11)

**Initial release**

- Extract betting odds from Flashscore for football and basketball matches
- Bookmaker-level odds with nested markets and selections (HOME_DRAW_AWAY, OVER_UNDER, ASIAN_HANDICAP, DRAW_NO_BET, DOUBLE_CHANCE, EUROPEAN_HANDICAP, BOTH_TEAMS_TO_SCORE)
- Opening odds and current odds per selection for line movement analysis
- Accept match URLs or match IDs (compatible with Flashscore Extractor `match_id` output)
- Filter by bet type via `betTypes` parameter
- Cap output with `maxItems` parameter
