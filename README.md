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
7. **Kalibrasyon:** Analiz edilen her haberden sonra fiyatın 15 dk / 1 saat / 4 saat içinde ne yaptığı ölçülür (`data/calibration.csv`).
8. **Telegram:** sinyaller, işlemler, rejim değişimleri, 20 dk'da bir özet, her gün 23:00'te detaylı rapor + yapay zeka yorumu.
   Komutlar: `/durum`, `/rejim`, `/kalibrasyon`, `/rapor`, `/dosyalar`, `/yardim`.

## Dosyalar
- `bot.py` ana döngü · `news.py` RSS · `filters.py` kural filtresi · `ai.py` Gemini · `market.py` BTC rejimi
- `trader.py` alım/çıkış/pozisyon takibi · `binance_api.py` Binance REST · `calibration.py` ölçüm · `report.py` gece raporu
- `config.py` tüm ayarlar · `check.py` kurulum testi · `analiz.py` kalibrasyon analizi · `start.sh` başlatıcı
- `data/` → `signals.csv`, `calibration.csv`, `trades.csv`, `positions.json`, `reports/`, `bot.log` (otomatik oluşur)
