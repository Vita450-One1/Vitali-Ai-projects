"""Build the results email (HTML) and send it with Gmail.

Everything in the email - prices, dates, links - comes straight from the data.
Only the verdict, headline and reasoning are written by the AI.
"""

import os
import smtplib
from datetime import date
from email.message import EmailMessage
from html import escape
from pathlib import Path

PREVIEW_FILE = Path(__file__).parent / "last_email.html"

VERDICT_STYLES = {
    "BUY NOW": ("#0f7b3f", "#e3f5ea", "🟢"),
    "WATCH": ("#9a6700", "#fff4d6", "🟡"),
    "WAIT": ("#4a5568", "#edf0f4", "⏳"),
}
FONT = "font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;"


def money(value) -> str:
    return f"${value:,.0f}"


def duration(minutes) -> str:
    if not minutes:
        return "-"
    return f"{minutes // 60}h {minutes % 60:02d}m"


def nice_date(iso: str) -> str:
    return date.fromisoformat(iso).strftime("%a %d %b")


def daily_lows(records: list) -> list:
    """Lowest price found on each day the agent ran, oldest first."""
    lows = {}
    for r in records:
        day = r["checked_at"][:10]
        lows[day] = min(lows.get(day, r["cheapest_price"]), r["cheapest_price"])
    return sorted(lows.items())


# --- Building blocks ---------------------------------------------------------

def stat_box(label: str, value: str, color: str = "#1a202c") -> str:
    return f"""
      <td style="padding:12px;background:#f7f9fc;border-radius:10px;text-align:center;width:33%;">
        <div style="font-size:12px;color:#718096;text-transform:uppercase;letter-spacing:.5px;">{label}</div>
        <div style="font-size:22px;font-weight:700;color:{color};margin-top:4px;">{value}</div>
      </td>"""


def results_table(results: list, budget: float) -> str:
    rows = []
    cheapest_price = results[0]["cheapest_options"][0]["price"] if results else None
    for r in results:
        best = r["cheapest_options"][0]
        is_cheapest = best["price"] == cheapest_price
        price_color = "#0f7b3f" if best["price"] <= budget else "#c53030"
        stops = "Direct" if best["stops"] == 0 else f"{best['stops']} stop{'s' * (best['stops'] > 1)}"
        rows.append(f"""
        <tr style="background:{'#f0fbf4' if is_cheapest else '#ffffff'};">
          <td style="padding:10px 8px;border-bottom:1px solid #edf2f7;">
            <b>{nice_date(r['depart_date'])}</b> → {nice_date(r['return_date'])}
            {'<span style="background:#0f7b3f;color:#fff;font-size:11px;padding:2px 6px;border-radius:8px;margin-left:4px;">BEST</span>' if is_cheapest else ''}
          </td>
          <td style="padding:10px 8px;border-bottom:1px solid #edf2f7;">{escape(', '.join(best['airlines']))}<br>
            <span style="color:#718096;font-size:12px;">{stops} · {duration(best['duration_minutes'])}</span></td>
          <td style="padding:10px 8px;border-bottom:1px solid #edf2f7;text-align:right;font-weight:700;color:{price_color};">{money(best['price'])}</td>
          <td style="padding:10px 8px;border-bottom:1px solid #edf2f7;text-align:right;">
            <a href="{escape(r['booking_link'])}" style="background:#2b6cb0;color:#fff;text-decoration:none;padding:6px 12px;border-radius:6px;font-size:13px;">View</a>
          </td>
        </tr>""")
    return f"""
      <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;font-size:14px;margin-top:8px;">
        <tr style="color:#718096;font-size:12px;text-transform:uppercase;">
          <th align="left" style="padding:6px 8px;">Dates</th><th align="left" style="padding:6px 8px;">Airline</th>
          <th align="right" style="padding:6px 8px;">Total</th><th></th>
        </tr>{''.join(rows)}
      </table>"""


def history_chart(records: list, budget: float) -> str:
    lows = daily_lows(records)[-10:]
    if len(lows) < 2:
        return '<p style="color:#718096;font-size:13px;">The price chart appears after a few days of checking.</p>'
    top = max(price for _, price in lows + [("", budget)])
    rows = []
    for day, price in lows:
        width = max(int(price / top * 100), 4)
        color = "#38a169" if price <= budget else "#e53e3e"
        rows.append(f"""
        <tr>
          <td style="padding:3px 8px 3px 0;font-size:12px;color:#718096;white-space:nowrap;">{date.fromisoformat(day).strftime('%d %b')}</td>
          <td style="padding:3px 0;width:100%;"><div style="background:{color};width:{width}%;height:14px;border-radius:4px;"></div></td>
          <td style="padding:3px 0 3px 8px;font-size:12px;font-weight:600;white-space:nowrap;">{money(price)}</td>
        </tr>""")
    return f"""
      <table width="100%" cellpadding="0" cellspacing="0">{''.join(rows)}</table>
      <p style="color:#718096;font-size:12px;margin:6px 0 0;">Cheapest price found each day · green = under your {money(budget)} budget</p>"""


def trip_card(trip: dict, report: dict, results: list, records: list) -> str:
    budget = trip["max_total_price"]
    verdict = report.get("verdict", "WATCH")
    color, background, icon = VERDICT_STYLES.get(verdict, VERDICT_STYLES["WATCH"])
    results = sorted(results, key=lambda r: r["cheapest_options"][0]["price"])
    best_today = results[0]["cheapest_options"][0]["price"] if results else None
    lowest_ever = min((r["cheapest_price"] for r in records), default=None)
    budget_color = "#0f7b3f" if best_today and best_today <= budget else "#c53030"

    return f"""
    <table width="100%" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:14px;margin-bottom:20px;box-shadow:0 1px 3px rgba(0,0,0,.08);">
      <tr><td style="padding:24px;">
        <div style="font-size:20px;font-weight:700;color:#1a202c;">{escape(trip['name'])}</div>
        <div style="color:#718096;font-size:14px;margin-top:4px;">
          {escape(trip['from'])} ⇄ {escape(trip['to'])} · {trip['adults']} travelers · {trip['nights']} nights ·
          leaving {nice_date(trip['earliest_departure'])} – {nice_date(trip['latest_departure'])}
        </div>

        <div style="background:{background};border-radius:10px;padding:16px;margin:18px 0;">
          <span style="background:{color};color:#fff;font-weight:700;font-size:13px;padding:4px 10px;border-radius:12px;">{icon} {escape(verdict)}</span>
          <div style="font-size:16px;font-weight:600;color:#1a202c;margin-top:10px;">{escape(report.get('headline', ''))}</div>
          <div style="font-size:14px;color:#4a5568;margin-top:6px;line-height:1.5;">{escape(report.get('reasoning', ''))}</div>
        </div>

        <table width="100%" cellpadding="0" cellspacing="6"><tr>
          {stat_box("Best today", money(best_today) if best_today else "-", budget_color)}
          {stat_box("Lowest ever", money(lowest_ever) if lowest_ever else "-")}
          {stat_box("Your budget", money(budget))}
        </tr></table>

        <div style="font-size:15px;font-weight:700;color:#1a202c;margin-top:22px;">Today's results</div>
        {results_table(results, budget) if results else '<p style="color:#718096;">No results today.</p>'}

        <div style="font-size:15px;font-weight:700;color:#1a202c;margin-top:22px;">Price trend</div>
        {history_chart(records, budget)}
      </td></tr>
    </table>"""


def build_email(watchlist: dict, reports: dict, results: list, history: dict,
                fake: bool, searches_used: int) -> tuple[str, str]:
    """Returns (subject, html)."""
    cards = []
    subject_parts = []
    for trip in watchlist["trips"]:
        route = f"{trip['from'].upper()}-{trip['to'].upper()}"
        trip_results = [r for r in results if r["route"] == route]
        report = reports.get(trip["name"], {"verdict": "WATCH", "headline": "",
                                            "reasoning": "The agent didn't give a verdict this time."})
        cards.append(trip_card(trip, report, trip_results, history.get(route, [])))
        best = min((r["cheapest_options"][0]["price"] for r in trip_results), default=None)
        subject_parts.append(f"{trip['to']} {report['verdict']}" + (f" from {money(best)}" if best else ""))

    subject = ("[TEST - fake prices] " if fake else "") + "✈️ " + " | ".join(subject_parts)
    fake_banner = """
      <div style="background:#fed7d7;color:#9b2c2c;padding:10px;border-radius:8px;text-align:center;font-weight:600;margin-bottom:16px;">
        Practice run: these prices are made up.
      </div>""" if fake else ""

    html = f"""<!doctype html>
<html><body style="margin:0;padding:0;background:#eef2f7;{FONT}">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#eef2f7;"><tr><td align="center" style="padding:24px 12px;">
    <table width="100%" cellpadding="0" cellspacing="0" style="max-width:640px;">
      <tr><td style="background:linear-gradient(135deg,#1e3a8a,#3b82f6);background-color:#1e3a8a;border-radius:14px;padding:28px 24px;margin-bottom:20px;">
        <div style="color:#bfdbfe;font-size:13px;letter-spacing:1px;text-transform:uppercase;">Flight Deal Hunter</div>
        <div style="color:#ffffff;font-size:26px;font-weight:700;margin-top:6px;">Your daily price report</div>
        <div style="color:#dbeafe;font-size:14px;margin-top:4px;">{date.today().strftime('%A, %d %B %Y')}</div>
      </td></tr>
      <tr><td style="height:20px;"></td></tr>
      <tr><td>{fake_banner}{''.join(cards)}</td></tr>
      <tr><td style="color:#718096;font-size:12px;text-align:center;padding:8px 16px 24px;line-height:1.6;">
        Prices are round-trip totals for all travelers, from Google Flights.
        Always confirm the final price before you book.<br>
        {searches_used} searches used this run · sent by your AI agent 🤖
      </td></tr>
    </table>
  </td></tr></table>
</body></html>"""
    return subject, html


def send_email(subject: str, html: str) -> None:
    sender = os.environ["GMAIL_ADDRESS"]
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = f"Flight Deal Hunter <{sender}>"
    message["To"] = os.environ.get("EMAIL_TO") or sender
    message.set_content("Open this email in an app that shows HTML to see your flight report.")
    message.add_alternative(html, subtype="html")
    password = os.environ["GMAIL_APP_PASSWORD"].replace(" ", "")

    try:  # Gmail's usual secure connection
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
            smtp.login(sender, password)
            smtp.send_message(message)
    except smtplib.SMTPAuthenticationError:
        raise RuntimeError("Gmail rejected the address or app password.") from None
    except (smtplib.SMTPServerDisconnected, OSError):
        # Some networks and antivirus programs block port 465: try port 587 instead.
        try:
            with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as smtp:
                smtp.starttls()
                smtp.login(sender, password)
                smtp.send_message(message)
        except smtplib.SMTPAuthenticationError:
            raise RuntimeError("Gmail rejected the address or app password.") from None
