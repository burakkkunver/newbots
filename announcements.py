"""Borsa listeleme duyuruları: Upbit, Coinbase ve Binance.

Her kaynak dakikada (Coinbase 5 dakikada) bir küçük bir istekle kontrol edilir. Bir kaynağa ilk kez
ulaşıldığında mevcut duyurular "görüldü" sayılır (eski duyurular için bildirim gelmez); sonrasında
yeni çıkan duyurular sinyal olarak döner. Kaynak sunucudan erişilemiyorsa sessizce atlanır.
"""
import json
import os
import re
import time

import requests

import config
from util import SRC_BINANCE, SRC_COINBASE, SRC_UPBIT

STATE_FILE = os.path.join(config.DATA_DIR, "announcements.json")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9,ko;q=0.8",
}
# Parantez içinde geçip coin olmayan kelimeler (piyasa adları vb.)
NOT_COINS = {"KRW", "USDT", "USDC", "BTC", "ETH", "USD", "EUR", "TRY", "FDUSD", "BNB", "SPOT", "MARGIN",
             "FUTURES", "PERP", "UTC", "KST", "AM", "PM", "API", "NEW", "TRADE"}


def tickers_in(title):
    out = []
    for group in re.findall(r"\(([^)]{1,80})\)", title):
        for tok in re.split(r"[,/\s]+", group):
            tok = tok.strip().upper()
            if re.fullmatch(r"[A-Z0-9]{2,12}", tok) and tok not in NOT_COINS and not tok.isdigit() and tok not in out:
                out.append(tok)
    return out


def _walk(obj, found):
    """JSON içinde 'title' alanı olan tüm kayıtları bulur (yanıt yapısı değişse de çalışsın)."""
    if isinstance(obj, dict):
        if isinstance(obj.get("title"), str) and ("id" in obj or "code" in obj):
            found.append(obj)
        for v in obj.values():
            _walk(v, found)
    elif isinstance(obj, list):
        for v in obj:
            _walk(v, found)
    return found


def parse_upbit(data):
    out = []
    for n in _walk(data, []):
        title = n["title"]
        low = title.lower()
        # Sadece yeni listeleme ("신규 거래지원" / "new digital asset" / "market support"), uyarı ve kaldırma değil
        if not ("신규 거래지원" in title or "new digital asset" in low or "market support for" in low):
            continue
        if any(w in title for w in ("유의", "종료", "중단")) or any(w in low for w in ("delist", "terminat", "caution")):
            continue
        nid = str(n.get("id"))
        out.append({"id": nid, "title": title, "tickers": tickers_in(title),
                    "link": f"https://upbit.com/service_center/notice?id={nid}"})
    return out


def parse_binance(data):
    out = []
    for a in _walk(data, []):
        title = a["title"]
        low = title.lower()
        if not any(w in low for w in ("will list", "will add", "adds", "listing", "launchpool", "hodler airdrop")):
            continue
        if any(w in low for w in ("delist", "remove", "will cease")):
            continue
        code = str(a.get("code") or a.get("id"))
        out.append({"id": code, "title": title, "tickers": tickers_in(title),
                    "link": f"https://www.binance.com/en/support/announcement/{code}"})
    return out


def parse_coinbase(data):
    bases = {}
    for p in data if isinstance(data, list) else []:
        base = str(p.get("base_currency", "")).upper()
        if base:
            bases.setdefault(base, []).append(p.get("id", ""))
    return [{"id": base, "title": f"Coinbase yeni işlem çifti ekledi: {', '.join(ids[:3])}", "tickers": [base],
             "link": "https://exchange.coinbase.com/markets"} for base, ids in bases.items()]


SOURCES = [
    {"name": SRC_UPBIT, "interval": 60, "parse": parse_upbit,
     "url": "https://api-manager.upbit.com/api/v1/announcements?os=web&page=1&per_page=20&category=trade"},
    {"name": SRC_BINANCE, "interval": 60, "parse": parse_binance,
     "url": "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query?type=1&pageNo=1&pageSize=15&catalogId=48"},
    {"name": SRC_COINBASE, "interval": 300, "parse": parse_coinbase,
     "url": "https://api.exchange.coinbase.com/products"},
]


class AnnouncementWatcher:
    def __init__(self):
        self.state = {}
        self.last = {}
        self.status = {s["name"]: "henüz kontrol edilmedi" for s in SOURCES}
        self.fails = {}
        try:
            with open(STATE_FILE) as f:
                self.state = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.state = {}

    def _save(self):
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.state, f)
        os.replace(tmp, STATE_FILE)

    def fetch(self, src):
        r = requests.get(src["url"], headers=HEADERS, timeout=12)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}")
        return src["parse"](r.json())

    def tick(self, force=False):
        """Zamanı gelen kaynakları kontrol eder, yeni duyuruları döndürür."""
        if not config.ANNOUNCEMENTS_ENABLED:
            return []
        new = []
        for src in SOURCES:
            name = src["name"]
            if not force and time.time() - self.last.get(name, 0) < src["interval"]:
                continue
            self.last[name] = time.time()
            try:
                entries = self.fetch(src)
            except Exception as e:
                self.fails[name] = self.fails.get(name, 0) + 1
                self.status[name] = f"erişilemiyor ({str(e)[:60]})"
                if self.fails[name] in (1, 30):
                    print(f"⚠️ {name} duyuruları alınamadı: {e}")
                continue
            self.fails[name] = 0
            self.status[name] = f"ok ({len(entries)} kayıt)"
            st = self.state.setdefault(name, {"seen": [], "baseline": False})
            seen = set(st["seen"])
            fresh = [e for e in entries if e["id"] not in seen]
            if st["baseline"]:
                for e in fresh:
                    e["source"] = name
                    e["ts"] = time.time()
                    new.append(e)
            elif entries:
                print(f"ℹ️ {name}: {len(entries)} mevcut duyuru başlangıç olarak kaydedildi (bildirim yok).")
                st["baseline"] = True
            st["seen"] = (st["seen"] + [e["id"] for e in fresh])[-1000:]
            if fresh or not st.get("saved"):
                st["saved"] = True
                self._save()
        return new
