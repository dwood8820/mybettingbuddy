# MyBettingBuddy

Football betting research: spreads, totals and player props next to real team and player results,
plus the O/U, Spread and Player Prop Splicers.

## How it stays up to date

| What | Where it comes from | How often |
|---|---|---|
| NFL schedule, lines, scores, team + player stats, graph history | nflverse, built by `scripts/build_data.py` | GitHub Actions every 3 hours → `data` branch |
| NCAAF (FBS) schedule, scores, DraftKings lines, weather, graph history since 2015 | ESPN, built by `scripts/build_ncaaf.py` (past closing lines cached in `ncaaf_lines.json`) | same job |
| NBA schedule, scores, team + player box scores, DraftKings lines, graph history since 2015-16 | sportsdataverse box scores (ESPN data) + ESPN lines, built by `scripts/build_nba.py` (past closing lines cached in `nba_lines.json`) | same job |
| NCAAB (Division I) schedule, scores, DraftKings lines, AP ranks, graph history since 2019-20 | sportsdataverse box scores + ESPN, built by `scripts/build_ncaab.py` (lines cached in `ncaab_lines.json`); loads only when the NCAAB tab opens | same job |
| Live scores and game clock | ESPN scoreboard via `netlify/functions/scores.mjs` | every minute during games |
| Injuries and latest headlines | ESPN game summary + team news via `netlify/functions/gamenews.mjs` | cached 20 minutes per game |
| Anytime TD odds | The Odds API via `netlify/functions/td-odds.mjs` | cached by time to kickoff: until 24h before, then until 2h before, then until kickoff (~3 credits per game per week) |
| Weather | Open-Meteo, straight from the browser | on page load |

The page (`site/index.html`) reads the data files from
`https://raw.githubusercontent.com/<owner>/<repo>/data/`, so data refreshes never trigger a Netlify deploy.

## Setup (one time)

1. **Netlify**: Add new site → Import an existing project → GitHub → pick this repo.
   Leave the build command empty; publish directory `site` and functions `netlify/functions` come from `netlify.toml`.
2. **Odds API key**: Site configuration → Environment variables → add `ODDS_API_KEY`.
3. **First data refresh**: GitHub → Actions → "Refresh data" → Run workflow.

## Editing the page

Edit `scripts/template.html`, then run `python scripts/build_page.py` to regenerate `site/index.html`, and push.
Each push to `main` is one Netlify deploy.
