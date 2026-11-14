import fs from "fs";
const SB = {
  nfl: "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard",
  ncaaf: "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard?groups=80&limit=300",
  nba: "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=20261114",
  ncaab: "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard?groups=50&limit=500&dates=20261114",
};
const out = {};
for (const [sp, url] of Object.entries(SB)) {
  const d = await (await fetch(url)).json();
  const evs = d.events || [];
  const pre = evs.filter(e => e.status?.type?.state === "pre");
  const withOdds = pre.filter(e => e.competitions?.[0]?.odds?.length);
  const e = withOdds[0];
  out[sp] = { n: evs.length, pre: pre.length, withOdds: withOdds.length, odds: e?.competitions[0].odds[0], comp: e && e.competitions[0].competitors.map(c => [c.homeAway, c.team.abbreviation]),
    post: (evs.find(e => e.status?.type?.state !== "pre")?.competitions?.[0]?.odds || [null])[0] };
}
fs.mkdirSync("pout", { recursive: true });
fs.writeFileSync("pout/news_snap.json", JSON.stringify(out));
