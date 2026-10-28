# START HERE — bot ko apne computer pe chalao (zero risk)

Ye guide aapko **paper-live** mode chalana sikhati hai: bot **asli market data**
(Gold, Silver, Oil, BTC, ETH) analyse karta hai aur **nakli £10,000** se trade
karta hai. **Koi account nahi, koi API key nahi, koi asli paisa nahi.**

---

## Step 1 — Python install karo (sirf ek baar)
- **Windows:** https://www.python.org/downloads/ se Python 3.12 download karo.
  Install karte waqt **"Add Python to PATH"** wala box ✅ tick karna zaroori hai.
- **Mac:** https://www.python.org/downloads/ se install karo.

Check karo — Terminal (Mac) ya Command Prompt (Windows) kholo aur likho:
```
python --version
```
`Python 3.12...` jaisa kuch dikhe to sahi hai. (Mac pe `python3` likhna pad sakta hai.)

## Step 2 — Bot ka code download karo
GitHub pe repo kholo → hara **Code** button → **Download ZIP** → unzip karo.
Us folder me Terminal/Command Prompt kholo (folder me `run.py` dikhna chahiye).

## Step 3 — Zaroori libraries install karo (sirf ek baar)
```
pip install -r requirements.txt
```

## Step 4 — Bot chalao 🚀
```
python run.py --paperlive
```
Bas! Ab bot:
- Har din ek baar asli market check karega
- Signal aane pe nakli BUY/SELL karega
- Sab kuch `trader.log` file me likhega aur screen pe dikhayega

**Window band mat karna** — band kiya to bot ruk jaayega. Computer on rakho,
sleep mode off karo.

> Pehle din aksar `equity 10,000 · 0 open` dikhega. Ye normal hai — strategies
> sirf sahi mauke pe trade karti hain. Positions din/hafton me khulengi.

Restart karoge to bot apna nakli account (positions, cash) yaad rakhega.

## Step 5 (optional) — Phone pe alert paao (Telegram)
1. Telegram me **@BotFather** ko message karo → `/newbot` → naam do → ek **token** milega.
2. Apne naye bot ko koi bhi message bhejo.
3. Browser me kholo: `https://api.telegram.org/bot<TOKEN>/getUpdates` →
   `"chat":{"id":12345...}` wala number aapka **chat id** hai.
4. Folder me `.env.example` ko copy karke naam `.env` rakho, aur bharo:
   ```
   TELEGRAM_BOT_TOKEN=aapka_token
   TELEGRAM_CHAT_ID=aapka_chat_id
   ```
Ab har trade ka alert phone pe aayega.

---

## Ab kya karna hai
- **Kam se kam 1–3 mahine** paper-live chalne do. Kuch mat badlo.
- Har hafte `trader.log` ya Telegram dekho: equity badh rahi hai ya gir rahi?
- **Sirf tab** asli paise ke baare me socho jab mahino tak behaviour achha ho —
  aur tab bhi sirf utna jo kho sako. Uske liye agla step: IG **demo** account.

⚠️ Yaad rakho: past performance future ki guarantee nahi. Ye ek experiment hai,
salary nahi.
