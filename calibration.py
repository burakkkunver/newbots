"""Kalibrasyon: analiz edilen her haberden sonra fiyat GERÇEKTE ne yaptı?

Her haber için sinyal anındaki gerçek Binance fiyatı kaydedilir (alım yapılsın ya da yapılmasın;
PASS ve filtrelenen haberler karşılaştırma grubu olarak çok değerli). 4 saat dolunca 1 dakikalık
mumlardan şunlar hesaplanıp data/calibration.csv dosyasına yazılır:
  - 15 dk / 1 saat / 4 saat sonraki getiri (%)
  - ilk 1 saat ve 4 saatteki en yüksek / en düşük nokta (%)  -> hedef ve stop ayarı için
  - aynı sürede BTC'nin getirisi ve farkı (coin - BTC)       -> haberin piyasadan bağımsız etkisi
Genel piyasa haberleri ("GENEL") BTC üzerinden ölçülür.
"""
import json
import os
import time

import config
from util import ALT_SOURCES, append_csv, fmt_ts, parse_ts, pct, read_csv

PENDING_FILE = os.path.join(config.DATA_DIR, "calib_pending.json")
CALIB_CSV = os.path.join(config.DATA_DIR, "calibration.csv")
HORIZON_MIN = 240
HEADER = ["sinyal_zamani", "yayin_zamani", "gecikme_dk", "kaynak", "coin", "sembol", "puan", "karar",
          "olay_turu", "kesinlik", "yenilik", "aktor", "olcek", "rejim", "ikinci_gorus", "durum_kodu",
          "fiyat_sinyal", "yayindan_sinyale", "r15dk", "r1s", "r4s", "max1s", "min1s", "max4s", "min4s",
          "btc_r1s", "btc_r4s", "fark_r1s", "fark_r4s", "olcum_zamani", "baslik", "link"]
STABLES = {"USDT", "USDC", "FDUSD", "DAI", "TUSD", "BUSD", "USDE", "USDP", "PYUSD", "EUR", "TRY"}
BUCKETS = [("1-4", 0, 4.5), ("5-6", 4.5, 6.5), ("7", 6.5, 7.5), ("8", 7.5, 8.5), ("9-10", 8.5, 11)]


def _num(v):
    return "" if v is None else f"{v:.2f}"


class Calibrator:
    def __init__(self, bx):
        self.bx = bx
        try:
            with open(PENDING_FILE) as f:
                self.pending = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.pending = []

    def _save(self):
        tmp = PENDING_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.pending, f)
        os.replace(tmp, PENDING_FILE)

    def add(self, item, res, code, regime_name, review_txt=""):
        """Haberi ölçüm listesine ekler. Coin gerçek Binance'te yoksa ölçülemez (False)."""
        coin = res.get("hedef_coin") or "GENEL"
        symbol = "BTCUSDT" if coin == "GENEL" or coin in STABLES else f"{coin}USDT"
        try:
            base = self.bx.real_price(symbol)
        except Exception:
            return False
        self.pending.append({
            "ts": time.time(), "published": item["published"], "source": item["source"], "coin": coin,
            "symbol": symbol, "puan": res.get("puan"), "karar": res.get("karar", ""),
            "olay_turu": res.get("olay_turu", ""), "kesinlik": res.get("kesinlik", ""),
            "yenilik": res.get("yenilik", ""), "aktor": res.get("aktor", ""), "olcek": res.get("olcek", ""),
            "rejim": regime_name, "ikinci_gorus": review_txt, "durum_kodu": code, "base": base,
            "title": item["title"], "link": item["link"]})
        self._save()
        return True

    def process_due(self, max_items=20):
        """Süresi (4 saat) dolan ölçümleri hesaplayıp CSV'ye yazar. Kaç kayıt işlendiğini döner."""
        now, done, keep, changed = time.time(), 0, [], False
        for rec in self.pending:
            if done >= max_items or now < rec["ts"] + HORIZON_MIN * 60 + 120:
                keep.append(rec)
                continue
            changed = True
            try:
                row = self._measure(rec)
            except Exception as e:
                rec["tries"] = rec.get("tries", 0) + 1
                print(f"⚠️ Kalibrasyon ölçümü başarısız ({rec['symbol']}): {e}")
                if rec["tries"] < 5:
                    keep.append(rec)
                continue
            if row:
                append_csv(CALIB_CSV, HEADER, row)
            done += 1
        if changed:
            self.pending = keep
            self._save()
        return done

    def _window_stats(self, candles, start_ts, base, minutes):
        end_ms = start_ts * 1000 + minutes * 60000
        w = [k for k in candles if k[0] < end_ms]
        if not w:
            return None, None, None
        return (pct(float(w[-1][4]), base), pct(max(float(k[2]) for k in w), base),
                pct(min(float(k[3]) for k in w), base))

    def _measure(self, rec):
        start = min(rec["published"], rec["ts"])
        need = int((rec["ts"] - start) / 60) + HORIZON_MIN + 3
        kl = self.bx.real_klines(rec["symbol"], "1m", start_ts=start, limit=min(1000, need))
        if not kl:
            return None
        sig_minute_ms = int(rec["ts"] // 60 * 60 * 1000)
        post = [k for k in kl if k[0] >= sig_minute_ms]
        base = rec["base"]
        r15, _, _ = self._window_stats(post, rec["ts"], base, 15)
        r1, mx1, mn1 = self._window_stats(post, rec["ts"], base, 60)
        r4, mx4, mn4 = self._window_stats(post, rec["ts"], base, HORIZON_MIN)
        pre_move = pct(base, float(kl[0][1]))

        if rec["symbol"] == "BTCUSDT":
            btc, btc_base = post, float(post[0][1]) if post else base
        else:
            btc = self.bx.real_klines("BTCUSDT", "1m", start_ts=rec["ts"], limit=HORIZON_MIN + 2)
            btc_base = float(btc[0][1]) if btc else None
        b1 = b4 = None
        if btc and btc_base:
            b1, _, _ = self._window_stats(btc, rec["ts"], btc_base, 60)
            b4, _, _ = self._window_stats(btc, rec["ts"], btc_base, HORIZON_MIN)
        f1 = r1 - b1 if r1 is not None and b1 is not None else None
        f4 = r4 - b4 if r4 is not None and b4 is not None else None
        puan = rec.get("puan")
        return [fmt_ts(rec["ts"]), fmt_ts(rec["published"]), int((rec["ts"] - rec["published"]) / 60),
                rec["source"], rec["coin"], rec["symbol"], "" if puan is None else int(puan), rec["karar"],
                rec["olay_turu"], rec["kesinlik"], rec["yenilik"], rec["aktor"], rec["olcek"], rec["rejim"],
                rec["ikinci_gorus"], rec["durum_kodu"], f"{base:.8g}", _num(pre_move), _num(r15), _num(r1),
                _num(r4), _num(mx1), _num(mn1), _num(mx4), _num(mn4), _num(b1), _num(b4), _num(f1), _num(f4),
                fmt_ts(time.time()), rec["title"], rec["link"]]


# ==========================================
# İSTATİSTİK (Telegram, gece raporu ve analiz.py ortak kullanır)
# ==========================================
def load_rows(since_ts=None, measured_since=None):
    rows = read_csv(CALIB_CSV)
    out = []
    for r in rows:
        try:
            if since_ts and parse_ts(r["sinyal_zamani"]) < since_ts:
                continue
            if measured_since and parse_ts(r["olcum_zamani"]) < measured_since:
                continue
        except (KeyError, ValueError):
            continue
        out.append(r)
    return out


def f(row, key):
    try:
        return float(row.get(key, ""))
    except (TypeError, ValueError):
        return None


def score_bucket(row):
    p = f(row, "puan")
    if p is None:
        return "?"
    for name, lo, hi in BUCKETS:
        if lo <= p < hi:
            return name
    return "?"


ALT_NAMES = {"hacim_haberli": "Hacim patlaması + haber", "hacim_patlamasi": "Hacim patlaması (habersiz)",
             "hacim_habersiz": "Hacim patlaması (habersiz)", "hacim_ai_onay": "Hacim + Gemini onayı",
             "hacim_ai_red": "Hacim, Gemini reddetti", "hacim_ai_yok": "Hacim, Gemini yanıt vermedi"}


def alt_group(row):
    """Alternatif sinyal grubu: hacim (haberli/habersiz) veya hangi borsanın listeleme duyurusu."""
    ev = row.get("olay_turu", "")
    return ALT_NAMES.get(ev) or f"Listeleme: {row.get('kaynak', '?')}"


def _mean(vals):
    return sum(vals) / len(vals) if vals else None


def _share(vals, cond):
    return 100.0 * sum(1 for v in vals if cond(v)) / len(vals) if vals else None


def group_stats(rows, key_fn, order=None):
    groups = {}
    for r in rows:
        groups.setdefault(key_fn(r), []).append(r)
    keys = order if order else sorted(groups, key=lambda k: -len(groups[k]))
    out = []
    for k in keys:
        rs = groups.get(k)
        if not rs:
            continue

        def vals(key):
            return [v for v in (f(r, key) for r in rs) if v is not None]
        mx1, mn1, r1 = vals("max1s"), vals("min1s"), vals("r1s")
        out.append({"grup": k, "n": len(rs), "r15": _mean(vals("r15dk")), "r1": _mean(r1), "r4": _mean(vals("r4s")),
                    "max1": _mean(mx1), "max4": _mean(vals("max4s")), "hit2": _share(mx1, lambda v: v >= 2),
                    "stop2": _share(mn1, lambda v: v <= -2), "pos1": _share(r1, lambda v: v > 0),
                    "fark1": _mean(vals("fark_r1s"))})
    return out


def _p(v, sign=True):
    if v is None:
        return "-"
    return f"{v:+.1f}%" if sign else f"%{v:.0f}"


def format_group_lines(stats, label=""):
    lines = []
    for s in stats:
        lines.append(f"<b>{s['grup']}{label}</b> (n={s['n']}): 1s {_p(s['r1'])} | 4s {_p(s['r4'])} | "
                     f"max1s {_p(s['max1'])} | +%2'ye ulaşan {_p(s['hit2'], False)} | "
                     f"-%2 gören {_p(s['stop2'], False)} | BTC'ye göre {_p(s['fark1'])}")
    return lines


def telegram_summary(days=7):
    since = time.time() - days * 86400
    rows = load_rows(since_ts=since)
    pending = 0
    try:
        with open(PENDING_FILE) as fh:
            pending = len(json.load(fh))
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    if not rows:
        return (f"🎯 <b>Kalibrasyon</b>\nHenüz tamamlanmış ölçüm yok. Her haber 4 saat sonra ölçülür.\n"
                f"Bekleyen ölçüm: {pending}")
    lines = [f"🎯 <b>Kalibrasyon — son {days} gün</b> ({len(rows)} ölçüm, {pending} bekleyen)",
             "1s/4s: ortalama getiri | max1s: ilk 1 saatteki en yüksek nokta ortalaması", ""]
    news = [r for r in rows if r.get("kaynak") not in ALT_SOURCES]
    alt = [r for r in rows if r.get("kaynak") in ALT_SOURCES]
    lines.append("<b>Haberler — puana göre:</b>")
    lines += format_group_lines(group_stats(news, score_bucket, [b[0] for b in BUCKETS]), " puan")
    lines.append("\n<b>Haberler — karara göre:</b>")
    lines += format_group_lines(group_stats(news, lambda r: r.get("durum_kodu") or "?")[:6])
    lines.append("\n<b>Hacim tarayıcı ve listeleme duyuruları:</b>")
    lines += format_group_lines(group_stats(alt, alt_group)) or ["henüz ölçüm yok"]
    return "\n".join(lines)
