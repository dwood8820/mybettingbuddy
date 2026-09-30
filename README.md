# MyBettingBuddy

Football betting research: spreads, totals and player props next to real team and player results,
plus the O/U, Spread and Player Prop Splicers.

## How it stays up to date

| What | Where it comes from | How often |
|---|---|---|
| Schedule, lines, scores, team + player stats, splicer history | nflverse, built by `scripts/build_data.py` | GitHub Actions every 3 hours → `data` branch |
| Live scores and game clock | ESPN scoreboard via `netlify/functions/scores.mjs` | every minute during games |
| Anytime TD odds | The Odds API via `netlify/functions/td-odds.mjs` | cached 24 hours per game |
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
