"""İzleme listesi haberleri: nabız izleme listesi + CoinGecko trend coinleri için Google News araması."""
import email.utils
import os
import shutil
import sys
from urllib.parse import parse_qs, urlparse
from xml.sax.saxutils import escape

SP = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(SP, "data_watch")
shutil.rmtree(DATA, ignore_errors=True)
os.environ.update(DATA_DIR=DATA, TELEGRAM_BOT_TOKEN="x", TELEGRAM_CHAT_ID="1", GEMINI_API_KEY="k",
                  BINANCE_API_KEY="a", BINANCE_SECRET="b", PULSE_ENABLED="False", PAPER_ENABLED="False")
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


sim = S.Sim()
S.install(sim)


class Resp:
    def __init__(self, status, data=None, content=b""):
        self.status_code, self._data, self.content = status, data, content

    def json(self):
        return self._data


class Web:
    """Sahte CoinGecko + Google News."""
    def __init__(self):
        self.trending = []          # [(sembol, ad)]
        self.search_names = {}      # sembol -> ad (CoinGecko arama)
        self.news = {}              # arama terimi -> [(başlık, yayıncı, kaç dk önce)]
        self.queries, self.cg_calls = [], []
        self.google_status = 200

    def get(self, url, params=None, headers=None, timeout=None):
        if "coingecko" in url:
            self.cg_calls.append((url, params))
            if url.endswith("/search/trending"):
                return Resp(200, {"coins": [{"item": {"symbol": s, "name": n}} for s, n in self.trending]})
            if url.endswith("/search"):
                sym = params["query"]
                name = self.search_names.get(sym)
                return Resp(200, {"coins": [{"symbol": sym, "name": name, "market_cap_rank": 50}] if name else []})
        if "news.google.com" in url:
            q = parse_qs(urlparse(url).query)["q"][0]
            self.queries.append(q)
            if self.google_status != 200:
                return Resp(self.google_status)
            term = q.split('"')[1]
            parts = ['<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>Google News</title>']
            for i, (title, pub, mins) in enumerate(self.news.get(term, [])):
                dt = email.utils.formatdate(S.fake_time() - mins * 60, usegmt=True)
                parts.append(f"<item><title>{escape(title + ' - ' + pub)}</title>"
                             f"<link>https://news.google.com/rss/articles/{abs(hash(title))}</link>"
                             f"<pubDate>{dt}</pubDate><source url=\"https://example.com\">{escape(pub)}</source></item>")
            parts.append("</channel></rss>")
            return Resp(200, content="".join(parts).encode())
        raise ConnectionError(f"test: ağ yok ({url})")


web = Web()
import requests  # noqa: E402
requests.get = web.get

import notify  # noqa: E402
SENT = []
notify.send_telegram = lambda m: SENT.append(m) or True
import bot as B  # noqa: E402
import report as R  # noqa: E402
import trader as T  # noqa: E402
import ai as A  # noqa: E402
import watchnews as W  # noqa: E402
for mod in (B, R, T):
    mod.send_telegram = notify.send_telegram

print("1) Ad sadeleştirme, başlık eşleştirme, yayıncı ayırma")
check(W.short_name("Pyth Network") == "Pyth" and W.short_name("Aerodrome Finance") == "Aerodrome"
      and W.short_name("Starknet") == "Starknet", "Pyth Network -> Pyth, Aerodrome Finance -> Aerodrome")
check(W.mentions("Starknet wants to become an L1", "STRK", "Starknet") and W.mentions("$STRK rallies", "STRK", "")
      and not W.mentions("Ethereum gas fees drop", "STRK", "Starknet"), "ad veya sembol tam kelime olarak geçmeli")
check(W.split_title("Pyth DAO approves rule - The Block", "The Block") == ("Pyth DAO approves rule", "The Block"),
      "Google News başlığından yayıncı ayrıldı")


class FakeAI(S.AIStub):
    chains = {"main": ["f"], "cheap": ["f"], "review": ["p"]}

    def __init__(self):
        self.stats = {"calls": 0, "errors": 0, "cost_usd": 0.0, "fallbacks": 0}
        self.day = dict(self.stats)
        self.last_fatal_error = None
        self.next, self.seen_items = None, []

    def analyze(self, item):
        self.seen_items.append(item)
        return self.next(item) if callable(self.next) else self.next

    def review(self, item, res, ctx, reg):
        return {"onay": True, "model_onay": True, "guven": 80, "sebep": "somut", "karsi": [], "model": "p"}

    def judge_spike(self, **kw):
        return None

    def commentary(self, d):
        return "yorum"

    def reset_day(self):
        pass


B.GeminiAnalyzer = FakeAI
bot = B.Bot()
bot.trader.startup()
bot.market.current = "BOGA"
bot.market.metrics = {"ch1": 0.1, "ch4": 0.5, "ch24": 2.0, "price": 84000, "at": S.fake_time()}

print("2) Hangi coinler aranıyor: önce nabız izleme listesi, sonra CoinGecko trendleri")
bot.pulse.state = {"ts": S.fake_time(), "izleme": [{"coin": "STRK", "guc": 2, "neden": "x"}, {"coin": "W", "guc": 1, "neden": "y"},
                                                     {"coin": "BTC", "guc": 1, "neden": "z"}, {"coin": "XY", "guc": 1, "neden": "q"}]}
web.trending = [("PYTH", "Pyth Network"), ("ETH", "Ethereum"), ("STRK", "Starknet"), ("SOL", "Solana")]
web.search_names = {"W": "Wormhole"}
coins = bot.watch.pick_coins()
check([s for s, _ in coins] == ["STRK", "W", "PYTH", "SOL"], f"sıra ve elemeler doğru: {coins}")
check(dict(coins)["W"] == "Wormhole" and dict(coins)["STRK"] == "Starknet", "adlar: trend listesi + CoinGecko araması")
n_cg = len(web.cg_calls)
bot.watch.pick_coins()
check(not any(c[0].endswith("/search") and c[1] == {"query": "W"} for c in web.cg_calls[n_cg:]), "bulunan ad önbellekten")

print("3) Arama: başlıkta coin geçmeli, 3 saatten eski olmamalı, aynı haber iki kez gelmemeli")
web.news = {
    "Starknet": [("Starknet says it wants to become an L1, eyes quantum resistance", "Decrypt", 40),
                 ("Ethereum layer-2 activity cools down", "CoinDesk", 20),                       # coin geçmiyor
                 ("Starknet launches staking v2", "The Block", 300)],                             # 5 saat önce
    "Pyth": [("Pyth DAO approves the 100% Rule for protocol revenue", "The Block", 15),
             ("Pyth DAO approves the 100% Rule for protocol revenue", "CoinTelegraph", 12)],     # aynı haber
    "Solana": [("Solana Foundation partners with Visa on stablecoin settlement", "Reuters", 30),
               ("Solana price prediction: can SOL reach $300?", "CoinCodex", 25)],
    "Wormhole": [],
}
found = bot.watch.run_once()
titles = [it["title"] for it in bot.watch.queue]
check(found == 4 and len(titles) == 4, f"4 yeni haber kuyrukta: {titles}")
check(not any("layer-2 activity" in t or "staking v2" in t for t in titles), "ilgisiz ve eski haber elendi")
check(titles.count("Pyth DAO approves the 100% Rule for protocol revenue") == 1, "aynı haber tek kez")
check(any('"Pyth" crypto when:1d' == q for q in web.queries), "Pyth Network için 'Pyth' arandı")
it0 = next(i for i in bot.watch.queue if "Pyth" in i["title"])
check(it0["source"] == "İzleme haberi" and "The Block" in it0["summary"] and it0["watch"], "kaynak ve yayıncı bilgisi")
check(bot.watch.run_once() == 0, "ikinci turda aynı haberler tekrar kuyruğa girmez")
check("4 coin" in bot.watch.status_text() and "STRK" in bot.watch.status_text(), bot.watch.status_text())

print("4) Ana döngü: izleme haberleri normal haber yolundan geçer")
facts = A.GeminiAnalyzer.build_result({"hedef_coin": "SOL", "olay_turu": "ortaklik", "kesinlik": "resmi", "yenilik": "yeni",
                                       "aktor": "birinci_lig", "olcek": "buyuk", "coin_ozel": True,
                                       "fiyat_zaten_hareket_etti": False, "yon": "olumlu", "sebep": "Visa ortaklığı"}, "f")
pass_res = A.GeminiAnalyzer.build_result({"hedef_coin": "GENEL", "olay_turu": "diger", "yon": "notr"}, "f")
bot.ai.next = lambda item: facts if "Visa" in item["title"] else pass_res
bot.watch_tick()
rows = R.read_csv(R.SIGNALS_CSV)
by_title = {r["baslik"]: r for r in rows}
sol = by_title.get("Solana Foundation partners with Visa on stablecoin settlement")
check(sol and sol["kaynak"] == "İzleme haberi" and sol["durum_kodu"] == "ALINDI", f"Visa haberi -> {sol and sol['durum_kodu']}")
check(by_title["Solana price prediction: can SOL reach $300?"]["durum_kodu"] == "FILTRE",
      "fiyat tahmini başlığı kural filtresinde kaldı (Gemini'ye gitmedi)")
check(any("Yayıncı:" in i["summary"] for i in bot.ai.seen_items), "Gemini'ye yayıncı bilgisi gitti")
check(len(bot.feed.headlines_about("STRK", 24)) == 1, "izleme haberi hacim patlaması değerlendirmesi için hafızada")

print("5) Haberden beri fiyat zaten gittiyse 'tren kaçtı'; çok eski haber işlenmez")
bot.trader.positions.clear()
bot.trader.state["cooldown"] = {}
sim.real["XRPUSDT"] = 2.10
sim.kline_fn = lambda sym, st, lim: [[st, "2.0", "2.0", "2.0", "2.0"]] * lim if sym == "XRPUSDT" else \
    [[st + i * 60000] + [str(sim.real[sym])] * 4 for i in range(lim)]
web.trending = [("XRP", "XRP")]
web.news = {"XRP": [("XRP Ledger adds native lending, Ripple says", "CoinDesk", 90)]}
bot.pulse.state = {}
bot.watch.run_once()
bot.ai.next = A.GeminiAnalyzer.build_result({"hedef_coin": "XRP", "olay_turu": "ana_ag_lansman", "kesinlik": "resmi",
                                             "yenilik": "yeni", "aktor": "birinci_lig", "olcek": "buyuk", "coin_ozel": True,
                                             "fiyat_zaten_hareket_etti": False, "yon": "olumlu", "sebep": "x"}, "f")
bot.ai.next["puan"], bot.ai.next["karar"] = 8.0, "BUY"
bot.watch_tick()
check(R.read_csv(R.SIGNALS_CSV)[-1]["durum_kodu"] == "ENGEL_TREN", "haberden beri +%5 -> tren kaçtı")
old = dict(bot.watch.queue[0]) if bot.watch.queue else None
stale = {"id": "watch:old", "title": "ADA gets major upgrade", "title_key": "adagetsmajorupgrade", "link": "l",
         "source": "İzleme haberi", "published": S.fake_time() - 200 * 60, "summary": "", "categories": "", "watch": True}
n_rows = len(R.read_csv(R.SIGNALS_CSV))
bot.watch.queue.append(stale)
bot.watch_tick()
check(len(R.read_csv(R.SIGNALS_CSV)) == n_rows, "200 dk önceki haber (sınır 180) işlenmedi")

print("6) Gemini yanıt vermezse 3 deneme, sonra AI_YOK")
web.trending = [("ADA", "Cardano")]
web.news = {"Cardano": [("Cardano Foundation announces treasury buyback", "The Block", 10)]}
bot.watch.run_once()
bot.ai.next = None
for _ in range(3):
    bot.watch_tick()
check(R.read_csv(R.SIGNALS_CSV)[-1]["durum_kodu"] == "AI_YOK" and not bot.watch_pending, "3 denemeden sonra AI_YOK")

print("7) Google sınırlarsa tur yarıda kesilir, bot etkilenmez")
web.trending = [("PYTH", "Pyth Network"), ("SOL", "Solana"), ("ADA", "Cardano")]
web.google_status = 429
q_before = len(web.queries)
check(bot.watch.run_once() == 0 and len(web.queries) == q_before + 1, "429'dan sonra diğer coinler aranmadı")
check("başarısız" in bot.watch.status, bot.watch.status)
web.google_status = 200

print("8) Nabız haber sayımına izleme aramaları karışmaz (geri besleme olmasın)")
bot.feed.recent = {}
bot.feed.add_recent({"id": "r1", "title": "Solana expands to new markets", "title_key": "k1", "source": "CoinDesk",
                     "published": S.fake_time() - 600, "summary": "", "categories": "", "link": ""})
for i in range(3):
    bot.feed.add_recent({"id": f"w{i}", "title": f"Solana news {i}", "title_key": f"w{i}", "source": "İzleme haberi",
                         "published": S.fake_time() - 600, "summary": "", "categories": "", "link": "", "watch": True})
d, text = bot.pulse.collect()
check(dict((c, n) for c, n, _ in d["mentions"]).get("SOL") == 1, f"SOL 1 kez sayıldı (izleme haberleri hariç): {d['mentions']}")
check(all(src != "İzleme haberi" for src, _ in d["headlines"]), "nabız başlıklarında izleme haberi yok")

print("9) /durum ve gece raporu")
bot.send_summary()
check("İzleme haberleri:" in SENT[-1], "/durum'da izleme haberleri satırı")
html, _ = bot.reporter.build()
check("İzleme haberleri:" in html and "İzleme haberi" in html, "raporda durum satırı ve kaynak sayımı")

print(f"\nTüm izleme listesi haberi testleri geçti ({n_ok} kontrol).")
