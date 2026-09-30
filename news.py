"""RSS ile haber çekme. Kota yok, API anahtarı yok, ücretsiz.

Birden fazla kaynak paralel taranır, sadece son MAX_NEWS_AGE_MIN dakikada yayınlanmış
ve daha önce görülmemiş haberler döndürülür (en yeni en önde).
"""
import calendar
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor

import feedparser
import requests

import config

FEEDS = {
    "Cointelegraph": "https://cointelegraph.com/rss",
    "CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "Decrypt": "https://decrypt.co/feed",
    "The Block": "https://www.theblock.co/rss.xml",
    "CryptoSlate": "https://cryptoslate.com/feed/",
    "NewsBTC": "https://www.newsbtc.com/feed/",
    "Bitcoinist": "https://bitcoinist.com/feed/",
    "CryptoPotato": "https://cryptopotato.com/feed/",
    "U.Today": "https://u.today/rss",
    "BeInCrypto": "https://beincrypto.com/feed/",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
}

SEEN_FILE = os.path.join(config.DATA_DIR, "seen_news.json")
MAX_SEEN = 5000


def _clean_html(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", text).strip()


def _title_key(title):
    """Farklı sitelerde aynı haberi yakalamak için normalize edilmiş başlık."""
    return re.sub(r"[^a-z0-9]", "", (title or "").lower())[:70]


class NewsFeed:
    def __init__(self):
        self.seen = {}           # anahtar -> görülme zamanı
        self.cache_headers = {}  # feed -> (etag, last_modified)
        self.first_seen = {}     # yayın tarihi olmayan haberler için
        self.feed_errors = {}
        self._load()

    # ---------- kalıcı durum ----------
    def _load(self):
        try:
            with open(SEEN_FILE) as f:
                self.seen = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.seen = {}

    def _save(self):
        if len(self.seen) > MAX_SEEN:
            newest = sorted(self.seen.items(), key=lambda kv: kv[1])[-MAX_SEEN:]
            self.seen = dict(newest)
        tmp = SEEN_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.seen, f)
        os.replace(tmp, SEEN_FILE)

    def mark_seen(self, item):
        now = time.time()
        self.seen[item["id"]] = now
        self.seen["t:" + item["title_key"]] = now
        self._save()

    def is_seen(self, item):
        return item["id"] in self.seen or ("t:" + item["title_key"]) in self.seen

    # ---------- çekme ----------
    def _fetch_one(self, name, url):
        headers = dict(HEADERS)
        etag, modified = self.cache_headers.get(name, (None, None))
        if etag:
            headers["If-None-Match"] = etag
        if modified:
            headers["If-Modified-Since"] = modified
        try:
            r = requests.get(url, headers=headers, timeout=12)
            if r.status_code == 304:
                return name, []
            if r.status_code != 200:
                self.feed_errors[name] = f"HTTP {r.status_code}"
                return name, []
            self.cache_headers[name] = (r.headers.get("ETag"), r.headers.get("Last-Modified"))
            parsed = feedparser.parse(r.content)
            self.feed_errors.pop(name, None)
        except Exception as e:
            self.feed_errors[name] = str(e)[:80]
            return name, []

        items = []
        now = time.time()
        for entry in parsed.entries[:30]:
            title = _clean_html(entry.get("title", ""))
            if not title:
                continue
            link = entry.get("link", "")
            news_id = entry.get("id") or link or title
            t = entry.get("published_parsed") or entry.get("updated_parsed")
            if t:
                published = calendar.timegm(t)
                if published > now + 300:   # saat dilimi hatalı feed
                    published = now
            else:
                published = self.first_seen.setdefault(news_id, now)
            tags = [tg.get("term", "") for tg in entry.get("tags", []) if tg.get("term")]
            items.append({
                "id": news_id,
                "title": title,
                "title_key": _title_key(title),
                "summary": _clean_html(entry.get("summary", ""))[:500],
                "link": link,
                "source": name,
                "published": published,
                "categories": ", ".join(tags[:8]),
            })
        return name, items

    def fetch_fresh(self):
        """Taze ve görülmemiş haberleri döndürür (en yeni önce)."""
        with ThreadPoolExecutor(max_workers=len(FEEDS)) as pool:
            results = list(pool.map(lambda kv: self._fetch_one(*kv), FEEDS.items()))

        now = time.time()
        max_age = config.MAX_NEWS_AGE_MIN * 60
        fresh, keys = [], set()
        stale_count = 0
        for _, items in results:
            for it in items:
                if self.is_seen(it) or it["title_key"] in keys:
                    continue
                if now - it["published"] > max_age:
                    stale_count += 1
                    continue
                keys.add(it["title_key"])
                fresh.append(it)

        fresh.sort(key=lambda x: x["published"], reverse=True)
        ok = len(FEEDS) - len(self.feed_errors)
        print(f"\n📰 RSS: {ok}/{len(FEEDS)} kaynak OK | {len(fresh)} taze yeni haber "
              f"(>{config.MAX_NEWS_AGE_MIN:.0f} dk eski {stale_count} haber atlandı)")
        return fresh
