"""The agent's tools: search flights, remember prices, look up price history.

Set FAKE_FLIGHTS=1 to use made-up prices while you develop, so you don't
spend your free SerpApi searches.
"""

import json
import os
import random
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import requests

FAKE_MODE = os.environ.get("FAKE_FLIGHTS") == "1"
HERE = Path(__file__).parent
HISTORY_FILE = HERE / ("price_history_fake.json" if FAKE_MODE else "price_history.json")

searches_left = 0  # set by the agent at the start of each run
todays_results = []  # every successful search in this run, for the email
reports = {}  # the agent's verdict for each trip, filled by submit_report


# --- Price memory: a simple JSON file -------------------------------------

def load_history() -> dict:
    if HISTORY_FILE.exists():
        return json.loads(HISTORY_FILE.read_text())
    return {}


def save_price(route: str, record: dict) -> None:
    history = load_history()
    history.setdefault(route, []).append(record)
    HISTORY_FILE.write_text(json.dumps(history, indent=2))


def route_key(origin: str, destination: str) -> str:
    return f"{origin.upper()}-{destination.upper()}"


# --- Tool 1: look at past prices -------------------------------------------

def get_price_history(origin: str, destination: str) -> dict:
    """Every price we've seen for this route, plus the lowest one."""
    records = load_history().get(route_key(origin, destination), [])
    if not records:
        return {"route": route_key(origin, destination), "message": "No history yet."}
    lowest = min(records, key=lambda r: r["cheapest_price"])
    return {
        "route": route_key(origin, destination),
        "searches_so_far": len(records),
        "lowest_ever": lowest,
        "recent": records[-15:],
    }


# --- Tool 2: search flights (and remember the result) ----------------------

def google_flights_link(origin, destination, depart_date, return_date) -> str:
    query = f"Flights from {origin} to {destination} on {depart_date} through {return_date}"
    return f"https://www.google.com/travel/flights?q={quote(query)}"


def fake_search(depart_date: str) -> dict:
    """Made-up but realistic-looking prices for practice runs."""
    day = date.fromisoformat(depart_date)
    base = 900 + 60 * (day.weekday() in (4, 5, 6)) + random.randint(-120, 120)
    return {
        "best_flights": [
            {"price": base + i * 70, "total_duration": 175 + i * 90,
             "flights": [{"airline": airline}] * (1 + (i > 0))}
            for i, airline in enumerate(["Wizz Air", "El Al", "LOT"])
        ],
        "price_insights": {"price_level": random.choice(["low", "typical", "high"]),
                           "typical_price_range": [850, 1150]},
    }


def serpapi_search(origin, destination, depart_date, return_date, adults) -> dict:
    response = requests.get(
        "https://serpapi.com/search",
        params={
            "engine": "google_flights",
            "departure_id": origin,
            "arrival_id": destination,
            "outbound_date": depart_date,
            "return_date": return_date,
            "type": 1,  # round trip
            "adults": adults,
            "currency": "USD",
            "hl": "en",
            "api_key": os.environ["SERPAPI_KEY"],
        },
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


def search_flights(origin: str, destination: str, depart_date: str,
                   nights: int, adults: int = 1) -> dict:
    """Search round-trip flights leaving on depart_date for `nights` nights. Costs one search."""
    global searches_left
    try:
        return_date = (date.fromisoformat(depart_date) + timedelta(days=int(nights))).isoformat()
    except ValueError:
        return {"error": f"Bad date '{depart_date}', use YYYY-MM-DD"}
    if searches_left <= 0:
        return {"error": "Search budget for today is used up. Work with what you have."}
    searches_left -= 1

    if FAKE_MODE:
        data = fake_search(depart_date)
    else:
        data = serpapi_search(origin, destination, depart_date, return_date, adults)
    if "error" in data:
        return {"error": data["error"]}

    options = [o for o in data.get("best_flights", []) + data.get("other_flights", [])
               if o.get("price")]
    if not options:
        return {"error": f"No flights found for {depart_date} - {return_date}"}
    options.sort(key=lambda o: o["price"])

    cheapest = [
        {
            "price": o["price"],
            "airlines": sorted({leg.get("airline", "?") for leg in o.get("flights", [])}),
            "stops": max(len(o.get("flights", [])) - 1, 0),
            "duration_minutes": o.get("total_duration"),
        }
        for o in options[:3]
    ]
    insights = data.get("price_insights", {})
    result = {
        "route": route_key(origin, destination),
        "depart_date": depart_date,
        "return_date": return_date,
        "adults": adults,
        "cheapest_options": cheapest,
        "google_price_level": insights.get("price_level"),
        "typical_price_range": insights.get("typical_price_range"),
        "booking_link": google_flights_link(origin, destination, depart_date, return_date),
        "searches_left_today": searches_left,
    }

    # Remember every search, so tomorrow's run can compare.
    save_price(route_key(origin, destination), {
        "checked_at": datetime.now().isoformat(timespec="minutes"),
        "depart_date": depart_date,
        "return_date": return_date,
        "cheapest_price": cheapest[0]["price"],
        "google_price_level": insights.get("price_level"),
    })
    todays_results.append(result)
    # The AI doesn't get the link, so it can't miscopy it.
    return {k: v for k, v in result.items() if k != "booking_link"}


def links_table() -> str:
    """Booking links for today's searches, written by code so they are always correct."""
    if not todays_results:
        return ""
    lines = ["Booking links (checked by code, cheapest first):"]
    for r in sorted(todays_results, key=lambda r: r["cheapest_options"][0]["price"]):
        best = r["cheapest_options"][0]
        stops = "direct" if best["stops"] == 0 else f"{best['stops']} stop(s)"
        lines.append(
            f"  ${best['price']:>6}  {r['depart_date']} -> {r['return_date']}  "
            f"{', '.join(best['airlines'])}, {stops}\n          {r['booking_link']}"
        )
    return "\n".join(lines)


# --- Tool 3: hand in the final verdict --------------------------------------

def submit_report(trip_name: str, verdict: str, headline: str, reasoning: str) -> dict:
    """The agent's final answer for one trip, as structured data for the email."""
    if verdict not in ("BUY NOW", "WAIT", "WATCH"):
        return {"error": "verdict must be BUY NOW, WAIT or WATCH"}
    reports[trip_name] = {"verdict": verdict, "headline": headline, "reasoning": reasoning}
    return {"saved": True}
