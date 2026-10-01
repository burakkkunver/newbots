"""Kripto Haber + Gemini Analiz + Binance Otomatik Alım Botu — ana döngü.

Çalıştırma:  ./start.sh      (veya: source env.sh && python3 bot.py)

Akış: RSS -> kural filtresi -> Gemini olgu çıkarma (puanı kod hesaplar) -> BTC rejimine göre puan eşiği
      -> ucuz kontroller (testnet, bakiye, tren kaçtı mı) -> güçlü modelden ikinci görüş -> alım.
Her haber kalibrasyon için ölçülür, pozisyonlar ayrı thread'de 10 sn'de bir takip edilir,
her gün 23:00'te detaylı rapor gelir.
"""
import os
import sys
import threading
import time
import traceback

import config
import filters
from ai import GeminiAnalyzer
from calibration import CALIB_CSV, HEADER as CALIB_HEADER, Calibrator, telegram_summary
from market import Market, rules_text
from news import NewsFeed
from notify import esc, poll_commands, send_document, send_long, send_telegram
from report import REPORT_DIR, SIGNALS_CSV, SIGNALS_HEADER, Reporter
from trader import TRADES_CSV, TRADES_HEADER, Trader
from util import append_csv, fmt_ts, migrate_csv, today_str

MAX_AI_FAILS_PER_NEWS = 3
HELP = ("🤖 <b>Komutlar</b>\n"
        "/durum — bakiye, açık pozisyonlar, BTC rejimi\n"
        "/rejim — BTC rejimi ve geçerli alım kuralları\n"
        "/kalibrasyon — haberlerden sonra fiyat gerçekte ne yaptı (son 7 gün)\n"
        "/rapor — gün sonu raporunu şimdi hazırla\n"
        "/dosyalar — CSV verilerini ve son raporu dosya olarak gönder\n"
        "/yardim — bu mesaj")


def check_env():
    missing = [n for n, v in (("GEMINI_API_KEY", config.GEMINI_API_KEY),
                              ("TELEGRAM_BOT_TOKEN", config.TELEGRAM_TOKEN),
                              ("TELEGRAM_CHAT_ID", config.TELEGRAM_CHAT_ID)) if not v]
    if config.TRADE_ENABLED:
        missing += [n for n, v in (("BINANCE_API_KEY", config.BINANCE_API_KEY),
                                   ("BINANCE_SECRET", config.BINANCE_SECRET)) if not v]
    if missing:
        print(f"❌ Eksik ortam değişkenleri: {', '.join(missing)}\n   Önce: source env.sh")
        sys.exit(1)


def log_signal(item, res, regime_name, review_txt, code, desc):
    append_csv(SIGNALS_CSV, SIGNALS_HEADER, [
        fmt_ts(time.time()), fmt_ts(item["published"]), int((time.time() - item["published"]) / 60),
        item["source"], res.get("hedef_coin", ""), int(res.get("puan", 0)), res.get("karar", ""),
        res.get("olay_turu", ""), res.get("kesinlik", ""), res.get("yenilik", ""), res.get("aktor", ""),
        res.get("olcek", ""), regime_name, review_txt, code, desc, res.get("sebep", ""), item["title"], item["link"]])


class Bot:
    def __init__(self):
        for path, header in ((SIGNALS_CSV, SIGNALS_HEADER), (TRADES_CSV, TRADES_HEADER), (CALIB_CSV, CALIB_HEADER)):
            migrate_csv(path, header)
        self.feed = NewsFeed()
        self.ai = GeminiAnalyzer()
        self.trader = Trader()
        self.market = Market(self.trader.bx)
        self.calib = Calibrator(self.trader.bx)
        self.reporter = Reporter(self.trader, self.market, self.ai, self.feed)
        self.ai_fails = {}
        self.analyzed = 0
        self.filtered = 0
        self.fatal_notified = None
        self.last_summary = time.time()
        self.stop_event = threading.Event()

    # ---------- başlangıç ----------
    def start(self):
        try:
            usdt = self.trader.startup()
            exch = f"Binance {'TESTNET' if config.TEST_MODE else '⚠️ GERÇEK HESAP'} bağlandı, cüzdanda {usdt:.2f} USDT"
        except Exception as e:
            exch = f"⚠️ Binance bağlantı hatası: {esc(str(e))}"
        print(exch)
        regime = self.market.refresh(force=True)
        threading.Thread(target=self.trader.monitor_forever, args=(self.stop_event,), daemon=True).start()
        send_telegram(
            f"🚀 <b>Kripto Haber Botu Başlatıldı</b>\n\n{exch}\n"
            f"<b>Bot bütçesi:</b> {config.BUDGET_USDT:g} USDT | <b>Açık pozisyon:</b> {len(self.trader.positions)}\n"
            f"<b>BTC rejimi:</b> {esc(self.market.describe(regime))}\n"
            f"<b>Geçerli kurallar:</b> {rules_text(regime['name'])}\n"
            f"<b>Zarar kes:</b> -%{config.HARD_STOP_PCT:g} (borsada) | <b>Time-stop:</b> 7-8 puanda "
            f"{config.TIME_STOP_MIN:g} dk\n"
            f"<b>Analiz modeli:</b> {esc(', '.join(self.ai.chains['main'][:2]))}\n"
            f"<b>İkinci görüş:</b> {esc(', '.join(self.ai.chains['review'][:2])) if config.REVIEW_ENABLED else 'kapalı'}\n"
            f"<b>Haber yaşı sınırı:</b> {config.MAX_NEWS_AGE_MIN:g} dk | <b>Gece raporu:</b> "
            f"{config.REPORT_HOUR:02d}:{config.REPORT_MINUTE:02d}\n\n{HELP}")

    def known_bases(self):
        return {v["base"] for v in self.trader.bx.symbols.values()}

    # ---------- haber işleme ----------
    def process(self, item, regime):
        print("-" * 60)
        pre = filters.prefilter(item["title"])
        if pre:
            res = {"hedef_coin": filters.extract_coin(item["title"], self.known_bases()), "puan": float(pre["puan"]),
                   "karar": "PASS", "olay_turu": pre["filtre"], "sebep": pre["sebep"]}
            print(f"🚫 {pre['sebep']} | {item['title'][:70]}")
            self.feed.mark_seen(item)
            self.filtered += 1
            log_signal(item, res, regime["name"], "", "FILTRE", pre["sebep"])
            self.calib.add(item, res, "FILTRE", regime["name"])
            return

        res = self.ai.analyze(item)
        if res is None:
            self.ai_fails[item["id"]] = self.ai_fails.get(item["id"], 0) + 1
            if self.ai.last_fatal_error and self.ai.last_fatal_error != self.fatal_notified:
                self.fatal_notified = self.ai.last_fatal_error
                send_telegram(f"❌ <b>Gemini API hatası</b>\n{esc(self.ai.last_fatal_error)}")
            if self.ai_fails[item["id"]] >= MAX_AI_FAILS_PER_NEWS:
                self.feed.mark_seen(item)
            return
        self.feed.mark_seen(item)
        self.analyzed += 1

        code, desc, review = self.decide(item, res, regime)
        print(f"💼 {code}: {desc}")
        if code == "IKINCI_GORUS_YOK":
            review_txt = "alinamadi"
        elif review:
            review_txt = f"{'onay' if review['onay'] else 'red'} {review['guven']:.0f}"
        else:
            review_txt = ""
        log_signal(item, res, regime["name"], review_txt, code, desc)
        self.calib.add(item, res, code, regime["name"], review_txt)
        self.notify_decision(item, res, regime, code, desc, review)

    def decide(self, item, res, regime):
        """(durum_kodu, açıklama, ikinci_görüş) döner."""
        if res["karar"] != "BUY":
            return "PASS", "", None
        if res["puan"] < regime["min_score"]:
            return "REJIM_ESIGI", f"{regime['ad']} rejiminde alım için en az {regime['min_score']} puan gerekli.", None
        ok, code, desc, ctx = self.trader.precheck(res["hedef_coin"], res["puan"], item, regime)
        if not ok:
            return code, desc, None
        review = None
        if config.REVIEW_ENABLED:
            review = self.ai.review(item, res, ctx, self.market.describe(regime))
            if review is None:
                return "IKINCI_GORUS_YOK", "İkinci görüş alınamadı (Gemini yoğun), güvenlik için alım yapılmadı.", None
            if not review["onay"]:
                why = review["sebep"] or "; ".join(review["karsi"])
                return "IKINCI_GORUS_RED", f"İkinci görüş reddetti (güven {review['guven']:.0f}): {why}", review
        code, desc = self.trader.execute_buy(ctx, res, item, regime, review)
        return code, desc, review

    def notify_decision(self, item, res, regime, code, desc, review):
        if code == "ALINDI":
            return   # detaylı mesajı trader gönderdi
        facts = f"{esc(res.get('olay_turu', ''))}/{esc(res.get('kesinlik', ''))}/{esc(res.get('aktor', ''))}"
        if code == "PASS":
            if res["puan"] >= config.NOTIFY_MIN_SCORE:
                send_telegram(
                    f"🔍 <b>HABER (PASS)</b> — {res['puan']:.0f}/10 | {esc(res['hedef_coin'])} | {facts}\n"
                    f"<b>Başlık:</b> {esc(item['title'])}\n<b>Sebep:</b> {esc(res['sebep'])}\n"
                    f"<i>{esc(res.get('puan_notu', ''))}</i>")
            return
        extra = ""
        if review and review.get("karsi"):
            extra = "\n<b>Karşı nedenler:</b>\n" + "\n".join(f"• {esc(k)}" for k in review["karsi"])
        send_telegram(
            f"🟡 <b>ALIM ADAYI — alım yapılmadı</b>\n\n<b>Coin:</b> {esc(res['hedef_coin'])} | "
            f"<b>Puan:</b> {res['puan']:.0f}/10 | {facts}\n<b>Rejim:</b> {regime['ad']}\n"
            f"<b>Başlık:</b> {esc(item['title'])}\n<b>Sebep:</b> {esc(res['sebep'])}\n"
            f"<b>Neden alınmadı:</b> {esc(desc)}{extra}")

    # ---------- komutlar ----------
    def send_summary(self):
        bad = ", ".join(self.feed.feed_errors) or "hepsi OK"
        send_telegram(self.trader.summary_text(
            self.market.describe(), self.ai.stats,
            f"{self.analyzed} haber analiz edildi, {self.filtered} kural filtresine takıldı | RSS sorunlu: {bad}"))

    def handle_command(self, cmd):
        print(f"📩 Telegram komutu: {cmd}")
        if cmd in ("/durum", "/ozet", "/status"):
            self.send_summary()
        elif cmd == "/rejim":
            info = self.market.refresh()
            send_telegram(f"🌍 <b>BTC rejimi:</b> {esc(self.market.describe(info))}\n"
                          f"<b>Kurallar:</b> {rules_text(info['name'])}")
        elif cmd in ("/kalibrasyon", "/kalib"):
            send_long(telegram_summary(7))
        elif cmd == "/rapor":
            send_telegram("📝 Rapor hazırlanıyor, yapay zeka yorumu 1 dakikayı bulabilir...")
            self.reporter.run(manual=True)
        elif cmd in ("/dosyalar", "/dosya", "/veri"):
            sent = 0
            for path in (CALIB_CSV, SIGNALS_CSV, TRADES_CSV):
                sent += bool(send_document(path, os.path.basename(path)))
            if os.path.isdir(REPORT_DIR):
                reports = sorted(os.listdir(REPORT_DIR))
                if reports:
                    sent += bool(send_document(os.path.join(REPORT_DIR, reports[-1]), "Son rapor"))
            if not sent:
                send_telegram("Henüz gönderilecek veri dosyası yok.")
        elif cmd in ("/yardim", "/help", "/start"):
            send_telegram(HELP)

    def poll(self, wait=0):
        for cmd in poll_commands(wait):
            try:
                self.handle_command(cmd)
            except Exception as e:
                print(f"❌ Komut hatası ({cmd}): {e}")
                traceback.print_exc()

    # ---------- ana döngü ----------
    def loop(self):
        while True:
            cycle = time.time()
            try:
                regime = self.market.refresh()
                items = self.feed.fetch_fresh()
                for item in items[:config.MAX_ANALYSES_PER_CYCLE]:
                    self.process(item, regime)
                    self.poll(0)   # uzun analizlerde de komutlar cevapsız kalmasın
                done = self.calib.process_due()
                if done:
                    print(f"🎯 {done} kalibrasyon ölçümü tamamlandı.")
                if self.reporter.due():
                    try:
                        self.reporter.run()
                    except Exception as e:
                        # Rapor hatası botu etkilemesin: o gün bir kez bildir, her dakika tekrar deneme
                        traceback.print_exc()
                        self.trader.state["last_report"] = today_str()
                        self.trader._save()
                        send_telegram(f"⚠️ Gece raporu hazırlanamadı: {esc(str(e))}\nBot normal çalışmaya devam ediyor; "
                                      f"kayıtlar tutuluyor.")
                if time.time() - self.last_summary >= config.SUMMARY_MINUTES * 60:
                    self.send_summary()
                    self.last_summary = time.time()
            except KeyboardInterrupt:
                raise
            except Exception as e:
                print(f"❌ DÖNGÜ HATASI: {e}")
                traceback.print_exc()
                time.sleep(5)
            # Bir sonraki taramaya kadar Telegram'ı dinleyerek bekle (komutlara anında cevap)
            while True:
                left = config.POLL_SECONDS - (time.time() - cycle)
                if left <= 1:
                    break
                self.poll(min(left, 25))


def main():
    check_env()
    print("🚀 Bot başlatılıyor...")
    bot = Bot()
    try:
        bot.start()
        bot.loop()
    except KeyboardInterrupt:
        bot.stop_event.set()
        print("\n👋 Bot durduruldu.")
        send_telegram("🛑 <b>Bot durduruldu.</b> (Açık emirler Binance'te durmaya devam eder)")


if __name__ == "__main__":
    main()
