"""İzleme listesi haberleri: ilgi gören coinler için coine özel haber araması (hacim patlamasını beklemeden).

Genel haber siteleri ve kanallar küçük projelerin kendi gelişmelerini (Starknet'in L1 kararı, Pyth DAO oylaması...)
ya geç yazıyor ya hiç yazmıyor. Bu modül her WATCH_NEWS_MINUTES dakikada bir şu coinler için Google News'te son 1 günün
haberlerini arar:
  - Piyasa Nabzı'nın izleme listesi (Gemini'nin "hikâyesi var" dediği coinler)
  - CoinGecko trend coinleri (insanların şu an en çok aradığı coinler)
Başlığında coinin adı veya sembolü geçen, son WATCH_NEWS_MAX_AGE_MIN dakikadaki yeni haberler kuyruğa konur ve ana
döngüde normal haber yolundan geçer (kural filtresi -> Gemini -> puan -> "tren kaçtı" kontrolü). Arama arka planda
yapılır, ana döngüyü bekletmez. Google News ve CoinGecko anahtarsız ve ücretsizdir.
"""
import calendar
import hashlib
import json
import os
import re
import threading
import time
from urllib.parse import quote

import feedparser
import requests

import config
from filters import NAME_MAP, title_mentions
from news import _clean_html, _title_key
from util import fmt_ts

STATE_FILE = os.path.join(config.DATA_DIR, "watch_news.json")
GNEWS_URL = "https://news.google.com/rss/search"
CG = "https://api.coingecko.com/api/v3"
SOURCE = "İzleme haberi"
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
           "Accept": "application/rss+xml, application/xml, application/json;q=0.9, */*;q=0.8"}
SKIP = {"BTC", "ETH", "USDT", "USDC", "FDUSD", "DAI", "TUSD", "BUSD", "USDE", "USDP", "PYUSD", "WBTC", "STETH", "GENEL"}
# Arama ve eşleştirmede adın sonundaki genel kelimeler atılır: "Pyth Network" -> "Pyth", "Aerodrome Finance" -> "Aerodrome"
NAME_SUFFIXES = (" network", " protocol", " finance", " token", " coin", " chain", " labs", " foundation", " dao")
REVERSE_NAMES = {}
for _name, _sym in NAME_MAP.items():
    REVERSE_NAMES.setdefault(_sym, _name.title())


def short_name(name):
    n = (name or "").strip()
    low = n.lower()
    for suf in NAME_SUFFIXES:
        if low.endswith(suf) and len(n) - len(suf) >= 3:
            return n[:-len(suf)].strip()
    return n


def mentions(title, sym, name):
    """Başlık bu coinle ilgili mi? Sembol (STRK, $STRK) veya ad (Starknet) tam kelime olarak geçmeli."""
    if title_mentions(title, sym):
        return True
    n = short_name(name)
    return len(n) >= 3 and bool(re.search(r"(?<![A-Za-z0-9])" + re.escape(n) + r"(?![A-Za-z0-9])", title, re.I))


def split_title(title, publisher):
    """Google News başlığı "Başlık - Yayıncı" biçimindedir; yayıncıyı ayırır."""
    title = _clean_html(title)
    if publisher and title.endswith(" - " + publisher):
        return title[:-len(" - " + publisher)].strip(), publisher
    if " - " in title:
        head, tail = title.rsplit(" - ", 1)
        if 0 < len(tail) <= 40:
            return head.strip(), publisher or tail.strip()
    return title, publisher or ""


class WatchNews:
    def __init__(self, pulse=None, feed=None):
        self.pulse, self.feed = pulse, feed
        self.queue, self.lock = [], threading.Lock()
        self.sent = set()           # bu oturumda kuyruğa konan haberler (iki kez gönderilmesin)
        self.last_run = 0.0
        self.status = "henüz çalışmadı" if config.WATCH_NEWS_ENABLED else "kapalı (WATCH_NEWS_ENABLED=False)"
        self.last_coins, self.last_found = [], 0
        self.stats = {"runs": 0, "searches": 0, "found": 0}
        try:
            with open(STATE_FILE) as f:
                self.names = json.load(f).get("names", {})
        except (FileNotFoundError, json.JSONDecodeError, AttributeError):
            self.names = {}

    def _save(self):
        try:
            tmp = STATE_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump({"names": self.names}, f)
            os.replace(tmp, STATE_FILE)
        except OSError as e:
            print(f"⚠️ İzleme haberleri durumu yazılamadı: {e}")

    def _cg(self, path, params=None):
        headers = dict(HEADERS)
        if config.COINGECKO_API_KEY:
            headers["x-cg-demo-api-key"] = config.COINGECKO_API_KEY
        r = requests.get(f"{CG}{path}", params=params, headers=headers, timeout=15)
        if r.status_code != 200:
            raise RuntimeError(f"CoinGecko HTTP {r.status_code}")
        return r.json()

    # ---------- hangi coinler aranacak ----------
    def trending(self):
        """CoinGecko trend coinleri: [(sembol, ad)]. Adlar önbelleğe yazılır."""
        data = self._cg("/search/trending")
        out = []
        for c in data.get("coins", [])[:15]:
            it = c.get("item", {})
            sym, name = str(it.get("symbol", "")).upper(), str(it.get("name", "")).strip()
            if sym:
                out.append((sym, name))
                if name:
                    self.names[sym] = name
        return out

    def name_of(self, sym):
        """Sembolün coin adı: önbellek -> bilinen adlar -> CoinGecko araması (en büyük piyasa değerli eşleşme)."""
        if sym in self.names:
            return self.names[sym]
        if sym in REVERSE_NAMES:
            return REVERSE_NAMES[sym]
        name = ""
        try:
            hits = [c for c in self._cg("/search", {"query": sym}).get("coins", [])
                    if str(c.get("symbol", "")).upper() == sym]
            hits.sort(key=lambda c: c.get("market_cap_rank") or 10 ** 9)
            name = str(hits[0].get("name", "")).strip() if hits else ""
        except Exception as e:
            print(f"⚠️ {sym} için coin adı bulunamadı: {e}")
            return ""
        self.names[sym] = name
        return name

    def pick_coins(self):
        """Önce nabız izleme listesi (daha güçlü sinyal), sonra CoinGecko trendleri."""
        picked = []
        if self.pulse and self.pulse.fresh():
            picked += [w["coin"] for w in self.pulse.state.get("izleme", [])]
        trend = []
        try:
            trend = self.trending()
        except Exception as e:
            print(f"⚠️ İzleme haberleri: CoinGecko trend alınamadı ({e})")
        picked += [s for s, _ in trend]
        out = []
        for sym in picked:
            sym = str(sym).upper()
            if sym and sym not in SKIP and sym not in out:
                out.append(sym)
        coins = []
        for sym in out[:config.WATCH_NEWS_MAX_COINS]:
            name = self.name_of(sym)
            if name or len(sym) >= 3:   # adı bilinmeyen 1-2 harfli sembolle (W, S...) arama anlamsız sonuç verir
                coins.append((sym, name))
        self._save()
        return coins

    # ---------- arama ----------
    def search(self, sym, name):
        """Coin için son 1 günün Google News haberleri, haber öğesi biçiminde (yaş ve ilgi filtresinden geçmiş)."""
        term = short_name(name) if name and len(short_name(name)) >= 3 else sym
        q = f'"{term}" crypto when:1d'
        url = f"{GNEWS_URL}?q={quote(q)}&hl=en-US&gl=US&ceid=US:en"
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            raise RuntimeError(f"Google News HTTP {r.status_code}")
        self.stats["searches"] += 1
        now, out = time.time(), []
        for e in feedparser.parse(r.content).entries[:25]:
            src = e.get("source") or {}
            title, publisher = split_title(e.get("title", ""), src.get("title") if isinstance(src, dict) else "")
            t = e.get("published_parsed") or e.get("updated_parsed")
            if not title or not t:
                continue
            published = min(calendar.timegm(t), now)
            if now - published > config.WATCH_NEWS_MAX_AGE_MIN * 60 or not mentions(title, sym, name):
                continue
            link = e.get("link", "")
            out.append({"id": "watch:" + hashlib.sha1((link or title).encode()).hexdigest()[:16],
                        "title": title, "title_key": _title_key(title), "link": link, "source": SOURCE,
                        "published": published, "categories": "", "watch": True, "watch_coin": sym,
                        "summary": f"Yayıncı: {publisher or 'bilinmiyor'} | Aranan coin: {sym}"
                                   + (f" ({name})" if name else "")})
        return out

    def run_once(self):
        """Bir arama turu. Yeni bulunan haberleri kuyruğa koyar, kaç tane bulunduğunu döner."""
        self.last_run = time.time()
        self.stats["runs"] += 1
        coins = self.pick_coins()
        self.last_coins = [s for s, _ in coins]
        found, errors = [], 0
        for i, (sym, name) in enumerate(coins):
            if i:
                time.sleep(1.5)   # Google'a nazik ol
            try:
                found += self.search(sym, name)
            except Exception as e:
                errors += 1
                print(f"⚠️ İzleme haberleri: {sym} aranamadı ({e})")
                if "429" in str(e) or "503" in str(e):
                    break   # Google sınırladı: bu turu bitir, sonraki turda tekrar
        # Aynı haber birkaç yayıncıdan gelebilir: en erken yayınlananı tut ("tren kaçtı" kontrolü ondan ölçülsün)
        new, keys = [], set()
        for it in sorted(found, key=lambda x: x["published"]):
            if it["id"] in self.sent or it["title_key"] in keys or (self.feed and self.feed.is_seen(it)):
                continue
            keys.add(it["title_key"])
            new.append(it)
        new = sorted(new, key=lambda x: -x["published"])[:config.WATCH_NEWS_MAX_PER_RUN]
        with self.lock:
            self.queue.extend(new)
            self.sent.update(it["id"] for it in new)
        self.last_found = len(new)
        self.stats["found"] += len(new)
        when = fmt_ts(self.last_run, with_date=False)
        self.status = (f"son arama {when}: {len(coins)} coin, {len(new)} yeni haber"
                       + (f", {errors} arama başarısız" if errors else ""))
        print(f"🔭 İzleme haberleri: {len(coins)} coin arandı ({', '.join(self.last_coins[:10])}), {len(new)} yeni haber")
        return len(new)

    def drain(self):
        with self.lock:
            items, self.queue = self.queue, []
        return items

    # ---------- arka plan ----------
    def due(self):
        return config.WATCH_NEWS_ENABLED and time.time() - self.last_run >= config.WATCH_NEWS_MINUTES * 60

    def start(self, stop_event, first_delay=90):
        if not config.WATCH_NEWS_ENABLED:
            return
        self.last_run = time.time() - config.WATCH_NEWS_MINUTES * 60 + first_delay   # ilk arama nabızdan sonra

        def loop():
            while not stop_event.is_set():
                if self.due():
                    try:
                        self.run_once()
                    except Exception as e:
                        self.status = f"hata: {str(e)[:80]}"
                        print(f"⚠️ İzleme haberleri hatası: {e}")
                stop_event.wait(30)
        threading.Thread(target=loop, daemon=True).start()

    def status_text(self):
        if not config.WATCH_NEWS_ENABLED:
            return self.status
        coins = ", ".join(self.last_coins[:8]) + ("..." if len(self.last_coins) > 8 else "")
        return f"{self.status}" + (f" | izlenen: {coins}" if coins else "")
