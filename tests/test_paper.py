"""Sanal işlem motoru: testnette olmayan coinler (Binance gerçek / Gate.io / MEXC fiyatı) + testnet aynası."""
import os
import shutil
import sys

SP = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(SP, "data_paper")
shutil.rmtree(DATA, ignore_errors=True)
os.environ.update(DATA_DIR=DATA, WATCH_NEWS_ENABLED="False", TELEGRAM_BOT_TOKEN="x", TELEGRAM_CHAT_ID="1", GEMINI_API_KEY="k",
                  BINANCE_API_KEY="a", BINANCE_SECRET="b", PULSE_ENABLED="False")
sys.path.insert(0, os.path.dirname(SP))
sys.path.insert(0, SP)
import sim as S  # noqa: E402
import time  # noqa: E402
time.sleep = lambda s: None
import config  # noqa: E402
from util import now_local  # noqa: E402

# Sahte saati bugün 09:00'a al: test içinde saatler ilerlese de gün değişmesin (gün sonu raporu "bugün"ü görsün)
_n = now_local()
S.CLOCK["offset"] += _n.replace(hour=9, minute=0, second=0, microsecond=0).timestamp() - _n.timestamp()

n_ok = 0


def check(c, m):
    global n_ok
    assert c, m
    n_ok += 1
    print("  ✓", m)


sim = S.Sim()
S.install(sim)
V = S.Venues()
S.install_venues(V)

import notify  # noqa: E402
SENT, LONG, DOCS = [], [], []
notify.send_telegram = lambda m: SENT.append(m) or True
import bot as B  # noqa: E402
import report as R  # noqa: E402
import trader as T  # noqa: E402
import paper as P  # noqa: E402
import ai as A  # noqa: E402
import news as NW  # noqa: E402
import calibration as C  # noqa: E402
import announcements as AN  # noqa: E402
for mod in (B, R, T, P):
    mod.send_telegram = notify.send_telegram
R.send_long = B.send_long = lambda m: LONG.append(m)
B.send_document = lambda p, c="": DOCS.append(p) or os.path.exists(p)


class FakeAI(S.AIStub):
    chains = {"main": ["f"], "cheap": ["f"], "review": ["p"]}

    def __init__(self):
        self.stats = {"calls": 0, "errors": 0, "cost_usd": 0.0, "fallbacks": 0}
        self.day = dict(self.stats)
        self.last_fatal_error = None
        self.next, self.review_calls, self.spike, self.spike_calls, self.alert = None, 0, None, 0, None

    def analyze(self, item):
        return self.next

    def review(self, item, res, ctx, reg):
        self.review_calls += 1
        self.last_ctx = ctx
        return {"onay": True, "model_onay": True, "guven": 80, "sebep": "somut katalizör", "karsi": [], "model": "p"}

    def judge_spike(self, **kw):
        self.spike_calls += 1
        return self.spike

    def commentary(self, d):
        return "yorum"

    def reset_day(self):
        pass

    def health_alert(self):
        a, self.alert = self.alert, None
        return a


B.GeminiAnalyzer = FakeAI
bot = B.Bot()
bot.trader.startup()
bot.market.current = "BOGA"
bot.market.metrics = {"ch1": 0.1, "ch4": 0.5, "ch24": 2.0, "price": 84000, "at": S.fake_time()}
reg = bot.market.info()


def facts(coin, ev, aktor, olcek="buyuk", kesinlik="resmi"):
    return A.GeminiAnalyzer.build_result({"hedef_coin": coin, "olay_turu": ev, "kesinlik": kesinlik, "yenilik": "yeni",
                                          "aktor": aktor, "olcek": olcek, "coin_ozel": True,
                                          "fiyat_zaten_hareket_etti": False, "yon": "olumlu", "sebep": "test"}, "f")


def news(title, source="CoinDesk"):
    return {"id": title, "title": title, "title_key": NW._title_key(title), "link": "http://n/" + title[:24],
            "source": source, "published": S.fake_time() - 60, "summary": "", "categories": ""}


def last_signal():
    return R.read_csv(R.SIGNALS_CSV)[-1]


def paper_pos(coin, kind="sanal"):
    return next((p for p in bot.paper.positions if p["coin"] == coin and p["kind"] == kind), None)


def listing(coin, source=AN.SRC_UPBIT, ident=None):
    bot.handle_listing({"source": source, "id": ident or coin, "title": f"Market Support for {coin}({coin}) (KRW, USDT Market)",
                        "tickers": AN.tickers_in(f"Market Support for {coin}({coin}) (KRW, USDT Market)"),
                        "link": "u", "ts": S.fake_time() - 20})


print("0) Upbit başlığındaki 'Market' kelimesi coin sanılmıyor")
check(AN.tickers_in("Market Support for Reserve Rights(RSR) (KRW, USDT Market)") == ["RSR"], "sadece RSR")

print("1) Haber: coin gerçek Binance'te var, testnette yok -> ikinci görüş + sanal alım (Binance fiyatı)")
sim.real["DATAUSDT"] = 1.0
sim.spread["DATAUSDT"] = 0.2
bot.ai.next = facts("DATA", "ortaklik", "birinci_lig")          # 7 + büyük ölçek = 8 puan
bot.process(news("Data partners with Visa"), reg)
pos = paper_pos("DATA")
check(last_signal()["durum_kodu"] == "SANAL_ALINDI" and pos and pos["venue"] == "binance", "SANAL_ALINDI, fiyat: Binance")
check(bot.ai.review_calls == 1 and bot.ai.last_ctx.get("coin_volume") == 123456789,
      "ikinci görüş soruldu, gerçek hacim verisiyle")
check(abs(pos["entry"] - 1.001) < 1e-9 and pos["mode"] == "trailing" and pos["score"] == 8,
      "giriş satış fiyatından (ask 1.001), boğada izleyen stop")
check(any("Sanal İşlem Açıldı" in m and "testnette yok" in m and "Binance" in m for m in SENT), "sanal alım mesajı")
check(not bot.trader.positions, "testnette emir verilmedi")
check(abs(pos["cost"] - 35.0) < 0.01, f"tutar puan/rejim kuralıyla: {pos['cost']:.2f} USDT")

print("2) Sanal izleyen stop: +%5 zirve, sonra geri çekilme -> kâr korunarak kapanır (komisyon ve spread dahil)")
for p in (1.03, 1.05, 1.03):
    sim.real["DATAUSDT"] = p
    bot.paper.manage()
check(paper_pos("DATA") is None, "pozisyon kapandı")
row = R.read_csv(P.PAPER_CSV)[-1]
exp = ((1.03 * 0.999) * 0.999 / (1.001 * 1.001) - 1) * 100
check(row["tur"] == "sanal" and row["cikis_sebebi"] == "İZLEYEN STOP" and abs(float(row["kar_yuzde"]) - exp) < 0.01,
      f"İZLEYEN STOP, K/Z {row['kar_yuzde']}% (beklenen {exp:.2f}%)")
check(abs(bot.paper.state["realized"]["sanal"] - 35.0 * exp / 100) < 0.01, "sanal bütçeye işlendi")
check(any("Sanal Pozisyon Kapandı" in m and "komisyon dahil" in m for m in SENT), "kapanış mesajı")
bot.ai.next = facts("DATA", "ortaklik", "birinci_lig")
bot.process(news("Data partners with Mastercard"), reg)
check(last_signal()["durum_kodu"] == "SANAL_BEKLEME", "kapanan coin bekleme süresinde")

print("3) Upbit listelemesi: coin hiç Binance'te yok, Gate.io'da var -> hızlı yol, sanal alım")
V.px["gateio"]["PONS"] = 0.05
V.open["gateio"]["PONS"] = 0.045                      # haberden beri +%11 (< %30)
V.spread["gateio"]["PONS"] = 0.4
reviews = bot.ai.review_calls
n_sent = len(SENT)
listing("PONS")
pos = paper_pos("PONS")
check(last_signal()["durum_kodu"] == "SANAL_ALINDI" and pos and pos["venue"] == "gateio", "SANAL_ALINDI, fiyat: Gate.io")
check(bot.ai.review_calls == reviews and pos["mode"] == "trailing" and pos["score"] == 10,
      "ikinci görüş yok, izleyen stop, puan 10")
check(any("Sanal İşlem Açıldı" in m and "Gate.io" in m and "Hızlı yol" in m for m in SENT[n_sent:]), "mesajda Gate.io + hızlı yol")
check(not any("LİSTELEME DUYURUSU" in m for m in SENT[n_sent:]), "ayrıca listeleme bildirimi gönderilmedi")

print("4) Listeleme ama fiyat haberden beri +%40 -> sanal yolda da tren kaçtı")
V.px["gateio"]["ZZZ"] = 0.014
V.open["gateio"]["ZZZ"] = 0.01
listing("ZZZ")
check(last_signal()["durum_kodu"] == "SANAL_TREN" and "Gate.io" in last_signal()["aciklama"], "SANAL_TREN")
check(any("LİSTELEME DUYURUSU" in m and "Tren kaçtı" in m for m in SENT[-2:]), "listeleme bildirimi sebebiyle gitti")

print("5) Hiçbir kaynakta olmayan coin ve düşük hacimli coin")
listing("NOWHERE")
check(last_signal()["durum_kodu"] == "SANAL_FIYAT_YOK" and "Gate.io" in last_signal()["aciklama"], "SANAL_FIYAT_YOK")
V.px["mexc"]["LOWV"] = 2.0
V.vol["mexc"]["LOWV"] = 20000
listing("LOWV")
check(last_signal()["durum_kodu"] == "SANAL_HACIM", "24s hacim 20 bin $ -> SANAL_HACIM")

print("6) Sadece MEXC'de olan coin -> sanal alım (MEXC fiyatı ve mumu)")
V.px["mexc"]["MXA"] = 3.0
V.open["mexc"]["MXA"] = 2.9
listing("MXA")
pos = paper_pos("MXA")
check(last_signal()["durum_kodu"] == "SANAL_ALINDI" and pos and pos["venue"] == "mexc", "SANAL_ALINDI, fiyat: MEXC")
check(any(c[0] == "mexc" and c[1] == "klines" for c in V.calls), "haber anı fiyatı MEXC mumundan okundu")

print("7) Gate.io erişilemiyor: tur atlanır; 15 dk sonra başka borsaya geçilir")
V.px["mexc"]["PONS"] = 0.0501
V.down.add("gateio")
bot.paper.manage()
check(paper_pos("PONS")["venue"] == "gateio", "kısa kesintide aynı borsada bekliyor")
S.advance(16)
bot.paper.manage()
check(paper_pos("PONS")["venue"] == "mexc", "15 dk fiyat yok -> MEXC fiyatıyla devam")
V.down.discard("gateio")

print("8) Testnet alımı -> gerçek fiyat aynası; ikisi farklı fiyatlarla bağımsız kapanır")
sim.px["SOLUSDT"] = sim.real["SOLUSDT"] = 150.0
bot.ai.next = facts("SOL", "ortaklik", "birinci_lig")
n_sent = len(SENT)
bot.process(news("Solana partners with Visa"), reg)
tpos = next((p for p in bot.trader.positions if p["symbol"] == "SOLUSDT"), None)
mpos = paper_pos("SOL", "ayna")
check(last_signal()["durum_kodu"] == "ALINDI" and tpos and mpos, "testnet alımı + ayna açıldı")
check(mpos["testnet_id"] == tpos["id"] and abs(mpos["cost"] - tpos["cost"]) < 1e-9 and mpos["mode"] == tpos["mode"],
      "ayna aynı tutar ve kurallarla")
check(any("İşlem Açıldı" in m and "ayna" in m for m in SENT[n_sent:]), "alım mesajında ayna notu")
sim.px["SOLUSDT"] = 145.0          # testnet -%3,3: borsadaki stop dolar
sim.real["SOLUSDT"] = 151.0        # gerçek piyasa yükseliyor
sim.tick()
bot.trader.manage_positions()
bot.paper.manage()
check(not bot.trader.positions and paper_pos("SOL", "ayna"), "testnet stop oldu, ayna gerçek fiyatla devam ediyor")
for p in (155.0, 158.0, 154.0):
    sim.real["SOLUSDT"] = p
    bot.paper.manage()
check(paper_pos("SOL", "ayna") is None, "ayna izleyen stopla kapandı")
crow = R.read_csv(P.PAPER_CSV)[-1]
check(crow["tur"] == "ayna" and float(crow["kar_yuzde"]) > 2 and float(crow["testnet_kar_yuzde"]) < -2,
      f"ayna {crow['kar_yuzde']}% / testnet {crow['testnet_kar_yuzde']}%")
check(any("Ayna kapandı" in m and "testnette aynı işlem" in m for m in SENT[-3:]), "ayna kapanış mesajı testnet sonucuyla")

print("9) Çıkış kuralları: yatayda sabit kâr al, time-stop, süre sınırı, -%2 stop")
bot.market.current = "YATAY"
yreg = bot.market.info()
config.PAPER_BUDGET_USDT = 1000          # önceki sanal pozisyonlar 100 USDT'yi doldurdu
item = news("Direct test")


def open_paper(coin, score, regime, price):
    sim.real[f"{coin}USDT"] = price
    ok, code, desc, ctx = bot.paper.precheck(coin, score, item, regime)
    assert ok, (code, desc)
    code, desc = bot.paper.execute_buy(ctx, {"puan": float(score), "olay_turu": "test"}, item, regime)
    assert code == "SANAL_ALINDI", (code, desc)
    return paper_pos(coin)


p1 = open_paper("TPA", 8, yreg, 10.0)
check(p1["mode"] == "fixed" and abs(p1["tp"] - 10.2) < 1e-9, "yatay: sabit kâr al +%2")
sim.real["TPAUSDT"] = 10.25
bot.paper.manage()
check(R.read_csv(P.PAPER_CSV)[-1]["cikis_sebebi"] == "KÂR AL", "KÂR AL")
open_paper("TSA", 7, yreg, 4.0)
S.advance(21)
bot.paper.manage()
check(R.read_csv(P.PAPER_CSV)[-1]["cikis_sebebi"].startswith("TIME-STOP"), "7 puanda 20 dk'da sıçrama yok -> TIME-STOP")
open_paper("DLA", 9, yreg, 2.0)
S.advance(241)
bot.paper.manage()
check(R.read_csv(P.PAPER_CSV)[-1]["cikis_sebebi"] == "SÜRE DOLDU", "9 puanda time-stop yok, 240 dk sonra SÜRE DOLDU")
open_paper("SLA", 9, yreg, 5.0)
sim.real["SLAUSDT"] = 4.875
bot.paper.manage()
r9 = R.read_csv(P.PAPER_CSV)[-1]
check(r9["cikis_sebebi"] == "ZARAR KES" and -2.8 < float(r9["kar_yuzde"]) < -2.5, f"-%2,5'te ZARAR KES ({r9['kar_yuzde']}%)")

print("10) Sanal pozisyon sınırı ve bütçe")
config.PAPER_MAX_OPEN = len([p for p in bot.paper.positions if p["kind"] == "sanal"])
ok, code, _, _ = bot.paper.precheck("NEWC", 9, item, yreg)
check(not ok and code == "SANAL_MAKS", "maks. sanal pozisyon dolu")
config.PAPER_MAX_OPEN = 50
config.PAPER_BUDGET_USDT = 30
sim.real["NEWCUSDT"] = 1.0
ok, code, desc, _ = bot.paper.precheck("NEWC", 9, item, yreg)
check(not ok and code == "SANAL_BAKIYE", f"bütçe yetersiz: {desc}")
config.PAPER_BUDGET_USDT = 100

print("11) Rapor, /sanal, /durum, /dosyalar")
html, _ = bot.reporter.build()
check("Sanal işlemler" in html and "Testnette olmayan coinler" in html and "Ayna" in html, "gece raporunda sanal bölüm")
check("SOLUSDT" in html and "testnet" in html, "raporda ayna ve testnet karşılaştırması")
bot.handle_command("/sanal")
check("Son 7 gün" in LONG[-1] and "Fiyat kaynakları" in LONG[-1], "/sanal ayrıntılı özet")
bot.handle_command("/durum")
check("Sanal işlemler" in SENT[-1] and "Sanal bütçe" in SENT[-1], "/durum'da sanal işlemler")
bot.handle_command("/dosyalar")
check(any(p.endswith("sanal_islemler.csv") for p in DOCS), "/dosyalar sanal işlem dosyasını gönderiyor")

print("12) Kalibrasyon: Binance'te olmayan coin Gate.io mumlarıyla ölçülür")
it = {"title": "PONS news", "link": "http://c/1", "source": "T", "published": S.fake_time() - 60}
check(bot.calib.add(it, {"hedef_coin": "PONS", "puan": 8.0}, "SANAL_ALINDI", "BOGA"), "ölçüm listesine eklendi")
check(bot.calib.pending[-1]["symbol"] == "PONSUSDT@gateio", "sembol@borsa olarak kaydedildi")
V.open["gateio"]["PONS"] = 0.05
V.px["gateio"]["PONS"] = 0.055
S.advance(245)
bot.calib.process_due()
crow = [r for r in C.load_rows() if r["link"] == "http://c/1"]
check(crow and crow[0]["sembol"] == "PONSUSDT@gateio" and float(crow[0]["max1s"]) > 5, f"ölçüldü: {crow[0] if crow else None}")

print("13) Yeniden başlatınca sanal pozisyonlar ve bütçe hatırlanıyor")
again = P.PaperTrader(bot.prices)
check(len(again.positions) == len(bot.paper.positions) and
      abs(again.state["realized"]["sanal"] - bot.paper.state["realized"]["sanal"]) < 1e-9, "paper.json'dan yüklendi")

print("14) Hacim patlaması: haber/trend kanıtı yoksa Gemini'ye sorulmuyor")
sig = {"coin": "ADA", "symbol": "ADAUSDT", "move": 3.0, "ratio": 4.0, "vol": 300000, "price": 0.5, "ch24": 4.0,
       "news": [], "ts": S.fake_time()}
before = bot.ai.spike_calls
bot.handle_volume(sig)
check(bot.ai.spike_calls == before and last_signal()["durum_kodu"] == "HACIM_HABERSIZ", "kanıt yok -> sorulmadı")
bot.feed.add_recent(dict(news("Cardano launches new DeFi hub $ADA"), published=S.fake_time() - 600))
bot.ai.spike = {"hikaye_var": False, "guc": 3, "katalizor": "-", "risk": "-", "sebep": "zayıf", "model": "f"}
bot.handle_volume(dict(sig, ts=S.fake_time() + 1))
check(bot.ai.spike_calls == before + 1 and last_signal()["durum_kodu"] == "HACIM_AI_RED", "haber var -> Gemini'ye soruldu")

print("15) Gemini 3 kez yanıt vermezse haber AI_YOK olarak kaydedilir; sağlık uyarısı Telegram'a gider")
bot.ai.next = None
n = news("Some fresh headline about SOL ecosystem")
for _ in range(3):
    bot.process(n, reg)
check(last_signal()["durum_kodu"] == "AI_YOK" and bot.feed.is_seen(n), "AI_YOK kaydı, haber görüldü sayıldı")
html, _ = bot.reporter.build()
check("Gemini yanıt vermedi: 1" in html, "haber hunisinde görünüyor")
bot.ai.alert = "⚠️ <b>Gemini çalışmıyor</b> test"
bot.ai_health_tick()
check(SENT[-1].startswith("⚠️ <b>Gemini çalışmıyor</b>"), "sağlık uyarısı gönderildi")

print(f"\nTüm sanal işlem testleri geçti ({n_ok} kontrol).")

if os.getenv("DUMP"):
    import re as _re
    for m in SENT:
        if any(k in m for k in ("Sanal İşlem Açıldı", "Sanal Pozisyon Kapandı", "Ayna kapandı", "Durum Özeti")):
            print("-" * 70)
            print(_re.sub(r"<[^>]+>", "", m))
    print("-" * 70)
    print(_re.sub(r"<[^>]+>", "", LONG[-1] if LONG else ""))
    print("-" * 70)
    html, _ = bot.reporter.build()
    print(_re.sub(r"<[^>]+>", "", html))
