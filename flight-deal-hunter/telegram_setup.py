"""Find your Telegram chat ID and send a test message.

1. Save your bot token:  setx TELEGRAM_BOT_TOKEN "123456:ABC..."  (then restart VS Code)
2. Run:  .venv\\Scripts\\python.exe telegram_setup.py
3. When it says "Waiting...", send your bot any message in Telegram, e.g. "hi"
   (or add the bot to a group and send /start@yourbot in the group)
"""

import os
import sys

import requests

token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
if not token:
    sys.exit("TELEGRAM_BOT_TOKEN isn't set. Save it with setx, then restart VS Code.")
api = f"https://api.telegram.org/bot{token}"

me = requests.get(f"{api}/getMe", timeout=30).json()
if not me.get("ok"):
    sys.exit(f"Telegram didn't accept the token: {me.get('description')}")
bot = me["result"]["username"]
print(f"Your bot is @{bot}  ->  https://t.me/{bot}")

# If a webhook was ever set, Telegram won't hand out messages here. Remove it.
requests.get(f"{api}/deleteWebhook", timeout=30)

chats = {}
for attempt in range(3):
    if attempt == 0:
        print(f"\nWaiting... open https://t.me/{bot} in Telegram, press Start, and send 'hi'.")
    data = requests.get(f"{api}/getUpdates", params={"timeout": 25}, timeout=40).json()
    for update in data.get("result", []):
        message = update.get("message") or update.get("my_chat_member") or {}
        chat = message.get("chat")
        if chat:
            chats[chat["id"]] = chat.get("title") or chat.get("first_name") or chat.get("username")
    if chats:
        break

if not chats:
    sys.exit(f"\nNo message arrived. Make sure you're writing to @{bot} (not BotFather), "
             "then run this again.")

print("\nChats that have messaged your bot:")
for chat_id, name in chats.items():
    print(f"  {name}:  {chat_id}")
    requests.post(f"{api}/sendMessage",
                  json={"chat_id": chat_id, "text": "✅ Your Flight Deal Hunter can reach this chat!"},
                  timeout=30)
print("\nA test message was sent to each chat. Save the ID you want with:")
print('  setx TELEGRAM_CHAT_ID "the-id"     (several: "id1,id2")')
