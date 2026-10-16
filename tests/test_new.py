import asyncio
import os
import shutil
import sys
from datetime import datetime, timezone
from types import SimpleNamespace as N

SP = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(SP, "data_new")
shutil.rmtree(DATA, ignore_errors=True)
os.environ.update(DATA_DIR=DATA, WATCH_NEWS_ENABLED="False", PAPER_ENABLED="False", SPIKE_AI_REQUIRE_EVIDENCE="False", PULSE_MINUTES="60", SPIKE_AI_MAX_PER_HOUR="30", TELEGRAM_BOT_TOKEN="x", TELEGRAM_CHAT_ID="1", GEMINI_API_KEY="k",
                  BINANCE_API_KEY="a", BINANCE_SECRET="b", TG_API_ID="12345", TG_API_HASH="abc")
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


print("0) Öğrenme modu varsayılanları (TEST_MODE=True)")
import market as MK  # noqa: E402
check(config.LEARNING and config.ALT_SIGNALS_TRADE and config.REVIEW_MIN_CONFIDENCE == 50,
      "öğrenme modu açık: alternatif sinyallerle alım açık, ikinci görüş güveni 50")
check({k: MK.effective_min_score(k) for k in config.REGIMES} ==
      {"COK_BOGA": 7, "BOGA": 7, "YATAY": 7, "DUSUS": 8, "COK_DUSUS": 9}, "rejim eşikleri 1 puan düşük, en az 7")

print("1) Telegram kanal okuyucu (sahte Telethon)")
import tgnews as TG  # noqa: E402

it = TG.to_item("WatcherGuru", 77, 1000.0, "JUST IN: 🇺🇸 Coinbase lists $PUMP for spot trading\nMore https://x.com/a")
check(it["title"] == "JUST IN: 🇺🇸 Coinbase lists $PUMP for spot trading" and it["source"] == "TG @WatcherGuru"
      and it["link"] == "https://t.me/WatcherGuru/77" and "http" not in it["summary"], "mesaj haber öğesine çevrildi")
check(TG.to_item("x", 1, 1.0, "📷") is None, "boş/sadece resim mesajı atlandı")
check(TG.to_item("x", 2, 1.0, "BREAKING:\nBinance will list XYZ (XYZ) today")["title"].startswith("BREAKING: Binance will list"),
      "kısa ilk satır ikinci satırla birleştirildi")


def msg(i, text, mins_ago=1):
    return N(id=i, raw_text=text, date=datetime.fromtimestamp(time.time() - mins_ago * 60, tz=timezone.utc))


class FakeClient:
    def __init__(self, authorized=True):
        self.authorized = authorized
        self.channels = {"WatcherGuru": [msg(10, "old news message here")], "TreeNewsFeed": [msg(5, "tree old message here")],
                         "BWEnews": [], "wublockchainenglish": [], "binance_announcements": []}
        self.flood = False

    async def connect(self):
        pass

    async def disconnect(self):
        pass

    async def is_user_authorized(self):
        return self.authorized

    async def get_entity(self, name):
        if name not in self.channels:
            raise ValueError("No user has that username")
        return name

    async def get_messages(self, ent, limit=1, min_id=0):
        if self.flood:
            self.flood = False
            e = type("FloodWaitError", (Exception,), {})("wait")
            e.seconds = 3
            raise e
        msgs = [m for m in self.channels[ent] if m.id > min_id]
        return sorted(msgs, key=lambda m: -m.id)[:limit]


fc = FakeClient()
tg = TG.TelegramNews(client_factory=lambda: fc)
check(tg.enabled, "API anahtarları varsa okuyucu etkin")
loop = asyncio.new_event_loop()
loop.run_until_complete(tg._poll_channel(fc, "WatcherGuru", "WatcherGuru"))
check(tg.last_ids["WatcherGuru"] == 10 and tg.drain() == [], "ilk okumada eski mesajlar işlenmedi (başlangıç noktası)")
fc.channels["WatcherGuru"] += [msg(11, "JUST IN: Upbit lists SUI for KRW trading"), msg(12, "📷"),
                               msg(13, "Binance to delist ABC")]
loop.run_until_complete(tg._poll_channel(fc, "WatcherGuru", "WatcherGuru"))
items = tg.drain()
check([i["id"] for i in items] == ["tg:WatcherGuru:11", "tg:WatcherGuru:13"] and tg.last_ids["WatcherGuru"] == 13,
      "yeni mesajlar sırayla kuyruğa girdi, boş mesaj atlandı")
fc.flood = True
loop.run_until_complete(tg._poll_channel(fc, "WatcherGuru", "WatcherGuru"))
check("bekletiyor" in tg.channel_status["WatcherGuru"], "Telegram 'yavaşla' derse bekleyip devam ediyor")
tg2 = TG.TelegramNews(client_factory=lambda: fc)
check(tg2.last_ids.get("WatcherGuru") == 13, "okunan son mesaj yeniden başlatınca hatırlanıyor")
config.TG_NEWS_CHANNELS = ["WatcherGuru", "YokBoyleKanal"]
tg3 = TG.TelegramNews(client_factory=lambda: FakeClient(authorized=False))
loop.run_until_complete(tg3._main())
check("tg_login.py" in tg3.status, f"giriş yapılmamışsa açık talimat: {tg3.status}")
tg4 = TG.TelegramNews(client_factory=lambda: fc)
tg4._stop.set()
loop.run_until_complete(tg4._main())
check("bulunamadı" in tg4.channel_status["YokBoyleKanal"] and tg4.status.startswith("ok (1/2"),
      f"bulunamayan kanal atlandı: {tg4.status_text()}")
config.TG_NEWS_CHANNELS = ["WatcherGuru", "TreeNewsFeed", "BWEnews", "wublockchainenglish", "binance_announcements"]

print("2) Gemini: nabız ve hacim yorumu ayrıştırma")
import ai as A  # noqa: E402
from google.genai import errors  # noqa: E402

PULSE_JSON = ('{"ozet": "AI sektörü öne çıkıyor, PUMP ve STRK haber ve hacimle destekleniyor.", "duygu": "olumlu", '
              '"sicak_anlatilar": ["AI", "meme"], "izleme_listesi": [{"coin": "$fet", "guc": 2, "neden": "AI trendi"}, '
              '{"coin": "SOL", "guc": 5, "neden": "ETF haberi"}, {"coin": "USDT", "guc": 1, "neden": "x"}], '
              '"uzak_dur": [{"coin": "XRP", "neden": "aşırı ısınma"}]}')
SPIKE_JSON = '{"hikaye_var": true, "guc": 8, "katalizor": "Upbit listelemesi", "risk": "geri çekilme", "sebep": "Somut."}'


class FM:
    def list(self):
        return [N(name="models/" + n, supported_actions=["generateContent"])
                for n in ["gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-3.1-pro-preview"]]

    def generate_content(self, model, contents, config):
        if "Piyasa nabzını" in contents or "nabzını" in contents:
            txt = PULSE_JSON
        elif "hacim patlaması" in contents:
            txt = SPIKE_JSON
        else:
            txt = "{}"
        return N(text=txt, usage_metadata=None)


A.genai.Client = lambda api_key: N(models=FM())
g = A.GeminiAnalyzer()
p = g.pulse_analysis("veri")
check(p and [w["coin"] for w in p["izleme"]] == ["FET", "SOL"] and p["izleme"][1]["guc"] == 3
      and p["uzak_dur"][0]["coin"] == "XRP" and p["duygu"] == "olumlu",
      "nabız: semboller temizlendi, stablecoin atıldı, güç 1-3 aralığına sıkıştırıldı")
j = g.judge_spike(coin="SUI", move=3.1, ratio=4.2, vol="900K USDT", ch24="+6%", trending="evet", watch="hayır",
                  pulse="-", regime="Yatay", headlines="- [TG @WatcherGuru, 3 dk önce] Upbit lists SUI")
check(j and j["hikaye_var"] and j["guc"] == 8 and j["katalizor"] == "Upbit listelemesi", "hacim yorumu ayrıştırıldı")

print("3) Piyasa Nabzı (sahte CoinGecko / Korku&Açgözlülük / Binance)")
import pulse as PL  # noqa: E402

CG = {
    "trending": {"coins": [{"item": {"symbol": "pump", "name": "Pump.fun", "market_cap_rank": 60,
                                      "data": {"price_change_percentage_24h": {"usd": 14.3}}}},
                           {"item": {"symbol": "fet", "name": "ASI", "market_cap_rank": 80,
                                     "data": {"price_change_percentage_24h": {"usd": 2.8}}}}],
                 "categories": [{"name": "AI Agents"}, {"name": "Meme"}]},
    "categories": [{"name": "AI Agents", "market_cap": 9e9, "market_cap_change_24h": 8.2},
                   {"name": "Tiny", "market_cap": 1e6, "market_cap_change_24h": 90},
                   {"name": "Meme", "market_cap": 5e10, "market_cap_change_24h": 4.1},
                   {"name": "DeFi", "market_cap": 8e10, "market_cap_change_24h": -1.5}],
    "fng": {"data": [{"value": "61", "value_classification": "Greed"}, {"value": "55"}]},
}


def fake_get(url, params=None, headers=None, timeout=None):
    key = "trending" if "trending" in url else "categories" if "categories" in url else "fng"
    return N(status_code=200, json=lambda: CG[key])


PL.requests.get = fake_get
sim = S.Sim()
S.install(sim)
sim.real.update({"PUMPUSDT": 0.0065, "FETUSDT": 0.25, "STRKUSDT": 0.056})
sim.px.update({"FETUSDT": 0.25})
sim.ch24 = {"PUMPUSDT": 14.3, "STRKUSDT": 13.7, "FETUSDT": 2.8, "BTCUSDT": 0.5}


class FakeAI(S.AIStub):
    chains = {"main": ["f"], "cheap": ["f"], "review": ["p"]}
    stats = {"calls": 0, "errors": 0, "cost_usd": 0.0, "fallbacks": 0}
    day = dict(stats)
    last_fatal_error = None

    def __init__(self):
        self.next, self.review_answer, self.spike, self.pulse_text = None, None, None, None
        self.spike_calls = 0

    def analyze(self, item):
        return self.next() if callable(self.next) else self.next

    def review(self, item, res, ctx, reg):
        return self.review_answer

    def judge_spike(self, **kw):
        self.spike_calls += 1
        self.last_spike = kw
        return self.spike

    def pulse_analysis(self, text):
        self.pulse_text = text
        return {"ozet": "AI öne çıkıyor.", "duygu": "olumlu", "anlatilar": ["AI"], "model": "p",
                "izleme": [{"coin": "FET", "guc": 2, "neden": "AI trendi"}, {"coin": "ADA", "guc": 1, "neden": "x"}],
                "uzak_dur": [{"coin": "XRP", "neden": "ısınma"}]}

    def commentary(self, d):
        return "yorum"

    def reset_day(self):
        pass


import notify  # noqa: E402
sent, longs = [], []
notify.send_telegram = lambda m: sent.append(m) or True
import bot as B  # noqa: E402
import report as R  # noqa: E402
for mod in (B, R, MK):
    mod.send_telegram = notify.send_telegram
B.send_long = R.send_long = lambda m: longs.append(m)
B.GeminiAnalyzer = FakeAI
import news as NW  # noqa: E402

bot = B.Bot()
bot.trader.startup()
bot.market.current = "YATAY"
bot.market.metrics = {"ch1": 0.1, "ch4": -0.2, "ch24": 0.5, "price": 84000, "at": S.fake_time()}
now = S.fake_time()
for t, src, mins in [("PUMP explodes as Pump.fun launches new app", "TG @WatcherGuru", 30),
                     ("Fetch.ai FET partners with big lab", "CoinDesk", 50), ("FET AI agents surge", "TG @TreeNewsFeed", 20),
                     ("FET older story", "Decrypt", 400)]:
    bot.feed.add_recent({"title": t, "title_key": NW._title_key(t), "source": src, "published": now - mins * 60,
                         "link": "l", "summary": "", "id": t})
bot.scanner.history.append((now - 600, "STRK", 3.0))
bot.scanner.snapshots.append((now, {"PUMPUSDT": 1, "FETUSDT": 1, "STRKUSDT": 1, "SOLUSDT": 1, "ADAUSDT": 1}))
data, text = bot.pulse.collect()
print("   " + text.replace("\n", "\n   ")[:1200])
check(all(v == "ok" for v in bot.pulse.status.values()), f"tüm nabız kaynakları okundu: {bot.pulse.status}")
check([t["symbol"] for t in data["trending"]] == ["PUMP", "FET"] and data["sectors_up"][0][0] == "AI Agents"
      and all(n != "Tiny" for n, _ in data["sectors_up"]), "trend coinler ve büyük sektörler alındı (küçük sektör elendi)")
check(data["fng"][:2] == [61, "Greed"] and data["gainers"][0][0] == "PUMP", "Korku&Açgözlülük ve Binance yükselenler")
check(dict((c, n) for c, n, o in data["mentions"]).get("FET") == 2 and ("STRK", 1) in data["spikes"],
      "haber yoğunluğu (son 2 saat) ve hacim patlamaları sayıldı")
check(bot.pulse.due(), "ilk açılışta nabız hemen çalışmalı")
check(bot.pulse.run() and bot.pulse.watch_entry("FET") and bot.pulse.is_trending("PUMP"), "nabız çalıştı, izleme listesi hazır")
check(bot.pulse.should_notify(), "ilk nabız Telegram'a gönderilecek")
bot.pulse.mark_notified()
check(not bot.pulse.should_notify(), "sonraki özet 4 saat sonra")
brief = bot.pulse.brief_html()
check("Piyasa Nabzı" in brief and "FET ★★" in brief and "Greed" in brief, "nabız mesajı")

print("4) Haber akışı: nabız bonusu + öğrenme modu")


def facts(coin, kind):
    base = {"hedef_coin": coin, "kesinlik": "resmi", "yenilik": "yeni", "olcek": "orta", "coin_ozel": True,
            "fiyat_zaten_hareket_etti": False, "yon": "olumlu", "sebep": "test"}
    base.update({"6": {"olay_turu": "ortaklik", "aktor": "orta"}, "7": {"olay_turu": "ortaklik", "aktor": "birinci_lig"}}[kind])
    return A.GeminiAnalyzer.build_result(base, "fake")


def news(title, mins=2, source="CoinDesk"):
    return {"id": title, "title": title, "title_key": NW._title_key(title), "link": "http://n/" + title.replace(" ", "_"),
            "source": source, "published": S.fake_time() - mins * 60, "summary": "", "categories": ""}


bot.trader.bx.symbols["FETUSDT"] = dict(bot.trader.bx.symbols["SOLUSDT"], base="FET")
bot.trader.bx._symbols_loaded_at = S.fake_time() + 10 ** 6
bot.ai.review_answer = {"onay": True, "model_onay": True, "guven": 55, "sebep": "ok", "karsi": [], "model": "p"}
reg = bot.market.info()
bot.ai.next = lambda: facts("FET", "6")
bot.process(news("Fetch.ai partners with mid-size lab"), reg)
rows = R.read_csv(R.SIGNALS_CSV)
check(rows[-1]["durum_kodu"] == "ALINDI" and rows[-1]["puan"] == "7",
      "6 puanlık FET haberi izleme listesi bonusuyla 7 oldu; yatay rejimde öğrenme eşiği 7 -> güven 55 ile alındı")
bot.ai.next = lambda: facts("ADA", "7")
bot.ai.review_answer = {"onay": True, "model_onay": True, "guven": 45, "sebep": "zayıf", "karsi": ["x"], "model": "p"}
bot.ai.review_answer["onay"] = 45 >= config.REVIEW_MIN_CONFIDENCE
bot.process(news("Cardano partners with big bank"), reg)
check(R.read_csv(R.SIGNALS_CSV)[-1]["durum_kodu"] == "IKINCI_GORUS_RED", "güven 45 < 50 -> reddedildi")
bot.ai.next = lambda: facts("XRP", "7")
bot.process(news("Ripple partners with big bank"), reg)
r = R.read_csv(R.SIGNALS_CSV)[-1]
check(r["puan"] == "6" and r["durum_kodu"] == "PASS", "uzak dur listesindeki XRP: 7 -> 6, alınmadı")

print("5) Telegram mesajları ana döngüde")
calls = {"n": 0}


def flaky():
    calls["n"] += 1
    return None if calls["n"] == 1 else facts("SOL", "7")


bot.ai.next = flaky
bot.ai.review_answer = {"onay": True, "model_onay": True, "guven": 70, "sebep": "ok", "karsi": [], "model": "p"}
bot.tg.queue.put(TG.to_item("WatcherGuru", 500, S.fake_time() - 60, "JUST IN: Solana partners with Visa"))
bot.tg.queue.put(TG.to_item("WatcherGuru", 499, S.fake_time() - 3600, "Old message about Solana"))
bot.tg_tick()
check(len(bot.tg_pending) == 1, "Gemini yanıt vermeyen Telegram haberi tekrar denenecek; 60 dk'lık eski mesaj atlandı")
bot.tg_tick()
r = R.read_csv(R.SIGNALS_CSV)[-1]
check(r["kaynak"] == "TG @WatcherGuru" and r["durum_kodu"] == "ALINDI" and not bot.tg_pending,
      "ikinci denemede işlendi ve alındı (kaynak: TG @WatcherGuru)")
check(any(i.get("source") == "TG @WatcherGuru" and "Visa" in i["title"] for i in bot.feed.recent.values()),
      "Telegram haberi nabız ve hacim eşleştirmesi için son başlıklara eklendi")

print("6) Hacim patlaması: Gemini yorumu")
for p in list(bot.trader.positions):
    bot.trader.positions.remove(p)
bot.trader.state["cooldown"] = {}
sim.real["ADAUSDT"] = sim.px["ADAUSDT"]
sig = {"coin": "ADA", "symbol": "ADAUSDT", "move": 3.1, "ratio": 4.2, "vol": 900000, "price": 0.5, "ch24": 6.0,
       "news": [], "ts": S.fake_time()}
bot.feed.add_recent({"title": "Cardano ADA gets Upbit KRW listing", "title_key": "adaup", "source": "TG @BWEnews",
                     "published": S.fake_time() - 300, "link": "l2", "summary": "", "id": "x"})
bot.ai.spike = {"hikaye_var": False, "guc": 3, "katalizor": "-", "risk": "pump", "sebep": "Sebepsiz.", "model": "f"}
n_sent = len(sent)
bot.handle_volume(dict(sig))
check(R.read_csv(R.SIGNALS_CSV)[-1]["durum_kodu"] == "HACIM_AI_RED" and len(sent) == n_sent,
      "Gemini hikâye görmedi -> kayıt, Telegram'a mesaj yok")
check("Upbit KRW listing" in bot.ai.last_spike["headlines"] and bot.ai.last_spike["watch"].startswith("evet"),
      "Gemini'ye Telegram haberi ve izleme listesi bilgisi gitti")
bot.ai.spike = {"hikaye_var": True, "guc": 8, "katalizor": "Upbit listelemesi", "risk": "geri çekilme",
                "sebep": "Somut katalizör.", "model": "f"}
bot.handle_volume(dict(sig, ts=S.fake_time()))
r = R.read_csv(R.SIGNALS_CSV)[-1]
check(r["durum_kodu"] == "ALINDI" and r["olay_turu"] == "hacim_ai_onay", "Gemini onayı + öğrenme modu -> ADA alındı")
config.SPIKE_AI_MAX_PER_HOUR = bot.ai.spike_calls
before = bot.ai.spike_calls
bot.handle_volume(dict(sig, coin="SOL", symbol="SOLUSDT", ts=S.fake_time()))
check(bot.ai.spike_calls == before and R.read_csv(R.SIGNALS_CSV)[-1]["durum_kodu"] == "HACIM_SINIR",
      "saatlik Gemini sınırı dolunca değerlendirmeden kaydediliyor (HACIM_SINIR)")
config.SPIKE_AI_MAX_PER_HOUR = 30

print("7) Komutlar, başlangıç mesajı ve rapor")
longs.clear()
bot.handle_command("/nabiz")
check(longs and "Piyasa Nabzı" in longs[-1], "/nabiz")
sent.clear()
bot.start()
check(any("öğrenme modu AÇIK" in m and "Piyasa Nabzı" in m and "@WatcherGuru" in m for m in sent),
      "başlangıç mesajında öğrenme modu, nabız ve Telegram kanalları")
bot.tg.stop()
html, data_txt = bot.reporter.build()
check("🧭 <b>Piyasa Nabzı</b>" in html and "Telegram kanalları:" in html and "FET" in html, "gece raporunda nabız ve Telegram")
check("TG @WatcherGuru" in html, "Telegram kaynağı haber hunisinde görünüyor")
bot.handle_command("/durum")
check("Nabız:" in sent[-1] and "Telegram kanalları:" in sent[-1], "/durum nabız ve Telegram durumunu gösteriyor")
print(f"\nTüm yeni özellik testleri geçti ({n_ok} kontrol).")
