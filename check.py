"""Kurulum testi: Telegram, Gemini, Binance ve RSS bağlantılarını tek tek dener. Emir GÖNDERMEZ."""
import config
from notify import send_telegram


def step(name, fn):
    try:
        print(f"✅ {name}: {fn()}")
    except Exception as e:
        print(f"❌ {name}: {e}")


def gemini():
    from ai import GeminiAnalyzer
    import time
    a = GeminiAnalyzer()
    flash = [n for n in a.available if "gemini" in n]
    print(f"   Erişilebilir Gemini modelleri ({len(flash)}): {', '.join(flash[:25]) or 'YOK'}")
    r = a.analyze({"source": "test", "published": time.time(), "summary": "",
                   "title": "Coinbase lists Solana-based token BONK for spot trading", "categories": ""})
    if r is None:
        raise RuntimeError(a.last_fatal_error or "yanıt alınamadı")
    return r


def binance():
    from binance_api import Binance
    b = Binance(config.BINANCE_API_KEY, config.BINANCE_SECRET, testnet=config.TEST_MODE)
    b.sync_time()
    b.load_symbols(force=True)
    return (f"{'TESTNET' if config.TEST_MODE else 'GERÇEK'} | USDT: {b.free('USDT'):.2f} | "
            f"{len(b.symbols)} USDT çifti | gerçek BTC fiyatı: {b.real_price('BTCUSDT'):.0f}")


def rss():
    from news import NewsFeed, FEEDS
    f = NewsFeed()
    for name, url in FEEDS.items():
        _, items = f._fetch_one(name, url)
        print(f"   {'✅' if items else '❌'} {name}: {len(items)} haber {f.feed_errors.get(name, '')}")
    return f"{len(FEEDS) - len(f.feed_errors)}/{len(FEEDS)} kaynak çalışıyor"


if __name__ == "__main__":
    step("Telegram", lambda: send_telegram("🔧 Kurulum testi: Telegram bağlantısı çalışıyor.") or "gönderilemedi")
    step("Gemini", gemini)
    step("Binance", binance)
    step("RSS", rss)
