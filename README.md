# apify-flashscore-matches-odds

Apify actor that extracts betting odds from Flashscore. See [`.actor/README.md`](.actor/README.md) for the end-user documentation.

## Project Structure

```
.actor/           Apify configuration (actor.json, input_schema.json, dataset_schema.json, README.md, CHANGELOG.md)
src/
  spiders/        Scrapy spiders
  items.py        Scrapy item definitions
  itemloaders.py  Item loaders with field processors
  pipelines.py    NullStripPipeline, LimitItemsNumberPipeline
  settings.py     Scrapy settings
  main.py         Apify entry point — input parsing, request construction
tests/
  test_e2e.py     End-to-end tests against live Flashscore API
```

## Running Locally

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt

# Set INPUT.json
mkdir -p storage/key_value_stores/default
echo '{"startUrls":[{"url":"https://www.flashscore.com/match/football/arsenal-west-ham/8Cxbx9Wh/"}]}' > storage/key_value_stores/default/INPUT.json

python -m scrapy crawl flashscore_odds
```

## API Endpoints Used

- `pobtm` — bookmaker menu per match (returns list of bookmakers offering odds)
- `ope2` — per-bookmaker odds detail (returns markets and selections)

Both endpoints are at `global.ds.lsapp.eu/odds/pq_graphql`. No proxy required.

## Deployment

Deployed via GitHub merge to `main` (CI triggers Apify build). Run `apify push` once for first-time bootstrap only.
