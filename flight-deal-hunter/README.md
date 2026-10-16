# Smart Flight Deal Hunter

An AI agent that watches flight prices for your trips, remembers every price it
sees, and tells you whether to **BUY NOW**, **WAIT**, or **WATCH**.

| Step | What it adds | Status |
|---|---|---|
| 1 | Smart searching with a search budget, price memory, verdicts | ✅ |
| 2 | Emails you only when there's a real reason | next |
| 3 | Runs every morning by itself (GitHub Actions) | later |

## Files

| File | Job |
|---|---|
| `watchlist.json` | Your trips: route, date window, nights, travelers, budget |
| `tools.py` | The tools: `search_flights`, `get_price_history`, and the price memory |
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

## Why a search budget?

SerpApi's free plan gives about 250 searches a month, roughly 8 a day. Instead of
checking every date, the agent gets `searches_per_run` searches and must
**decide** which dates are worth checking. It uses past prices to choose.
Choosing how to spend a limited resource is a core agent skill.
