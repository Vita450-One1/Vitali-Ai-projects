"""Send a short Telegram message with today's result.

Needs two settings (Windows: setx, GitHub: repository secrets):
  TELEGRAM_BOT_TOKEN  the token BotFather gave you
  TELEGRAM_CHAT_ID    who gets the message; several IDs separated by commas
Run `python telegram_setup.py` to find your chat ID.
"""

import os
from datetime import date
from html import escape

import requests

from email_report import money, nice_date, record_total, total

VERDICT_ICONS = {"BUY NOW": "🟢", "WATCH": "🟡", "WAIT": "⏳"}


def earlier_lowest(records: list) -> float | None:
    """The lowest total seen BEFORE today (today's prices are already in the history)."""
    today = date.today().isoformat()
    earlier = [record_total(r) for r in records if r["checked_at"][:10] < today]
    return min(earlier, default=None)


def trip_message(trip: dict, report: dict, results: list, records: list) -> tuple[str, bool]:
    """Returns (message text, is it important today?)."""
    verdict = report.get("verdict", "WATCH")
    lines = [f"✈️ <b>{escape(trip['name'])}</b>: {VERDICT_ICONS.get(verdict, '')} <b>{escape(verdict)}</b>"]
    if report.get("headline"):
        lines.append(escape(report["headline"]))

    if not results:
        lines.append("No prices found today.")
        return "\n".join(lines), verdict == "BUY NOW"

    best_result = min(results, key=lambda r: total(r["cheapest_options"][0]))
    best = best_result["cheapest_options"][0]
    best_total = total(best)
    budget = trip["max_total_price"]
    stops = "direct" if best["stops"] == 0 else f"{best['stops']} stop(s)"
    previous_low = earlier_lowest(records)
    new_low = previous_low is not None and best_total < previous_low

    lines.append("")
    lines.append(f"💰 Best today: <b>{money(best_total)}</b> total "
                 f"({escape(', '.join(best['airlines']))}, {stops})")
    lines.append(f"📅 {nice_date(best_result['depart_date'])} → {nice_date(best_result['return_date'])}")
    cabin, checked = trip.get("carry_on_bags", 0), trip.get("checked_bags", 0)
    if cabin or checked:
        lines.append(f"🧳 incl. {cabin} cabin bag(s) + {checked} suitcase(s, estimated)")
    lines.append(f"🎯 Budget {money(budget)}: {'✅ under' if best_total <= budget else '❌ over'}")
    if new_low:
        lines.append(f"📉 <b>New lowest price!</b> (before: {money(previous_low)})")
    elif previous_low is not None:
        lines.append(f"📊 Lowest before today: {money(previous_low)}")
    lines.append(f'🔗 <a href="{escape(best_result["booking_link"])}">View on Google Flights</a>')

    important = verdict == "BUY NOW" or new_low
    return "\n".join(lines), important


def build_messages(watchlist: dict, reports: dict, results: list, history: dict,
                   fake: bool) -> list[str]:
    """One message per trip, following each trip's "telegram" setting."""
    messages = []
    for trip in watchlist["trips"]:
        route = f"{trip['from'].upper()}-{trip['to'].upper()}"
        text, important = trip_message(
            trip, reports.get(trip["name"], {}),
            [r for r in results if r["route"] == route], history.get(route, []),
        )
        mode = trip.get("telegram", "every_day")  # "every_day", "important_only" or "off"
        if mode == "off" or (mode == "important_only" and not important):
            continue
        if fake:
            text = "🧪 <i>Practice run - made-up prices</i>\n" + text
        messages.append(text + "\n\n📧 Full report in your email")
    return messages


def send(text: str) -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"].strip()
    for chat_id in os.environ["TELEGRAM_CHAT_ID"].split(","):
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id.strip(), "text": text, "parse_mode": "HTML",
                  "disable_web_page_preview": True},
            timeout=30,
        )
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram said: {data.get('description', response.status_code)}")
