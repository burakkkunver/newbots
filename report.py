"""Gece raporu: her gün REPORT_HOUR:REPORT_MINUTE'te (yerel saat) detaylı gün sonu raporu + yapay zeka yorumu.
Rapor ayrıca data/reports/YYYY-MM-DD.txt olarak kaydedilir."""
import html
import os
import re
import time

import config
from calibration import BUCKETS, alt_group, f, format_group_lines, group_stats, load_rows, score_bucket
from notify import esc, send_long, send_telegram
from prices import VENUE_NAMES
from util import ALT_SOURCES, day_start_ts, fmt_ts, now_local, read_csv, today_str

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
    "HACIM_HABERLI": "Hacim patlaması + haber", "HACIM_HABERSIZ": "Hacim patlaması (habersiz)",
    "LISTELEME": "Listeleme duyurusu", "HACIM_AI_ONAY": "Hacim + Gemini onayı",
    "HACIM_AI_RED": "Hacim, Gemini reddetti", "HACIM_AI_YOK": "Hacim, Gemini yanıt vermedi",
    "HACIM_BUTCE": "Hacim, Gemini bütçesi doldu", "HACIM_SINIR": "Hacim, saatlik Gemini sınırı",
    "AI_YOK": "Gemini yanıt vermedi", "SANAL_ALINDI": "Sanal alındı (testnette yok)",
    "SANAL_FIYAT_YOK": "Sanal: fiyat bulunamadı", "SANAL_HACIM": "Sanal: hacim düşük", "SANAL_TREN": "Sanal: tren kaçtı",
    "SANAL_POZISYON": "Sanal: zaten pozisyon var", "SANAL_BEKLEME": "Sanal: coin beklemede",
    "SANAL_MAKS": "Sanal: maks. pozisyon dolu", "SANAL_BAKIYE": "Sanal: bütçe yetersiz",
}


def _counts(items):
    out = {}
    for it in items:
        out[it] = out.get(it, 0) + 1
    return sorted(out.items(), key=lambda kv: -kv[1])


def _strip(text):
    return html.unescape(re.sub(r"<[^>]+>", "", text))


def _avg(vals):
    return sum(vals) / len(vals) if vals else 0.0


class Reporter:
    def __init__(self, trader, market, ai, feed, scanner=None, ann=None, pulse=None, tg=None, paper=None):
        self.trader, self.market, self.ai, self.feed = trader, market, ai, feed
        self.scanner, self.ann, self.pulse, self.tg, self.paper = scanner, ann, pulse, tg, paper

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
                send_telegram(f"🧠 Yapay zeka yorumu alınamadı. İstatistikler yukarıda.\n<b>Gemini:</b> "
                              f"{esc(self.ai.status_line())}")
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

    # ---------- sanal işlemler ----------
    def paper_section(self, detailed=False):
        p = self.paper
        if not p or not config.PAPER_ENABLED:
            return "🧪 <b>Sanal işlemler</b>: kapalı (PAPER_ENABLED=False)"
        closed = p.closed_today()
        realized = p.state["realized"]
        S = ["🧪 <b>Sanal işlemler</b> (gerçek fiyatla, para harcanmadı)",
             f"Sanal bütçe: {p.equity():.2f} USDT (başlangıç {config.PAPER_BUDGET_USDT:g}) | toplam gerçekleşen "
             f"{realized.get('sanal', 0):+.2f} USDT"]
        sanal = [c for c in closed if c["kind"] == "sanal"]
        ayna = [c for c in closed if c["kind"] == "ayna"]
        if sanal:
            wins = sum(1 for c in sanal if c["pnl"] > 0)
            S.append(f"<b>Testnette olmayan coinler</b> — bugün {len(sanal)} işlem, {wins} kârlı, "
                     f"{sum(c['pnl'] for c in sanal):+.2f} USDT")
            for c in sanal:
                S.append(f"• {esc(c['coin'])} {int(c['score'])}/10 [{VENUE_NAMES.get(c['venue'], c['venue'])}, "
                         f"{'izleyen' if c['mode'] == 'trailing' else 'sabit'}] {c['pct']:+.2f}% (zirve "
                         f"+{c['peak_pct']:.1f}%, dip {c['trough_pct']:+.1f}%) — {esc(c['reason'])}, {c['minutes']} dk")
        else:
            S.append("Testnette olmayan coinler: bugün kapanan sanal işlem yok")
        if ayna:
            tn = [c["testnet_pct"] for c in ayna if c.get("testnet_pct") is not None]
            S.append(f"<b>Ayna</b> (testnet işlemlerinin gerçek fiyatla sonucu) — bugün {len(ayna)} işlem, ortalama "
                     f"{_avg([c['pct'] for c in ayna]):+.2f}%"
                     + (f" | aynı işlemler testnette ortalama {_avg(tn):+.2f}%" if tn else ""))
            for c in ayna:
                S.append(f"• {esc(c['coin'])}USDT {int(c['score'])}/10 [{'izleyen' if c['mode'] == 'trailing' else 'sabit'}] "
                         f"{c['pct']:+.2f}% (zirve +{c['peak_pct']:.1f}%, dip {c['trough_pct']:+.1f}%) — "
                         f"{esc(c['reason'])}, {c['minutes']} dk"
                         + (f" | testnet {c['testnet_pct']:+.2f}%" if c.get("testnet_pct") is not None else ""))
        elif p.mirror_enabled:
            S.append("Ayna: bugün kapanan yok")
        lines = p.position_lines()
        S.append(f"Açık sanal pozisyonlar ({len(lines)}):")
        S.extend(lines or ["• yok"])
        if detailed:
            week = [c for c in p.state["closed"] if c["closed_at"] >= time.time() - 7 * 86400]
            for kind, name in (("sanal", "Sanal (testnette olmayan)"), ("ayna", "Ayna")):
                ks = [c for c in week if c["kind"] == kind]
                if ks:
                    S.append(f"Son 7 gün {name}: {len(ks)} işlem, kazanan %"
                             f"{100 * sum(1 for c in ks if c['pnl'] > 0) / len(ks):.0f}, ortalama "
                             f"{_avg([c['pct'] for c in ks]):+.2f}%, toplam {sum(c['pnl'] for c in ks):+.2f} USDT")
            st = p.px.status
            S.append("Fiyat kaynakları: " + (", ".join(f"{VENUE_NAMES.get(k, k)}: {esc(v)}" for k, v in st.items())
                                             or "henüz istek yapılmadı"))
        return "\n".join(S)

    # ---------- rapor içeriği ----------
    def build(self):
        today = today_str()
        start = day_start_ts()
        all_rows = [r for r in read_csv(SIGNALS_CSV) if r.get("zaman", "").startswith(today) and "durum_kodu" in r]
        signals = [r for r in all_rows if r.get("kaynak") not in ALT_SOURCES]   # haberler
        alt_rows = [r for r in all_rows if r.get("kaynak") in ALT_SOURCES]      # hacim + duyurular
        closed = self.trader.closed_today()
        calib_all = load_rows(measured_since=start)
        calib_today = [r for r in calib_all if r.get("kaynak") not in ALT_SOURCES]
        calib_alt = [r for r in calib_all if r.get("kaynak") in ALT_SOURCES]
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
                real = f", gerçek piyasada {c['real_pct']:+.2f}%" if c.get("real_pct") is not None else ""
                S.append(f"• {c.get('symbol', '?')} {int(c.get('score') or 0)}/10 [{c.get('regime', '?')}, {mode}] "
                         f"{c.get('pct', 0):+.2f}% (zirve +{c.get('peak_pct') or 0:.1f}%{real}) — "
                         f"{esc(c.get('reason', '?'))}, {c.get('minutes', '?')} dk")
            S.append("Çıkış sebepleri: " + ", ".join(f"{esc(k.split(' (')[0])} {v}"
                                                      for k, v in _counts([c.get("reason", "?") for c in closed])))
        else:
            S.append("\n📈 <b>Bugünkü işlemler</b>: kapanan işlem yok")
        if self.paper and config.PAPER_ENABLED:
            S.append("\n" + self.paper_section())

        # Piyasa
        changes = self.market.today_changes()
        S.append(f"\n🌍 <b>Piyasa</b>\nŞu an: {esc(self.market.describe())}")
        if changes:
            S.append("Gün içi rejim: " + " → ".join(
                f"{fmt_ts(e['ts'], with_date=False)} {config.REGIMES[e['regime']]['ad']}" for e in changes))

        # Piyasa Nabzı
        if self.pulse and self.pulse.state.get("ozet"):
            ps = self.pulse.state
            when = fmt_ts(ps["ts"], with_date=ps["ts"] < start)[:16]
            S.append(f"\n🧭 <b>Piyasa Nabzı</b> (son: {when}, duygu: {esc(ps.get('duygu'))})")
            S.append(esc(ps["ozet"]))
            S.append("Sıcak anlatılar: " + esc(", ".join(ps.get("anlatilar", [])) or "-"))
            wc = self.pulse.today_watch_counts(start)
            if wc:
                S.append("Bugün izleme listesine en çok girenler: " + esc(", ".join(f"{c} ({n})" for c, n in wc)))

        # Haber hunisi
        codes = [r.get("durum_kodu", "?") for r in signals]
        analyzed = [r for r in signals if r.get("durum_kodu") not in ("FILTRE", "AI_YOK")]
        buckets = {b[0]: 0 for b in BUCKETS}
        for r in analyzed:
            b = score_bucket(r)
            if b in buckets:
                buckets[b] += 1
        candidates = [r for r in analyzed if r.get("karar") == "BUY"]
        S.append(f"\n📰 <b>Haber hunisi</b>\nİşlenen taze haber: {len(signals)} | Kural filtresi: {codes.count('FILTRE')} | "
                 f"Gemini analizi: {len(analyzed)}"
                 + (f" | Gemini yanıt vermedi: {codes.count('AI_YOK')}" if "AI_YOK" in codes else ""))
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
                             and r.get("durum_kodu") not in ("ALINDI", "SANAL_ALINDI")], key=lambda r: -f(r, "max4s"))[:5]
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

        # Alternatif sinyaller
        S.append(f"\n📡 <b>Hacim tarayıcı ve listeleme duyuruları</b> "
                 f"({'alım AÇIK' if config.ALT_SIGNALS_TRADE else 'sadece bildirim + kayıt'})")
        S.append("Bugünkü sinyaller: " + (", ".join(f"{CODE_NAMES.get(k, k)} {v}" for k, v in
                                                     _counts([r.get("durum_kodu", "?") for r in alt_rows])) or "yok"))
        if calib_alt:
            S.append(f"Bugün ölçülen {len(calib_alt)} sinyalin sonucu:")
            S.extend(format_group_lines(group_stats(calib_alt, alt_group)))
        if self.scanner:
            st = self.scanner.stats
            S.append(f"Tarayıcı: {st['scans']} tarama, {st['candidates']} aday incelendi, {st['signals']} sinyal "
                     f"({esc(self.scanner.status)})")
        if self.ann:
            S.append("Duyuru kaynakları: " + esc(", ".join(f"{k}: {v}" for k, v in self.ann.status.items())))
        if self.tg:
            S.append("Telegram kanalları: " + esc(self.tg.status_text()))

        d = self.ai.day
        bad_feeds = ", ".join(self.feed.feed_errors) or "hepsi çalışıyor"
        S.append(f"\n🤖 <b>Gemini</b>: {esc(self.ai.status_line())}\n{d['calls']} çağrı, {d['errors']} hata, "
                 f"{d.get('skipped', 0)} atlandı, {d['fallbacks']} yedek model | tahmini maliyet: "
                 f"{esc(self.ai.spend_line())}\n📡 <b>RSS</b>: {esc(bad_feeds)}")
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
