# Flashscore Betting Odds Extractor

Extract pre-match and live in-play betting odds from Flashscore for football and basketball matches. Get bookmaker-level odds across the bet types each sport publishes — 1X2, over/under, both teams to score, double chance, two-way, Asian handicap and next goal — each with its opening price and latest movement, in a structured JSON format ready for odds comparison, arbitrage detection, and prediction model pipelines. No proxy required.

## Features

- **Multi-bookmaker odds** — Returns all bookmakers available for each match via the Flashscore odds feed
- **Pre-match or live in-play odds** — Choose with `oddsType`. Pre-match returns the current and opening line before kick-off; live returns in-play prices that move during the match, including in-play-only markets such as next goal. `both` returns each, tagged by `odds_type`
- **Bet types by sport and state** — Pre-match football publishes HOME_DRAW_AWAY (1X2), OVER_UNDER, BOTH_TEAMS_TO_SCORE and DOUBLE_CHANCE; pre-match basketball publishes HOME_DRAW_AWAY, HOME_AWAY (two-way), OVER_UNDER and ASIAN_HANDICAP. Live football adds ASIAN_HANDICAP and NEXT_GOAL
- **Opening price and latest movement** — Every selection carries its opening line plus `change_direction` and `previous_odds`, so you can see which way a price just moved and from where
- **Football and basketball** — Works for any football or basketball match on Flashscore
- **Flexible input** — Accept Flashscore match page URLs or raw match IDs (same IDs output by [Flashscore Extractor](https://apify.com/extractify-labs/flashscore-extractor))
- **Bet type filter** — Limit output to specific bet types to reduce data volume and cost
- **Structured JSON output** — Nested bookmakers → markets → odds hierarchy, suitable for direct database ingestion
- **No proxy required** — Communicates directly with Flashscore's odds API; no residential proxy costs
- **$1 per 1,000 results** — Pay-per-result billing; one result = one match item

## Use Cases

**Odds Comparison Platforms**
Aggregate live and opening odds from multiple bookmakers in a single actor run. The nested bookmakers → markets → odds structure maps cleanly to comparison UI components. Feed results into a database and surface best-price tables in real time.

**Arbitrage Detection**
Identify mispriced markets by comparing odds across bookmakers for the same selection. Opening odds establish the market's initial line; current odds reveal where the market has moved. Example: if Bookmaker A prices Home at 2.10 and Bookmaker B at 2.40, the spread may support a surebet.

**Prediction Model Training**
Use opening odds as the market's consensus probability at match start. Compare your model's implied probability to the market's implied probability to detect edge. Feed `opening_odds` into your baseline and `odds` as the closing line.

**Line Movement Analysis**
Track how bookmakers adjust lines from open to match time. By comparing `opening_odds` with `odds` per selection and bookmaker, you can infer sharp money activity and market direction.

**Real-Time Odds Monitoring**
Schedule actor runs at regular intervals to capture a time series of odds snapshots. Trigger alerts when the difference between current and opening odds exceeds a threshold.

**Sports Media and Content Feeds**
Power odds tickers, matchup preview articles, and editorial content with live bookmaker lines directly from Flashscore.

## Input Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `startUrls` | array | Conditional | — | Flashscore match page URLs. Required if `matchIds` is not provided. Example: `https://www.flashscore.com/match/football/arsenal-west-ham/8Cxbx9Wh/` |
| `matchIds` | array | Conditional | — | Flashscore match IDs (e.g. `["8Cxbx9Wh", "8r8XHz43"]`). These are the same IDs in the `match_id` field of [Flashscore Extractor](https://apify.com/extractify-labs/flashscore-extractor) output. Either `startUrls` or `matchIds` must be provided. |
| `oddsType` | string | No | `prematch` | Which odds to return: `prematch` (current and opening pre-match lines), `live` (in-play prices, available only while a match is being played), or `both` (each market returned twice, tagged by `odds_type`). |
| `betTypes` | array | No | all types | Filter results to specific bet types. **Bet types differ by sport** — football publishes `HOME_DRAW_AWAY`, `OVER_UNDER`, `BOTH_TEAMS_TO_SCORE`, `DOUBLE_CHANCE`; basketball publishes `HOME_DRAW_AWAY`, `HOME_AWAY`, `OVER_UNDER`, `ASIAN_HANDICAP`. `DRAW_NO_BET` and `EUROPEAN_HANDICAP` are accepted but rarely published. Filtering a match to only bet types it does not offer returns that match with no odds, so omit this to return every market the match publishes. |
| `maxItems` | integer | No | unlimited | Maximum number of match items to return. Each match is one item. |

> **Note on bookmaker availability:** Bookmakers published for each match depend on the geographic location of the Apify server running the actor. Flashscore validates requests against the actual client IP — this cannot be overridden. When run on Apify's infrastructure, the actor returns bookmakers available in the European/UK region.

### Example Input

Using match URLs:

```json
{
  "startUrls": [
    { "url": "https://www.flashscore.com/match/football/arsenal-west-ham/8Cxbx9Wh/" }
  ],
  "betTypes": ["HOME_DRAW_AWAY", "OVER_UNDER"],
  "maxItems": 100
}
```

Using match IDs (from Flashscore Extractor output):

```json
{
  "matchIds": ["8Cxbx9Wh", "8r8XHz43"],
  "betTypes": ["HOME_DRAW_AWAY"]
}
```

## Output Format

One item per match. Each item contains top-level match metadata and a `bookmakers` array with nested markets and odds.

### Top-Level Fields

| Field | Type | Example | Notes |
|-------|------|---------|-------|
| `match_id` | string | `"8Cxbx9Wh"` | Flashscore match ID; cross-reference with Flashscore Extractor |
| `match_url` | string | `"https://www.flashscore.com/match/football/arsenal-west-ham/8Cxbx9Wh/"` | Full URL for `startUrls` input; redirect URL (`/match/?mid=…`) for `matchIds` input |
| `sport` | string | `"football"` | `"football"` or `"basketball"`. Absent when `matchIds` input is used. |
| `scraped_at` | string | `"2026-05-11T15:24:38+00:00"` | ISO 8601 UTC timestamp of extraction |
| `bookmakers` | array | — | Array of bookmaker objects (see below) |

### Bookmaker Object

| Field | Type | Example | Notes |
|-------|------|---------|-------|
| `bookmaker_id` | integer | `16` | Flashscore internal bookmaker ID |
| `bookmaker_name` | string | `"bet365"` | Bookmaker display name |
| `markets` | array | — | Array of market objects (see below) |

### Market Object

| Field | Type | Example | Notes |
|-------|------|---------|-------|
| `bet_type` | string | `"HOME_DRAW_AWAY"` | Bet type category (see Input Parameters for full list) |
| `bet_scope` | string | `"FULL_TIME"` | Match period the market covers: `FULL_TIME` = 90 minutes; `FULL_TIME_OVER_TIME` = includes extra time |
| `odds_type` | string | `"LIVE"` | Which feed this market came from: `PREMATCH` or `LIVE`. |
| `has_live_betting` | boolean | `true` | Whether this bookmaker takes in-play bets on this match. Describes the bookmaker, not the prices — see `odds_type` for the feed a market came from. |
| `odds` | array | — | Array of odds objects (see below) |

### Odds Object

| Field | Type | Example | Notes |
|-------|------|---------|-------|
| `selection` | string | `"HOME"`, `"DRAW"`, `"AWAY"`, `"OVER"`, `"UNDER"` | Outcome label |
| `odds` | float | `2.1` | Current decimal odds |
| `opening_odds` | float or null | `2.25` | Opening line at market open; null if not available |
| `handicap` | float or null | `2.5` | Handicap value for OVER_UNDER and ASIAN_HANDICAP bets; null for all other bet types |
| `is_active` | boolean | `true` | Whether odds are currently live |

### Example Output

```json
{
  "match_id": "8Cxbx9Wh",
  "match_url": "https://www.flashscore.com/match/football/arsenal-west-ham/8Cxbx9Wh/",
  "sport": "football",
  "scraped_at": "2026-05-11T15:24:38.247353+00:00",
  "bookmakers": [
    {
      "bookmaker_id": 16,
      "bookmaker_name": "bet365",
      "markets": [
        {
          "bet_type": "HOME_DRAW_AWAY",
          "bet_scope": "FULL_TIME",
          "has_live_betting": false,
          "odds": [
            {
              "selection": "HOME",
              "odds": 6.0,
              "opening_odds": 5.5,
              "handicap": null,
              "is_active": true
            },
            {
              "selection": "DRAW",
              "odds": 4.2,
              "opening_odds": 4.33,
              "handicap": null,
              "is_active": true
            },
            {
              "selection": "AWAY",
              "odds": 1.55,
              "opening_odds": 1.62,
              "handicap": null,
              "is_active": true
            }
          ]
        },
        {
          "bet_type": "OVER_UNDER",
          "bet_scope": "FULL_TIME",
          "has_live_betting": false,
          "odds": [
            {
              "selection": "OVER",
              "odds": 1.87,
              "opening_odds": 1.9,
              "handicap": 2.5,
              "is_active": true
            },
            {
              "selection": "UNDER",
              "odds": 1.87,
              "opening_odds": 1.85,
              "handicap": 2.5,
              "is_active": true
            }
          ]
        }
      ]
    }
  ]
}
```

## Chaining with Flashscore Extractor

This actor chains directly with [Flashscore Extractor](https://apify.com/extractify-labs/flashscore-extractor). The `match_id` field in Flashscore Extractor output is the same ID used by the `matchIds` input here. A typical pipeline:

1. Run **Flashscore Extractor** with your sport, day offset, and league filter to get a list of match items
2. Extract the `match_id` values from the output
3. Pass them as `matchIds` to **Flashscore Betting Odds Extractor** to get betting odds per match

No additional URL construction is needed. Team names and match metadata from Flashscore Extractor can be joined to this actor's output using `match_id`.

## Limitations

- **No team names in output** — Home team and away team names are not available from the odds API without an additional request per match. To get team names, use [Flashscore Extractor](https://apify.com/extractify-labs/flashscore-extractor) and join on `match_id`. This is a known v1 limitation.
- **No match date or league name** — Match date/time and competition name are not included in v1 output. Join with Flashscore Extractor output using `match_id` to enrich your dataset.
- **`sport` absent for `matchIds` input** — When you provide match IDs rather than URLs, the `sport` field is not present in the output (there is no URL to parse the sport from). Use `startUrls` input if you need the sport field, or join with Flashscore Extractor on `match_id`.
- **Live odds exist only while a match is in play** — With `oddsType: "live"` a match that has not kicked off, or has already finished, returns no live markets; use `prematch` (the default) before and after the match, or `both` to take whatever is available. Bookmaker coverage is also thinner in-play, because some bookmakers withdraw their prices once a match starts.
- **Each run is a snapshot** — Live prices move continuously. A run captures them at the moment it executes; schedule runs to build a time series.
- **Bookmaker availability is geo-fixed** — The bookmakers returned are those available from Apify's server location (European/UK region). This cannot be changed via input parameters.
- **Football and basketball only** — Other sports available on Flashscore (tennis, hockey, etc.) may work but are not tested or supported in v1.
- **Point-in-time snapshot** — Each run captures odds at the moment of execution. The actor does not stream or poll odds changes. For continuous monitoring, schedule repeated runs.
- **No historical odds** — Odds from completed matches are not retained after the match ends. Archive your results if you need historical data.

## FAQ

**Q: Why are some bookmakers not showing in my results?**

A: Bookmaker availability on Flashscore is determined by the geographic location of the server making the request. The Flashscore odds API validates requests against the actual client IP address, and there is no way to override this. When you run this actor on Apify's infrastructure, you will receive bookmakers available in the European/UK region.

**Q: What is the difference between `odds` and `opening_odds`?**

A: `opening_odds` is the line published when the betting market first opened (typically days before the match). `odds` is the current line at the time the actor ran. The difference between them reveals line movement: if `opening_odds = 2.5` and `odds = 2.1`, the bookmaker has moved the line significantly, which often signals sharp money on the other side. For arbitrage detection, compare `odds` across bookmakers. For line movement analysis, compare `opening_odds` to `odds` for each selection.

**Q: Does this actor require a proxy?**

A: No. This actor communicates directly with Flashscore's odds API without a proxy. No residential proxy costs apply.

**Q: Why is `sport` missing from some items?**

A: When you provide match IDs via the `matchIds` parameter rather than full match URLs, there is no URL to parse the sport name from, so the `sport` field is absent. To get the sport field in output, either use `startUrls` with full Flashscore match page URLs, or join with [Flashscore Extractor](https://apify.com/extractify-labs/flashscore-extractor) output on `match_id`.

**Q: How do I get team names in the output?**

A: Team names are not available from the odds API endpoint in v1. Run [Flashscore Extractor](https://apify.com/extractify-labs/flashscore-extractor) to get match metadata (which includes `home_team_name` and `away_team_name`) and join the two datasets on `match_id`.

**Q: What bet types are supported?**

A: Which bet types exist depends on the sport. Football matches publish `HOME_DRAW_AWAY` (1X2), `OVER_UNDER`, `BOTH_TEAMS_TO_SCORE` and `DOUBLE_CHANCE`. Basketball matches publish `HOME_DRAW_AWAY`, `HOME_AWAY` (two-way), `OVER_UNDER` and `ASIAN_HANDICAP`. `DRAW_NO_BET` and `EUROPEAN_HANDICAP` are accepted by the filter and parsed when present, but Flashscore rarely publishes them.

Live football additionally publishes `ASIAN_HANDICAP` and `NEXT_GOAL` (who scores next, with a `NONE` outcome for no further goal). `NEXT_GOAL` exists only in-play.

Use the `betTypes` input to filter, but note that filtering a football match to a basketball-only type such as `ASIAN_HANDICAP` (or vice versa) matches nothing and returns that match with no odds. The run log says so explicitly, naming what you asked for and what the match actually offers. Omit `betTypes` to get everything.

**Q: One of my match IDs returned an empty `bookmakers` array. Why?**

A: If a match ID is invalid or the match has no odds data on Flashscore (for example, the match has not opened for betting, or it is from a league that bookmakers do not cover), the actor returns an item with `bookmakers: []` and continues processing remaining matches. No error is raised and the actor does not stop.

## Related Actors

- **[Flashscore Extractor](https://apify.com/extractify-labs/flashscore-extractor)** — Extract match listings, scores, fixtures, and standings from Flashscore. Use this to discover match IDs and metadata, then feed them into this actor for odds data.
- **[Flashscore Results](https://apify.com/extractify-labs/flashscore-results)** — Historical match results and scores. Pair with odds data to build post-match analysis datasets and backtesting pipelines.
- **[Flashscore Team Fixtures](https://apify.com/extractify-labs/flashscore-team-fixtures)** — Upcoming and past fixtures for a specific team. Use to identify which matches to pull odds for.
- **[Flashscore Countries & Leagues](https://apify.com/extractify-labs/flashscore-countries-leagues)** — Discover all countries, leagues, and sports available on Flashscore.
