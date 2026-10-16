import os, sys, shutil, json
SP = os.path.dirname(os.path.abspath(__file__)); DATA = os.path.join(SP, "data_legacy"); shutil.rmtree(DATA, ignore_errors=True); os.makedirs(DATA)
os.environ.update(DATA_DIR=DATA, TELEGRAM_BOT_TOKEN="x", TELEGRAM_CHAT_ID="1", GEMINI_API_KEY="k", BINANCE_API_KEY="a", BINANCE_SECRET="b")
sys.path.insert(0, os.path.dirname(SP)); sys.path.insert(0, SP)
import sim as S, time
# Eski sürümün state.json formatı (score/mode/peak_pct yok)
json.dump({"realized_pnl": 1.2, "cooldown": {}, "closed": [{"symbol": "SOLUSDT", "pnl": 1.2, "pct": 3.4, "closed_at": time.time() - 60, "reason": "KÂR AL"}]},
          open(os.path.join(DATA, "state.json"), "w"))
s = S.Sim(); S.install(s)
import trader as T, report as R, market
T.send_telegram = lambda m: True
tr = T.Trader(); tr.startup()
from types import SimpleNamespace as N
rep = R.Reporter(tr, market.Market(tr.bx), N(day={"calls": 0, "errors": 0, "fallbacks": 0, "cost_usd": 0.0}, status_line=lambda: "✅ test",
  spend_line=lambda: "bugün $0.000"), N(feed_errors={}))
html, data = rep.build()
print([l for l in html.split("\n") if "SOLUSDT" in l or "Çıkış" in l])
print("kaydedilen eski kayıt:", json.load(open(os.path.join(DATA, "state.json")))["closed"][0])
print(tr.summary_text("test").split("\n")[7])
