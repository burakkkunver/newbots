"""BTC rejimi: piyasa ortamına göre alımların ne kadar agresif olacağını belirler.

BTC'nin son 1 / 4 / 24 saatlik değişimi gerçek Binance verisinden (5 dk mumlar) hesaplanır.
Rejim değişimi için aynı sonuç art arda 2 kez görülmeli (eşik çevresinde gidip gelmesin).
Ani çöküş (Çok düşüş) ise beklemeden hemen devreye girer.
"""
import json
import os
import time

import config
from notify import send_telegram
from util import day_start_ts, fmt_ts, pct

STATE_FILE = os.path.join(config.DATA_DIR, "market.json")
ORDER = ["COK_DUSUS", "DUSUS", "YATAY", "BOGA", "COK_BOGA"]


def classify(ch1, ch4, ch24):
    if ch24 <= config.REGIME_CRASH_24H or ch1 <= config.REGIME_CRASH_1H:
        return "COK_DUSUS"
    if ch24 >= config.REGIME_STRONG_BULL_24H and ch4 >= 0:
        return "COK_BOGA"
    if ch24 >= config.REGIME_BULL_24H:
        return "BOGA"
    if ch24 > config.REGIME_FLAT_24H:
        return "YATAY"
    return "DUSUS"


def rules_text(name):
    r = config.REGIMES[name]
    exit_txt = "izleyen stop" if r["exit"] == "trailing" else "küçük sabit kâr al"
    return (f"alım için en az {r['min_score']} puan, tutar ×{r['alloc']:g}, çıkış: {exit_txt}"
            + (f", süre ×{r['hold_mult']:g}" if r["hold_mult"] != 1 else ""))


class Market:
    def __init__(self, bx):
        self.bx = bx
        self.current = None
        self.metrics = {}
        self.candidate = None
        self.candidate_count = 0
        self.log = []
        self.last_check = 0
        self._load()

    # ---------- kalıcı durum ----------
    def _load(self):
        try:
            with open(STATE_FILE) as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return
        self.log = data.get("log", [])
        # Yarım saatten eski bilgiyle başlamayalım, ilk hesaplama doğrudan geçerli olsun
        if time.time() - data.get("metrics", {}).get("at", 0) < 1800:
            self.current = data.get("current")
            self.metrics = data.get("metrics", {})

    def _save(self):
        self.log = self.log[-300:]
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"current": self.current, "metrics": self.metrics, "log": self.log}, f)
        os.replace(tmp, STATE_FILE)

    # ---------- dışarıya açık ----------
    def info(self):
        name = self.current or "YATAY"
        d = dict(config.REGIMES[name])
        d["name"] = name
        d.update({k: self.metrics.get(k, 0.0) for k in ("ch1", "ch4", "ch24", "price")})
        d["known"] = self.current is not None
        return d

    def describe(self, info=None):
        i = info or self.info()
        if not i["known"]:
            return f"{i['ad']} (BTC verisi henüz alınamadı, temkinli varsayılan)"
        return f"{i['ad']} (BTC 24s {i['ch24']:+.1f}%, 4s {i['ch4']:+.1f}%, 1s {i['ch1']:+.1f}%)"

    def today_changes(self):
        start = day_start_ts()
        return [e for e in self.log if e["ts"] >= start]

    def refresh(self, force=False):
        if not force and time.time() - self.last_check < config.REGIME_CHECK_MIN * 60:
            return self.info()
        self.last_check = time.time()
        try:
            kl = self.bx.real_klines("BTCUSDT", "5m", limit=289)
            closes = [float(k[4]) for k in kl]
        except Exception as e:
            print(f"⚠️ BTC rejimi hesaplanamadı: {e}")
            return self.info()
        if len(closes) < 13:
            return self.info()
        price = closes[-1]

        def change(n):
            return pct(price, closes[-1 - n]) if len(closes) > n else pct(price, closes[0])

        ch1, ch4, ch24 = change(12), change(48), change(288)
        self.metrics = {"ch1": ch1, "ch4": ch4, "ch24": ch24, "price": price, "at": time.time()}
        new = classify(ch1, ch4, ch24)

        if self.current is None:
            self._switch(new, announce=False)
        elif new == self.current:
            self.candidate, self.candidate_count = None, 0
        elif new == "COK_DUSUS" or (self.candidate == new and self.candidate_count + 1 >= 2):
            self._switch(new, announce=True)
        else:
            if self.candidate == new:
                self.candidate_count += 1
            else:
                self.candidate, self.candidate_count = new, 1
        self._save()
        return self.info()

    def _switch(self, new, announce):
        old = self.current
        self.current = new
        self.candidate, self.candidate_count = None, 0
        m = self.metrics
        self.log.append({"ts": time.time(), "regime": new, "ch24": round(m["ch24"], 2),
                         "ch4": round(m["ch4"], 2), "ch1": round(m["ch1"], 2)})
        print(f"🌍 BTC rejimi: {new} ({fmt_ts(time.time(), False)})")
        if announce and old:
            arrow = "⬆️" if ORDER.index(new) > ORDER.index(old) else "⬇️"
            send_telegram(
                f"🔄 <b>BTC rejimi değişti</b> {arrow}\n"
                f"{config.REGIMES[old]['ad']} → <b>{config.REGIMES[new]['ad']}</b>\n"
                f"BTC 24s {m['ch24']:+.2f}% | 4s {m['ch4']:+.2f}% | 1s {m['ch1']:+.2f}%\n"
                f"Yeni kurallar: {rules_text(new)}")
