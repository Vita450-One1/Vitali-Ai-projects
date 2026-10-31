"""Find your Telegram chat ID and send a test message.

1. Save your bot token:  setx TELEGRAM_BOT_TOKEN "123456:ABC..."  (then restart VS Code)
2. Open your bot in Telegram and send it any message, e.g. "hi"
   (or add the bot to a group and send a message in the group)
3. Run:  .venv\\Scripts\\python.exe telegram_setup.py
"""

import os
import sys

import requests

token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
if not token:
    sys.exit("TELEGRAM_BOT_TOKEN isn't set. Save it with setx, then restart VS Code.")

data = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=30).json()
if not data.get("ok"):
    sys.exit(f"Telegram didn't accept the token: {data.get('description')}")

chats = {}
for update in data["result"]:
    message = update.get("message") or update.get("my_chat_member") or {}
    chat = message.get("chat")
    if chat:
        chats[chat["id"]] = chat.get("title") or chat.get("first_name") or chat.get("username")

if not chats:
    sys.exit("No messages found. Send your bot a message in Telegram first, then run this again.")

print("Chats that have messaged your bot:")
for chat_id, name in chats.items():
    print(f"  {name}:  {chat_id}")
    requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                  json={"chat_id": chat_id, "text": "✅ Your Flight Deal Hunter can reach this chat!"},
                  timeout=30)
print("\nA test message was sent to each chat. Save the ID you want with:")
print('  setx TELEGRAM_CHAT_ID "the-id"     (several: "id1,id2")')
