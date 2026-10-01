"""Gece raporu: her gün REPORT_HOUR:REPORT_MINUTE'te (yerel saat) detaylı gün sonu raporu + yapay zeka yorumu.
Rapor ayrıca data/reports/YYYY-MM-DD.txt olarak kaydedilir."""
import html
import os
import re

import config
from calibration import BUCKETS, f, format_group_lines, group_stats, load_rows, score_bucket
from notify import esc, send_long, send_telegram
from util import day_start_ts, fmt_ts, now_local, read_csv, today_str

SIGNALS_CSV = os.path.join(config.DATA_DIR, "signals.csv")
SIGNALS_HEADER = ["zaman", "yayin", "gecikme_dk", "kaynak", "coin", "puan", "karar", "olay_turu", "kesinlik",
                  "yenilik", "aktor", "olcek", "rejim", "ikinci_gorus", "durum_kodu", "aciklama", "sebep",
                  "baslik", "link"]
REPORT_DIR = os.path.join(config.DATA_DIR, "reports")

CODE_NAMES = {
    "ALINDI": "Alındı", "PASS": "Pas (düşük puan)", "FILTRE": "Kural filtresi",
    "REJIM_ESIGI": "Rejim eşiğinin altında", "IKINCI_GORUS_RED": "İkinci görüş reddetti",
    "IKINCI_GORUS_YOK": "İkinci görüş alınamadı", "ENGEL_TESTNET": "Testnette yok", "ENGEL_TREN": "Tren kaçtı",
    "ENGEL_BAKIYE": "Bakiye yetersiz", "ENGEL_POZISYON": "Zaten pozisyon var", "ENGEL_BEKLEME": "Coin beklemede",
    "ENGEL_MAKS": "Maks. pozisyon dolu", "ENGEL_HATA": "Emir hatası", "KAPALI": "İşlem kapalı", "GENEL": "Coin yok",
}


def _counts(items):
    out = {}
    for it in items:
        out[it] = out.get(it, 0) + 1
    return sorted(out.items(), key=lambda kv: -kv[1])


def _strip(text):
    return html.unescape(re.sub(r"<[^>]+>", "", text))


class Reporter:
    def __init__(self, trader, market, ai, feed):
        self.trader, self.market, self.ai, self.feed = trader, market, ai, feed

    def due(self):
        now = now_local()
        if (now.hour, now.minute) < (config.REPORT_HOUR, config.REPORT_MINUTE):
            return False
        return self.trader.state.get("last_report") != today_str()

    def run(self, manual=False):
        print("📝 Gece raporu hazırlanıyor...")
        report_html, data_text = self.build()
        send_long(report_html)
        ai_text = None
        if config.REPORT_AI:
            ai_text = self.ai.commentary(data_text)
            if ai_text:
                send_long("🧠 <b>Yapay Zeka Yorumu</b>\n\n" + esc(ai_text.strip()))
            else:
                send_telegram("🧠 Yapay zeka yorumu alınamadı (Gemini yoğun olabilir). İstatistikler yukarıda.")
        os.makedirs(REPORT_DIR, exist_ok=True)
        path = os.path.join(REPORT_DIR, f"{today_str()}{'_manuel' if manual else ''}.txt")
        with open(path, "w") as fh:
            fh.write(_strip(report_html))
            fh.write("\n\n==== YAPAY ZEKA YORUMU ====\n" + (ai_text or "(alınamadı)") + "\n")
            fh.write("\n\n==== YAPAY ZEKAYA GÖNDERİLEN VERİ ====\n" + data_text + "\n")
        if not manual:
            self.trader.state["last_report"] = today_str()
            self.trader._save()
            self.ai.reset_day()
        return path

    # ---------- rapor içeriği ----------
    def build(self):
        today = today_str()
        start = day_start_ts()
        signals = [r for r in read_csv(SIGNALS_CSV) if r.get("zaman", "").startswith(today) and "durum_kodu" in r]
        closed = self.trader.closed_today()
        calib_today = load_rows(measured_since=start)
        calib_by_link = {r["link"]: r for r in load_rows(since_ts=start - 6 * 3600)}

        S = []   # Telegram (HTML)
        S.append(f"📅 <b>Gün Sonu Raporu — {now_local().strftime('%d.%m.%Y')}</b>"
                 f"{' (TESTNET)' if config.TEST_MODE else ''}")

        # Portföy
        pos_lines, open_value = self.trader.position_lines()
        equity = self.trader.bot_cash() + open_value
        day_pnl = sum(c["pnl"] for c in closed)
        S.append(f"\n💰 <b>Portföy</b>\nBot bütçesi: {equity:.2f} USDT (başlangıç {config.BUDGET_USDT:g}, "
                 f"{(equity / config.BUDGET_USDT - 1) * 100:+.2f}%)\nBugünkü gerçekleşen K/Z: {day_pnl:+.2f} USDT | "
                 f"Toplam gerçekleşen: {self.trader.state['realized_pnl']:+.2f} USDT")
        S.append(f"Açık pozisyonlar ({len(pos_lines)}):")
        S.extend(pos_lines or ["• yok"])

        # İşlemler
        if closed:
            wins = sum(1 for c in closed if c["pnl"] > 0)
            S.append(f"\n📈 <b>Bugünkü işlemler</b> ({len(closed)} işlem, {wins} kârlı, kazanma %{100 * wins / len(closed):.0f})")
            for c in closed:
                mode = {"trailing": "izleyen", "fixed": "sabit"}.get(c.get("mode"), "eski sürüm")
                S.append(f"• {c.get('symbol', '?')} {int(c.get('score') or 0)}/10 [{c.get('regime', '?')}, {mode}] "
                         f"{c.get('pct', 0):+.2f}% (zirve +{c.get('peak_pct') or 0:.1f}%) — "
                         f"{esc(c.get('reason', '?'))}, {c.get('minutes', '?')} dk")
            S.append("Çıkış sebepleri: " + ", ".join(f"{esc(k.split(' (')[0])} {v}"
                                                      for k, v in _counts([c.get("reason", "?") for c in closed])))
        else:
            S.append("\n📈 <b>Bugünkü işlemler</b>: kapanan işlem yok")

        # Piyasa
        changes = self.market.today_changes()
        S.append(f"\n🌍 <b>Piyasa</b>\nŞu an: {esc(self.market.describe())}")
        if changes:
            S.append("Gün içi rejim: " + " → ".join(
                f"{fmt_ts(e['ts'], with_date=False)} {config.REGIMES[e['regime']]['ad']}" for e in changes))

        # Haber hunisi
        codes = [r.get("durum_kodu", "?") for r in signals]
        analyzed = [r for r in signals if r.get("durum_kodu") != "FILTRE"]
        buckets = {b[0]: 0 for b in BUCKETS}
        for r in analyzed:
            b = score_bucket(r)
            if b in buckets:
                buckets[b] += 1
        candidates = [r for r in analyzed if r.get("karar") == "BUY"]
        S.append(f"\n📰 <b>Haber hunisi</b>\nİşlenen taze haber: {len(signals)} | Kural filtresi: {codes.count('FILTRE')} | "
                 f"Gemini analizi: {len(analyzed)}")
        S.append("Puan dağılımı: " + " | ".join(f"{k}: {v}" for k, v in buckets.items()))
        S.append(f"Alım adayı (BUY): {len(candidates)} → " + (", ".join(
            f"{CODE_NAMES.get(k, k)} {v}" for k, v in _counts([r.get('durum_kodu', '?') for r in candidates])) or "yok"))
        filt = _counts([r.get("aciklama", "").split("(")[0].replace("Kural filtresi:", "").strip()
                        for r in signals if r.get("durum_kodu") == "FILTRE"])
        if filt:
            S.append("Filtre türleri: " + ", ".join(f"{esc(k)} {v}" for k, v in filt[:4]))
        src = _counts([r.get("kaynak", "?") for r in signals])
        if src:
            S.append("Kaynaklar: " + ", ".join(f"{esc(k)} {v}" for k, v in src[:6]))

        # Kalibrasyon
        S.append(f"\n🎯 <b>Kalibrasyon</b> (bugün tamamlanan {len(calib_today)} ölçüm; her haber 4 saat sonra ölçülür)")
        if calib_today:
            S.extend(format_group_lines(group_stats(calib_today, score_bucket, [b[0] for b in BUCKETS]), " puan"))
            movers = sorted([r for r in calib_today if (f(r, "max4s") or 0) >= 2 and r.get("coin") != "GENEL"
                             and r.get("durum_kodu") != "ALINDI"], key=lambda r: -f(r, "max4s"))[:5]
            if movers:
                S.append("🔎 <b>Kaçırılan en büyük hareketler</b> (4 saatteki zirve):")
                for r in movers:
                    S.append(f"• {esc(r['coin'])} {f(r, 'max4s'):+.1f}% | puan {r['puan'] or '-'} | "
                             f"{CODE_NAMES.get(r['durum_kodu'], r['durum_kodu'])} | {esc(r['baslik'][:70])}")
            bad = sorted([r for r in calib_today if (f(r, "puan") or 0) >= 7 and (f(r, "r1s") or 0) < 0],
                         key=lambda r: f(r, "r1s"))[:3]
            if bad:
                S.append("⚠️ <b>Yüksek puanlı ama düşenler</b> (1 saat):")
                for r in bad:
                    S.append(f"• {esc(r['coin'])} {f(r, 'r1s'):+.1f}% | puan {r['puan']} | "
                             f"{CODE_NAMES.get(r['durum_kodu'], r['durum_kodu'])} | {esc(r['baslik'][:70])}")
        else:
            S.append("Henüz tamamlanmış ölçüm yok.")

        d = self.ai.day
        bad_feeds = ", ".join(self.feed.feed_errors) or "hepsi çalışıyor"
        S.append(f"\n🤖 <b>Gemini</b>: {d['calls']} çağrı, {d['errors']} hata, {d['fallbacks']} yedek model | "
                 f"bugünkü tahmini maliyet ${d['cost_usd']:.3f}\n📡 <b>RSS</b>: {esc(bad_feeds)}")
        report_html = "\n".join(S)

        # Yapay zekaya gönderilecek veri: rapor + bugünkü haber listesi (sonuçlarıyla)
        lines = []
        interesting = [r for r in signals if (f(r, "puan") or 0) >= 5 or r.get("karar") == "BUY"
                       or r.get("link") in calib_by_link]
        for r in interesting[-120:]:
            c = calib_by_link.get(r.get("link"))
            outcome = (f" | sonuç: 1s {c['r1s'] or '-'}%, max1s {c['max1s'] or '-'}%, 4s {c['r4s'] or '-'}%"
                       if c else "")
            g = lambda k: r.get(k) or "-"  # noqa: E731
            lines.append(f"{g('zaman')[11:16]} | {g('coin')} | puan {g('puan')} | {g('olay_turu')}/{g('kesinlik')}/"
                         f"{g('aktor')} | {g('durum_kodu')} | {g('baslik')[:90]}{outcome}")
        data_text = _strip(report_html) + "\n\nBUGÜNKÜ HABERLER (puan>=5, adaylar ve ölçülenler):\n" + \
            ("\n".join(lines) if lines else "(yok)")
        return report_html, data_text
