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


def scanner():
    from binance_api import Binance
    from scanner import _tradeable
    b = Binance("", "", testnet=config.TEST_MODE)
    prices = b.real_prices_all()
    usable = [s for s in prices if _tradeable(s)]
    kl = b.real_klines("UNIUSDT", "1m", limit=5)
    return f"{len(usable)} USDT çifti tek istekle alındı, mum verisi OK ({len(kl)} mum)"


def announcements():
    from announcements import SOURCES, AnnouncementWatcher
    w = AnnouncementWatcher()
    ok = 0
    for src in SOURCES:
        try:
            entries = w.fetch(src)
            ok += 1
            sample = entries[0]["title"][:70] if entries else "(şu an listeleme duyurusu yok)"
            print(f"   ✅ {src['name']}: {len(entries)} kayıt | örnek: {sample}")
        except Exception as e:
            print(f"   ❌ {src['name']}: erişilemiyor ({e}) -> bu kaynak atlanır, bot etkilenmez")
    return f"{ok}/{len(SOURCES)} kaynak erişilebilir"


def telegram_channels():
    if not config.TG_API_ID or not config.TG_API_HASH:
        return "yapılandırılmadı (isteğe bağlı) -> KURULUM.md 'Telegram haber kanalları' bölümü"
    try:
        from telethon.sync import TelegramClient
    except ImportError:
        raise RuntimeError("telethon kurulu değil: pip install --upgrade pip setuptools wheel && pip install -r requirements.txt")
    from tgnews import SESSION_PATH
    client = TelegramClient(SESSION_PATH, config.TG_API_ID, config.TG_API_HASH)
    client.connect()
    try:
        if not client.is_user_authorized():
            raise RuntimeError("giriş yapılmamış -> bir kez 'python3 tg_login.py' çalıştır")
        ok = 0
        for name in config.TG_NEWS_CHANNELS:
            try:
                msgs = client.get_messages(client.get_entity(name), limit=1)
                age = int((time.time() - msgs[0].date.timestamp()) / 60) if msgs else -1
                print(f"   ✅ @{name}: son mesaj {age} dk önce | {(msgs[0].raw_text or '')[:60].replace(chr(10), ' ') if msgs else ''}")
                ok += 1
            except Exception as e:
                print(f"   ❌ @{name}: {e}")
        return f"{ok}/{len(config.TG_NEWS_CHANNELS)} kanal okunabiliyor"
    finally:
        client.disconnect()


def pulse():
    import re
    from ai import GeminiAnalyzer
    from binance_api import Binance
    from market import Market
    from news import NewsFeed
    from pulse import MarketPulse
    from scanner import MomentumScanner
    b = Binance("", "", testnet=config.TEST_MODE)
    feed = NewsFeed()
    feed.fetch_fresh()                       # son başlıkları doldur
    sc = MomentumScanner(b, feed)
    sc.tick()                                # coin listesini doldur
    m = Market(b)
    m.refresh(force=True)
    p = MarketPulse(b, feed, sc, m, GeminiAnalyzer())
    data, text = p.collect()
    print("   Kaynaklar: " + ", ".join(f"{k}: {v}" for k, v in p.status.items()))
    for line in text.split("\n")[:9]:
        print(f"   {line[:150]}")
    if not p.run():
        raise RuntimeError("Gemini nabız yorumu alınamadı (yoğunluk olabilir, bot çalışırken tekrar dener)")
    print("   " + re.sub(r"<[^>]+>", "", p.brief_html()).replace("\n", "\n   "))
    return "ok"


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
    step("Hacim tarayıcı", scanner)
    step("Listeleme duyuruları", announcements)
    step("Telegram kanalları", telegram_channels)
    step("Piyasa Nabzı", pulse)
