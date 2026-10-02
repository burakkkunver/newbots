"""Hacim / momentum tarayıcı: haber sitelerine düşmeden önce başlayan hareketleri yakalamak için.

Dakikada bir gerçek Binance'teki TÜM USDT çiftlerinin fiyatı tek istekle alınır (ağırlık 4) ve son
60 dakika hafızada tutulur. 15 dakikada SCAN_MIN_MOVE_PCT'den fazla yükselen birkaç coin için
1 dakikalık mumlar çekilir (coin başına ağırlık 2); son 15 dakikanın hacmi önceki saatin ortalamasının
SCAN_VOL_RATIO katını geçerse "hacim patlaması" sinyali üretilir. Son saatlerde o coinle ilgili
haber varsa sinyal "haberli" sayılır. Toplam yük dakikada ~20 ağırlık (Binance sınırı 6.000).
"""
import time
from collections import deque

import config
from util import pct

STABLE_BASES = {"USDC", "FDUSD", "TUSD", "DAI", "USDP", "BUSD", "USDE", "PYUSD", "EUR", "TRY", "BRL",
                "AEUR", "EURI", "XUSD", "USD1", "BFUSD", "RLUSD", "PAXG", "WBTC", "WBETH", "BNSOL"}


def _tradeable(symbol):
    if not symbol.endswith("USDT") or len(symbol) <= 4:
        return False
    base = symbol[:-4]
    return base not in STABLE_BASES and not base.endswith(("UP", "DOWN", "BULL", "BEAR"))


class MomentumScanner:
    def __init__(self, bx, feed):
        self.bx = bx
        self.feed = feed
        self.snapshots = deque()      # (zaman, {sembol: fiyat})
        self.last_scan = 0
        self.cooldown = {}            # sembol -> bu zamana kadar tekrar sinyal verilmez
        self.errors = 0
        self.status = "henüz çalışmadı"
        self.stats = {"scans": 0, "candidates": 0, "signals": 0}

    def _price_ago(self, minutes, now):
        """'minutes' dakika önceki (en yakın) fiyat anlık görüntüsü. Boşluk 3 dk'dan fazlaysa None."""
        target = now - minutes * 60
        best = None
        for ts, prices in self.snapshots:
            if ts <= target:
                best = (ts, prices)
            else:
                break
        if best is None or target - best[0] > 180:
            return None
        return best[1]

    def tick(self):
        """Zamanı geldiyse tarama yapar. Yeni sinyallerin listesini döndürür."""
        if not config.SCANNER_ENABLED or time.time() - self.last_scan < config.SCAN_SECONDS:
            return []
        self.last_scan = time.time()
        try:
            prices = {s: p for s, p in self.bx.real_prices_all().items() if _tradeable(s)}
        except Exception as e:
            self.errors += 1
            self.status = f"hata: {str(e)[:80]}"
            if self.errors in (1, 10) or self.errors % 60 == 0:
                print(f"⚠️ Hacim tarayıcı fiyat alamadı: {e}")
            return []
        now = time.time()
        self.errors = 0
        self.status = f"ok ({len(prices)} çift)"
        self.snapshots.append((now, prices))
        while self.snapshots and now - self.snapshots[0][0] > 65 * 60:
            self.snapshots.popleft()
        self.stats["scans"] += 1

        old = self._price_ago(config.SCAN_WINDOW_MIN, now)
        if old is None:
            return []   # henüz yeterli geçmiş yok (açılıştan sonraki ilk 15 dk)
        movers = []
        for sym, p in prices.items():
            p0 = old.get(sym)
            if not p0 or now < self.cooldown.get(sym, 0):
                continue
            move = pct(p, p0)
            if move >= config.SCAN_MIN_MOVE_PCT:
                movers.append((move, sym, p))
        movers.sort(reverse=True)
        signals = []
        for move, sym, price in movers[:config.SCAN_MAX_CANDIDATES]:
            self.stats["candidates"] += 1
            sig = self._check_volume(sym, move, price)
            if sig:
                self.cooldown[sym] = now + config.SCAN_ALERT_COOLDOWN_MIN * 60
                signals.append(sig)
        self.stats["signals"] += len(signals)
        return signals

    def _check_volume(self, sym, move, price):
        try:
            kl = self.bx.real_klines(sym, "1m", limit=76)
        except Exception:
            return None
        done = kl[:-1]   # sonuncu mum henüz kapanmadı
        w = config.SCAN_WINDOW_MIN
        if len(done) < w + 30:
            return None
        recent = done[-w:]
        before = done[:-w][-60:]
        vol_recent = sum(float(k[7]) for k in recent)
        vol_before = sum(float(k[7]) for k in before) / len(before) * w
        if vol_recent < config.SCAN_MIN_VOL_USDT:
            return None
        ratio = vol_recent / vol_before if vol_before > 0 else 99.0
        if ratio < config.SCAN_VOL_RATIO:
            return None
        coin = sym[:-4]
        news = self.feed.headlines_about(coin, config.SCAN_NEWS_LOOKBACK_H)
        ch24 = None
        try:
            ch24 = self.bx.real_ticker24(sym)["change_pct"]
        except Exception:
            pass
        return {"coin": coin, "symbol": sym, "move": move, "ratio": ratio, "vol": vol_recent,
                "price": price, "ch24": ch24, "news": news[:3], "ts": time.time()}
