"""Daily flight price checker.

Every morning this script:
    1. searches Google Flights (through SerpApi) for each route in config.json
    2. asks Claude to turn the results into a short, readable email
    3. sends that email to you through Gmail

Run with --dry-run to print the email instead of sending it.
"""

import json
import os
import smtplib
import sys
from datetime import date
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import quote

import anthropic
import requests

CONFIG_FILE = Path(__file__).parent / "config.json"
MODEL = "claude-opus-5-5"
MAX_FLIGHTS_PER_ROUTE = 5

SYSTEM_PROMPT = """You write a short daily flight-price email.
You get JSON with today's search results for each route the user watches.

For each route:
- Lead with the cheapest price found and the airline(s), stops and duration.
- Say whether Google rates the price as low, typical or high, and compare it to
  the typical price range when that data is there.
- If the route has a max_price and the cheapest fare is at or below it, flag it
  clearly at the top of the email as a deal worth buying.
- Include the route's booking_link as a "View and book" link.

For round trips (routes with a return_date) the price is the total round-trip
fare, and the times shown are for the outbound flight.

Use only the prices and links in the data - never invent them. If a route has an
error or no flights, say so in one line.

Return only the HTML body of the email (no <html> or <head> tags), using simple
inline styles so it renders well in Gmail."""


# ---------------------------------------------------------------------------
# 1. Search flights
# ---------------------------------------------------------------------------

def google_flights_link(route: dict) -> str:
    query = f"Flights from {route['from']} to {route['to']} on {route['depart_date']}"
    if route.get("return_date"):
        query += f" through {route['return_date']}"
    return f"https://www.google.com/travel/flights?q={quote(query)}"


def summarize_flight(option: dict) -> dict:
    legs = option.get("flights", [])
    return {
        "price": option.get("price"),
        "airlines": sorted({leg.get("airline") for leg in legs if leg.get("airline")}),
        "stops": max(len(legs) - 1, 0),
        "total_duration_minutes": option.get("total_duration"),
        "departs": legs[0].get("departure_airport", {}).get("time") if legs else None,
        "arrives": legs[-1].get("arrival_airport", {}).get("time") if legs else None,
    }


def search_route(route: dict, currency: str) -> dict:
    params = {
        "engine": "google_flights",
        "departure_id": route["from"],
        "arrival_id": route["to"],
        "outbound_date": route["depart_date"],
        "type": 1 if route.get("return_date") else 2,  # 1 = round trip, 2 = one way
        "adults": route.get("adults", 1),
        "currency": currency,
        "hl": "en",
        "api_key": os.environ["SERPAPI_KEY"],
    }
    if route.get("return_date"):
        params["return_date"] = route["return_date"]

    result = {
        "route": route,
        "booking_link": google_flights_link(route),
    }
    try:
        response = requests.get("https://serpapi.com/search", params=params, timeout=60)
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as e:
        result["error"] = str(e)
        return result

    if "error" in data:
        result["error"] = data["error"]
        return result

    options = data.get("best_flights", []) + data.get("other_flights", [])
    options = [o for o in options if o.get("price") is not None]
    options.sort(key=lambda o: o["price"])
    result["cheapest_flights"] = [summarize_flight(o) for o in options[:MAX_FLIGHTS_PER_ROUTE]]

    insights = data.get("price_insights", {})
    result["price_insights"] = {
        "lowest_price": insights.get("lowest_price"),
        "price_level": insights.get("price_level"),
        "typical_price_range": insights.get("typical_price_range"),
    }
    # Prefer SerpApi's exact Google Flights link for this search when it returns one.
    result["booking_link"] = data.get("search_metadata", {}).get(
        "google_flights_url", result["booking_link"]
    )
    return result


# ---------------------------------------------------------------------------
# 2. Ask Claude to write the summary
# ---------------------------------------------------------------------------

def write_summary(results: list[dict], currency: str) -> str:
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
    payload = {"date": date.today().isoformat(), "currency": currency, "routes": results}
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": json.dumps(payload, indent=2)}],
        output_config={"effort": "low"},
        # If a safety classifier declines, retry on Anthropic's recommended fallback model.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("Claude declined to write the summary")
    return "".join(b.text for b in response.content if b.type == "text")


# ---------------------------------------------------------------------------
# 3. Send the email
# ---------------------------------------------------------------------------

def send_email(subject: str, html_body: str) -> None:
    sender = os.environ["GMAIL_ADDRESS"]
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = os.environ.get("EMAIL_TO") or sender
    message.set_content("Your email client does not support HTML. Open this email in Gmail.")
    message.add_alternative(html_body, subtype="html")

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(sender, os.environ["GMAIL_APP_PASSWORD"])
        smtp.send_message(message)


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    config = json.loads(CONFIG_FILE.read_text())
    currency = config.get("currency", "USD")

    results = []
    for route in config["routes"]:
        print(f"Searching {route['name']}...")
        results.append(search_route(route, currency))

    html = write_summary(results, currency)

    prices = [r["cheapest_flights"][0]["price"] for r in results if r.get("cheapest_flights")]
    subject = f"Flight prices {date.today():%b %d}"
    if prices:
        subject += f" - from {min(prices)} {currency}"

    if dry_run:
        print(f"\nSubject: {subject}\n\n{html}")
    else:
        send_email(subject, html)
        print(f"Sent: {subject}")


if __name__ == "__main__":
    main()
