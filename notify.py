"""Telegram bildirimleri, dosya gönderme ve komutlar (/durum, /rapor...)."""
import html
import os
import time

import requests

import config

_last_update_id = None
LIMIT = 3900


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


def send_long(message):
    """4096 karakterden uzun mesajları satır sınırlarından bölerek gönderir."""
    chunk = ""
    for line in message.split("\n"):
        while len(line) > LIMIT:            # tek satır bile çok uzunsa
            if chunk:
                send_telegram(chunk)
                chunk = ""
            send_telegram(line[:LIMIT])
            line = line[LIMIT:]
        if len(chunk) + len(line) + 1 > LIMIT:
            send_telegram(chunk)
            chunk = ""
        chunk += line + "\n"
    if chunk.strip():
        send_telegram(chunk)


def send_document(path, caption=""):
    if not config.TELEGRAM_TOKEN or not os.path.exists(path):
        return False
    url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendDocument"
    try:
        with open(path, "rb") as fh:
            r = requests.post(url, data={"chat_id": config.TELEGRAM_CHAT_ID, "caption": caption[:1000]},
                              files={"document": (os.path.basename(path), fh)}, timeout=60)
        if r.status_code != 200:
            print(f"❌ TELEGRAM dosya hatası {r.status_code}: {r.text[:200]}")
        return r.status_code == 200
    except Exception as e:
        print(f"❌ TELEGRAM dosya gönderilemedi: {e}")
        return False


def poll_commands(wait=0):
    """Sohbetten gelen komutları döndürür (ör. ['/durum']). Sadece kendi chat id'nden gelenler.
    wait > 0 ise mesaj gelene kadar en fazla o kadar saniye bekler (bu sırada bot uyur)."""
    global _last_update_id
    if not config.TELEGRAM_TOKEN:
        time.sleep(wait)
        return []
    url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/getUpdates"
    first_run = _last_update_id is None
    params = {"timeout": 0 if first_run else int(wait), "allowed_updates": '["message"]'}
    if not first_run:
        params["offset"] = _last_update_id + 1
    started = time.time()
    try:
        data = requests.get(url, params=params, timeout=int(wait) + 15).json()
    except Exception:
        data = {}
    if not data.get("ok"):
        # 409 Conflict (bot iki kez çalışıyor) vb. hatalarda döngü Telegram'ı meşgul etmesin
        if data.get("error_code") == 409:
            print("⚠️ Telegram 409: Bu bot token'ıyla başka bir program da mesaj okuyor (bot iki kez mi açık?).")
        time.sleep(max(0.0, wait - (time.time() - started)))
        return []
    commands = []
    for upd in data.get("result", []):
        _last_update_id = upd["update_id"]
        msg = upd.get("message") or {}
        if str(msg.get("chat", {}).get("id")) != str(config.TELEGRAM_CHAT_ID):
            continue
        text = (msg.get("text") or "").strip().lower()
        if text.startswith("/") and not first_run:   # bot kapalıyken yazılan eski komutlar atlanır
            commands.append(text.split()[0].split("@")[0])
    if first_run:
        _last_update_id = _last_update_id if _last_update_id is not None else 0
        time.sleep(max(0.0, wait - (time.time() - started)))
    return commands
