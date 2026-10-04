"""Telegram haber kanalları (Watcher.Guru, Tree News, BWEnews...): RSS'ten genelde dakikalar önce haber verirler.

Senin Telegram hesabınla (Telethon), SADECE config.TG_NEWS_CHANNELS listesindeki herkese açık kanalları okur.
Özel sohbetler, gruplar ve listede olmayan kanallar hiç okunmaz; bot mesaj göndermez, kanallara katılmaz.
Kanallar TG_POLL_SECONDS'ta bir kontrol edilir; yeni mesajlar haber öğesine çevrilip kuyruğa konur ve
ana döngüde RSS haberleriyle aynı yoldan (filtre -> Gemini -> puan -> rejim -> ikinci görüş) geçer.

İlk kurulum: my.telegram.org'dan TG_API_ID / TG_API_HASH al, env.sh'e yaz, bir kez `python3 tg_login.py` çalıştır.
"""
import asyncio
import json
import os
import queue
import re
import threading
import time

import config
from news import _title_key

SESSION_PATH = os.path.join(config.DATA_DIR, "tg_news")      # Telethon sonuna .session ekler
STATE_FILE = os.path.join(config.DATA_DIR, "tg_state.json")


def clean_text(text):
    text = re.sub(r"https?://\S+", "", text or "")
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def to_item(channel, msg_id, date_ts, text):
    """Kanal mesajını RSS haberiyle aynı biçime çevirir. Çok kısa/boş mesajlar (sadece resim vb.) atlanır."""
    text = clean_text(text)
    if len(text) < 15:
        return None
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    title = lines[0]
    if len(title) < 25 and len(lines) > 1:
        title = f"{title} {lines[1]}"
    title = title[:240]
    return {"id": f"tg:{channel}:{msg_id}", "title": title, "title_key": _title_key(title),
            "summary": " ".join(lines[1:])[:500], "link": f"https://t.me/{channel}/{msg_id}",
            "source": f"TG @{channel}", "published": date_ts, "categories": ""}


class TelegramNews:
    def __init__(self, client_factory=None):
        self.enabled = bool(config.TG_API_ID and config.TG_API_HASH)
        self.status = "başlatılmadı" if self.enabled else "yapılandırılmadı (isteğe bağlı, KURULUM.md)"
        self.channel_status = {}
        self.counts = {}
        self.queue = queue.Queue()
        self._factory = client_factory
        self._stop = threading.Event()
        try:
            with open(STATE_FILE) as f:
                self.last_ids = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.last_ids = {}

    def _save(self):
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.last_ids, f)
        os.replace(tmp, STATE_FILE)

    def _make_client(self):
        if self._factory:
            return self._factory()
        from telethon import TelegramClient
        return TelegramClient(SESSION_PATH, config.TG_API_ID, config.TG_API_HASH)

    # ---------- arka plan thread'i ----------
    def start(self):
        if self.enabled:
            threading.Thread(target=self._run, daemon=True, name="tgnews").start()

    def stop(self):
        self._stop.set()

    def _run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._main())
        except Exception as e:
            self.status = f"durdu: {str(e)[:80]}"
            print(f"❌ Telegram haber okuyucu durdu: {e}")
        finally:
            loop.close()

    async def _main(self):
        try:
            client = self._make_client()
        except ImportError:
            self.status = "telethon kurulu değil (pip install -r requirements.txt)"
            print(f"⚠️ Telegram kanalları: {self.status}")
            return
        await client.connect()
        if not await client.is_user_authorized():
            self.status = "giriş yapılmamış: sunucuda bir kez 'python3 tg_login.py' çalıştır"
            print(f"⚠️ Telegram kanalları: {self.status}")
            await client.disconnect()
            return
        entities = {}
        for name in config.TG_NEWS_CHANNELS:
            try:
                entities[name] = await client.get_entity(name)
                self.channel_status[name] = "ok"
            except Exception as e:
                self.channel_status[name] = f"bulunamadı ({str(e)[:50]})"
                print(f"⚠️ Telegram kanalı bulunamadı: @{name} ({e})")
        if not entities:
            self.status = "listedeki kanalların hiçbiri bulunamadı"
            await client.disconnect()
            return
        self.status = f"ok ({len(entities)}/{len(config.TG_NEWS_CHANNELS)} kanal okunuyor)"
        print(f"📨 Telegram kanalları: {', '.join('@' + n for n in entities)}")
        while not self._stop.is_set():
            for name, ent in entities.items():
                await self._poll_channel(client, name, ent)
                await asyncio.sleep(0.5)
            await asyncio.sleep(config.TG_POLL_SECONDS)
        await client.disconnect()

    async def _poll_channel(self, client, name, ent):
        last = self.last_ids.get(name)
        try:
            if last is None:
                # İlk kez: mevcut mesajlar başlangıç sayılır, eskiler işlenmez
                msgs = await client.get_messages(ent, limit=1)
                self.last_ids[name] = msgs[0].id if msgs else 0
                self._save()
                return
            msgs = await client.get_messages(ent, limit=30, min_id=last)
        except Exception as e:
            if type(e).__name__ == "FloodWaitError":   # Telegram "biraz yavaşla" dedi
                wait = int(getattr(e, "seconds", 30) or 30)
                self.channel_status[name] = f"Telegram bekletiyor ({wait} sn)"
                await asyncio.sleep(min(wait, 300))
            else:
                self.channel_status[name] = f"hata ({str(e)[:60]})"
            return
        new = sorted((m for m in msgs if m.id > last), key=lambda m: m.id)
        for m in new:
            text = getattr(m, "raw_text", None) or getattr(m, "message", None) or ""
            date_ts = m.date.timestamp() if getattr(m, "date", None) else time.time()
            item = to_item(name, m.id, date_ts, text)
            if item:
                self.queue.put(item)
                self.counts[name] = self.counts.get(name, 0) + 1
        if new:
            self.last_ids[name] = max(m.id for m in new)
            self._save()
        self.channel_status[name] = "ok"

    # ---------- ana döngü için ----------
    def drain(self):
        items = []
        while True:
            try:
                items.append(self.queue.get_nowait())
            except queue.Empty:
                return items

    def status_text(self):
        if not self.channel_status:
            return self.status
        parts = [f"@{n}: {s}" + (f" ({self.counts[n]} mesaj)" if self.counts.get(n) else "")
                 for n, s in self.channel_status.items()]
        return f"{self.status} | " + ", ".join(parts)
