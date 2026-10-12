"""Gerçek piyasa fiyatları: Binance (data-api), Gate.io ve MEXC'nin anahtarsız, herkese açık uç noktaları.

Sanal işlemler ve kalibrasyon, testnette (ya da hiç Binance'te) olmayan coinlerin gerçek fiyatını buradan okur.
Her borsa aynı biçimde döner: {"venue", "bid", "ask", "last", "vol24", "ch24"}
  bid: en iyi alış fiyatı (hemen satarsan alacağın), ask: en iyi satış fiyatı (hemen alırsan ödeyeceğin)
Coin o borsada işlem görmüyorsa None döner; ağ hatasında istisna fırlatılır (çağıran o turu atlar).
"""
import time

import requests

import config
from binance_api import BinanceError

GATE_URL = "https://api.gateio.ws/api/v4"
MEXC_URL = "https://api.mexc.com"
VENUE_NAMES = {"binance": "Binance", "gateio": "Gate.io", "mexc": "MEXC"}
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
FIND_CACHE_SEC = 600


def _pos(v):
    """Pozitif sayı ya da None."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x > 0 else None


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _quote(venue, last, bid, ask, vol24, ch24):
    if not last:
        return None
    bid, ask = bid or last, ask or last
    if bid > ask:   # bozuk / bayat defter
        bid = ask = last
    return {"venue": venue, "last": last, "bid": bid, "ask": ask, "vol24": vol24, "ch24": ch24}


class PriceSources:
    def __init__(self, bx):
        self.bx = bx
        self.status = {}
        self._cache = {}

    def _get(self, url, params):
        r = requests.get(url, params=params, headers=HEADERS, timeout=10)
        if r.status_code in (400, 404):
            return None   # bu borsada böyle bir çift yok
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}")
        return r.json()

    # ---------- tek coin fiyatı ----------
    def quote(self, venue, base):
        """Coinin bu borsadaki gerçek fiyatı (yoksa None)."""
        fn = {"binance": self._q_binance, "gateio": self._q_gateio, "mexc": self._q_mexc}.get(venue)
        if fn is None:
            raise ValueError(f"bilinmeyen borsa: {venue}")
        try:
            q = fn(base.upper())
        except Exception as e:
            self.status[venue] = f"hata: {e}"[:80]
            raise
        self.status[venue] = "ok"
        return q

    def _q_binance(self, base):
        try:
            t = self.bx.real_ticker24(f"{base}USDT")
        except BinanceError as e:
            if e.status == 400:
                return None
            raise
        return _quote("binance", _pos(t.get("price")), _pos(t.get("bid")), _pos(t.get("ask")),
                      _num(t.get("quote_volume")), _num(t.get("change_pct")))

    def _q_gateio(self, base):
        data = self._get(f"{GATE_URL}/spot/tickers", {"currency_pair": f"{base}_USDT"})
        if not data or not isinstance(data, list):
            return None
        t = data[0]
        return _quote("gateio", _pos(t.get("last")), _pos(t.get("highest_bid")), _pos(t.get("lowest_ask")),
                      _num(t.get("quote_volume")), _num(t.get("change_percentage")))

    def _q_mexc(self, base):
        t = self._get(f"{MEXC_URL}/api/v3/ticker/24hr", {"symbol": f"{base}USDT"})
        if isinstance(t, list):
            t = t[0] if t else None
        if not isinstance(t, dict):
            return None
        last, opn = _pos(t.get("lastPrice")), _pos(t.get("openPrice"))
        # MEXC'nin değişim yüzdesi alanı oran olarak gelebiliyor; açılış fiyatından kendimiz hesaplıyoruz
        return _quote("mexc", last, _pos(t.get("bidPrice")), _pos(t.get("askPrice")), _num(t.get("quoteVolume")),
                      (last / opn - 1) * 100 if last and opn else 0.0)

    def find(self, base, venues=None):
        """Coinin gerçek fiyatını sırayla borsalarda arar; işlem gördüğü ilk borsanın fiyatını döner (yoksa None)."""
        base = base.upper()
        venues = list(venues or config.PAPER_VENUES)
        key = (base, tuple(venues))
        hit = self._cache.get(key)
        if hit and time.time() - hit[0] < FIND_CACHE_SEC:
            if hit[1] is None:
                return None
            try:
                q = self.quote(hit[1], base)
                if q:
                    return q
            except Exception:
                pass
        failed = 0
        for v in venues:
            try:
                q = self.quote(v, base)
            except Exception as e:
                failed += 1
                print(f"⚠️ {VENUE_NAMES.get(v, v)} fiyatı alınamadı ({base}): {e}")
                continue
            if q:
                self._cache[key] = (time.time(), v)
                return q
        if not failed:
            self._cache[key] = (time.time(), None)   # hiçbir borsada yok (ağ hatası olduysa önbelleğe alma)
        return None

    # ---------- toplu fiyat (pozisyon takibi) ----------
    def quotes(self, pairs):
        """[(borsa, coin), ...] -> {(borsa, coin): fiyat}. Binance çiftleri tek istekte okunur.
        Fiyatı alınamayan çift sonuçta yer almaz."""
        out = {}
        bases = sorted({b for v, b in pairs if v == "binance"})
        if bases:
            try:
                books = self.bx.real_books([f"{b}USDT" for b in bases])
                for b in bases:
                    bid, ask = books.get(f"{b}USDT", (0, 0))
                    if bid > 0 and ask > 0:
                        out[("binance", b)] = _quote("binance", (bid + ask) / 2, bid, ask, None, None)
                self.status["binance"] = "ok"
            except Exception:
                pass   # bir sembol geçersizse tüm istek düşer; aşağıda tek tek denenir
        for v, b in pairs:
            if (v, b) in out:
                continue
            try:
                q = self.quote(v, b)
            except Exception as e:
                print(f"⚠️ {VENUE_NAMES.get(v, v)} fiyatı alınamadı ({b}): {e}")
                continue
            if q:
                out[(v, b)] = q
        return out

    # ---------- mumlar ----------
    def klines(self, venue, base, start_ts, minutes):
        """1 dakikalık mumlar, Binance biçiminde: [[açılış_ms, açılış, yüksek, düşük, kapanış], ...] (eskiden yeniye)"""
        base = base.upper()
        minutes = max(1, min(1000, int(minutes)))
        if venue == "binance":
            return self.bx.real_klines(f"{base}USDT", "1m", start_ts=start_ts, limit=minutes)
        start = int(start_ts // 60 * 60)
        if venue == "gateio":
            rows = self._get(f"{GATE_URL}/spot/candlesticks", {"currency_pair": f"{base}_USDT", "interval": "1m",
                                                               "from": start, "to": start + (minutes - 1) * 60}) or []
            out = []
            for r in rows:
                if isinstance(r, dict):
                    t, o, h, low, c = r.get("t"), r.get("o"), r.get("h"), r.get("l"), r.get("c")
                else:   # [zaman_sn, hacim_usdt, kapanış, yüksek, düşük, açılış, hacim_coin, kapandı_mı]
                    t, c, h, low, o = r[0], r[2], r[3], r[4], r[5]
                out.append([int(float(t)) * 1000, str(o), str(h), str(low), str(c)])
            return sorted(out)
        if venue == "mexc":
            out, t, end = [], start * 1000, (start + minutes * 60) * 1000
            for _ in range(5):
                if t >= end:
                    break
                rows = self._get(f"{MEXC_URL}/api/v3/klines", {"symbol": f"{base}USDT", "interval": "1m",
                                                                "startTime": t, "endTime": min(end, t + 500 * 60000) - 1,
                                                                "limit": 500}) or []
                if not rows:
                    t += 500 * 60000
                    continue
                out += [[int(r[0]), str(r[1]), str(r[2]), str(r[3]), str(r[4])] for r in rows if int(r[0]) < end]
                t = int(rows[-1][0]) + 60000
            return out
        raise ValueError(f"bilinmeyen borsa: {venue}")

    def price_at(self, venue, base, ts):
        """Verilen dakikanın başındaki (1 dk mum açılışı) gerçek fiyat; mum yoksa None."""
        kl = self.klines(venue, base, ts, 1)
        return float(kl[0][1]) if kl else None
