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
trip_routes = {}  # trip name -> route, set by hunter.py
trip_settings = {}  # route -> the trip from watchlist.json (filters, bags), set by hunter.py


def settings_for(route: str) -> dict:
    """The filters you chose for a route. The AI can't change these."""
    trip = trip_settings.get(route, {})
    return {
        "direct_only": bool(trip.get("direct_only", False)),
        "carry_on_bags": int(trip.get("carry_on_bags", 0)),
        "checked_bags": int(trip.get("checked_bags", 0)),
        "checked_bag_fee_estimate": float(trip.get("checked_bag_fee_estimate", 0)),
    }
MIN_DAYS_FOR_BUY = 3  # BUY NOW needs this many earlier days of history


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

def matching_records(route: str) -> list:
    """Past prices searched with the same filters (direct-only, cabin bags), so they compare fairly."""
    wanted = settings_for(route)
    return [
        r for r in load_history().get(route, [])
        if r.get("direct_only", False) == wanted["direct_only"]
        and r.get("carry_on_bags", 0) == wanted["carry_on_bags"]
    ]


def get_price_history(origin: str, destination: str) -> dict:
    """Every price we've seen for this route, plus the lowest one."""
    records = matching_records(route_key(origin, destination))
    if not records:
        return {"route": route_key(origin, destination), "message": "No history yet."}
    lowest = min(records, key=lambda r: r["cheapest_price"])
    return {
        "route": route_key(origin, destination),
        "searches_so_far": len(records),
        "earlier_days_checked": earlier_days(route_key(origin, destination)),
        "lowest_ever": lowest,
        "recent": records[-15:],
    }


def earlier_days(route: str) -> int:
    """On how many different days BEFORE today we checked this route."""
    today = date.today().isoformat()
    days = {r["checked_at"][:10] for r in matching_records(route)}
    return len({d for d in days if d < today})


# --- Tool 2: search flights (and remember the result) ----------------------

def google_flights_link(origin, destination, depart_date, return_date) -> str:
    query = f"Flights from {origin} to {destination} on {depart_date} through {return_date}"
    return f"https://www.google.com/travel/flights?q={quote(query)}"


def fake_search(depart_date: str, carry_on_bags: int = 0) -> dict:
    """Made-up but realistic-looking prices for practice runs."""
    day = date.fromisoformat(depart_date)
    base = 900 + 60 * (day.weekday() in (4, 5, 6)) + random.randint(-120, 120) + 30 * carry_on_bags
    return {
        "best_flights": [
            {"price": base + i * 70, "total_duration": 175 + i * 90,
             "flights": [{"airline": airline,
                          "extensions": ["Checked baggage for a fee", "Average legroom (29 in)"]}]
                        * (1 + (i > 0))}
            for i, airline in enumerate(["Wizz Air", "El Al", "LOT"])
        ],
        "price_insights": {"price_level": random.choice(["low", "typical", "high"]),
                           "typical_price_range": [850, 1150]},
    }


def serpapi_search(origin, destination, depart_date, return_date, adults, direct_only,
                   carry_on_bags) -> dict:
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
            "stops": 1 if direct_only else 0,  # 1 = nonstop only, 0 = any number of stops
            "bags": min(carry_on_bags, adults),  # cabin bags: their fees are included in the price
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
    settings = settings_for(route_key(origin, destination))  # set by you, not the AI
    direct_only = settings["direct_only"]
    try:
        return_date = (date.fromisoformat(depart_date) + timedelta(days=int(nights))).isoformat()
    except ValueError:
        return {"error": f"Bad date '{depart_date}', use YYYY-MM-DD"}
    if searches_left <= 0:
        return {"error": "Search budget for today is used up. Work with what you have."}
    searches_left -= 1

    if FAKE_MODE:
        data = fake_search(depart_date, settings["carry_on_bags"])
    else:
        data = serpapi_search(origin, destination, depart_date, return_date, adults, direct_only,
                              settings["carry_on_bags"])
    if "error" in data:
        return {"error": data["error"]}

    options = [o for o in data.get("best_flights", []) + data.get("other_flights", [])
               if o.get("price")]
    if direct_only:  # double-check in code: one flight segment = no stops
        options = [o for o in options if len(o.get("flights", [])) == 1]
    if not options:
        kind = "direct flights" if direct_only else "flights"
        return {"error": f"No {kind} found for {depart_date} - {return_date}"}
    options.sort(key=lambda o: o["price"])

    # Checked suitcases aren't in Google's price: add your estimate, both directions.
    suitcases = settings["checked_bags"] * settings["checked_bag_fee_estimate"] * 2
    cheapest = [
        {
            "price": o["price"],  # tickets (+ cabin bags, if you set carry_on_bags)
            "total_with_bags": round(o["price"] + suitcases),  # + estimated suitcase fees
            "airlines": sorted({leg.get("airline", "?") for leg in o.get("flights", [])}),
            "stops": max(len(o.get("flights", [])) - 1, 0),
            "duration_minutes": o.get("total_duration"),
            "baggage_notes": sorted({ext for leg in o.get("flights", [])
                                     for ext in leg.get("extensions", []) if "bag" in ext.lower()}),
        }
        for o in options[:3]
    ]
    insights = data.get("price_insights", {})
    result = {
        "route": route_key(origin, destination),
        "depart_date": depart_date,
        "return_date": return_date,
        "adults": adults,
        "cabin_bags_included_in_price": settings["carry_on_bags"],
        "estimated_suitcase_fees": round(suitcases),
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
        "total_with_bags": cheapest[0]["total_with_bags"],
        "google_price_level": insights.get("price_level"),
        "direct_only": direct_only,
        "carry_on_bags": settings["carry_on_bags"],
    })
    todays_results.append(result)
    # The AI doesn't get the link, so it can't miscopy it.
    return {k: v for k, v in result.items() if k != "booking_link"}


def links_table() -> str:
    """Booking links for today's searches, written by code so they are always correct."""
    if not todays_results:
        return ""
    lines = ["Booking links (checked by code, cheapest first, totals include bags):"]
    for r in sorted(todays_results, key=lambda r: r["cheapest_options"][0]["total_with_bags"]):
        best = r["cheapest_options"][0]
        stops = "direct" if best["stops"] == 0 else f"{best['stops']} stop(s)"
        lines.append(
            f"  ${best['total_with_bags']:>6}  {r['depart_date']} -> {r['return_date']}  "
            f"{', '.join(best['airlines'])}, {stops}\n          {r['booking_link']}"
        )
    return "\n".join(lines)


# --- Tool 3: hand in the final verdict --------------------------------------

def submit_report(trip_name: str, verdict: str, headline: str, reasoning: str) -> dict:
    """The agent's final answer for one trip, as structured data for the email."""
    if verdict not in ("BUY NOW", "WAIT", "WATCH"):
        return {"error": "verdict must be BUY NOW, WAIT or WATCH"}
    # A rule that matters is enforced here in code, not just asked for in the prompt.
    route = trip_routes.get(trip_name)
    if verdict == "BUY NOW" and route and earlier_days(route) < MIN_DAYS_FOR_BUY:
        return {"error": f"Rejected: BUY NOW needs at least {MIN_DAYS_FOR_BUY} earlier days "
                         f"of history, but there are only {earlier_days(route)}. "
                         "Submit again with WATCH and explain what you're waiting to learn."}
    reports[trip_name] = {"verdict": verdict, "headline": headline, "reasoning": reasoning}
    return {"saved": True}
