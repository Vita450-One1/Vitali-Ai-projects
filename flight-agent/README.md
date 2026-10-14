# Daily Flight Price Agent

Every morning it checks Google Flights for the trips you're watching and emails you
a short summary: the cheapest fares, whether today's price is low or high, a
**deal alert** when a fare drops under your target price, and a link to view and book.

```
GitHub Actions (every morning)
   -> flight_agent.py
        1. SerpApi Google Flights  -> today's prices for each route
        2. Claude                  -> writes the summary email
        3. Gmail                   -> sends it to you
```

> This is a *workflow* rather than a free-roaming agent: the code fetches the data
> and Claude does the part that needs judgement (comparing, highlighting, writing).
> For a daily job, that makes it cheaper and more predictable.

## 1. Choose your trips: `config.json`

```json
{
  "currency": "USD",
  "routes": [
    { "name": "New York to London", "from": "JFK", "to": "LHR",
      "depart_date": "2026-12-18", "return_date": "2027-01-03",
      "adults": 1, "max_price": 700 }
  ]
}
```

- `from` / `to`: airport codes (JFK, LHR, TLV...).
- Leave out `return_date` for a one-way trip.
- `max_price` (optional): when a fare is at or below this, the email flags it as a deal.

Each route uses one search per day, so 3 routes is about 90 searches a month.

## 2. Get the keys (one time)

| Secret | Where to get it |
|---|---|
| `ANTHROPIC_API_KEY` | https://platform.claude.com, under API keys |
| `SERPAPI_KEY` | Sign up at https://serpapi.com (there's a free monthly plan) and copy your key from the dashboard |
| `GMAIL_ADDRESS` | The Gmail address that sends the email |
| `GMAIL_APP_PASSWORD` | Google Account, then Security, then turn on 2-Step Verification, then **App passwords**. Create one, a 16-character code. This is *not* your normal password. |
| `EMAIL_TO` (optional) | Where to send the email. Defaults to `GMAIL_ADDRESS`. |

## 3. Test it on your computer

```bash
cd flight-agent
pip install -r requirements.txt
export ANTHROPIC_API_KEY=... SERPAPI_KEY=... GMAIL_ADDRESS=... GMAIL_APP_PASSWORD=...
python flight_agent.py --dry-run   # prints the email instead of sending it
python flight_agent.py             # sends it for real
```

## 4. Run it every morning

1. On GitHub, open the repo, then **Settings**, then **Secrets and variables**, then **Actions**,
   then **New repository secret**. Add each secret from the table above.
2. Open `.github/workflows/flight-agent.yml` and set the `cron` time. It is in **UTC**.
   For example, for 8:00 in New York (UTC-5) use `0 13 * * *`.
3. Open the **Actions** tab, choose **Daily flight prices**, then **Run workflow**, to test it right away.

## Ideas to extend it

- Save each day's prices to a file and include "down $40 since yesterday" in the email.
- Watch a date range ("any weekend in March") by searching several dates per route.
- Only send an email when there's a deal under `max_price`.
- Add a Telegram or WhatsApp message alongside the email.
