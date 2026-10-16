import os, sys, shutil
SP = os.path.dirname(os.path.abspath(__file__)); DATA = os.path.join(SP, "data_guard"); shutil.rmtree(DATA, ignore_errors=True)
os.environ.update(DATA_DIR=DATA, WATCH_NEWS_ENABLED="False", PAPER_ENABLED="False", SPIKE_AI_REQUIRE_EVIDENCE="False", TELEGRAM_BOT_TOKEN="x", TELEGRAM_CHAT_ID="1", GEMINI_API_KEY="k", BINANCE_API_KEY="a", BINANCE_SECRET="b", POLL_SECONDS="0")
sys.path.insert(0, os.path.dirname(SP)); sys.path.insert(0, SP)
import sim as S
s = S.Sim(); S.install(s)
import bot as B
sent = []; B.send_telegram = lambda m: sent.append(m) or True
class FakeAI(S.AIStub):
    chains = {"main": ["f"], "cheap": ["f"], "review": ["p"]}; stats = {"calls": 0, "errors": 0, "cost_usd": 0.0, "fallbacks": 0}; day = dict(stats); last_fatal_error = None
B.GeminiAnalyzer = FakeAI
bot = B.Bot(); bot.trader.startup()
n = {"c": 0}
def fetch():
    n["c"] += 1
    if n["c"] > 3: raise KeyboardInterrupt
    return []
bot.feed.fetch_fresh = fetch
bot.reporter.due = lambda: bot.trader.state.get("last_report") != B.today_str()
def boom(manual=False): raise RuntimeError("test hatası")
bot.reporter.run = boom
calls = {"n": 0}
def stop_after(wait=0):
    calls["n"] += 1
    if calls["n"] > 3: raise KeyboardInterrupt
bot.poll = lambda wait=0: None
try: bot.loop()
except KeyboardInterrupt: pass
print("hata mesajı sayısı:", sum("Gece raporu hazırlanamadı" in m for m in sent))
