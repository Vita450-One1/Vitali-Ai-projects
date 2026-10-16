# Smart Flight Deal Hunter

An AI agent that watches flight prices for your trips, remembers every price it
sees, and tells you whether to **BUY NOW**, **WAIT**, or **WATCH**.

| Step | What it adds | Status |
|---|---|---|
| 1 | Smart searching with a search budget, price memory, verdicts | ✅ |
| 2 | A designed email report with verdict, results table and price trend | ✅ |
| 3 | Runs every morning by itself (GitHub Actions) | ✅ |

## Files

| File | Job |
|---|---|
| `watchlist.json` | Your trips: route, date window, nights, travelers, budget |
| `tools.py` | The tools: `search_flights`, `get_price_history`, `submit_report`, and the price memory |
| `email_report.py` | Designs the HTML email and sends it with Gmail |
| `hunter.py` | The agent: instructions, tool descriptions, and the loop |
| `price_history.json` | Created automatically: every price the agent has seen |

## Run it (Windows, PowerShell)

```powershell
cd C:\agents\flight-deal-hunter
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt

# Practice with made-up prices (free, no SerpApi needed):
$env:FAKE_FLIGHTS="1"
.venv\Scripts\python.exe hunter.py

# Real prices (needs a free SerpApi key from serpapi.com):
$env:FAKE_FLIGHTS="0"
$env:SERPAPI_KEY="your-serpapi-key"
.venv\Scripts\python.exe hunter.py
```

`GEMINI_API_KEY` is read from Windows, the same as for the trip planner.

## Email

Every run saves the email as `last_email.html` (double-click it to preview).
To also receive it, save these once with `setx` (then restart VS Code):

| Variable | Value |
|---|---|
| `GMAIL_ADDRESS` | your Gmail address |
| `GMAIL_APP_PASSWORD` | a Gmail app password (Google Account, then Security, then App passwords) |
| `EMAIL_TO` (optional) | another address to send to |

Add `--no-email` to skip sending.

## Why a search budget?

SerpApi's free plan gives about 250 searches a month, roughly 8 a day. Instead of
checking every date, the agent gets `searches_per_run` searches and must
**decide** which dates are worth checking. It uses past prices to choose.
Choosing how to spend a limited resource is a core agent skill.

## Running every morning in the cloud (Step 3)

`.github/workflows/flight-deal-hunter.yml` runs the agent every day at 05:13 UTC
(08:13 Israel time in winter) on GitHub's computers, then saves
`price_history.json` back to the repo so the next run remembers today's prices.

One-time setup: in the repo on GitHub, open **Settings, then Secrets and
variables, then Actions** and add these repository secrets:

| Secret | Value |
|---|---|
| `GEMINI_API_KEY` | your Gemini key |
| `SERPAPI_KEY` | your SerpApi key |
| `GMAIL_ADDRESS` | your Gmail address |
| `GMAIL_APP_PASSWORD` | your 16-letter Gmail app password |
| `EMAIL_TO` (optional) | another address to send to |

Test it: open the **Actions** tab, choose **Flight Deal Hunter**, then **Run workflow**.
Every run also keeps a copy of the email under the run's **Artifacts** for 14 days.
