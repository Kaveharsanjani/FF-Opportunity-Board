# Vacancy Board

A self-updating fantasy football site: flex-eligible players ranked by vacated
targets/carries, usage rate, on-field %, position rank, contract AAV, and more.

## One-time setup

1. Create a new GitHub repo and upload everything in this folder, **keeping the
   folder structure** (the `.github/workflows/refresh-data.yml` file must stay
   at that exact path).
2. In the repo, go to **Settings → Pages** → under "Source" pick your default
   branch and the `/root` folder → Save. GitHub will give you a live URL after
   a minute or two (e.g. `https://yourusername.github.io/vacancy-board-site/`).
3. Go to **Settings → Actions → General → Workflow permissions** and select
   **"Read and write permissions."** This lets the scheduled job commit the
   refreshed `data.json` back to the repo.

That's it — no server, no hosting bill, nothing else to configure.

## How the auto-refresh works

- `.github/workflows/refresh-data.yml` runs `build_data.py` automatically
  every Tuesday and Friday (edit the `cron` line to change the schedule).
- `build_data.py` re-pulls fresh data from nflverse (rosters, stats, snap
  counts, contracts) and rewrites `data.json`.
- If anything changed, the workflow commits the new `data.json` straight to
  the repo. GitHub Pages picks it up automatically — no rebuild step needed.
- `index.html` fetches `data.json` fresh every time someone loads the page,
  so visitors always see whatever was last committed.

You can also trigger a refresh manually any time from the repo's **Actions**
tab → "Refresh Vacancy Board data" → **Run workflow** — handy right after a
trade or a big free-agent signing instead of waiting for the schedule.

## The one thing that does NOT auto-update

The **OC (offensive coordinator new/same)** column is hand-researched — there's
no clean structured data source for coaching staff changes. It's set as a
plain dictionary near the top of `build_data.py` (`OC_STATUS`). If a team
changes coordinators mid-season, edit that dictionary and either wait for the
next scheduled run or trigger the workflow manually.

## Files

- `index.html` — the site itself (fetches `data.json` at load time)
- `data.json` — the current snapshot of data (auto-refreshed)
- `build_data.py` — the script that rebuilds `data.json` from nflverse
- `.github/workflows/refresh-data.yml` — the schedule that runs it
