import os
import shutil
import sys

SP = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(SP, "data_fast")
shutil.rmtree(DATA, ignore_errors=True)
os.environ.update(DATA_DIR=DATA, WATCH_NEWS_ENABLED="False", PAPER_ENABLED="False", SPIKE_AI_REQUIRE_EVIDENCE="False", TELEGRAM_BOT_TOKEN="x", TELEGRAM_CHAT_ID="1", GEMINI_API_KEY="k",
                  BINANCE_API_KEY="a", BINANCE_SECRET="b", PULSE_ENABLED="False")
sys.path.insert(0, os.path.dirname(SP))
sys.path.insert(0, SP)
import sim as S  # noqa: E402
import time  # noqa: E402
time.sleep = lambda s: None
import config  # noqa: E402

n_ok = 0


def check(c, m):
    global n_ok
    assert c, m
    n_ok += 1
    print("  ✓", m)


import announcements as AN  # noqa: E402
check(next(s for s in AN.SOURCES if s["name"] == AN.SRC_UPBIT)["interval"] == 20, "Upbit duyuruları 20 sn'de bir")

sim = S.Sim()
S.install(sim)
for sym, p in {"NMRUSDT": 10.0, "RLCUSDT": 1.0, "XRPUSDT": 2.0}.items():
    sim.px[sym] = p
    sim.real[sym] = p
OPEN_AT_NEWS = {}
sim.kline_fn = lambda sym, st, lim: [[st, str(OPEN_AT_NEWS.get(sym, sim.real[sym]))] * 1 + [str(sim.real[sym])] * 3]

import notify  # noqa: E402
sent = []
notify.send_telegram = lambda m: sent.append(m) or True
import bot as B  # noqa: E402
import report as R  # noqa: E402
import trader as T  # noqa: E402
import ai as A  # noqa: E402
import news as NW  # noqa: E402
for mod in (B, R, T):
    mod.send_telegram = notify.send_telegram


class FakeAI(S.AIStub):
    chains = {"main": ["f"], "cheap": ["f"], "review": ["p"]}
    stats = {"calls": 0, "errors": 0, "cost_usd": 0.0, "fallbacks": 0}
    day = dict(stats)
    last_fatal_error = None

    def __init__(self):
        self.next, self.review_calls, self.spike = None, 0, None

    def analyze(self, item):
        return self.next

    def review(self, item, res, ctx, reg):
        self.review_calls += 1
        return {"onay": False, "model_onay": False, "guven": 30, "sebep": "temkin", "karsi": [], "model": "p"}

    def judge_spike(self, **kw):
        return self.spike

    def commentary(self, d):
        return "yorum"

    def reset_day(self):
        pass


B.GeminiAnalyzer = FakeAI
bot = B.Bot()
bot.trader.startup()
for sym in ("NMRUSDT", "RLCUSDT"):
    bot.trader.bx.symbols[sym] = dict(bot.trader.bx.symbols["SOLUSDT"], base=sym[:-4])
bot.trader.bx._symbols_loaded_at = S.fake_time() + 10 ** 6
bot.market.current = "YATAY"
bot.market.metrics = {"ch1": 0.0, "ch4": 0.0, "ch24": 0.3, "price": 84000, "at": S.fake_time()}
reg = bot.market.info()


def last():
    return R.read_csv(R.SIGNALS_CSV)[-1]


def reset_positions():
    bot.trader.positions.clear()
    bot.trader.state["cooldown"] = {}


print("1) Upbit duyurusu: fiyat haberden beri +%20 -> hızlı yoldan alınır (ikinci görüş yok, izleyen stop)")
OPEN_AT_NEWS["NMRUSDT"] = 10.0
sim.real["NMRUSDT"] = 12.0
sim.px["NMRUSDT"] = 12.0
bot.handle_listing({"source": AN.SRC_UPBIT, "id": "n1", "title": "Market Support for Numeraire(NMR) (KRW, USDT Market)",
                    "tickers": ["NMR"], "link": "u", "ts": S.fake_time() - 30})
pos = bot.trader.positions[-1] if bot.trader.positions else {}
check(last()["durum_kodu"] == "ALINDI" and bot.ai.review_calls == 0, "alındı, ikinci görüş sorulmadı")
check(pos.get("mode") == "trailing" and pos.get("score") == 10, "yatay rejime rağmen izleyen stop, puan 10")
check(any("Hızlı yol" in m and "İşlem Açıldı" in m for m in sent), "alım mesajında hızlı yol notu")
check(abs(pos.get("real_entry", 0) - 12.0) < 1e-9, "gerçek giriş fiyatı kaydedildi")

print("2) Fiyat haberden beri +%35 -> hızlı yolda bile 'tren kaçtı'")
reset_positions()
sim.real["NMRUSDT"] = 13.5
bot.handle_listing({"source": AN.SRC_UPBIT, "id": "n2", "title": "Market Support for Numeraire(NMR) (KRW)",
                    "tickers": ["NMR"], "link": "u2", "ts": S.fake_time() - 30})
check(last()["durum_kodu"] == "ENGEL_TREN", "%35 > %30 sınırı -> alınmadı")

print("3) Telegram'dan resmi birinci lig listeleme haberi (puan 10), fiyat +%27 -> hızlı yol")
reset_positions()
sim.real["NMRUSDT"] = 12.7
sim.px["NMRUSDT"] = 12.7


def facts(coin, ev, aktor, kesinlik="resmi", olcek="buyuk"):
    return A.GeminiAnalyzer.build_result({"hedef_coin": coin, "olay_turu": ev, "kesinlik": kesinlik, "yenilik": "yeni",
                                          "aktor": aktor, "olcek": olcek, "coin_ozel": True,
                                          "fiyat_zaten_hareket_etti": False, "yon": "olumlu", "sebep": "t"}, "f")


def news(title, source="TG @BWEnews"):
    return {"id": title, "title": title, "title_key": NW._title_key(title), "link": "http://n/" + title[:20],
            "source": source, "published": S.fake_time() - 40, "summary": "", "categories": ""}


bot.ai.next = facts("NMR", "listeleme", "birinci_lig")
bot.process(news("UPBIT LISTING: NMR KRW USDT market"), reg)
check(last()["durum_kodu"] == "ALINDI" and bot.ai.review_calls == 0, "+%27'de alındı, ikinci görüş sorulmadı")

print("4) Normal haber: %3 sınırı ve ikinci görüş aynen geçerli")
reset_positions()
OPEN_AT_NEWS["XRPUSDT"] = 2.0
sim.real["XRPUSDT"] = 2.08
bot.ai.next = facts("XRP", "ortaklik", "birinci_lig")
bot.process(news("Ripple partners with big bank", "CoinDesk"), reg)
check(last()["durum_kodu"] == "ENGEL_TREN", "ortaklık haberi +%4'te -> tren kaçtı (%3 sınırı)")
sim.real["XRPUSDT"] = 2.0
bot.ai.next = facts("XRP", "ortaklik", "birinci_lig", olcek="orta")
bot.process(news("Ripple partners with another bank", "CoinDesk"), reg)
check(last()["durum_kodu"] == "IKINCI_GORUS_RED" and bot.ai.review_calls == 1, "ortaklık haberi ikinci görüşe gitti")
bot.ai.next = facts("XRP", "listeleme", "orta")
bot.process(news("Small exchange lists XRP pair", "CoinDesk"), reg)
check(bot.ai.review_calls == 2 and last()["durum_kodu"] == "IKINCI_GORUS_RED",
      "küçük borsa listelemesi hızlı yola girmez, normal yoldan ikinci görüşe gider")

print("5) Gemini onaylı hacim patlaması: ikinci görüş sorulmadan alınır")
reset_positions()
calls_before = bot.ai.review_calls
bot.ai.spike = {"hikaye_var": True, "guc": 8, "katalizor": "RWA trendi", "risk": "geri dönüş", "sebep": "ok", "model": "f"}
bot.handle_volume({"coin": "RLC", "symbol": "RLCUSDT", "move": 8.5, "ratio": 6.0, "vol": 900000, "price": 1.0,
                   "ch24": 40.0, "news": [], "ts": S.fake_time()})
check(last()["durum_kodu"] == "ALINDI" and bot.ai.review_calls == calls_before, "RLC alındı, ikinci görüş sorulmadı")
check(any("Hacim patlaması + Gemini onayı" in m for m in sent), "alım mesajında hacim notu")

print("6) Gölge K/Z: kapanışta gerçek fiyat")
pos = next(p for p in bot.trader.positions if p["symbol"] == "RLCUSDT")
sim.px["RLCUSDT"] = 0.97          # testnet: -%3 -> stop
sim.real["RLCUSDT"] = 1.05        # gerçek piyasa: +%5 (testnet farklı gitti)
sim.tick()
bot.trader.manage_positions()
tr = R.read_csv(T.TRADES_CSV)[-1]
check(tr["sembol"] == "RLCUSDT" and tr["gercek_kar_yuzde"] == "5.00" and float(tr["kar_yuzde"]) < 0,
      f"testnette {tr['kar_yuzde']}%, gerçek piyasada {tr['gercek_kar_yuzde']}% olarak kaydedildi")
check(any("Gerçek piyasada:" in m and "+5.00%" in m for m in sent), "kapanış mesajında gerçek piyasa K/Z")
html, _ = bot.reporter.build()
check("gerçek piyasada +5.00%" in html, "gece raporunda gerçek piyasa K/Z")
print(f"\nTüm hızlı yol ve gölge K/Z testleri geçti ({n_ok} kontrol).")
