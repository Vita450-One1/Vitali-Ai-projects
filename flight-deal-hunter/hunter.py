"""Smart Flight Deal Hunter - Step 2: search smartly, remember, email the results.

Run:  python hunter.py               (real prices, uses SerpApi searches, sends email)
      python hunter.py --no-email    (skip the email, just save last_email.html)
      set FAKE_FLIGHTS=1 first to practice with made-up prices.
"""

import json
import os
import sys
import time
from datetime import date
from pathlib import Path

from google import genai
from google.genai import errors, types

import email_report
import tools

WATCHLIST_FILE = Path(__file__).parent / "watchlist.json"

# Tried in order: busy models are skipped, missing ones are dropped.
MODELS = [
    "gemini-flash-latest",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-flash-lite-latest",
    "gemini-3.5-flash-lite",
    "gemini-2.5-flash",
]

SYSTEM_PROMPT = f"""You are a flight deal hunter. Today is {date.today().isoformat()}.
For each trip on the watchlist you must find the best round-trip price and decide
whether the traveler should buy now.

How to work:
1. Start with get_price_history for each route to see what you already know.
2. You have a limited number of searches. Spend them wisely:
   - First spread a few searches across the WHOLE departure window, including
     the first and last allowed dates.
   - Then use the remaining searches near the cheapest dates you found, or near
     cheap dates from history.
   - Don't search the same dates twice in one run.
3. Every price is the TOTAL for all passengers.
4. When you're done, call submit_report ONCE for each trip with:
   - verdict: BUY NOW, WAIT, or WATCH.
     BUY NOW only if the price is at or below max_total_price AND you have
     history from at least 3 earlier DAYS (earlier_days_checked in the
     price history, NOT the number of dates searched) showing it is a good price (or prices
     are rising). With less history, choose WATCH. Choose WAIT when prices are
     clearly above normal and likely to drop.
   - headline: one short sentence with the key fact, e.g. "New lowest price:
     $847 for Aug 18-24" (no links - the email adds correct links itself).
   - reasoning: 2-4 sentences: how today compares with history, the cheapest
     DIRECT option if the cheapest one has stops, and what you're waiting for.
   After submitting all reports, reply with just: Done."""


# --- Tool descriptions (all the AI sees of tools.py) -----------------------

TOOL_DECLARATIONS = [
    types.FunctionDeclaration(
        name="get_price_history",
        description="Get all past prices recorded for a route, including the lowest ever. "
        "Free - doesn't use a search.",
        parameters_json_schema={
            "type": "object",
            "properties": {
                "origin": {"type": "string", "description": "Airport code, e.g. TLV"},
                "destination": {"type": "string", "description": "Airport code, e.g. BUD"},
            },
            "required": ["origin", "destination"],
        },
    ),
    types.FunctionDeclaration(
        name="search_flights",
        description="Search live round-trip prices for one departure date. "
        "Uses one search from today's limited budget. The result is saved to history.",
        parameters_json_schema={
            "type": "object",
            "properties": {
                "origin": {"type": "string"},
                "destination": {"type": "string"},
                "depart_date": {"type": "string", "description": "YYYY-MM-DD"},
                "nights": {"type": "integer", "description": "Length of stay"},
                "adults": {"type": "integer"},
            },
            "required": ["origin", "destination", "depart_date", "nights", "adults"],
        },
    ),
]

TOOL_DECLARATIONS.append(
    types.FunctionDeclaration(
        name="submit_report",
        description="Hand in your final verdict for one trip. Call once per trip, at the end.",
        parameters_json_schema={
            "type": "object",
            "properties": {
                "trip_name": {"type": "string", "description": "The trip's name from the watchlist"},
                "verdict": {"type": "string", "enum": ["BUY NOW", "WAIT", "WATCH"]},
                "headline": {"type": "string", "description": "One short sentence"},
                "reasoning": {"type": "string", "description": "2-4 sentences"},
            },
            "required": ["trip_name", "verdict", "headline", "reasoning"],
        },
    )
)

TOOL_FUNCTIONS = {
    "get_price_history": tools.get_price_history,
    "search_flights": tools.search_flights,
    "submit_report": tools.submit_report,
}


# --- Talking to Gemini (same retry/fallback idea as the trip planner) ------

client = genai.Client()  # reads GEMINI_API_KEY

config = types.GenerateContentConfig(
    system_instruction=SYSTEM_PROMPT,
    tools=[types.Tool(function_declarations=TOOL_DECLARATIONS)],
    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
)


def call_model(conversation: list):
    for attempt in range(4):
        for model in list(MODELS):
            try:
                return client.models.generate_content(
                    model=model, contents=conversation, config=config
                )
            except errors.APIError as e:
                if e.code == 404 and len(MODELS) > 1:
                    MODELS.remove(model)
                    continue
                if e.code not in (429, 503):
                    raise
                print(f"   [busy] {model} returned {e.code}")
                # 429 = this model's free quota is used up: skip it for the rest of the run.
                if e.code == 429 and len(MODELS) > 1:
                    MODELS.remove(model)
        wait = 10 * (attempt + 1)
        print(f"   [wait] all models busy, retrying in {wait} seconds...")
        time.sleep(wait)
    raise RuntimeError("Gemini is busy right now. Try again later.")


def run_agent(task: str) -> str:
    conversation = [types.Content(role="user", parts=[types.Part.from_text(text=task)])]
    for _ in range(25):  # safety limit: an agent should never loop forever
        response = call_model(conversation)
        conversation.append(response.candidates[0].content)
        if not response.function_calls:
            return response.text

        results = []
        for call in response.function_calls:
            print(f"   [tool] {call.name}({json.dumps(call.args)})")
            try:
                output = TOOL_FUNCTIONS[call.name](**call.args)
            except Exception as e:
                output = {"error": str(e)}
            results.append(types.Part.from_function_response(name=call.name, response=output))
        conversation.append(types.Content(role="user", parts=results))
    return "Stopped: the agent took too many steps."


def main() -> None:
    watchlist = json.loads(WATCHLIST_FILE.read_text())
    tools.searches_left = watchlist.get("searches_per_run", 6)
    tools.trip_routes = {t["name"]: tools.route_key(t["from"], t["to"]) for t in watchlist["trips"]}
    if tools.FAKE_MODE:
        print("*** FAKE MODE: prices are made up ***\n")

    task = (
        f"Here is the watchlist. You have {tools.searches_left} searches for this run.\n"
        + json.dumps(watchlist["trips"], indent=2)
    )
    searches_at_start = tools.searches_left
    final_message = run_agent(task)
    if not tools.reports:  # the agent forgot submit_report: keep its text instead
        for trip in watchlist["trips"]:
            tools.reports[trip["name"]] = {"verdict": "WATCH", "headline": "",
                                           "reasoning": final_message}

    for name, report in tools.reports.items():
        print(f"\n{name}: {report['verdict']} - {report['headline']}\n  {report['reasoning']}")
    print("\n" + tools.links_table())

    subject, html = email_report.build_email(
        watchlist, tools.reports, tools.todays_results, tools.load_history(),
        fake=tools.FAKE_MODE, searches_used=searches_at_start - tools.searches_left,
    )
    email_report.PREVIEW_FILE.write_text(html, encoding="utf-8")
    print(f"\nEmail preview saved: {email_report.PREVIEW_FILE.name} (double-click to open)")

    if "--no-email" in sys.argv:
        return
    if not (os.environ.get("GMAIL_ADDRESS") and os.environ.get("GMAIL_APP_PASSWORD")):
        print("Not sending: set GMAIL_ADDRESS and GMAIL_APP_PASSWORD to get it by email.")
        return
    try:
        email_report.send_email(subject, html)
        print(f"Email sent: {subject}")
    except Exception as e:
        print(f"\nEmail NOT sent: {e}")
        print("Check that GMAIL_ADDRESS is right and GMAIL_APP_PASSWORD is the 16-letter")
        print("app password (not your normal password). Antivirus email protection can")
        print("also block it. The report is still saved in last_email.html.")


if __name__ == "__main__":
    main()
