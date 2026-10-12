# Kripto Haber → Gemini → Binance Botu

Kurulum için: **[KURULUM.md](KURULUM.md)**

## Nasıl çalışır?
1. **Haber (RSS, kotasız):** 10 kaynak (Cointelegraph, CoinDesk, Decrypt, The Block, NewsBTC…) her 60 sn'de paralel taranır.
   Sadece son **20 dk** içinde yayınlanmış, daha önce görülmemiş haberler işlenir; en yeni haber önce.
2. **Kural filtresi (ücretsiz):** Fiyat tahmini, teknik analiz, "could soar" türü spekülasyon, özet/reklam ve
   "fiyat zaten %X yükseldi" başlıkları Gemini'ye gönderilmeden elenir.
3. **Gemini olgu çıkarır, puanı kod hesaplar:** Gemini puan vermez. Haberin olay türünü, kesinliğini (resmi/söylenti),
   yeniliğini, aktörün büyüklüğünü ve ölçeğini söyler; puan sabit bir tablodan hesaplanır
   (ör. söylenti en fazla 6, zaten bilinen haber -2, coine özel değilse en fazla 6).
4. **BTC rejimi:** BTC'nin 24s / 4s / 1s değişimine göre 5 kademe:

| Rejim | Koşul | Min. puan | Tutar | Çıkış |
|---|---|---|---|---|
| 🚀 Çok boğa | 24s ≥ +%4 ve 4s ≥ 0 | 7 | ×1.3 | İzleyen stop, süre ×2 |
| 📈 Boğa | 24s +%1.5 – +%4 | 7 | ×1.0 | İzleyen stop |
| ➖ Yatay / hafif düşüş | 24s −%2 – +%1.5 | 8 | ×0.7 | Küçük sabit kâr al |
| 📉 Düşüş | 24s −%5 – −%2 | 9 | ×0.5 | Küçük sabit kâr al |
| 🩸 Çok düşüş | 24s ≤ −%5 veya 1s ≤ −%2 | 10 | ×0.4 | Küçük sabit kâr al |

5. **Ucuz kontroller → ikinci görüş:** Testnette var mı, bakiye yetiyor mu, haberden sonra fiyat %3'ten fazla kaçtı mı?
   Geçen adaylar güçlü bir modele (pro) "bu haber fiyatı neden yükseltmez?" diye sorulur; onay gelirse alınır.
6. **Çıkış kuralları:**

| Puan | Maks. süre | İzleyen stop başlar / mesafe | Sabit kâr al (temkinli rejim) | Time-stop |
|---|---|---|---|---|
| 7 | 45 dk | +%1.5 / %1.0 | +%1.5 | 20 dk'da +%0.5 altıysa çık |
| 8 | 2 saat | +%2 / %1.2 | +%2 | 20 dk'da +%0.5 altıysa çık |
| 9 | 4 saat | +%3 / %1.5 | +%3 | yok |
| 10 | 8 saat | +%3 / %1.5 | +%4 | yok |

   - Her pozisyonda borsaya **-%2 zarar kes** emri girilir (bot kapalıyken de çalışır).
   - İzleyen stopu bot 10 sn'de bir kontrol eder ve borsadaki stop emrini yukarı taşır.
   - Süre dolunca pozisyon kapatılır; izleyen stop aktifse kâr korunarak devam edilir.
7. **Alternatif sinyaller:**
   - **Hacim tarayıcı:** Dakikada bir tüm Binance USDT çiftleri tek istekle taranır. 15 dk'da +%2'den fazla yükselen
     ve hacmi önceki saatin 3 katına çıkan coinler işaretlenir; son 6 saatte o coinle ilgili haber varsa Telegram'a bildirilir.
   - **Listeleme duyuruları:** Upbit ve Binance duyuruları dakikada bir, Coinbase'in yeni çiftleri 5 dakikada bir kontrol edilir.
   - Testnet öğrenme modunda bu sinyallerle alım açık (`ALT_SIGNALS_TRADE`).
8. **Telegram haber kanalları (isteğe bağlı):** Watcher.Guru, Tree News, BWEnews, Wu Blockchain ve Binance duyuruları
   senin hesabınla okunur (sadece bu kanallar); haberler RSS ile aynı yoldan geçer ama dakikalar önce gelir.
9. **Piyasa Nabzı:** 2 saatte bir CoinGecko trendleri/sektörleri, Korku&Açgözlülük, Binance yükselenleri, hacim patlamaları ve
   haber yoğunluğu Gemini'ye yorumlatılır; izleme listesindeki coinlerin haberleri +1 puan alır. Haberi veya trendi olan
   hacim patlamaları Gemini'ye "gerçek hikâye var mı?" diye sorulur.
10. **Testnet öğrenme modu:** Testnette eşikler gevşek (işlem örnekleri birikmesi için); gerçek hesapta devre dışı.
    **Hızlı yol:** Listelemeler (Upbit/Coinbase/9-10 puanlı resmi listeleme haberi) ve Gemini onaylı hacim patlamaları
    ikinci görüş beklemeden alınır; listelemelerde "tren kaçtı" sınırı %30. Her işlemde gerçek piyasa K/Z'si de kaydedilir.
11. **Sanal işlemler:** Coin testnette yoksa bot onu almış gibi yapar, gerçek fiyatını (Binance gerçek piyasa → Gate.io → MEXC)
    takip eder ve aynı kurallarla satar. Her testnet alımının da gerçek Binance fiyatıyla bir "aynası" tutulur
    (testnet fiyatları küçük coinlerde gerçek piyasadan çok sapabiliyor). Ayrıntı: KURULUM.md 9.4.
12. **İzleme listesi haberleri:** Nabız izleme listesindeki ve CoinGecko trend listesindeki coinler için 30 dk'da bir
    Google News'te coine özel haber aranır (hacim patlamasını beklemeden); bulunanlar normal haber yolundan geçer.
    Ayrıntı: KURULUM.md 9.6.
13. **Gemini sağlığı ve bütçesi:** Gemini art arda hata verirse Telegram'a sebebiyle uyarı gelir; haberler ucuz lite modelle,
    pro model sadece ikinci görüşte. Günlük bütçe sınırı (varsayılan 0,15 $ ≈ 200 TL/ay). Ayrıntı: KURULUM.md 9.5.
14. **Kalibrasyon:** Analiz edilen her haberden sonra fiyatın 15 dk / 1 saat / 4 saat içinde ne yaptığı ölçülür (`data/calibration.csv`).
15. **Telegram:** sinyaller, işlemler, rejim değişimleri, 20 dk'da bir özet, her gün 23:00'te detaylı rapor + yapay zeka yorumu.
   Komutlar: `/durum`, `/rejim`, `/nabiz`, `/sanal`, `/kalibrasyon`, `/rapor`, `/dosyalar`, `/yardim`.

## Dosyalar
- `bot.py` ana döngü · `news.py` RSS · `filters.py` kural filtresi · `ai.py` Gemini · `market.py` BTC rejimi
- `scanner.py` hacim tarayıcı · `announcements.py` Upbit/Coinbase/Binance listeleme duyuruları
- `pulse.py` Piyasa Nabzı · `tgnews.py` Telegram kanal okuyucu · `tg_login.py` Telegram tek seferlik giriş
- `trader.py` alım/çıkış/pozisyon takibi · `binance_api.py` Binance REST · `calibration.py` ölçüm · `report.py` gece raporu
- `paper.py` sanal işlemler (testnette olmayan coinler + gerçek fiyat aynası) · `prices.py` Binance/Gate.io/MEXC gerçek fiyatları
- `watchnews.py` izleme listesi / trend coinleri için coine özel haber araması (Google News)
- `config.py` tüm ayarlar · `check.py` kurulum testi · `analiz.py` kalibrasyon analizi · `start.sh` başlatıcı
- `data/` → `signals.csv`, `calibration.csv`, `trades.csv`, `sanal_islemler.csv`, `positions.json`, `paper.json`,
  `gemini_harcama.json`, `watch_news.json`, `reports/`, `bot.log` (otomatik oluşur)
