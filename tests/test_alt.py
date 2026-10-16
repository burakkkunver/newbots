import os, sys, shutil
SP = os.path.dirname(os.path.abspath(__file__)); DATA = os.path.join(SP, "data_alt"); shutil.rmtree(DATA, ignore_errors=True)
os.environ.update(DATA_DIR=DATA, WATCH_NEWS_ENABLED="False", PAPER_ENABLED="False", SPIKE_AI_REQUIRE_EVIDENCE="False", TELEGRAM_BOT_TOKEN="x", TELEGRAM_CHAT_ID="1", GEMINI_API_KEY="k", BINANCE_API_KEY="a", BINANCE_SECRET="b", TESTNET_OGRENME="False", SPIKE_AI_ENABLED="False", PULSE_ENABLED="False", LISTING_FAST_PATH="False", LISTING_SCORE="8", SPIKE_SKIP_REVIEW="False")
sys.path.insert(0, os.path.dirname(SP)); sys.path.insert(0, SP)
import sim as S, time
time.sleep = lambda s: None
from types import SimpleNamespace as N
import config, announcements as AN, scanner as SC, news as NW
n_ok = 0
def check(c, m):
    global n_ok
    assert c, m; n_ok += 1; print("  ✓", m)

print("1) Duyuru ayrıştırıcıları")
check(AN.tickers_in("온톨로지(ONT) 신규 거래지원 안내 (KRW, BTC, USDT 마켓)") == ["ONT"], "Upbit: piyasa adları elendi -> ONT")
check(AN.tickers_in("Binance Will List Sahara AI (SAHARA) and Lombard (BARD)") == ["SAHARA", "BARD"], "Binance: iki coin")
upbit = {"success": True, "data": {"notices": [
    {"id": 101, "title": "썬더코어(TT) 신규 거래지원 안내 (KRW 마켓)"},
    {"id": 102, "title": "[거래] 투자유의 종목 지정 안내 (XYZ)"},
    {"id": 103, "title": "[Trade] New digital asset on KRW Market (SUI)"},
    {"id": 104, "title": "거래지원 종료 안내 (ABC)"}]}}
p = AN.parse_upbit(upbit)
check([e["tickers"] for e in p] == [["TT"], ["SUI"]], f"Upbit: sadece yeni listelemeler ({[e['title'][:25] for e in p]})")
binance = {"code": "000000", "data": {"catalogs": [{"catalogId": 48, "articles": [
    {"id": 1, "code": "a1", "title": "Binance Will List Uniswap Labs Token (UNIX)"},
    {"id": 2, "code": "a2", "title": "Binance Will Add PENDLE on Earn, Buy Crypto, Convert & Margin"},
    {"id": 3, "code": "a3", "title": "Binance Will Delist ABC, DEF on 2026-10-10"}]}]}}
p = AN.parse_binance(binance)
check([e["id"] for e in p] == ["a1", "a2"] and p[0]["tickers"] == ["UNIX"], "Binance: delist hariç tutuldu")
cb = [{"id": "BTC-USD", "base_currency": "BTC"}, {"id": "SUI-USD", "base_currency": "SUI"}, {"id": "SUI-USDC", "base_currency": "SUI"}]
check([e["id"] for e in AN.parse_coinbase(cb)] == ["BTC", "SUI"], "Coinbase: coin başına bir kayıt")

print("2) Duyuru izleyici: ilk kontrol başlangıç, sonrakiler sinyal")
pages = {AN.SRC_UPBIT: [upbit], AN.SRC_BINANCE: [binance], AN.SRC_COINBASE: [cb, cb + [{"id": "NEW-USD", "base_currency": "NEWC"}]]}
def fake_get(url, headers, timeout):
    for src in AN.SOURCES:
        if src["url"] == url:
            if src["name"] == AN.SRC_BINANCE:
                return N(status_code=403, json=lambda: {})
            data = pages[src["name"]][0] if len(pages[src["name"]]) == 1 else pages[src["name"]].pop(0)
            return N(status_code=200, json=lambda d=data: d)
AN.requests.get = fake_get
w = AN.AnnouncementWatcher()
check(w.tick(force=True) == [], "ilk kontrolde eski duyurular için bildirim yok")
check("erişilemiyor" in w.status[AN.SRC_BINANCE] and w.status[AN.SRC_UPBIT].startswith("ok"), f"erişilemeyen kaynak işaretlendi: {w.status}")
upbit["data"]["notices"].insert(0, {"id": 105, "title": "아비트럼(ARB) 신규 거래지원 안내 (KRW 마켓)"})
new = w.tick(force=True)
check(sorted((e["source"], e["tickers"][0]) for e in new) == [(AN.SRC_COINBASE, "NEWC"), (AN.SRC_UPBIT, "ARB")], f"yeni duyurular: {[(e['source'], e['tickers']) for e in new]}")
check(w.tick(force=True) == [], "aynı duyuru ikinci kez gelmez")
w2 = AN.AnnouncementWatcher()
check(w2.state[AN.SRC_UPBIT]["baseline"], "görülen duyurular yeniden başlatınca hatırlanıyor")

print("3) Hacim tarayıcı")
sim = S.Sim(); S.install(sim)
sim.real = {"UNIUSDT": 6.0, "XYZUSDT": 1.0, "USDCUSDT": 1.0, "BTCUSDT": 84000.0, "SOLUSDT": 150.0}
VOL = {"UNIUSDT": "high", "XYZUSDT": "flat"}
def kl(sym, start, limit):
    now = int(S.fake_time() // 60 * 60 * 1000)
    out = []
    for i in range(limit):
        t = now - (limit - 1 - i) * 60000
        recent = i >= limit - 16
        q = 60000 if (VOL.get(sym) == "high" and recent) else 10000
        p = str(sim.real[sym])
        out.append([t, p, p, p, p, "0", 0, str(q)])
    return out
sim.kline_fn = kl
from binance_api import Binance
bx = Binance("a", "b", True)
feed = NW.NewsFeed()
feed.recent = {"k1": {"title": "Uniswap fee switch burns $263M UNI annually", "published": S.fake_time() - 3600,
                      "source": "CoinDesk", "link": "http://n/uni", "title_key": "k1"}}
sc = SC.MomentumScanner(bx, feed)
got = []
for minute in range(20):
    if minute == 16:
        sim.real["UNIUSDT"] = 6.0 * 1.035; sim.real["XYZUSDT"] = 1.04; sim.real["USDCUSDT"] = 1.03
    got += sc.tick()
    S.advance(1)
check(len(got) == 1 and got[0]["coin"] == "UNI", f"sadece hacmi patlayan UNI sinyal verdi ({[g['coin'] for g in got]})")
g = got[0]
check(abs(g["move"] - 3.5) < 0.01 and g["ratio"] > 3 and g["news"] and "Uniswap" in g["news"][0]["title"],
      f"+{g['move']:.1f}%, hacim {g['ratio']:.1f}x, haber: {g['news'][0]['title']}")
check(sc.stats["candidates"] >= 2, "fiyatı yükselen XYZ incelendi ama hacim yetersiz olduğu için elendi; USDC hiç bakılmadı")
weights = [c for c in sim.calls if c[3] == S.binance_api.MARKET_DATA_URL]
print(f"    gerçek piyasa istekleri: {len(weights)} istek / 20 dk (fiyat taraması + sadece adaylar için mum)")
check(len(weights) <= 20 + 6, "yük düşük: dakikada ~1 istek + aday başına 1-2")

print("4) Bot entegrasyonu (sadece bildirim modu)")
import notify
sent = []
notify.send_telegram = lambda m: sent.append(m) or True
import bot as B, report as R
for mod in (B, R):
    mod.send_telegram = notify.send_telegram
R.send_long = lambda m: sent.append(m)
class FakeAI(S.AIStub):
    chains = {"main": ["f"], "cheap": ["f"], "review": ["p"]}; stats = {"calls": 0, "errors": 0, "cost_usd": 0.0, "fallbacks": 0}
    day = dict(stats); last_fatal_error = None
    def review(self, item, res, ctx, reg): return {"onay": True, "model_onay": True, "guven": 80, "sebep": "ok", "karsi": [], "model": "p"}
    def commentary(self, d): return "yorum"
    def reset_day(self): pass
B.GeminiAnalyzer = FakeAI
sim2 = S.Sim(); S.install(sim2)
sim2.real.update({"UNIUSDT": 6.2, "ARBUSDT": 0.5, "XYZUSDT": 1.04}); sim2.px.update({"UNIUSDT": 6.2})
bot = B.Bot(); bot.trader.startup()
bot.market.current = "BOGA"; bot.market.metrics = {"ch1": 0.2, "ch4": 0.5, "ch24": 2.0, "price": 84000, "at": S.fake_time()}
sig = dict(g, ts=S.fake_time())
bot.handle_volume(sig)
bot.handle_volume(dict(g, coin="XYZ", symbol="XYZUSDT", news=[], ts=S.fake_time()))
bot.handle_listing({"source": AN.SRC_UPBIT, "id": "105", "title": "아비트럼(ARB) 신규 거래지원 안내 (KRW 마켓)",
                    "tickers": ["ARB"], "link": "http://upbit/105", "ts": S.fake_time()})
bot.handle_listing({"source": AN.SRC_BINANCE, "id": "a1", "title": "Binance Will List Foo (FOO)", "tickers": ["FOO"],
                    "link": "http://b/a1", "ts": S.fake_time()})
rows = R.read_csv(R.SIGNALS_CSV)
print("    durum kodları:", [(r["kaynak"], r["coin"], r["durum_kodu"]) for r in rows])
check([r["durum_kodu"] for r in rows] == ["HACIM_HABERLI", "HACIM_HABERSIZ", "LISTELEME", "LISTELEME"], "dört sinyal doğru kodla kaydedildi")
check(all(r["puan"] == "" for r in rows), "puan boş: haber puan tablolarını kirletmez")
check(not bot.trader.positions, "bildirim modunda alım yapılmadı")
check(any("HACİM PATLAMASI" in m and "Uniswap" in m for m in sent), "haberli hacim patlaması Telegram'a gitti")
check(not any("HACİM PATLAMASI" in m and "XYZ" in m for m in sent), "habersiz hacim patlaması Telegram'a gitmedi (sadece kayıt)")
check(any("Upbit LİSTELEME" in m and "Binance spot:</b> var" in m for m in sent), "Upbit listelemesi: Binance spotta var")
check(any("FOO" in m and "Binance spot:</b> yok" in m for m in sent), "Binance yeni listeleme: spotta henüz yok")
check(len(bot.calib.pending) == 3, f"spotta olan 3 sinyal kalibrasyona eklendi ({len(bot.calib.pending)})")

print("5) Alım modu açıkken (ALT_SIGNALS_TRADE=True)")
config.ALT_SIGNALS_TRADE = True
bot.trader.bx.symbols["UNIUSDT"] = dict(bot.trader.bx.symbols["SOLUSDT"], base="UNI")
bot.trader.bx._symbols_loaded_at = S.fake_time() + 10 ** 6
bot.handle_volume(dict(g, ts=S.fake_time()))
check(bot.trader.positions and bot.trader.positions[0]["symbol"] == "UNIUSDT", "haberli hacim patlaması + ikinci görüş onayı -> UNI alındı")
check(R.read_csv(R.SIGNALS_CSV)[-1]["durum_kodu"] == "ALINDI", "kayıt ALINDI")
bot.market.current = "DUSUS"
bot.handle_listing({"source": AN.SRC_UPBIT, "id": "106", "title": "(ARB) 신규 거래지원 안내", "tickers": ["ARB"],
                    "link": "http://upbit/106", "ts": S.fake_time()})
check(R.read_csv(R.SIGNALS_CSV)[-1]["durum_kodu"] == "REJIM_ESIGI", "düşüş rejiminde 8 puanlık sinyal eşiği geçemedi")
config.ALT_SIGNALS_TRADE = False

print("6) Rapor, /kalibrasyon ve analiz")
html, _ = bot.reporter.build()
sec = html[html.index("Hacim tarayıcı ve listeleme"):]
print("   ", sec.split("\n🤖")[0].replace("\n", "\n    "))
check("Hacim patlaması + haber" in sec and "Duyuru kaynakları" in sec, "raporda alternatif sinyal bölümü")
check("İşlenen taze haber: 0" in html, "haber hunisi alternatif sinyalleri haber saymıyor")
S.advance(245)
bot.calib.process_due()
import calibration as C
txt = C.telegram_summary(7)
check("Hacim patlaması + haber" in txt and "Listeleme: Upbit" in txt, "/kalibrasyon alternatif sinyalleri ayrı gösteriyor")
import analiz
analiz.main()
print(f"\nTüm alternatif sinyal testleri geçti ({n_ok} kontrol).")
