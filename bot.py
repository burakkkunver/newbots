"""Kripto Haber + Gemini Analiz + Binance Otomatik Alım Botu — ana döngü.

Çalıştırma:  source env.sh && python3 bot.py
"""
import csv
import os
import sys
import time
from datetime import datetime

import config
from ai import GeminiAnalyzer
from news import NewsFeed
from notify import esc, poll_commands, send_telegram
from trader import Trader

SIGNALS_CSV = os.path.join(config.DATA_DIR, "signals.csv")
MAX_AI_FAILS_PER_NEWS = 3


def log_signal(item, res, action):
    new_file = not os.path.exists(SIGNALS_CSV)
    with open(SIGNALS_CSV, "a", newline="") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["zaman", "yayin", "kaynak", "karar", "puan", "coin", "islem", "baslik", "sebep", "link"])
        w.writerow([datetime.now().isoformat(timespec="seconds"),
                    datetime.fromtimestamp(item["published"]).isoformat(timespec="seconds"),
                    item["source"], res["karar"], res["puan"], res["hedef_coin"], action,
                    item["title"], res["sebep"], item["link"]])


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


def run_bot():
    check_env()
    print("🚀 Bot başlatılıyor...")
    feed = NewsFeed()
    ai = GeminiAnalyzer()
    trader = Trader()

    try:
        usdt = trader.startup()
        exch = f"Binance {'TESTNET' if config.TEST_MODE else '⚠️ GERÇEK HESAP'} bağlandı, cüzdanda {usdt:.2f} USDT"
    except Exception as e:
        exch = f"⚠️ Binance bağlantı hatası: {esc(str(e))}"
    print(exch)
    send_telegram(
        f"🚀 <b>Kripto Haber Botu Başlatıldı</b>\n\n{exch}\n"
        f"<b>Bot bütçesi:</b> {config.BUDGET_USDT:g} USDT | <b>Açık pozisyon:</b> {len(trader.positions)}\n"
        f"<b>Model:</b> {', '.join(config.GEMINI_MODELS)}\n"
        f"<b>Haber yaşı sınırı:</b> {config.MAX_NEWS_AGE_MIN:g} dk | <b>Tarama:</b> {config.POLL_SECONDS} sn\n"
        f"<b>Alım eşiği:</b> puan ≥ {config.BUY_MIN_SCORE:g}\n"
        f"Durum için Telegram'a /durum yazabilirsin.")

    ai_fails = {}
    analyzed = 0
    last_summary = time.time()
    fatal_notified = None

    while True:
        loop_start = time.time()
        try:
            trader.manage_positions()

            items = feed.fetch_fresh()
            for item in items[:config.MAX_ANALYSES_PER_CYCLE]:
                print("-" * 60)
                res = ai.analyze(item)
                if res is None:
                    ai_fails[item["id"]] = ai_fails.get(item["id"], 0) + 1
                    if ai.last_fatal_error and ai.last_fatal_error != fatal_notified:
                        fatal_notified = ai.last_fatal_error
                        send_telegram(f"❌ <b>Gemini API hatası</b> (anahtar/faturalandırma?)\n{esc(ai.last_fatal_error)}")
                    if ai_fails[item["id"]] >= MAX_AI_FAILS_PER_NEWS:
                        feed.mark_seen(item)
                    continue
                feed.mark_seen(item)
                analyzed += 1

                puan, karar, coin = res["puan"], res["karar"], res["hedef_coin"]
                if karar == "BUY" and puan >= config.BUY_MIN_SCORE:
                    action = trader.try_buy(coin, puan, item, res["sebep"])
                    print(f"💼 {action}")
                    if not action.startswith("ALINDI"):
                        send_telegram(
                            f"🟢 <b>YÜKSEK POTANSİYEL</b> — alım yapılmadı\n\n<b>Coin:</b> {esc(coin)}\n"
                            f"<b>Puan:</b> {puan:.0f}/10\n<b>Başlık:</b> {esc(item['title'])}\n"
                            f"<b>Sebep:</b> {esc(res['sebep'])}\n<b>Neden alınmadı:</b> {esc(action)}")
                else:
                    action = "PASS"
                    if puan >= config.NOTIFY_MIN_SCORE:
                        send_telegram(
                            f"🔍 <b>HABER (PASS)</b> — {puan:.0f}/10 | {esc(coin)}\n"
                            f"<b>Başlık:</b> {esc(item['title'])}\n<b>Sebep:</b> {esc(res['sebep'])}")
                log_signal(item, res, action)
                # Bekleme sırasında açık pozisyonları da kontrol et
                if time.time() - loop_start > config.POLL_SECONDS:
                    trader.manage_positions()
                    loop_start = time.time()

            cmds = poll_commands()
            due = time.time() - last_summary >= config.SUMMARY_MINUTES * 60
            if due or any(c in ("/durum", "/ozet", "/status") for c in cmds):
                bad = ", ".join(feed.feed_errors) or "hepsi OK"
                send_telegram(trader.summary_text(
                    ai.stats, f"{analyzed} haber analiz edildi | RSS sorunlu: {bad}"))
                if due:
                    last_summary = time.time()

        except KeyboardInterrupt:
            raise
        except Exception as e:
            print(f"❌ DÖNGÜ HATASI: {e}")
            time.sleep(10)

        sleep_for = max(5, config.POLL_SECONDS - (time.time() - loop_start))
        print(f"💤 {sleep_for:.0f} sn bekleniyor...")
        time.sleep(sleep_for)


if __name__ == "__main__":
    try:
        run_bot()
    except KeyboardInterrupt:
        print("\n👋 Bot durduruldu.")
        send_telegram("🛑 <b>Bot durduruldu.</b> (Açık emirler Binance'te durmaya devam eder)")
