# Proje devir notu: Kripto Haber → Gemini → Binance botu

Bu dosya, projeye yeni başlayan Claude oturumunun önceki sohbetlerde konuşulanları bilmesi için yazıldı.
Son güncelleme: 16 Ekim 2026.

## 1. Kullanıcıyla çalışma kuralları (önemli)

- **Dil:** Türkçe yaz, sade ve kısa. Kullanıcı Telegram'da "Nefer" adını kullanıyor.
- **Kod değişikliğinden önce mutlaka danış.** Kullanıcı bunu açıkça istedi. Önce ne yapmayı düşündüğünü anlat, onay gelince yaz.
  - "Nasıl olur?", "ne önerirsin?" gibi sorular **onay değildir**. Öneri sun, onay bekle.
  - Belge ve ayar açıklaması gibi işlerde bile repoya bir şey göndermeden önce sor.
- **Geriye dönük test (backtest) istemiyor.** Ana odak grafik değil: haberleri ve trendleri takip edip yapay zekaya yorumlatmak ("piyasayı koklamak"). Grafikler ikincil.
- **Yapay zeka bütçesi:** en fazla ~200 TL/ay. Başka bir yapay zeka önerilecekse de bu sınır geçerli.
- **Güvenlik:** Büyük güvenlik önlemi istemiyor (50-100 $ ile başlayacak, şu an testnet). Ama `env.sh` içindeki anahtarlar ve `data/tg_news.session` asla repoya girmez, hiçbir yere yazılmaz.
- **Hedef:** Ayda en az %3 getiri kullanıcı için yeterli.
- **Akış:** Kullanıcı sunucudaki çıktıları ve `/dosyalar` ile gelen CSV'leri gönderir. Önce veriyi analiz et, sonra öneri sun.

## 2. Ortam

- **Repo:** `burakkkunver/newbots` (private).
- **Branch:** Bütün kod şu an `claude/crypto-news-bot-gemini-binance-j89q1k` dalında. Sunucu da bu dalı çekiyor. (Ana dala birleştirilirse sunucunun da o dala geçmesi gerekir.)
- **Sunucu:** Ubuntu VPS, kullanıcı `ubuntu`, klasör `~/newbots`, Python venv (`venv/`), bot `screen` içinde `./start.sh` ile çalışıyor. Log: `data/bot.log` (sona ekleniyor).
- **Güncelleme adımları:** screen içinde Ctrl+C → `cd ~/newbots && git pull` → (gerekirse `source env.sh`) → `python3 check.py` → `./start.sh`.
- **`check.py`:** Bağlantı testi, emir göndermez. Bot dururken çalıştırılmalı (Telegram oturum dosyası kilitlenmesin).
- **`env.sh`:** Gitignore'da. Gerçek anahtarlar orada: Binance TESTNET, Gemini, Telegram bot token ve chat id, TG_API_ID/HASH. `TEST_MODE="True"`.
- **Gemini:** google-genai SDK, ücretli katman. Kullanıcı kredi yüklüyor; 7-12 Ekim arasında kredi bittiği için Gemini çalışmadı, sonra yeniden yükledi.
- **Testler:** `tests/` klasöründe çevrimdışı testler var (sahte Binance, Gemini, Gate.io/MEXC, Google News, CoinGecko; internet gerekmez). Çalıştırma: `bash tests/run_all.sh`. Her kod değişikliğinden sonra hepsi geçmeli, yeni özelliğe yeni test eklenmeli. Varsayılan bir ayar değişince eski setler o ayarı başlarındaki `os.environ.update(...)` satırında sabitler. Ayrıntı: `tests/README.md`.
- **Ağ:** Claude'un bulut ortamından Binance, Gate.io, MEXC ve Google News'e erişim yoktu. Gerçek doğrulama hep sunucuda `check.py` ile yapıldı.

## 3. Mimari (dosyalar)

- `bot.py`: Ana döngü. RSS → kural filtresi → Gemini olgu çıkarma → puan tablosu → BTC rejimi → ucuz kontroller → ikinci görüş → alım. Telegram komutları da burada.
- `news.py`: 10 RSS kaynağı, 20 dk yaş sınırı. `filters.py`: kural filtresi, coin eşleştirme (`NAME_MAP`, `title_mentions`).
- `ai.py`: Gemini.
  - Puanı Gemini vermez; Gemini olguları çıkarır, puanı sabit tablo hesaplar.
  - Amaca göre model zinciri: haber = flash-lite (`cheap`), hacim/nabız/rapor = flash (`main`), ikinci görüş = pro (`review`).
  - Sağlık takibi: art arda 5 hatada Telegram uyarısı (anahtar/kredi hatasında ilk hatada), düzelince mesaj, 6 hatada 5 dk mola.
  - Günlük bütçe `GEMINI_GUNLUK_BUTCE_USD=0.15`: %70'te nabız, %100'de hacim yorumu durur. Harcama `data/gemini_harcama.json`.
- `market.py`: 5 kademeli BTC rejimi.
- `trader.py`: Binance testnet alım ve çıkış emirleri. -%2 sabit stop borsada; izleyen stop; yatay ve düşüş rejimlerinde OCO ile sabit kâr al; 7-8 puanda 20 dk time-stop; puana göre süre sınırı. Gerçek fiyatla gölge K/Z (`gercek_*` sütunları).
- `paper.py` + `prices.py`: Sanal işlem.
  - Testnette olmayan coinler gerçek fiyatla (Binance data-api → Gate.io → MEXC) almış gibi yapılıp aynı kurallarla satılır. Ayrı 100 USDT sanal bütçe, ask/bid ve %0,1 komisyon.
  - "Ayna": her testnet alımının gerçek Binance fiyatıyla kopyası.
  - Komut `/sanal`, kayıt `data/sanal_islemler.csv`.
- `scanner.py`: Dakikada bir tüm USDT çiftleri taranır; 15 dk'da +%2 ve hacim 3x olunca hacim patlaması sayılır. Haberi veya trendi olmayan patlama Gemini'ye sorulmaz.
- `announcements.py`: Upbit (20 sn), Binance, Coinbase listeleme duyuruları.
- `tgnews.py`: Telethon ile seçili herkese açık Telegram kanalları. `tg_login.py` tek seferlik giriş.
- `pulse.py`: Piyasa Nabzı, 2 saatte bir.
  - Veri: CoinGecko trend ve sektörler, Korku&Açgözlülük, Binance yükselenler, hacim patlamaları, haber yoğunluğu.
  - Sonuç izleme listesi: listedeki coinin olumlu haberine +1 puan.
- `watchnews.py`: İzleme listesi haberleri. Her 30 dk'da bir nabız izleme listesi ve CoinGecko trend coinleri için Google News'te coine özel haber aranır. Yaş sınırı 3 saat, kaynak etiketi "İzleme haberi". Nabız haber sayımına karışmaz.
- `calibration.py`: Her sinyalden sonra fiyatın 15 dk / 1 saat / 4 saat sonucu ölçülür. Binance'te olmayan coinlerde sembol `XYZUSDT@gateio` biçiminde.
- `report.py`: 23:00 gece raporu ve yapay zeka yorumu. `analiz.py`: sunucuda tablo analizi.
- Rehberler: `KURULUM.md` (bölüm 0-11, 9.1-9.6), `README.md`, `env.sh.example`.

## 4. Strateji ayarları (özet)

- **Rejimler:**

  | Rejim | Min. puan | Tutar | Çıkış |
  |---|---|---|---|
  | Çok boğa | 7 | ×1,3 | izleyen stop, süre ×2 |
  | Boğa | 7 | ×1,0 | izleyen stop |
  | Yatay | 8 | ×0,7 | sabit kâr al |
  | Düşüş | 9 | ×0,5 | sabit kâr al |
  | Çok düşüş | 10 | ×0,4 | sabit kâr al |

  Testnet öğrenme modunda eşikler 1 düşük (en az 7).
- **Puana göre:**

  | Puan | Süre | İzleyen stop başlar / mesafe | Sabit kâr al |
  |---|---|---|---|
  | 7 | 45 dk | +%1,5 / %1 | +%1,5 |
  | 8 | 2 sa | +%2 / %1,2 | +%2 |
  | 9 | 4 sa | +%3 / %1,5 | +%3 |
  | 10 | 8 sa | +%3 / %1,5 | +%4 |

  Time-stop sadece 7-8 puanda.
- **Bütçe:** 100 USDT sanal; işlem başı en az 11, en fazla 50 USDT.
- **Hızlı yol:**
  - Upbit/Coinbase listelemeleri ve resmi, birinci lig listeleme haberleri (puan ≥9) ikinci görüşsüz alınır, "tren kaçtı" sınırı %30, çıkış izleyen stopla.
  - Gemini'nin onayladığı hacim patlamaları ikinci görüşsüz alınır.
- **"Tren kaçtı":** Haberden sonra fiyat %3 yükseldiyse normal haberlerde alım yok.

## 5. Veriden öğrenilenler

- **Normal RSS haberleri** 1 saatte neredeyse hiç fiyat oynatmıyor. 1-8 puanlı haberlerin hiçbiri 1 saatte +%2'ye ulaşmadı.
- **Upbit listelemeleri en güçlü sinyal:** n=4, 1 saatte ortalama +%16, 1 saatlik zirve ortalaması +%39. Ama çok oynak (GTC: +%73 zirve, -%27 dip).
- **İkinci görüş:** Kurumsal ve ETF haberlerinde haklı çıktı. Hacim patlamalarında fazla katıydı, bu yüzden onaylı patlamalarda kaldırıldı.
- **Hikâyesiz hacim patlamaları** yazı tura (~820 örnek, ortalama ≈0).
- **Tekrarlanan patlamalar** (48 saatte 2+): 4 saatlik ortalama getiri ≈0, daha yüksek zirve ama %60'ı -%3 de görüyor. Tek başına kazandırmıyor; arkasında hikâye olması lazım.
- **Testnet fiyatları küçük coinlerde güvenilmez.** RSR: testnet -%0,25 ile kapandı, aynı anda gerçek piyasa +%35'teydi. Ayna bunun için eklendi.
- **Gemini 7-12 Ekim arası kapalıydı** (kredi bitti). Eski kod bunu bildirmiyordu, artık uyarıyor. Eski düzende harcama günde ~1 $'dı (nabız pro modelle saatte bir çalışıyordu), şimdi bütçe sınırlı.
- **Kaçırılan fırsat örnekleri:**
  - STRK (+%85/hafta): tarayıcı 16 kez yakaladı ama Gemini kapalıydı. Hikâye haberi geç geldi ve yanlışlıkla ETH'ye atandı.
  - PYTH: BWEnews'te "DAO 100% Rule" haberi vardı, Gemini kapalı olduğu için işlenmedi.

## 6. Commit geçmişi (son)

- `8beb621`: Hızlı yol, gerçek piyasa gölge K/Z.
- `b0048a6`: Sanal işlem + ayna, Gemini sağlık uyarıları, amaca göre model, günlük bütçe, hacim kanıt filtresi, nabız 2 saatte bir flash, AI_YOK kaydı, Upbit "MARKET" düzeltmesi. (Bu tur kullanıcıya sormadan yapıldı; kullanıcı bundan sonra danışılmasını istedi.)
- `d25472e`: İzleme listesi haberleri (watchnews.py), kullanıcı onayıyla.
- Devir notu (bu dosya) ve `tests/` klasörü, kullanıcı onayıyla (hesap değişikliği öncesi).

## 7. Güncel durum (16 Ekim 2026)

- Sunucuda son kod çekildi, `check.py` temiz. Gemini, Gate.io, MEXC, Google News ve CoinGecko erişilebilir.
- **TreeNewsFeed ölü** (~14 gündür mesaj yok). Yerine `@ChannelPANews` önerildi. Kullanıcının `env.sh`'e şu satırı eklemesi gerekiyordu, son `check.py`'de henüz devrede değildi:
  `export TG_NEWS_CHANNELS="WatcherGuru,ChannelPANews,BWEnews,wublockchainenglish,binance_announcements"`
  Ekledikten sonra `source env.sh` yapmadan `check.py` eski listeyi gösterir.
- Bir sonraki adım: kullanıcı bir günlük gece raporunu ve `/dosyalar` çıktısını gönderecek. İzleme haberleri, sanal işlemler ve Gemini harcama dağılımına birlikte bakılacak.

## 8. Bekleyen öneriler (hepsi kullanıcı onayı bekliyor)

1. **Fiyat sayfası filtresi:** "price today", "live price", "to USD", "marketcap and chart" başlıkları Gemini'ye gitmeden elensin. İzleme haberlerinde görüldü.
2. **Nabız maliyeti:** `gemini-3.8-flash` düşünme ayarını (MINIMAL) reddediyor. Bot ayarsız deneyince model varsayılan olarak daha uzun düşünüyor; bir nabız ~0,010 $ tuttu. Seçenekler: nabzı lite modelle çalıştırmak, LOW düşünme ayarı denemek ya da nabzı 3-4 saatte bire çekmek. Bir günlük harcama verisine bakılıp karar verilecek.
3. **Bithumb listeleme takibi:** Kore'nin 2. büyük borsası, Upbit takibine benzer.
4. **Coin eşleştirme hatası:** `filters.extract_coin`, "Ethereum L2 Starknet..." başlığını ETH saydı. `NAME_MAP` sırasında "ethereum", "starknet"ten önce eşleşiyor.
5. **Hacim değerlendirmesine bağlam:** Gemini'ye coinin 48 saatteki patlama sayısı ve haftalık değişimi de gitsin.
6. **İleride:** Gate.io API ile gerçek işlem. Sanal işlem altyapısı buna hazırlık.

Kullanıcının reddettikleri: backtest betiği; hacim patlamasıyla tetiklenen ("çek") haber araması. Bunun yerine izleme listesiyle tetiklenen arama yapıldı.
