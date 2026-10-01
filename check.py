"""Kurulum testi: Telegram, Gemini (analiz + ikinci görüş), Binance, BTC rejimi ve RSS bağlantılarını dener.
Emir GÖNDERMEZ.  Çalıştırma: source env.sh && source venv/bin/activate && python3 check.py"""
import time

import config
from notify import send_telegram


def step(name, fn):
    try:
        print(f"✅ {name}: {fn()}")
    except Exception as e:
        print(f"❌ {name}: {e}")


def gemini():
    from ai import GeminiAnalyzer
    a = GeminiAnalyzer()
    flash = [n for n in a.available if "flash" in n or "pro" in n]
    print(f"   Erişilebilir flash/pro modelleri ({len(flash)}): {', '.join(flash) or 'YOK'}")
    item = {"source": "test", "published": time.time(), "summary": "", "categories": "",
            "title": "Coinbase lists Solana-based token BONK for spot trading"}
    r = a.analyze(item)
    if r is None:
        raise RuntimeError(a.last_fatal_error or "analiz yanıtı alınamadı")
    print(f"   Analiz: puan {r['puan']:.0f}/10 ({r['puan_notu']})")
    if config.REVIEW_ENABLED:
        rv = a.review(item, r, {"coin_ch24": 2.0, "coin_volume": 3e8, "late_move": 0.3}, "📈 Boğa (test)")
        if rv is None:
            print("   ⚠️ İkinci görüş modeli şu an yanıt vermedi (yoğunluk olabilir), bot çalışırken tekrar dener.")
        else:
            print(f"   İkinci görüş [{rv['model']}]: {'ONAY' if rv['onay'] else 'RED'} (güven {rv['guven']:.0f})")
    return f"tahmini maliyet ${a.stats['cost_usd']:.4f}"


def binance():
    from binance_api import Binance
    b = Binance(config.BINANCE_API_KEY, config.BINANCE_SECRET, testnet=config.TEST_MODE)
    b.sync_time()
    b.load_symbols(force=True)
    sol = b.symbols.get("SOLUSDT", {})
    stop_type = "STOP_LOSS (piyasa)" if "STOP_LOSS" in sol.get("order_types", []) else "STOP_LOSS_LIMIT"
    return (f"{'TESTNET' if config.TEST_MODE else 'GERÇEK'} | USDT: {b.free('USDT'):.2f} | "
            f"{len(b.symbols)} USDT çifti | stop emri türü: {stop_type} | OCO: {'var' if sol.get('oco') else 'yok'}")


def regime():
    from binance_api import Binance
    from market import Market, rules_text
    m = Market(Binance("", "", testnet=config.TEST_MODE))
    info = m.refresh(force=True)
    return f"{m.describe(info)} -> {rules_text(info['name'])}"


def rss():
    from news import FEEDS, NewsFeed
    f = NewsFeed()
    for name, url in FEEDS.items():
        _, items = f._fetch_one(name, url)
        print(f"   {'✅' if items else '❌'} {name}: {len(items)} haber {f.feed_errors.get(name, '')}")
    return f"{len(FEEDS) - len(f.feed_errors)}/{len(FEEDS)} kaynak çalışıyor"


if __name__ == "__main__":
    step("Telegram", lambda: send_telegram("🔧 Kurulum testi: Telegram bağlantısı çalışıyor.") or "gönderilemedi")
    step("Gemini", gemini)
    step("Binance", binance)
    step("BTC rejimi", regime)
    step("RSS", rss)
