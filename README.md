# Kripto Haber → Gemini → Binance Botu

Kurulum için: **[KURULUM.md](KURULUM.md)**

## Nasıl çalışır?
1. **Haber (RSS, kotasız):** 10 kaynak (Cointelegraph, CoinDesk, Decrypt, The Block, NewsBTC…) her 60 sn'de paralel taranır.
   Sadece son **20 dk** içinde yayınlanmış ve daha önce görülmemiş haberler işlenir; en yeni haber önce. Aynı haber farklı sitelerde çıkarsa bir kez analiz edilir.
2. **Gemini analizi:** `gemini-2.5-flash` (düşünme kapalı → hızlı ve ucuz). 503/429 gelirse 2-4-8 sn bekleyip tekrar dener, olmazsa `gemini-2.5-flash-lite`'a geçer. Başarısız haber kaybolmaz, sonraki turda tekrar denenir.
3. **Geç kalma filtresi:** Haber yayınlandığı dakikadaki **gerçek** Binance fiyatı ile şimdiki fiyat karşılaştırılır. Fiyat zaten %3'ten fazla yükselmişse alım yapılmaz ("tren kaçtı").
4. **Puana göre işlem** (`puan ≥ 7` ve `karar = BUY`):

| Puan | Kâr al | Maks. bekleme | Bütçeden pay |
|---|---|---|---|
| 7 | %2 | 3 saat | %25 |
| 8 | %3.5 | 8 saat | %35 |
| 9 | %6 | 24 saat | %50 |
| 10 | %10 | 48 saat | %60 |

   - Market alım → hemen **OCO** (kâr al + %6 felaket stopu). `STOP_LOSS_PCT=0` ile stop tamamen kapatılabilir.
   - Süre dolunca **sadece kârdaysa** (≥ %0.4) satar. Zarardaysa satmaz, kâra geçmesini bekler.
   - Bakiye minimum işlem tutarına (11 $) yetmiyorsa yeni pozisyon açılmaz. Aynı coinde ikinci pozisyon açılmaz.
5. **Telegram:** sinyaller, açılan/kapanan işlemler, her 20 dk'da bir özet. `/durum` komutu anlık özet verir.

## Dosyalar
- `bot.py` ana döngü · `news.py` RSS · `ai.py` Gemini · `trader.py` işlem/pozisyon · `binance_api.py` Binance REST · `config.py` ayarlar
- `check.py` kurulum testi · `start.sh` başlatıcı · `env.sh.example` ayar şablonu
- `data/` → `trades.csv`, `signals.csv`, `positions.json`, `bot.log` (otomatik oluşur)
