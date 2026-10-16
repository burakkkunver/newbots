import os, sys, shutil
from types import SimpleNamespace as N
SP = os.path.dirname(os.path.abspath(__file__)); DATA = os.path.join(SP, "data_check"); shutil.rmtree(DATA, ignore_errors=True)
os.environ.update(DATA_DIR=DATA, TELEGRAM_BOT_TOKEN="x", TELEGRAM_CHAT_ID="1", GEMINI_API_KEY="k", BINANCE_API_KEY="a", BINANCE_SECRET="b")
sys.path.insert(0, os.path.dirname(SP)); sys.path.insert(0, SP)
import sim as S, time
time.sleep = lambda s: None
s = S.Sim(); S.install(s)
import notify; notify.send_telegram = lambda m: True
import ai as A
FACTS = '{"hedef_coin":"BONK","olay_turu":"listeleme","kesinlik":"resmi","yenilik":"yeni","aktor":"birinci_lig","olcek":"orta","coin_ozel":true,"fiyat_zaten_hareket_etti":false,"yon":"olumlu","sebep":"Coinbase listeledi"}'
class M:
    def list(self): return [N(name="models/"+n, supported_actions=["generateContent"]) for n in ["gemini-3.5-flash","gemini-3.5-flash-lite","gemini-3.1-pro-preview"]]
    def generate_content(self, model, contents, config):
        txt = FACTS if "Görevin PUAN VERMEK" in contents else '{"karsi_nedenler":["x"],"onay":true,"guven":65,"sebep":"ok"}'
        return N(text=txt, usage_metadata=N(prompt_token_count=800, candidates_token_count=100, thoughts_token_count=50))
A.genai.Client = lambda api_key: N(models=M())
import check
check.send_telegram = notify.send_telegram
import news
news.NewsFeed._fetch_one = lambda self, name, url: (name, [1, 2])
check.step("Telegram", lambda: check.send_telegram("x") or "gönderilemedi")
check.step("Gemini", check.gemini)
check.step("Binance", check.binance)
check.step("BTC rejimi", check.regime)
check.step("RSS", check.rss)
