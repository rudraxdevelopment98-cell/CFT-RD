"""Connect Telegram alerts in one step. Run it on the computer that runs the bot:

    python -m tools.telegram_setup

1. Asks for the bot token from @BotFather (typing is hidden).
2. Checks the token with Telegram.
3. Waits for you to send any message to your bot, and reads your chat id.
4. Sends a test message to your phone.
5. Saves TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID into .env (other lines kept).
The token is never printed or sent anywhere except Telegram.
"""
from __future__ import annotations

import getpass
import os
import sys
import time

API = "https://api.telegram.org/bot{token}/{method}"


def latest_chat_id(updates: dict):
    """Chat id of the most recent private message in a getUpdates reply."""
    for u in reversed(updates.get("result", [])):
        msg = u.get("message") or u.get("edited_message") or {}
        chat = msg.get("chat") or {}
        if chat.get("id") is not None:
            return chat["id"]
    return None


def upsert_env(path: str, values: dict) -> None:
    """Set KEY=value lines in a .env file, keeping every other line."""
    lines = []
    if os.path.exists(path):
        with open(path) as f:
            lines = f.read().splitlines()
    done = set()
    for i, line in enumerate(lines):
        key = line.split("=", 1)[0].strip()
        if key in values:
            lines[i] = f"{key}={values[key]}"
            done.add(key)
    lines += [f"{k}={v}" for k, v in values.items() if k not in done]
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    try:
        os.chmod(path, 0o600)                     # owner-only on Mac/Linux
    except OSError:
        pass


def call(session, token, method, **params):
    r = session.get(API.format(token=token, method=method), params=params, timeout=20)
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(data.get("description", f"Telegram error {r.status_code}"))
    return data


def main(env_path=".env"):
    import requests
    s = requests.Session()
    token = getpass.getpass("Paste your bot token from @BotFather (hidden): ").strip()
    try:
        me = call(s, token, "getMe")["result"]
    except Exception as e:
        sys.exit(f"That token didn't work: {e}")
    print(f"Token OK: your bot is @{me['username']}")
    print(f"Now open Telegram, find @{me['username']}, press Start and send it any message.")

    chat_id = None
    for _ in range(40):                           # wait up to ~2 minutes
        chat_id = latest_chat_id(call(s, token, "getUpdates"))
        if chat_id:
            break
        time.sleep(3)
    if not chat_id:
        sys.exit("No message arrived. Send your bot a message and run this again.")

    call(s, token, "sendMessage", chat_id=chat_id,
         text="Trading bot connected. Every BUY, SELL and alert will arrive here.")
    upsert_env(env_path, {"TELEGRAM_BOT_TOKEN": token, "TELEGRAM_CHAT_ID": chat_id})
    print(f"Done. A test message was sent to you, and the settings were saved in {env_path}.")


if __name__ == "__main__":
    main()
