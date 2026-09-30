"""Telegram bildirimleri ve basit komutlar (/durum)."""
import html
import time

import requests

import config

_last_update_id = None


def esc(text):
    """Telegram HTML modunda &, <, > karakterleri mesajı bozmasın diye kaçırılır."""
    return html.escape(str(text or ""), quote=False)


def send_telegram(message):
    if not config.TELEGRAM_TOKEN or not config.TELEGRAM_CHAT_ID:
        print("❌ HATA: Telegram Token veya Chat ID eksik!")
        return False
    url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": config.TELEGRAM_CHAT_ID, "text": message[:4000],
               "parse_mode": "HTML", "disable_web_page_preview": True}
    for attempt in range(3):
        try:
            r = requests.post(url, json=payload, timeout=15)
            if r.status_code == 200:
                print("✅ TELEGRAM: Mesaj gönderildi.")
                return True
            if r.status_code == 429:
                wait = r.json().get("parameters", {}).get("retry_after", 5)
                time.sleep(min(wait, 30))
                continue
            print(f"❌ TELEGRAM HATASI {r.status_code}: {r.text[:200]}")
            if r.status_code == 400:
                # HTML parse hatası olursa düz metin olarak dene
                payload.pop("parse_mode", None)
                continue
            return False
        except Exception as e:
            print(f"❌ TELEGRAM BAĞLANTI HATASI: {e}")
            time.sleep(2)
    return False


def poll_commands():
    """Sohbetten gelen komutları döndürür (ör. ['/durum']). Sadece kendi chat id'nden gelenler."""
    global _last_update_id
    if not config.TELEGRAM_TOKEN:
        return []
    url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/getUpdates"
    params = {"timeout": 0, "allowed_updates": '["message"]'}
    if _last_update_id is not None:
        params["offset"] = _last_update_id + 1
    try:
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
    except Exception:
        return []
    commands = []
    first_run = _last_update_id is None
    for upd in data.get("result", []):
        _last_update_id = upd["update_id"]
        msg = upd.get("message") or {}
        if str(msg.get("chat", {}).get("id")) != str(config.TELEGRAM_CHAT_ID):
            continue
        text = (msg.get("text") or "").strip().lower()
        if text.startswith("/") and not first_run:
            commands.append(text.split()[0].split("@")[0])
    return commands
