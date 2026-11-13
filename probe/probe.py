import json, urllib.request, os
os.makedirs('pout', exist_ok=True)
def get(u):
    r = urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'mybettingbuddy'}), timeout=60)
    return json.loads(r.read())
B = 'https://site.api.espn.com/apis/site/v2/sports/football/college-football'
def summarize(sb, n=4):
    out = {'count': len(sb.get('events', [])), 'withOdds': 0, 'sample': []}
    for ev in sb.get('events', []):
        c = ev['competitions'][0]
        if c.get('odds'): out['withOdds'] += 1
    for ev in sb.get('events', [])[:n]:
        c = ev['competitions'][0]
        out['sample'].append({'name': ev.get('name'), 'date': ev.get('date'), 'status': ev['status']['type'],
            'venue': c.get('venue'), 'neutral': c.get('neutralSite'), 'conf': c.get('conferenceCompetition'),
            'weather': ev.get('weather'), 'competitors': [{k: x.get(k) for k in ('homeAway', 'score', 'curatedRank')} | {'team': {k: x['team'].get(k) for k in ('id', 'abbreviation', 'displayName', 'shortDisplayName', 'color', 'alternateColor', 'conferenceId')}} for x in c['competitors']],
            'odds': c.get('odds')})
    return out
res = {}
for label, u in [('current', f'{B}/scoreboard?groups=80&limit=300'),
                 ('2026wk5', f'{B}/scoreboard?groups=80&seasontype=2&week=5&dates=2026&limit=300'),
                 ('2025wk5', f'{B}/scoreboard?groups=80&seasontype=2&week=5&dates=2025&limit=300'),
                 ('2022wk5', f'{B}/scoreboard?groups=80&seasontype=2&week=5&dates=2022&limit=300')]:
    try: res[label] = summarize(get(u))
    except Exception as e: res[label] = {'error': str(e)}
try:
    t = get(f'{B}/teams?groups=80&limit=300')
    teams = t['sports'][0]['leagues'][0]['teams']
    res['teams'] = {'count': len(teams), 'sample': [x['team'] for x in teams[:2]]}
except Exception as e: res['teams'] = {'error': str(e)}
try:
    ev = get(f'{B}/scoreboard?groups=80&seasontype=2&week=5&dates=2025&limit=5')['events'][0]
    s = get(f'{B}/summary?event={ev["id"]}')
    res['summary_keys'] = list(s.keys()); res['pickcenter'] = s.get('pickcenter'); res['againstTheSpread'] = s.get('againstTheSpread')
    core = get(f'https://sports.core.api.espn.com/v2/sports/football/leagues/college-football/events/{ev["id"]}/competitions/{ev["id"]}/odds')
    res['core_odds'] = core.get('items', [])[:2]
except Exception as e: res['summary_err'] = str(e)
json.dump(res, open('pout/probe.json', 'w'), indent=1, default=str)
print(json.dumps({k: (v.get('count'), v.get('withOdds')) if isinstance(v, dict) and 'count' in v else '..' for k, v in res.items()}))
