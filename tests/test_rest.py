import os
import shutil
import sys
from types import SimpleNamespace as N

SP = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(SP, "data_rest")
shutil.rmtree(DATA, ignore_errors=True)
os.environ.update(DATA_DIR=DATA, WATCH_NEWS_ENABLED="False", PAPER_ENABLED="False", SPIKE_AI_REQUIRE_EVIDENCE="False", TELEGRAM_BOT_TOKEN="x", TELEGRAM_CHAT_ID="1", GEMINI_API_KEY="k",
                  BINANCE_API_KEY="a", BINANCE_SECRET="b", TESTNET_OGRENME="False", SPIKE_AI_ENABLED="False", PULSE_ENABLED="False", LISTING_FAST_PATH="False", LISTING_SCORE="8", SPIKE_SKIP_REVIEW="False")
sys.path.insert(0, os.path.dirname(SP))
sys.path.insert(0, SP)

import sim as S  # noqa: E402
import time  # noqa: E402

time.sleep = lambda s: None   # beklemeleri atla

import config  # noqa: E402
import notify  # noqa: E402

SENT, DOCS, LONG = [], [], []
notify.send_telegram = lambda m: SENT.append(m) or True
import market  # noqa: E402
import trader as T  # noqa: E402
import report as R  # noqa: E402
import bot as B  # noqa: E402
import ai as A  # noqa: E402
from google.genai import errors  # noqa: E402

for mod in (market, T, R, B):
    mod.send_telegram = notify.send_telegram
R.send_long = B.send_long = lambda m: LONG.append(m)
B.send_document = lambda p, c="": DOCS.append(p) or os.path.exists(p)

n_ok = 0


def check(cond, msg):
    global n_ok
    assert cond, msg
    n_ok += 1
    print("  ✓", msg)


sim = S.Sim()
S.install(sim)

# ---------------------------------------------------------------
print("1) BTC rejimi")
bx = T.Binance("a", "b", True)


def hist(ch24, ch4, ch1, n=289):
    """Son değeri 100 olan, 24s/4s/1s önceki değerleri verilen yüzdelere uyan seri."""
    now = 100.0
    p24, p4, p1 = now / (1 + ch24 / 100), now / (1 + ch4 / 100), now / (1 + ch1 / 100)
    out = []
    for i in range(n):
        back = n - 1 - i          # kaç mum önce
        if back >= 48:
            v = p24 + (p4 - p24) * (288 - back) / 240
        elif back >= 12:
            v = p4 + (p1 - p4) * (48 - back) / 36
        else:
            v = p1 + (now - p1) * (12 - back) / 12
        out.append(v)
    return out


check(market.classify(0, 0, 5) == "COK_BOGA" and market.classify(0, -1, 5) == "BOGA", "sınıflandırma: çok boğa / boğa")
check(market.classify(0, 0, 0) == "YATAY" and market.classify(0, 0, -3) == "DUSUS", "sınıflandırma: yatay / düşüş")
check(market.classify(-2.5, 0, 1) == "COK_DUSUS" and market.classify(0, 0, -6) == "COK_DUSUS", "sınıflandırma: ani çöküş")
mk = market.Market(bx)
sim.btc_hist = hist(5, 1, 0.2)
i = mk.refresh(force=True)
check(i["name"] == "COK_BOGA" and abs(i["ch24"] - 5) < 0.01 and abs(i["ch4"] - 1) < 0.01, f"ilk hesap: {mk.describe()}")
SENT.clear()
sim.btc_hist = hist(0.5, -0.5, -0.2)
check(mk.refresh(force=True)["name"] == "COK_BOGA", "yatay sinyali 1. kez: henüz değişmedi (titreme koruması)")
check(mk.refresh(force=True)["name"] == "YATAY", "2. kez: YATAY'a geçti")
check(any("BTC rejimi değişti" in m for m in SENT), "rejim değişimi Telegram'a bildirildi")
sim.btc_hist = hist(-1, -2, -2.5)
check(mk.refresh(force=True)["name"] == "COK_DUSUS", "ani çöküş (1s -%2.5): beklemeden ÇOK DÜŞÜŞ")
check(len(mk.today_changes()) >= 3, "gün içi değişim kaydı tutuluyor")
mk2 = market.Market(bx)
check(mk2.current == "COK_DUSUS", "yeniden başlatınca son rejim hatırlanıyor")

# ---------------------------------------------------------------
print("2) Gemini model zinciri (gerçek model listenle)")
REAL_LIST = ("gemini-2.5-flash gemini-2.5-pro gemini-2.5-flash-preview-tts gemini-2.5-pro-preview-tts gemini-flash-latest "
             "gemini-flash-lite-latest gemini-pro-latest gemini-2.5-flash-lite gemini-2.5-flash-image gemini-3-flash-preview "
             "gemini-3.1-pro-preview gemini-3.1-pro-preview-customtools gemini-3.1-flash-lite-preview gemini-3.1-flash-lite "
             "gemini-3-pro-image-preview gemini-3-pro-image gemini-3.1-flash-image-preview gemini-3.1-flash-image "
             "gemini-3.1-flash-lite-image gemini-3.5-flash gemini-3.5-flash-lite gemini-omni-flash-preview gemini-omni-1.1-flash "
             "gemini-3.5-transcribe gemini-3.6-flash gemini-3.7-flash gemini-3.8-flash gemini-3.1-flash-tts-preview "
             "gemini-3.8-flash-tts gemini-3.8-flash-lite-tts").split()
FACTS = ('{"hedef_coin":"SOL","olay_turu":"listeleme","kesinlik":"resmi","yenilik":"yeni","aktor":"birinci_lig",'
         '"olcek":"orta","coin_ozel":true,"fiyat_zaten_hareket_etti":false,"yon":"olumlu","sebep":"Upbit listeledi"}')
REVIEW_OK = '{"karsi_nedenler":["a","b","c"],"onay":true,"guven":72,"sebep":"Somut ve yeni katalizör."}'


class FakeModels:
    def __init__(self, behaviors):
        self.behaviors, self.calls = behaviors, []

    def list(self):
        return [N(name="models/" + n, supported_actions=["generateContent"]) for n in REAL_LIST]

    def generate_content(self, model, contents, config):
        self.calls.append((model, config.thinking_config))
        b = self.behaviors.get(model, "busy")
        if callable(b):
            b = b(config)
        if b == "busy":
            raise errors.ServerError(503, {"error": {"code": 503, "message": "high demand", "status": "UNAVAILABLE"}})
        if b == "gone":
            raise errors.ClientError(404, {"error": {"code": 404, "message": "no longer available", "status": "NOT_FOUND"}})
        if b == "badkey":
            raise errors.ClientError(403, {"error": {"code": 403, "message": "API key not valid", "status": "PERMISSION_DENIED"}})
        um = N(prompt_token_count=900, candidates_token_count=120, thoughts_token_count=0)
        return N(text=b, usage_metadata=um)


def make_ai(behaviors):
    fm = FakeModels(behaviors)
    A.genai.Client = lambda api_key: N(models=fm)
    return A.GeminiAnalyzer(), fm


thinking_strict = lambda cfg: ('{"x":1}' if False else (REVIEW_OK if cfg.thinking_config is None else "think400"))


def pro_behavior(cfg):
    if cfg.thinking_config is not None:
        raise errors.ClientError(400, {"error": {"code": 400, "message": "thinking_level is not supported", "status": "INVALID_ARGUMENT"}})
    return REVIEW_OK


ai, fm = make_ai({"gemini-3.5-flash-lite": FACTS, "gemini-3.1-pro-preview": pro_behavior})
check(ai.chains["main"] == ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.5-flash-lite", "gemini-flash-latest",
                            "gemini-flash-lite-latest"], f"hacim/nabız zinciri (takma adlar yedekte): {ai.chains['main']}")
check(ai.chains["cheap"][:3] == ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-flash-lite-latest"],
      f"haber analizi ucuz zincir (lite önce): {ai.chains['cheap']}")
check(ai.chains["review"][:3] == ["gemini-3.1-pro-preview", "gemini-2.5-pro", "gemini-pro-latest"],
      f"ikinci görüş zinciri: {ai.chains['review']}")
it = {"title": "Upbit lists SOL", "summary": "", "source": "T", "published": S.fake_time() - 120, "categories": ""}
r = ai.analyze(it)
check(r and r["hedef_coin"] == "SOL" and r["puan"] == 9 and r["karar"] == "BUY", f"olgulardan puan: {r['puan']} {r['karar']}")
check([c[0] for c in fm.calls] == ["gemini-3.5-flash-lite"], "haber analizi doğrudan ucuz lite modelle yapıldı")
fm.calls.clear()
ai.judge_spike(coin="SOL", move=3, ratio=4, vol="1M", ch24="+5%", trending="hayır", watch="hayır", pulse="-",
               regime="Boğa", headlines="- yok")
check([c[0] for c in fm.calls] == ["gemini-3.8-flash"] * 2 + ["gemini-3.7-flash"] * 2 + ["gemini-3.5-flash-lite"],
      "hacim yorumu: yoğun flash modeller 2'şer denendi, sonra lite")
fm.calls.clear()
ai.judge_spike(coin="SOL", move=3, ratio=4, vol="1M", ch24="+5%", trending="hayır", watch="hayır", pulse="-",
               regime="Boğa", headlines="- yok")
check([c[0] for c in fm.calls] == ["gemini-3.5-flash-lite"], "ikinci çağrıda doğrudan çalışan model (yapışkan)")
rv = ai.review(it, r, {"coin_ch24": 3.2, "coin_volume": 5e8, "late_move": 0.4}, "📈 Boğa")
check(rv and rv["onay"] and rv["guven"] == 72, "ikinci görüş: 400 düşünme hatasından sonra ayarsız denendi, onay")
check(fm.calls[-1][1] is None and fm.calls[-2][1] is not None, "düşünme ayarı ilk denemede vardı, sonra kaldırıldı")
ai2, fm2 = make_ai({"gemini-3.1-pro-preview": "gone", "gemini-2.5-pro": "gone", "gemini-pro-latest":
                    '{"karsi_nedenler":[],"onay":true,"guven":40,"sebep":"zayıf"}'})
rv2 = ai2.review(it, r, {}, "Boğa")
check(rv2 and not rv2["onay"] and rv2["model_onay"], "güven 40 < 60 -> onay sayılmadı")
check("gemini-3.1-pro-preview" in ai2.dead and "gemini-2.5-pro" in ai2.dead, "404 veren modeller listeden çıkarıldı")
ai3, _ = make_ai({m: "badkey" for m in REAL_LIST})
check(ai3.analyze(it) is None and "403" in (ai3.last_fatal_error or ""), "403 anahtar hatası: hemen durur, hata bildirilir")
ai4, _ = make_ai({"gemini-3.8-flash": "Günün özeti: test yorumu."})
check(ai4.commentary("veri") == "Günün özeti: test yorumu.", "gece raporu yorumu metin olarak alındı")
check(ai.day["calls"] > 0 and ai.day["cost_usd"] > 0, f"günlük maliyet takibi: ${ai.day['cost_usd']:.5f}")

# ---------------------------------------------------------------
print("3) Kalibrasyon")
import calibration as C  # noqa: E402

cal = C.Calibrator(bx)
item = {"title": "Upbit lists SOL", "link": "http://a/1", "source": "T", "published": S.fake_time() - 180}
sim.real["SOLUSDT"] = 149.0 * (1 + 0.0002 * 3)
check(cal.add(item, {"hedef_coin": "SOL", "puan": 9.0, "karar": "BUY", "olay_turu": "listeleme"}, "ALINDI", "BOGA", "onay 72"),
      "haber ölçüm listesine eklendi")
check(not cal.add(item, {"hedef_coin": "NOPE", "puan": 5.0}, "PASS", "BOGA"), "gerçek Binance'te olmayan coin ölçülemez")
cal.add(dict(item, link="http://a/2", title="Genel piyasa"), {"hedef_coin": "GENEL", "puan": 4.0, "karar": "PASS"},
        "PASS", "BOGA")
check(cal.process_due() == 0, "4 saat dolmadan ölçüm yapılmaz")


def klines(sym, start_ms, limit):
    if sym == "BTCUSDT":
        return [[start_ms + i * 60000, "84000", "84100", "83900", str(84000 * (1 + 0.00001 * i))] for i in range(limit)]
    base = 149.0
    out = []
    for i in range(limit):
        c = base * (1 + 0.0002 * i)
        out.append([start_ms + i * 60000, str(c), str(c * 1.003), str(c * 0.997), str(c)])
    return out


sim.kline_fn = klines
S.advance(245)
check(cal.process_due() == 2, "4 saat sonra 2 kayıt ölçüldü")
rows = C.load_rows()
r1 = [x for x in rows if x["coin"] == "SOL"][0]
print("   ", {k: r1[k] for k in ("r15dk", "r1s", "r4s", "max1s", "min1s", "max4s", "btc_r1s", "fark_r1s", "yayindan_sinyale")})
check(0 < float(r1["r15dk"]) < float(r1["r1s"]) < float(r1["r4s"]) and float(r1["fark_r1s"]) > 0,
      "15dk < 1s < 4s getiri, BTC'ye göre fark pozitif")
check([x for x in rows if x["coin"] == "GENEL"][0]["sembol"] == "BTCUSDT", "genel haber BTC üzerinden ölçüldü")
summary = C.telegram_summary(7)
print(summary)
check("9-10 puan" in summary and "n=1" in summary, "Telegram kalibrasyon özeti")

# ---------------------------------------------------------------
print("4) Ana akış (Bot.process) + rapor + komutlar")


class FakeAI(S.AIStub):
    def __init__(self):
        self.chains = {"main": ["fake-flash"], "cheap": ["fake-flash"], "review": ["fake-pro"]}
        self.stats = {"calls": 3, "errors": 0, "cost_usd": 0.01, "fallbacks": 0}
        self.day = dict(self.stats)
        self.last_fatal_error = None
        self.next = None
        self.review_answer = None
        self.reset_called = False

    def analyze(self, item):
        return self.next

    def review(self, item, res, ctx, regime_text):
        return self.review_answer

    def commentary(self, data):
        self.last_data = data
        return "1. Günün özeti: test <b>yorumu</b>"

    def reset_day(self):
        self.reset_called = True


B.GeminiAnalyzer = FakeAI
bot = B.Bot()
bot.trader.startup()
bot.market.current = "BOGA"
bot.market.metrics = {"ch1": 0.1, "ch4": 0.5, "ch24": 2.0, "price": 84000, "at": S.fake_time()}
reg = bot.market.info()


def news(title, mins=2):
    import news as NW
    return {"id": title, "title": title, "title_key": NW._title_key(title), "link": "http://n/" + title.replace(" ", "_"),
            "source": "Cointelegraph", "published": S.fake_time() - mins * 60, "summary": "", "categories": ""}


def facts(coin, score_kind):
    base = {"hedef_coin": coin, "kesinlik": "resmi", "yenilik": "yeni", "olcek": "orta", "coin_ozel": True,
            "fiyat_zaten_hareket_etti": False, "yon": "olumlu", "sebep": "test"}
    base.update({"9": {"olay_turu": "listeleme", "aktor": "birinci_lig"},
                 "7": {"olay_turu": "ortaklik", "aktor": "birinci_lig"},
                 "4": {"olay_turu": "yorum", "aktor": "yok"}}[score_kind])
    return A.GeminiAnalyzer.build_result(base, "fake")


sim.kline_fn = None
for k in ("SOLUSDT", "XRPUSDT", "ADAUSDT"):
    sim.real[k] = sim.px[k]
SENT.clear()
bot.process(news("XRP price prediction: bulls eye $3"), reg)
bot.ai.next = facts("ADA", "4")
bot.process(news("Analyst comments on Cardano"), reg)
bot.ai.next = facts("XRP", "7")
bot.ai.review_answer = {"onay": False, "model_onay": False, "guven": 35, "sebep": "Zaten fiyatlanmış.",
                        "karsi": ["eski haber", "küçük ölçek", "piyasa zayıf"], "model": "fake-pro"}
bot.process(news("Ripple partners with big bank"), reg)
bot.ai.next = facts("SOL", "9")
bot.ai.review_answer = {"onay": True, "model_onay": True, "guven": 80, "sebep": "Güçlü katalizör.", "karsi": [],
                        "model": "fake-pro"}
bot.process(news("Upbit lists SOL"), reg)
yatay = dict(config.REGIMES["YATAY"], name="YATAY")
bot.ai.next = facts("ADA", "7")
bot.process(news("Cardano partners with oil giant"), yatay)

sig = R.read_csv(R.SIGNALS_CSV)
codes = [s["durum_kodu"] for s in sig]
print("    durum kodları:", codes)
check(codes == ["FILTRE", "PASS", "IKINCI_GORUS_RED", "ALINDI", "REJIM_ESIGI"], "her yol doğru kodla kaydedildi")
check(len(bot.trader.positions) == 1 and bot.trader.positions[0]["symbol"] == "SOLUSDT", "sadece onaylanan SOL alındı")
check(any("ALIM ADAYI" in m and "Karşı nedenler" in m for m in SENT), "reddedilen aday karşı nedenlerle bildirildi")
check(any("İşlem Açıldı" in m and "İkinci görüş" in m for m in SENT), "alım mesajında ikinci görüş var")
check(any("en az 8 puan" in m for m in SENT), "rejim eşiği mesajı")
check(len(bot.calib.pending) >= 4, f"kalibrasyona eklendi ({len(bot.calib.pending)} kayıt)")

# Kapanan bir işlem ekle ve raporu üret
bot.trader.state["closed"].append({"symbol": "XRPUSDT", "score": 8, "regime": "BOGA", "mode": "trailing", "pnl": 0.9,
                                   "pct": 2.6, "peak_pct": 3.9, "reason": "İZLEYEN STOP", "opened_at": S.fake_time() - 3600,
                                   "closed_at": S.fake_time(), "minutes": 60, "title": "t", "event": "ortaklik"})
LONG.clear()
html_text, data_text = bot.reporter.build()
print(html_text)
check("Gün Sonu Raporu" in html_text and "Haber hunisi" in html_text and "İZLEYEN STOP" in html_text, "rapor bölümleri")
check("Kural filtresi: 1" in html_text and "Alındı 1" in html_text, "haber hunisi sayıları")
path = bot.reporter.run(manual=False)
check(os.path.exists(path) and bot.trader.state.get("last_report") and bot.ai.reset_called, f"rapor kaydedildi: {os.path.basename(path)}")
check(any("Yapay Zeka Yorumu" in m and "&lt;b&gt;" in m for m in LONG), "yapay zeka yorumu HTML-güvenli gönderildi")
check(not bot.reporter.due(), "aynı gün ikinci kez otomatik rapor yok")

bot.handle_command("/durum")
check("Durum Özeti" in SENT[-1], "/durum")
bot.handle_command("/kalibrasyon")
check("Kalibrasyon" in LONG[-1], "/kalibrasyon")
DOCS.clear()
bot.handle_command("/dosyalar")
check(any(p.endswith("signals.csv") for p in DOCS) and any("reports" in p for p in DOCS), f"/dosyalar: {len(DOCS)} dosya")
bot.handle_command("/rejim")
check("BTC rejimi" in SENT[-1], "/rejim")

# send_long bölme
import importlib  # noqa: E402
nt = importlib.reload(notify)
parts = []
nt.send_telegram = lambda m: parts.append(m) or True
nt.send_long("satır\n" * 2000)
check(len(parts) >= 3 and all(len(p) <= 3901 for p in parts), f"uzun mesaj {len(parts)} parçaya bölündü")

print(f"\nTüm testler geçti ({n_ok} kontrol).")
