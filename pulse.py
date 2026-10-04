"""Piyasa Nabzı (trend radarı): piyasayı genel olarak "koklar".

Her PULSE_MINUTES dakikada bir şunlar toplanır ve Gemini'ye yorumlatılır:
  - CoinGecko trend coinleri ve trend kategoriler (insanlar şu an neyi arıyor)
  - CoinGecko sektör performansı (para hangi anlatıya akıyor: AI, meme, DeFi, L2...)
  - Korku & Açgözlülük endeksi (genel duygu)
  - Binance 24 saatte en çok yükselen/düşenler (hacmi 5 milyon $ üstü)
  - Son 4 saatin hacim patlamaları (bizim tarayıcı)
  - Haber yoğunluğu: son 2 saatte haberlerde (RSS + Telegram) en çok adı geçen coinler
Sonuç: kısa yorum + izleme listesi. İzleme listesindeki coinlerin olumlu haberlerine puan bonusu verilir,
hacim patlaması değerlendirmesinde de bu bilgi kullanılır. Tüm kaynaklar ücretsizdir; biri çalışmazsa atlanır.
"""
import json
import os
import time
from collections import Counter

import requests

import config
from filters import coins_in_title
from notify import esc
from scanner import _tradeable
from util import fmt_ts

STATE_FILE = os.path.join(config.DATA_DIR, "pulse.json")
CG = "https://api.coingecko.com/api/v3"
FRESH_SEC = 3 * 3600   # izleme listesi bu kadar süre geçerli
STABLES = {"USDT", "USDC", "FDUSD", "DAI", "TUSD", "BUSD", "USDE", "USDP", "PYUSD"}


class MarketPulse:
    def __init__(self, bx, feed, scanner, market, ai):
        self.bx, self.feed, self.scanner, self.market, self.ai = bx, feed, scanner, market, ai
        self.status = {}
        try:
            with open(STATE_FILE) as f:
                self.state = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.state = {}
        self.last_run = self.state.get("ts", 0)

    def _save(self):
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.state, f)
        os.replace(tmp, STATE_FILE)

    def _get(self, url, params=None):
        headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
        if config.COINGECKO_API_KEY and url.startswith(CG):
            headers["x-cg-demo-api-key"] = config.COINGECKO_API_KEY
        r = requests.get(url, params=params, headers=headers, timeout=15)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}")
        return r.json()

    # ---------- veri toplama ----------
    def collect(self):
        d, now = {}, time.time()
        try:
            tr = self._get(f"{CG}/search/trending")
            items = [c.get("item", {}) for c in tr.get("coins", [])][:15]
            d["trending"] = [{"symbol": str(c.get("symbol", "")).upper(), "name": c.get("name", ""),
                              "rank": c.get("market_cap_rank"),
                              "ch24": ((c.get("data") or {}).get("price_change_percentage_24h") or {}).get("usd")}
                             for c in items if c.get("symbol")]
            d["trending_cats"] = [c.get("name") for c in tr.get("categories", []) if c.get("name")][:6]
            self.status["CoinGecko trend"] = "ok"
        except Exception as e:
            self.status["CoinGecko trend"] = f"hata ({str(e)[:40]})"
        try:
            cats = self._get(f"{CG}/coins/categories", {"order": "market_cap_change_24h_desc"})
            big = [c for c in cats if (c.get("market_cap") or 0) >= 3e8 and c.get("market_cap_change_24h") is not None]
            big.sort(key=lambda c: -c["market_cap_change_24h"])
            d["sectors_up"] = [(c["name"], c["market_cap_change_24h"]) for c in big[:8]]
            d["sectors_down"] = [(c["name"], c["market_cap_change_24h"]) for c in big[-4:]]
            self.status["CoinGecko sektörler"] = "ok"
        except Exception as e:
            self.status["CoinGecko sektörler"] = f"hata ({str(e)[:40]})"
        try:
            fng = self._get("https://api.alternative.me/fng/", {"limit": 2}).get("data", [])
            d["fng"] = [int(fng[0]["value"]), fng[0].get("value_classification", ""),
                        int(fng[1]["value"]) if len(fng) > 1 else None]
            self.status["Korku&Açgözlülük"] = "ok"
        except Exception as e:
            self.status["Korku&Açgözlülük"] = f"hata ({str(e)[:40]})"
        try:
            rows = [x for x in self.bx.real_tickers24_all()
                    if _tradeable(x.get("symbol", "")) and float(x.get("quoteVolume", 0)) >= 5e6]
            rows.sort(key=lambda x: -float(x["priceChangePercent"]))
            d["gainers"] = [(x["symbol"][:-4], float(x["priceChangePercent"]), float(x["quoteVolume"])) for x in rows[:12]]
            d["losers"] = [(x["symbol"][:-4], float(x["priceChangePercent"])) for x in rows[-5:]]
            self.status["Binance 24s"] = "ok"
        except Exception as e:
            self.status["Binance 24s"] = f"hata ({str(e)[:40]})"

        d["spikes"] = Counter(c for ts, c, _ in self.scanner.history if now - ts <= 4 * 3600).most_common(10)

        bases = self.scanner.bases() or {v["base"] for v in self.bx.symbols.values()}
        recent, older = Counter(), Counter()
        for it in list(self.feed.recent.values()):
            if "_coins" not in it:
                it["_coins"] = sorted(c for c in coins_in_title(it["title"], bases) if c not in STABLES)
            (recent if now - it["published"] <= 2 * 3600 else older).update(it["_coins"])
        d["mentions"] = [(c, n, older.get(c, 0)) for c, n in recent.most_common(10)]
        d["headlines"] = [(it["source"], it["title"]) for it in sorted(
            self.feed.recent.values(), key=lambda x: -x["published"]) if now - it["published"] <= 2 * 3600][:25]
        d["regime"] = self.market.describe()
        return d, self.format(d)

    @staticmethod
    def format(d):
        def pct(v):
            return f"{v:+.1f}%" if isinstance(v, (int, float)) else "?"
        L = [f"BTC rejimi: {d.get('regime', '?')}"]
        if d.get("fng"):
            v, cls, prev = d["fng"]
            L.append(f"Korku & Açgözlülük endeksi: {v} ({cls})" + (f", dün {prev}" if prev is not None else ""))
        if d.get("trending"):
            L.append("CoinGecko trend coinler: " + ", ".join(
                f"{t['symbol']} (sıra {t['rank'] or '?'}, 24s {pct(t['ch24'])})" for t in d["trending"]))
        if d.get("trending_cats"):
            L.append("CoinGecko trend kategoriler: " + ", ".join(d["trending_cats"]))
        if d.get("sectors_up"):
            L.append("24s en çok yükselen sektörler: " + ", ".join(f"{n} {pct(v)}" for n, v in d["sectors_up"]))
            L.append("24s en çok düşen sektörler: " + ", ".join(f"{n} {pct(v)}" for n, v in d.get("sectors_down", [])))
        if d.get("gainers"):
            L.append("Binance 24s en çok yükselenler: " + ", ".join(
                f"{c} {pct(p)} (hacim {v / 1e6:.0f}M$)" for c, p, v in d["gainers"]))
            L.append("Binance 24s en çok düşenler: " + ", ".join(f"{c} {pct(p)}" for c, p in d.get("losers", [])))
        L.append("Son 4 saatin hacim patlamaları: " + (", ".join(f"{c} ({n} kez)" for c, n in d.get("spikes", [])) or "yok"))
        L.append("Son 2 saatte haberlerde en çok geçen coinler (önceki 10 saatte): " + (
            ", ".join(f"{c} {n} ({o})" for c, n, o in d.get("mentions", [])) or "yok"))
        if d.get("headlines"):
            L.append("Son 2 saatin başlıkları:")
            L.extend(f"- [{s}] {t[:140]}" for s, t in d["headlines"])
        return "\n".join(L)

    # ---------- çalıştırma ----------
    def due(self):
        return config.PULSE_ENABLED and time.time() - self.last_run >= config.PULSE_MINUTES * 60

    def run(self):
        """Veriyi toplar, Gemini'ye yorumlatır. Başarılıysa True."""
        self.last_run = time.time()
        print("🧭 Piyasa Nabzı hazırlanıyor...")
        d, text = self.collect()
        res = self.ai.pulse_analysis(text)
        if res is None:
            self.status["Gemini"] = "yanıt alınamadı"
            return False
        self.status["Gemini"] = "ok"
        log = (self.state.get("log", []) + [{"ts": time.time(), "izleme": [w["coin"] for w in res["izleme"]],
                                              "duygu": res["duygu"]}])[-72:]
        self.state = dict(res, ts=time.time(), trending=[t["symbol"] for t in d.get("trending", [])],
                          fng=d.get("fng"), sectors_up=d.get("sectors_up", [])[:5],
                          last_notify=self.state.get("last_notify", 0), log=log)
        self._save()
        print(f"🧭 Nabız: {res['duygu']} | izleme: {', '.join(w['coin'] for w in res['izleme']) or '-'}")
        return True

    def should_notify(self):
        return (config.PULSE_NOTIFY_HOURS > 0 and self.fresh()
                and time.time() - self.state.get("last_notify", 0) >= config.PULSE_NOTIFY_HOURS * 3600 - 60)

    def mark_notified(self):
        self.state["last_notify"] = time.time()
        self._save()

    # ---------- diğer modüller için ----------
    def fresh(self):
        return time.time() - self.state.get("ts", 0) <= FRESH_SEC

    def watch_entry(self, coin):
        if not self.fresh():
            return None
        return next((w for w in self.state.get("izleme", []) if w["coin"] == coin), None)

    def avoid_entry(self, coin):
        if not self.fresh():
            return None
        return next((w for w in self.state.get("uzak_dur", []) if w["coin"] == coin), None)

    def is_trending(self, coin):
        return self.fresh() and coin in self.state.get("trending", [])

    def apply_bonus(self, res):
        """İzleme listesindeki coinin olumlu haberine +bonus, uzak dur listesindekine -1. res'i yerinde günceller."""
        coin = res.get("hedef_coin")
        w, a = self.watch_entry(coin), self.avoid_entry(coin)
        note = None
        if a:
            res["puan"] = max(1.0, res["puan"] - 1)
            note = "nabız: uzak dur listesinde -1"
        elif w and res.get("yon") == "olumlu" and res["puan"] >= 5:
            bonus = config.PULSE_SCORE_BONUS
            res["puan"] = min(10.0, res["puan"] + bonus)
            note = f"nabız izleme listesi +{bonus:g}"
        if note:
            res["puan_notu"] = (res.get("puan_notu", "") + "; " + note).strip("; ")
            coin_ok = coin not in ("GENEL", "") and coin not in STABLES
            res["karar"] = "BUY" if res["puan"] >= config.BUY_MIN_SCORE and res.get("yon") == "olumlu" and coin_ok \
                else "PASS"
            print(f"🧭 {coin}: {note} -> puan {res['puan']:.0f}")
        return res

    def short_text(self):
        """Yapay zekaya ve rapora verilecek kısa nabız özeti."""
        if not self.state.get("ozet"):
            return "henüz nabız yok"
        age = int((time.time() - self.state["ts"]) / 60)
        watch = ", ".join(f"{w['coin']}({w['guc']})" for w in self.state.get("izleme", [])) or "-"
        return (f"{self.state['ozet']} | duygu: {self.state.get('duygu')} | sıcak anlatılar: "
                f"{', '.join(self.state.get('anlatilar', [])) or '-'} | izleme: {watch} ({age} dk önce)")

    def brief_html(self):
        s = self.state
        if not s.get("ozet"):
            return "🧭 <b>Piyasa Nabzı</b>\nHenüz nabız hazırlanmadı."
        icon = {"olumlu": "🟢", "olumsuz": "🔴"}.get(s.get("duygu"), "⚪")
        L = [f"🧭 <b>Piyasa Nabzı</b> — {fmt_ts(s['ts'], with_date=False)}",
             f"<b>Duygu:</b> {icon} {esc(s.get('duygu'))}"
             + (f" | <b>Korku&Açgözlülük:</b> {s['fng'][0]} ({esc(s['fng'][1])})" if s.get("fng") else ""),
             f"<b>Sıcak anlatılar:</b> {esc(', '.join(s.get('anlatilar', [])) or '-')}"]
        if s.get("sectors_up"):
            L.append("<b>Öne çıkan sektörler:</b> " + esc(", ".join(f"{n} {v:+.1f}%" for n, v in s["sectors_up"][:4])))
        L.append(f"\n{esc(s['ozet'])}")
        if s.get("izleme"):
            L.append("\n<b>İzleme listesi:</b>")
            L.extend(f"• {esc(w['coin'])} {'★' * w['guc']} — {esc(w['neden'])}" for w in s["izleme"])
        if s.get("uzak_dur"):
            L.append("<b>Uzak dur:</b> " + esc(", ".join(f"{w['coin']} ({w['neden']})" for w in s["uzak_dur"])))
        return "\n".join(L)

    def today_watch_counts(self, since):
        return Counter(c for e in self.state.get("log", []) if e["ts"] >= since for c in e["izleme"]).most_common(8)
