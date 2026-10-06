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


def _list(name):
    return [m.strip() for m in os.getenv(name, "").split(",") if m.strip()]


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
# Testnet öğrenme modu: para sahte olduğu için eşikler bilinçli olarak gevşetilir ki işlem örnekleri biriksin.
#   - rejim puan eşikleri 1 düşük (en az 7), ikinci görüş güveni 50, hacim/listeleme sinyalleriyle alım açık
# Gerçek hesapta (TEST_MODE=False) hiçbir zaman devreye girmez.
TESTNET_OGRENME = _bool("TESTNET_OGRENME", True)
LEARNING = TEST_MODE and TESTNET_OGRENME
# False yapılırsa bot sadece analiz + Telegram yapar, hiç emir göndermez.
TRADE_ENABLED = _bool("TRADE_ENABLED", True)

# Rapor ve CSV'lerdeki saatler bu saat dilimine göre yazılır (sunucu UTC olsa bile).
TIMEZONE = os.getenv("BOT_TIMEZONE", "Europe/Istanbul")

# ==========================================
# GEMINI
# ==========================================
# Boş bırakılırsa bot, anahtarın erişebildiği en yeni "flash" ve "flash-lite" modellerini otomatik seçer.
# Elle model yazılırsa önce onlar denenir. 503/429 gelirse sıradaki modele geçilir.
GEMINI_MODELS = _list("GEMINI_MODELS")
GEMINI_RETRIES_PER_MODEL = _int("GEMINI_RETRIES_PER_MODEL", 2)
# İkinci görüş ve gece raporu için güçlü modeller. Boşsa en yeni "pro" modeller otomatik seçilir.
REVIEW_MODELS = _list("REVIEW_MODELS")
# Alım adayları ikinci bir modele "şeytanın avukatı" olarak sorulsun mu?
REVIEW_ENABLED = _bool("REVIEW_ENABLED", True)
# ikinci görüşün güveni (0-100) en az bu olmalı (öğrenme modunda 50)
REVIEW_MIN_CONFIDENCE = _float("REVIEW_MIN_CONFIDENCE", 50 if LEARNING else 60)

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
# BTC REJİMİ (piyasa ortamı)
# ==========================================
# BTC'nin son 24 saat / 4 saat / 1 saatlik değişimine göre 5 kademe:
REGIME_STRONG_BULL_24H = _float("REGIME_STRONG_BULL_24H", 4.0)   # 24s >= +%4 (ve 4s >= 0) -> Çok boğa
REGIME_BULL_24H = _float("REGIME_BULL_24H", 1.5)                 # 24s >= +%1.5 -> Boğa
REGIME_FLAT_24H = _float("REGIME_FLAT_24H", -2.0)                # 24s > -%2 -> Yatay / hafif düşüş
REGIME_CRASH_24H = _float("REGIME_CRASH_24H", -5.0)              # 24s <= -%5 -> Çok düşüş
REGIME_CRASH_1H = _float("REGIME_CRASH_1H", -2.0)                # 1s <= -%2 (ani çöküş) -> Çok düşüş
REGIME_CHECK_MIN = _float("REGIME_CHECK_MIN", 5)                 # kaç dakikada bir hesaplansın

# min_score: alım için gereken en düşük puan | alloc: tutar çarpanı
# exit: "trailing" = izleyen stop (sabit hedef yok), "fixed" = küçük sabit kâr al
# hold_mult: maksimum bekleme süresi çarpanı
REGIMES = {
    "COK_BOGA":  {"ad": "🚀 Çok boğa", "min_score": 7, "alloc": 1.3, "exit": "trailing", "hold_mult": 2.0},
    "BOGA":      {"ad": "📈 Boğa", "min_score": 7, "alloc": 1.0, "exit": "trailing", "hold_mult": 1.0},
    "YATAY":     {"ad": "➖ Yatay / hafif düşüş", "min_score": 8, "alloc": 0.7, "exit": "fixed", "hold_mult": 1.0},
    "DUSUS":     {"ad": "📉 Düşüş", "min_score": 9, "alloc": 0.5, "exit": "fixed", "hold_mult": 1.0},
    "COK_DUSUS": {"ad": "🩸 Çok düşüş", "min_score": 10, "alloc": 0.4, "exit": "fixed", "hold_mult": 1.0},
}

# ==========================================
# İŞLEM / RİSK
# ==========================================
BUY_MIN_SCORE = _float("BUY_MIN_SCORE", 7)             # Rejim ne olursa olsun bunun altı asla alınmaz
# Botun kullanacağı sanal bütçe. Testnet hesabında 10.000 USDT olsa bile bot sadece bu kadarını kullanır.
BUDGET_USDT = _float("BUDGET_USDT", 100)
MIN_TRADE_USDT = _float("MIN_TRADE_USDT", 11)          # Binance min. işlem ~5-10$, üstünde pay bırakıldı
MAX_TRADE_USDT = _float("MAX_TRADE_USDT", 50)
MAX_OPEN_POSITIONS = _int("MAX_OPEN_POSITIONS", 5)
# Her pozisyonda borsaya girilen zarar kes. Ne olursa olsun alım fiyatının bu kadar altında satılır.
# (Eski STOP_LOSS_PCT ayarı artık kullanılmıyor.)
HARD_STOP_PCT = _float("HARD_STOP_PCT", 2.0)
# Stop-limit emrinin limit fiyatı stop fiyatının bu kadar altına konur (hızlı düşüşte dolması için)
STOP_LIMIT_GAP_PCT = _float("STOP_LIMIT_GAP_PCT", 0.8)
# Time-stop: alımdan bu kadar dakika sonra kâr bu yüzdenin altındaysa pozisyon kapatılır (sadece 7-8 puan)
TIME_STOP_MIN = _float("TIME_STOP_MIN", 20)
TIME_STOP_MIN_PROFIT = _float("TIME_STOP_MIN_PROFIT", 0.5)
# Açık pozisyonlar kaç saniyede bir kontrol edilsin (izleyen stop ve time-stop için)
MONITOR_SECONDS = _int("MONITOR_SECONDS", 10)
# İzleyen stop borsada en az bu kadar % yukarı taşınabilecekse güncellenir (gereksiz emir trafiği olmasın)
TRAIL_UPDATE_MIN_PCT = _float("TRAIL_UPDATE_MIN_PCT", 0.2)
# Aynı coinde pozisyon kapandıktan sonra tekrar girmeden önce beklenecek süre
COIN_COOLDOWN_MIN = _float("COIN_COOLDOWN_MIN", 60)

# Puana göre strateji:
#   hold_min   : maksimum bekleme (dakika, rejim çarpanıyla çarpılır)
#   trail_act  : izleyen stopun devreye girdiği kâr (%)
#   trail_dist : izleyen stopun zirveden uzaklığı (%)
#   tp_fixed   : temkinli rejimlerde (yatay/düşüş) sabit kâr al hedefi (%)
#   alloc      : bütçeden ayrılacak pay (rejim çarpanıyla çarpılır)
#   time_stop  : 20 dk kuralı uygulansın mı
SCORE_RULES = {
    7:  {"hold_min": _float("HOLD_MIN_7", 45),  "trail_act": 1.5, "trail_dist": 1.0,
         "tp_fixed": _float("TP_FIXED_7", 1.5), "alloc": 0.25, "time_stop": True},
    8:  {"hold_min": _float("HOLD_MIN_8", 120), "trail_act": 2.0, "trail_dist": 1.2,
         "tp_fixed": _float("TP_FIXED_8", 2.0), "alloc": 0.35, "time_stop": True},
    9:  {"hold_min": _float("HOLD_MIN_9", 240), "trail_act": 3.0, "trail_dist": 1.5,
         "tp_fixed": _float("TP_FIXED_9", 3.0), "alloc": 0.50, "time_stop": False},
    10: {"hold_min": _float("HOLD_MIN_10", 480), "trail_act": 3.0, "trail_dist": 1.5,
         "tp_fixed": _float("TP_FIXED_10", 4.0), "alloc": 0.60, "time_stop": False},
}

# ==========================================
# ALTERNATİF SİNYALLER (hacim tarayıcı + borsa listeleme duyuruları)
# ==========================================
# Hacim tarayıcı: dakikada bir tüm USDT çiftleri taranır (tek istek). 15 dk'da fiyatı SCAN_MIN_MOVE_PCT
# kadar yükselen VE hacmi önceki saatin SCAN_VOL_RATIO katına çıkan coinler işaretlenir.
SCANNER_ENABLED = _bool("SCANNER_ENABLED", True)
SCAN_SECONDS = _int("SCAN_SECONDS", 60)
SCAN_WINDOW_MIN = _int("SCAN_WINDOW_MIN", 15)
SCAN_MIN_MOVE_PCT = _float("SCAN_MIN_MOVE_PCT", 2.0)
SCAN_VOL_RATIO = _float("SCAN_VOL_RATIO", 3.0)
SCAN_MIN_VOL_USDT = _float("SCAN_MIN_VOL_USDT", 50000)     # son 15 dk en az bu kadar işlem hacmi
SCAN_MAX_CANDIDATES = _int("SCAN_MAX_CANDIDATES", 8)       # her taramada hacmine bakılan en fazla coin
SCAN_ALERT_COOLDOWN_MIN = _float("SCAN_ALERT_COOLDOWN_MIN", 60)
SCAN_NEWS_LOOKBACK_H = _float("SCAN_NEWS_LOOKBACK_H", 6)   # hacim patlamasıyla eşleştirilecek haberlerin yaşı
SCAN_NOTIFY_ALL = _bool("SCAN_NOTIFY_ALL", False)          # False: sadece haberle eşleşenler Telegram'a gider
# Upbit / Coinbase / Binance listeleme duyuruları
ANNOUNCEMENTS_ENABLED = _bool("ANNOUNCEMENTS_ENABLED", True)
# False: bu sinyaller sadece Telegram'a bildirilir ve kalibrasyona kaydedilir (ilk hafta böyle kalsın).
# True: haberle eşleşen hacim patlamaları ve listelemeler, ALT_SIGNAL_SCORE puanlı haber gibi alım sürecine girer.
ALT_SIGNALS_TRADE = _bool("ALT_SIGNALS_TRADE", LEARNING)
ALT_SIGNAL_SCORE = _float("ALT_SIGNAL_SCORE", 8)
# Hacim patlamaları Gemini'ye "arkasında gerçek bir hikâye var mı?" diye sorulur
SPIKE_AI_ENABLED = _bool("SPIKE_AI_ENABLED", True)
SPIKE_AI_MIN_SCORE = _float("SPIKE_AI_MIN_SCORE", 7)        # Gemini'nin hikâye gücü puanı en az bu olmalı
SPIKE_AI_MAX_PER_HOUR = _int("SPIKE_AI_MAX_PER_HOUR", 30)   # maliyet sınırı
# Gemini'nin onayladığı hacim patlamalarına ikinci görüş sorulmaz (veri: ikinci görüş 6/6 reddetti, 4'ü +%2'yi geçti;
# hacim yorumunu yapan Gemini zaten 24 saatlik yükselişi ve haberleri görüyor)
SPIKE_SKIP_REVIEW = _bool("SPIKE_SKIP_REVIEW", True)
# Listeleme hızlı yolu: Upbit/Coinbase listelemeleri ve resmi, birinci lig listeleme haberleri (puan >= 9)
# ikinci görüş beklemeden alınır; "tren kaçtı" sınırı %3 yerine LISTING_MAX_LATE_PCT, çıkış izleyen stopla.
# (veri: NMR Upbit listelemesi haberde +%27'deydi, sonra 1 saatte +%24,5 daha gitti)
LISTING_FAST_PATH = _bool("LISTING_FAST_PATH", True)
LISTING_MAX_LATE_PCT = _float("LISTING_MAX_LATE_PCT", 30)
LISTING_SCORE = _float("LISTING_SCORE", 10)                 # borsa duyurusundan gelen listelemenin puanı
UPBIT_POLL_SECONDS = _int("UPBIT_POLL_SECONDS", 20)

# ==========================================
# PİYASA NABZI (trend radarı)
# ==========================================
# Her saat: CoinGecko trend coin/sektörler + Korku&Açgözlülük + Binance en çok yükselenler + hacim patlamaları
# + haber yoğunluğu -> Gemini yorumu ve izleme listesi. İzleme listesindeki coinlerin haberlerine puan bonusu.
PULSE_ENABLED = _bool("PULSE_ENABLED", True)
PULSE_MINUTES = _float("PULSE_MINUTES", 60)
PULSE_NOTIFY_HOURS = _float("PULSE_NOTIFY_HOURS", 4)       # Telegram'a kaç saatte bir özet gelsin (0 = hiç)
PULSE_SCORE_BONUS = _float("PULSE_SCORE_BONUS", 1)         # izleme listesindeki coin haberine eklenecek puan
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY", "")     # isteğe bağlı (ücretsiz "demo" anahtarı)

# ==========================================
# TELEGRAM HABER KANALLARI (isteğe bağlı, my.telegram.org'dan API anahtarı gerekir)
# ==========================================
TG_API_ID = _int("TG_API_ID", 0)
TG_API_HASH = os.getenv("TG_API_HASH", "")
TG_NEWS_CHANNELS = _list("TG_NEWS_CHANNELS") or [
    "WatcherGuru",            # Watcher.Guru: en hızlı genel kripto/makro manşetler ("JUST IN")
    "TreeNewsFeed",           # Tree News: borsa duyuruları + 2000+ X hesabından süzülmüş manşetler
    "BWEnews",                # BWEnews: çok hızlı, Asya borsaları ve listelemeler
    "wublockchainenglish",    # Wu Blockchain: az ama kaliteli, Asya/madencilik/zincir üstü
    "binance_announcements",  # Binance resmi duyurular (listeleme, yeni çiftler)
]
TG_POLL_SECONDS = _int("TG_POLL_SECONDS", 30)

# ==========================================
# RAPORLAMA
# ==========================================
SUMMARY_MINUTES = _float("SUMMARY_MINUTES", 20)
REPORT_HOUR = _int("REPORT_HOUR", 23)                  # Gece raporu saati (BOT_TIMEZONE'a göre)
REPORT_MINUTE = _int("REPORT_MINUTE", 0)
REPORT_AI = _bool("REPORT_AI", True)                   # Gece raporuna yapay zeka yorumu eklensin mi

DATA_DIR = os.getenv("DATA_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
os.makedirs(DATA_DIR, exist_ok=True)
