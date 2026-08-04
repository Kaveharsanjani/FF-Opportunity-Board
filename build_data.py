"""
Builds data.json for the Vacancy Board site from free nflverse data.

Run this manually any time, or let the GitHub Actions workflow
(.github/workflows/refresh-data.yml) run it on a schedule.

NOTE on the "oc" (offensive coordinator) field: there is no clean,
structured, machine-readable source for "did this team change OCs".
The OC_STATUS dict below was hand-researched and is a snapshot as of
when it was last edited. This script does NOT try to auto-update it.
If a team changes coordinators, edit OC_STATUS by hand and re-run.
"""
import json
import re
import datetime
import pandas as pd
import numpy as np

SEASON = 2025  # the completed season whose stats we're using
BASE = "https://github.com/nflverse/nflverse-data/releases/download"

# ---------------------------------------------------------------------------
# Hand-maintained: which teams have a NEW offensive coordinator for the
# upcoming season vs. the SAME one as last season. Update by hand as needed.
# ---------------------------------------------------------------------------
OC_STATUS = {
    'ARI':'NEW','ATL':'NEW','BAL':'NEW','BUF':'NEW','CHI':'NEW','CLE':'NEW',
    'DEN':'NEW','DET':'NEW','KC':'NEW','LA':'NEW','LAC':'NEW','LV':'NEW',
    'MIA':'NEW','NYG':'NEW','NYJ':'NEW','PHI':'NEW','PIT':'NEW','SEA':'NEW',
    'TB':'NEW','TEN':'NEW','WAS':'NEW',
    'CAR':'SAME','CIN':'SAME','DAL':'SAME','GB':'SAME','HOU':'SAME',
    'IND':'SAME','JAX':'SAME','MIN':'SAME','NE':'SAME','NO':'SAME','SF':'SAME',
}

CURRENT_TEAMS = ['ARI','ATL','BAL','BUF','CAR','CHI','CIN','CLE','DAL','DEN','DET','GB',
                  'HOU','IND','JAX','KC','LA','LAC','LV','MIA','MIN','NE','NO','NYG','NYJ',
                  'PHI','PIT','SEA','SF','TB','TEN','WAS']


def get_season_gs(df, season):
    """Prefer PFR's combined multi-team row (e.g. '2TM') over summing per-team rows."""
    d = df[df.season == season].copy()

    def pick(g):
        combo = g[g['tm'].str.match(r'^\dTM$', na=False)]
        if len(combo) > 0:
            return combo['gs'].iloc[0]
        return g['gs'].sum()

    return d.groupby('pfr_id').apply(pick)


def main():
    print("Loading player/team season stats...")
    ps = pd.read_parquet(f"{BASE}/stats_player/stats_player_reg_{SEASON}.parquet")
    ts = pd.read_parquet(f"{BASE}/stats_team/stats_team_reg_{SEASON}.parquet")
    ts['offensive_plays'] = ts['attempts'] + ts['sacks_suffered'] + ts['carries']
    team_plays = ts.set_index('team')['offensive_plays'].to_dict()

    print("Loading current rosters...")
    roster_current = pd.read_parquet(f"{BASE}/rosters/roster_{SEASON+1}.parquet")
    r_current = (roster_current.sort_values('week').drop_duplicates('gsis_id', keep='last')
                 [['gsis_id', 'full_name', 'position', 'team', 'pfr_id']])
    current_team = r_current.set_index('gsis_id')['team'].to_dict()
    pfrid_by_gsis = r_current.set_index('gsis_id')['pfr_id'].to_dict()

    print("Computing games started (PFR advanced stats)...")
    rec = pd.read_parquet(f"{BASE}/pfr_advstats/advstats_season_rec.parquet")
    rush = pd.read_parquet(f"{BASE}/pfr_advstats/advstats_season_rush.parquet")
    gs_rec = get_season_gs(rec, SEASON)
    gs_rush = get_season_gs(rush, SEASON)
    games_started = pd.concat([gs_rec, gs_rush], axis=1, keys=['gs_rec', 'gs_rush']).max(axis=1)
    games_started_dict = games_started.to_dict()

    print("Computing exposure-based usage rate / on-field % (week-by-week)...")
    pw = pd.read_parquet(f"{BASE}/stats_player/stats_player_week_{SEASON}.parquet")
    tw = pd.read_parquet(f"{BASE}/stats_team/stats_team_week_{SEASON}.parquet")
    sc = pd.read_parquet(f"{BASE}/snap_counts/snap_counts_{SEASON}.parquet")

    pw = pw[pw.season_type == 'REG'].copy()
    tw = tw[tw.season_type == 'REG'].copy()
    tw['offensive_plays'] = tw['attempts'] + tw['sacks_suffered'] + tw['carries']
    team_week_plays = tw.set_index(['team', 'week'])['offensive_plays'].to_dict()

    sc_reg = sc[(sc.season == SEASON) & (sc.game_type == 'REG')].copy()
    sc_active = sc_reg[sc_reg['offense_snaps'] > 0][['pfr_player_id', 'team', 'week', 'offense_snaps']].copy()
    gsis_by_pfrid = {v: k for k, v in pfrid_by_gsis.items() if pd.notna(v)}
    sc_active['player_id'] = sc_active['pfr_player_id'].map(gsis_by_pfrid)
    sc_active['team_week_plays'] = sc_active.apply(
        lambda r: team_week_plays.get((r['team'], r['week'])), axis=1
    )
    exposure = sc_active.dropna(subset=['player_id']).groupby('player_id').agg(
        on_field_snaps=('offense_snaps', 'sum'),
        exposure_plays=('team_week_plays', 'sum'),
    ).reset_index()

    pw_small = pw[['player_id', 'week', 'team', 'carries', 'targets']].copy()
    pw_small['touches'] = pw_small['carries'].fillna(0) + pw_small['targets'].fillna(0)
    touches_by_player = pw_small.groupby('player_id')['touches'].sum().reset_index()

    exposure = exposure.merge(touches_by_player, on='player_id', how='left')
    exposure['touches'] = exposure['touches'].fillna(0)
    exposure['usage_rate'] = exposure['touches'] / exposure['exposure_plays']
    exposure['on_field_pct'] = exposure['on_field_snaps'] / exposure['exposure_plays']
    exposure_dict = exposure.set_index('player_id')[['usage_rate', 'on_field_pct']].to_dict(orient='index')

    print("Computing vacated targets / carries per team...")
    ps25 = ps[['player_id', 'player_name', 'position', 'recent_team', 'carries', 'targets']].copy()
    ps25['current_team'] = ps25['player_id'].map(current_team)
    ps25['left_2025_team'] = ps25['current_team'] != ps25['recent_team']

    vacated_targets = (ps25[ps25['left_2025_team']].groupby('recent_team')['targets'].sum()
                        .rename('vacated_targets').reset_index().rename(columns={'recent_team': 'team'}))
    vacated_carries = (ps25[ps25['left_2025_team']].groupby('recent_team')['carries'].sum()
                        .rename('vacated_carries').reset_index().rename(columns={'recent_team': 'team'}))
    vac = vacated_targets.merge(vacated_carries, on='team', how='outer').fillna(0)

    def stats_for(col):
        m, s = vac[col].mean(), vac[col].std()
        return {'mean': round(m, 2), 'std': round(s, 2), 'lo': round(m - s, 2),
                'hi': round(m + s, 2), 'hi2': round(m + 2 * s, 2)}

    vt_stats = stats_for('vacated_targets')
    vc_stats = stats_for('vacated_carries')

    def color_for(v, st):
        if v > st['hi2']: return 'purple'
        if v > st['hi']: return 'green'
        if v < st['lo']: return 'red'
        return 'yellow'

    vac['vt_color'] = vac['vacated_targets'].apply(lambda v: color_for(v, vt_stats))
    vac['vc_color'] = vac['vacated_carries'].apply(lambda v: color_for(v, vc_stats))

    print("Computing fantasy position ranks (PPR)...")
    skill = ps[ps.position.isin(['WR', 'RB', 'TE'])].copy()
    skill['pos_rank'] = skill.groupby('position')['fantasy_points_ppr'].rank(ascending=False, method='min')
    skill['flex_rank'] = skill['fantasy_points_ppr'].rank(ascending=False, method='min')
    pc = skill[skill.position.isin(['WR', 'TE'])].copy()
    pc['pc_rank'] = pc['fantasy_points_ppr'].rank(ascending=False, method='min')
    skill = skill.merge(pc[['player_id', 'pc_rank']], on='player_id', how='left')
    ranks_by_pid = skill.set_index('player_id')[['pos_rank', 'flex_rank', 'pc_rank']].to_dict(orient='index')

    print("Loading active contracts (AAV)...")
    contracts = pd.read_parquet(f"{BASE}/contracts/historical_contracts.parquet")
    active = contracts[(contracts.is_active == True) & (contracts.gsis_id.notna())].copy()
    active = active.sort_values('year_signed').drop_duplicates('gsis_id', keep='last')
    aav_by_gsis = active.set_index('gsis_id')['apy'].to_dict()

    print("Loading team names...")
    teams_df = pd.read_parquet(f"{BASE}/teams/teams_colors_logos.parquet")
    teams_df = teams_df[teams_df.team_abbr.isin(CURRENT_TEAMS)].copy()
    teams_df['city'] = teams_df.apply(lambda r: r['team_name'].replace(r['team_nick'], '').strip(), axis=1)
    team_info = {
        row.team_abbr: {'full': row.team_name, 'city': row.city, 'nick': row.team_nick}
        for row in teams_df.itertuples()
    }

    print("Assembling final player list...")
    flex = r_current[r_current['position'].isin(['WR', 'RB', 'TE'])].copy()
    flex = flex.merge(
        ps25[['player_id', 'carries', 'targets', 'recent_team']],
        left_on='gsis_id', right_on='player_id', how='left'
    )
    flex = flex.merge(vac, on='team', how='left')
    flex['vacated_targets'] = flex['vacated_targets'].fillna(0)
    flex['vacated_carries'] = flex['vacated_carries'].fillna(0)

    players = []
    for row in flex.itertuples():
        gsis = row.gsis_id
        exp = exposure_dict.get(gsis, {})
        ranks = ranks_by_pid.get(gsis, {})
        aav = aav_by_gsis.get(gsis)
        players.append({
            'name': row.full_name,
            'pos': row.position,
            'team': row.team,
            'vac': int(row.vacated_targets),
            'vacColor': row.vt_color if pd.notna(row.vt_color) else 'yellow',
            'vacCar': int(row.vacated_carries) if row.position == 'RB' else None,
            'vacCarColor': row.vc_color if pd.notna(row.vc_color) else 'yellow',
            'usage': exp.get('usage_rate') if exp.get('usage_rate') is not None and not pd.isna(exp.get('usage_rate')) else None,
            'gs': int(games_started_dict[pfrid_by_gsis.get(gsis)]) if pfrid_by_gsis.get(gsis) in games_started_dict and pd.notna(games_started_dict.get(pfrid_by_gsis.get(gsis))) else None,
            'onField': exp.get('on_field_pct') if exp.get('on_field_pct') is not None and not pd.isna(exp.get('on_field_pct')) else None,
            'oc': OC_STATUS.get(row.team),
            'posRank': int(ranks['pos_rank']) if ranks.get('pos_rank') is not None and pd.notna(ranks.get('pos_rank')) else None,
            'flexRank': int(ranks['flex_rank']) if ranks.get('flex_rank') is not None and pd.notna(ranks.get('flex_rank')) else None,
            'pcRank': int(ranks['pc_rank']) if ranks.get('pc_rank') is not None and pd.notna(ranks.get('pc_rank')) else None,
            'tgt2025': int(row.targets) if pd.notna(row.targets) else 0,
            'car2025': int(row.carries) if pd.notna(row.carries) else 0,
            'aav': round(float(aav) * 1_000_000) if aav is not None and pd.notna(aav) else None,
        })

    output = {
        'generatedAt': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'season': SEASON,
        'vacStats': {'targets': vt_stats, 'carries': vc_stats},
        'teamInfo': team_info,
        'players': players,
    }

    with open('data.json', 'w') as f:
        json.dump(output, f, separators=(',', ':'))

    print(f"Wrote data.json with {len(players)} players.")


if __name__ == '__main__':
    main()
