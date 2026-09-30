"""Tüm ayarlar burada. Hepsi env.sh üzerinden değiştirilebilir, kod içine dokunmaya gerek yok."""
import os


def _bool(name, default):
    val = os.getenv(name)
    if val is None or val.strip() == "":
        return default
    return val.strip().lower() in ("1", "true", "yes", "evet", "on")


def _float(name, default):
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return float(default)


def _int(name, default):
    try:
        return int(float(os.getenv(name, default)))
    except ValueError:
        return int(default)


# ==========================================
# API ANAHTARLARI
# ==========================================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_SECRET = os.getenv("BINANCE_SECRET", "")

# TEST_MODE=True -> Binance Spot Testnet (sahte para). False -> GERÇEK hesap.
TEST_MODE = _bool("TEST_MODE", True)
# False yapılırsa bot sadece analiz + Telegram yapar, hiç emir göndermez.
TRADE_ENABLED = _bool("TRADE_ENABLED", True)

# ==========================================
# GEMINI
# ==========================================
# Sırayla denenir: ilki 503/429 verirse bir sonrakine geçilir. Buradakiler erişilebilir değilse
# bot, anahtarın erişebildiği en yeni "flash" ve "flash-lite" modellerini otomatik seçer.
GEMINI_MODELS = [m.strip() for m in os.getenv(
    "GEMINI_MODELS", "gemini-2.5-flash,gemini-2.5-flash-lite").split(",") if m.strip()]
GEMINI_RETRIES_PER_MODEL = _int("GEMINI_RETRIES_PER_MODEL", 3)

# ==========================================
# HABER TAKİBİ
# ==========================================
POLL_SECONDS = _int("POLL_SECONDS", 60)                # RSS kaç saniyede bir taransın
MAX_NEWS_AGE_MIN = _float("MAX_NEWS_AGE_MIN", 20)      # Bundan eski haberler analiz edilmez
MAX_ANALYSES_PER_CYCLE = _int("MAX_ANALYSES_PER_CYCLE", 12)
# Haber yayınlandıktan sonra fiyat zaten bu kadar % yükseldiyse "tren kaçtı" -> alım yok
LATE_MOVE_PCT = _float("LATE_MOVE_PCT", 3.0)
NOTIFY_MIN_SCORE = _float("NOTIFY_MIN_SCORE", 5)       # Bu puanın altındaki PASS'ler Telegram'a gitmez

# ==========================================
# İŞLEM / RİSK
# ==========================================
BUY_MIN_SCORE = _float("BUY_MIN_SCORE", 7)
# Botun kullanacağı sanal bütçe. Testnet hesabında 10.000 USDT olsa bile bot sadece bu kadarını kullanır.
BUDGET_USDT = _float("BUDGET_USDT", 100)
MIN_TRADE_USDT = _float("MIN_TRADE_USDT", 11)          # Binance min. işlem ~5-10$, üstünde pay bırakıldı
MAX_TRADE_USDT = _float("MAX_TRADE_USDT", 50)
MAX_OPEN_POSITIONS = _int("MAX_OPEN_POSITIONS", 5)
# Felaket stopu. 0 yapılırsa hiç zarar kesilmez, sadece kâr al emri girilir.
STOP_LOSS_PCT = _float("STOP_LOSS_PCT", 6)
# Süre dolduğunda en az bu kadar kârdaysa satar (komisyonu karşılasın diye). Zararda asla süre-satışı yapmaz.
MIN_EXIT_PROFIT_PCT = _float("MIN_EXIT_PROFIT_PCT", 0.4)
# Aynı coinde pozisyon kapandıktan sonra tekrar girmeden önce beklenecek süre
COIN_COOLDOWN_MIN = _float("COIN_COOLDOWN_MIN", 60)

# Puana göre strateji: kâr hedefi (%), maksimum bekleme (saat), bütçeden ayrılacak pay
TIERS = {
    7:  {"tp": _float("TP_7", 2.0),  "hold_h": _float("HOLD_7", 3),   "alloc": 0.25},
    8:  {"tp": _float("TP_8", 3.5),  "hold_h": _float("HOLD_8", 8),   "alloc": 0.35},
    9:  {"tp": _float("TP_9", 6.0),  "hold_h": _float("HOLD_9", 24),  "alloc": 0.50},
    10: {"tp": _float("TP_10", 10.0), "hold_h": _float("HOLD_10", 48), "alloc": 0.60},
}

# ==========================================
# RAPORLAMA
# ==========================================
SUMMARY_MINUTES = _float("SUMMARY_MINUTES", 20)

DATA_DIR = os.getenv("DATA_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
os.makedirs(DATA_DIR, exist_ok=True)
