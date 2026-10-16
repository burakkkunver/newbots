import os, sys, shutil, json, csv
SP = os.path.dirname(os.path.abspath(__file__)); DATA = os.path.join(SP, "data_legacy2"); shutil.rmtree(DATA, ignore_errors=True); os.makedirs(DATA)
os.environ.update(DATA_DIR=DATA, WATCH_NEWS_ENABLED="False", PAPER_ENABLED="False", SPIKE_AI_REQUIRE_EVIDENCE="False", TELEGRAM_BOT_TOKEN="x", TELEGRAM_CHAT_ID="1", GEMINI_API_KEY="k", BINANCE_API_KEY="a", BINANCE_SECRET="b", TESTNET_OGRENME="False", SPIKE_AI_ENABLED="False", PULSE_ENABLED="False")
sys.path.insert(0, os.path.dirname(SP)); sys.path.insert(0, SP)
import sim as S, time
from datetime import datetime
now_iso = datetime.now().isoformat(timespec="seconds")
# Eski sürüm dosyaları (ilk sürümün başlıkları)
with open(os.path.join(DATA, "signals.csv"), "w", newline="") as f:
    w = csv.writer(f); w.writerow(["zaman", "yayin", "kaynak", "karar", "puan", "coin", "islem", "baslik", "sebep", "link"])
    w.writerow([now_iso, now_iso, "CT", "BUY", 8, "XRP", "ALINDI", "eski haber", "x", "l"])
with open(os.path.join(DATA, "trades.csv"), "w", newline="") as f:
    w = csv.writer(f); w.writerow(["acilis", "kapanis", "sembol", "puan", "giris", "cikis", "maliyet", "kar_usdt", "kar_yuzde", "sebep", "sure_dk", "haber"])
    w.writerow([now_iso, now_iso, "SOLUSDT", 8, 150, 155, 35, 1.2, 3.4, "KÂR AL", 30, "eski"])
json.dump({"realized_pnl": 1.2, "cooldown": {}, "closed": [{"symbol": "SOLUSDT", "pnl": 1.2, "pct": 3.4, "closed_at": time.time() - 60, "reason": "KÂR AL"}]},
          open(os.path.join(DATA, "state.json"), "w"))
s = S.Sim(); S.install(s)
import notify; sent = []; notify.send_telegram = lambda m: sent.append(m) or True
import bot as B, report as R
R.send_long = lambda m: sent.append(m); R.send_telegram = notify.send_telegram
from types import SimpleNamespace as N
class FakeAI(S.AIStub):
    chains = {"main": ["f"], "cheap": ["f"], "review": ["p"]}; stats = {"calls": 0, "errors": 0, "cost_usd": 0.0, "fallbacks": 0}
    day = dict(stats); last_fatal_error = None
    def commentary(self, d): return "yorum"
    def reset_day(self): pass
B.GeminiAnalyzer = FakeAI
bot = B.Bot(); bot.trader.startup()
print("data klasörü:", sorted(os.listdir(DATA)))
path = bot.reporter.run()
print("rapor:", os.path.basename(path), "| gönderilen mesaj:", len(sent))
print([l for l in sent[0].split("\n") if "SOLUSDT" in l or "Haber hunisi" in l or "İşlenen" in l])
import analiz; analiz.main()
