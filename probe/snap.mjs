import { build } from "../netlify/functions/gamenews.mjs";
import fs from "fs";
const SB = {
  nfl: "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard",
  ncaaf: "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard?groups=80&limit=300",
  nba: "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=20261113",
  ncaab: "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard?groups=50&limit=500&dates=20261113",
};
const LIM = { nfl: 20, ncaaf: 60, nba: 20, ncaab: 80 };
const out = { nflmap: {}, stats: {} };
for (const [sp, url] of Object.entries(SB)) {
  const d = await (await fetch(url)).json();
  const evs = (d.events || []).slice(0, LIM[sp]);
  out[sp] = {}; let inj = 0, nn = 0, err = 0;
  for (const ev of evs) {
    try {
      const r = await build(sp, ev.id); out[sp][ev.id] = r;
      inj += (r.home?.inj.length || 0) + (r.away?.inj.length || 0); nn += r.news.length;
      if (sp === "nfl") out.nflmap[`${r.away.abbr}@${r.home.abbr}`] = ev.id;
    } catch (e) { err++; console.log(sp, ev.id, String(e)); }
  }
  out.stats[sp] = { games: evs.length, inj, news: nn, err };
  console.log(sp, out.stats[sp]);
}
fs.mkdirSync("pout", { recursive: true });
fs.writeFileSync("pout/news_snap.json", JSON.stringify(out));
