import os, sys, shutil
SP = os.path.dirname(os.path.abspath(__file__)); DATA = os.path.join(SP, "data_nt"); shutil.rmtree(DATA, ignore_errors=True)
os.environ.update(DATA_DIR=DATA, WATCH_NEWS_ENABLED="False", PAPER_ENABLED="False", SPIKE_AI_REQUIRE_EVIDENCE="False", TELEGRAM_BOT_TOKEN="x", TELEGRAM_CHAT_ID="1", GEMINI_API_KEY="k", BINANCE_API_KEY="a", BINANCE_SECRET="b", TESTNET_OGRENME="False", SPIKE_AI_ENABLED="False", PULSE_ENABLED="False")
sys.path.insert(0, os.path.dirname(SP)); sys.path.insert(0, SP)
import sim as S; s = S.Sim(); S.install(s)
import bot as B, announcements as AN
sent = []; B.send_telegram = lambda m: sent.append(m) or True
class FakeAI(S.AIStub):
    chains = {"main": ["f"], "cheap": ["f"], "review": ["p"]}; stats = {"calls": 0, "errors": 0, "cost_usd": 0.0, "fallbacks": 0}; day = dict(stats); last_fatal_error = None
B.GeminiAnalyzer = FakeAI
bot = B.Bot(); bot.trader.startup()
t = "Binance Will Add 7 bStocks Tokenized Securities as Collateral Asset - 2026-10-03"
e = AN.parse_binance({"data": [{"id": 1, "code": "x", "title": t}]})[0]
bot.handle_listing(dict(e, source=AN.SRC_BINANCE, ts=S.fake_time()))
print("sembol:", e["tickers"], "| telegram mesajı:", len(sent), "| kalibrasyon:", len(bot.calib.pending))
