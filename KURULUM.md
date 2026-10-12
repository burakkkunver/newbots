# 🛠️ Sunucuya (VPS) Kurulum Rehberi

Bu rehber, botu uzaktaki Ubuntu sunucuna sıfırdan kurmanı ve `screen` içinde 7/24 çalıştırmanı adım adım anlatır.
Komutları olduğu gibi kopyala-yapıştır yapabilirsin. `#` ile başlayan satırlar açıklamadır, çalıştırılmaz.

---

## 0. Başlamadan önce hazırda olması gerekenler

| Ne | Nereden |
|---|---|
| Sunucu IP adresi + kullanıcı adı + şifre/SSH anahtarı | VPS sağlayıcının paneli |
| **Binance TESTNET** API Key + Secret | https://testnet.binance.vision → GitHub ile giriş → *Generate HMAC_SHA256 Key* |
| Gemini API anahtarı | https://aistudio.google.com/apikey (faturalandırma açık olan projeden) |
| Telegram bot token + chat id | Zaten `env.sh` dosyanda var |

> ⚠️ Binance **gerçek** hesabın API anahtarı testnette çalışmaz, testnet anahtarı da gerçek hesapta çalışmaz. `TEST_MODE="True"` iken mutlaka testnet anahtarını kullan.

---

## 1. Sunucuya bağlan

**Windows (PowerShell veya CMD):**
```bash
ssh root@SUNUCU_IP
```
İlk bağlantıda `yes` yaz, sonra şifreni gir (yazarken ekranda görünmez, normaldir).

**Telefondan:** *Termius* uygulaması → New Host → IP, kullanıcı adı, şifre.

---

## 2. Eski botu durdur (varsa)

```bash
screen -ls                 # çalışan screen oturumlarını listeler
screen -r OTURUM_ADI       # eski bota bağlan
# Ctrl + C  -> eski botu durdurur
exit                       # screen oturumunu kapatır
```

Eski `env.sh` dosyanın yerini not et (ör. `/root/env.sh`). Anahtarları oradan alacağız.

---

## 3. Gerekli sistem paketlerini kur (sadece ilk seferde)

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git screen nano
```

Kontrol: `python3 --version` → 3.9 veya üstü olmalı.

---

## 4. Kodu sunucuya indir

Repo gizli (private) olduğu için GitHub şifre yerine **token** ister.

1. GitHub → sağ üst profil → **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**
2. *Repository access*: sadece `newbots` → *Permissions → Contents*: **Read-only** → oluştur, token'ı kopyala.
3. Sunucuda:

```bash
cd ~
git clone -b claude/crypto-news-bot-gemini-binance-j89q1k https://github.com/burakkkunver/newbots.git
cd newbots
```
Kullanıcı adı sorarsa GitHub kullanıcı adını, şifre sorarsa **token'ı** yapıştır.

> Alternatif (git istemezsen): Bilgisayarında GitHub'dan ZIP indir, **WinSCP** ile sunucuda `/root/newbots` klasörüne yükle.

---

## 5. Python sanal ortamı ve kütüphaneler (sadece ilk seferde)

```bash
cd ~/newbots
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
```

Bu 4 kütüphaneyi kurar: `google-genai` (Gemini), `feedparser` (RSS), `requests`, `telethon` (Telegram kanalları).
Başka hiçbir şey yüklemen gerekmez.

---

## 6. Ayar dosyasını (env.sh) hazırla

**Seçenek A – eski env.sh dosyanı kullan** (içi zaten dolu):
```bash
cp /root/env.sh ~/newbots/env.sh      # yolu kendi dosyanın yeriyle değiştir
nano ~/newbots/env.sh
```
- `CRYPTOCOMPARE_API_KEY` satırı artık gereksiz (silebilir veya bırakabilirsin, zararı yok).
- Daha önce `export STOP_LOSS_PCT="6"` satırını eklediysen **sil** (artık kullanılmıyor, stop sabit %2: `HARD_STOP_PCT`).
- İstersen şu satırları ekle:
```bash
export BUDGET_USDT="100"
export SUMMARY_MINUTES="20"
export REPORT_HOUR="23"
```

**Seçenek B – şablondan sıfırdan oluştur:**
```bash
cp env.sh.example env.sh
nano env.sh
```

nano'da kaydetmek: **Ctrl + O → Enter**, çıkmak: **Ctrl + X**.

Önemli ayarlar:

| Ayar | Anlamı |
|---|---|
| `TEST_MODE="True"` | Binance Testnet (sahte para). **Şimdilik böyle kalsın.** |
| `BUDGET_USDT` | Botun kullanacağı sanal bütçe. Testnet cüzdanında 10.000 $ olsa da bot sadece bu kadarıyla işlem yapar. |
| `HARD_STOP_PCT` | Her pozisyonda borsaya girilen zarar kes (%). Varsayılan 2. |
| `SUMMARY_MINUTES` | Telegram'a kaç dakikada bir özet gelsin. |
| `REPORT_HOUR` | Gece raporunun saati (Türkiye saati). Varsayılan 23. |
| `REVIEW_ENABLED` | Alım adaylarına güçlü modelden ikinci görüş. Varsayılan açık. |
| `SCANNER_ENABLED` / `ANNOUNCEMENTS_ENABLED` | Hacim tarayıcı / listeleme duyuruları. Varsayılan açık. |
| `ALT_SIGNALS_TRADE` | Bu iki kaynaktan gelen sinyallerle alım. Varsayılan **kapalı** (sadece bildirim + kayıt). |

Diğer tüm ayarlar (rejim eşikleri, puan kuralları, süreler) `config.py` içinde açıklamalı olarak duruyor.

---

## 7. Bağlantı testi (emir göndermez)

```bash
cd ~/newbots
source env.sh
source venv/bin/activate
python3 check.py
```

Beklenen çıktı:
```
✅ Telegram: True                -> Telegram'a "Kurulum testi" mesajı gelir
   Analiz: puan 9/10 (...)
   İkinci görüş [gemini-...-pro...]: ONAY/RED (güven ..)
✅ Gemini: tahmini maliyet $0.00..
✅ Binance: TESTNET | USDT: 10000.00 | ... | stop emri türü: ... | OCO: var
✅ BTC rejimi: 📈 Boğa (BTC 24s +2.1%, ...) -> alım için en az 7 puan, ...
✅ RSS: 10/10 kaynak çalışıyor
✅ Sanal işlem fiyat kaynakları: 3/3 kaynak çalışıyor
```

Gemini satırı ❌ verirse altında **son hata** ve ne yapman gerektiği yazar (kredi bitti, anahtar geçersiz, kota...).
Bir satır ❌ verirse aşağıdaki **Sorun Giderme** bölümüne bak. 1-2 RSS kaynağının ❌ olması sorun değil.

---

## 8. Botu screen içinde başlat

```bash
cd ~/newbots
screen -S haberbot
./start.sh
```

Telegram'a **"🚀 Kripto Haber Botu Başlatıldı"** mesajı gelmeli.

**Ekrandan ayrılmak (bot çalışmaya devam eder):** `Ctrl + A`, bırak, sonra `D`
Artık SSH'ı kapatabilirsin.

**Tekrar bota bakmak:**
```bash
screen -r haberbot
```

**Botu durdurmak:** screen içindeyken `Ctrl + C`.
> Bot durunca Binance'teki stop ve OCO emirleri silinmez, bekler (yani %2 zarar kes her zaman borsada durur).
> Bot yeniden başladığında pozisyonları `data/positions.json` dosyasından hatırlar ve takibe devam eder.
> Bot kapalıyken izleyen stop yukarı taşınamaz ve time-stop çalışamaz; bunlar bot açılınca devam eder.

---

## 9. Günlük kullanım

**Telegram komutları:**

| Komut | Ne yapar |
|---|---|
| `/durum` | Bakiye, açık pozisyonlar (stop/izleyen stop seviyesi, kalan süre), BTC rejimi |
| `/rejim` | BTC rejimi ve şu an geçerli alım kuralları |
| `/nabiz` | Piyasa Nabzı: sıcak anlatılar, izleme listesi (şimdi hazırlar) |
| `/sanal` | Sanal işlemler: testnette olmayan coinler ve testnet işlemlerinin gerçek fiyat aynası (9.4) |
| `/kalibrasyon` | Son 7 günde haberlerden sonra fiyat gerçekte ne yaptı (puan gruplarına göre) |
| `/rapor` | Gün sonu raporunu hemen hazırlar (normalde her gün 23:00'te otomatik gelir) |
| `/dosyalar` | Veri dosyalarını (CSV) ve son raporu Telegram'a dosya olarak gönderir |
| `/yardim` | Komut listesi |

**Sunucuda:**

| İş | Komut |
|---|---|
| Kalibrasyon analizi (tablo) | `cd ~/newbots && source venv/bin/activate && python3 analiz.py` |
| Son 7 günün analizi | `python3 analiz.py 7` |
| Log'un son 50 satırı | `tail -n 50 ~/newbots/data/bot.log` |
| Canlı log | `tail -f ~/newbots/data/bot.log` (çıkış: Ctrl + C) |
| Kapanan işlemler | `cat ~/newbots/data/trades.csv` |
| Sanal işlemler | `cat ~/newbots/data/sanal_islemler.csv` |
| Gemini hataları | `grep -E "GEMINI|Gemini .*(hata|kota)|bağlantı hatası" ~/newbots/data/bot.log \| tail -20` |
| Tüm sinyaller | `cat ~/newbots/data/signals.csv` |
| Açık pozisyonlar | `cat ~/newbots/data/positions.json` |

`trades.csv` ve `signals.csv` dosyalarını WinSCP ile bilgisayarına çekip Excel'de açabilirsin.

---

## 9.1 Kalibrasyon: puanlar gerçekten işe yarıyor mu?

Bot analiz ettiği **her** haberi ölçer: alınsın ya da alınmasın, PASS ve filtrelenenler dahil.
Sinyal anındaki gerçek Binance fiyatını kaydeder, 4 saat sonra 1 dakikalık mumlardan şunları hesaplar:

| Sütun | Anlamı |
|---|---|
| `r15dk`, `r1s`, `r4s` | Sinyalden 15 dk / 1 saat / 4 saat sonraki getiri (%) |
| `max1s`, `max4s` | O süre içindeki en yüksek nokta (%). Kâr al ve izleyen stop ayarı için. |
| `min1s`, `min4s` | O süre içindeki en düşük nokta (%). %2 stop gereğinden sık mı patlıyor, buradan görülür. |
| `btc_r1s`, `fark_r1s` | Aynı sürede BTC'nin getirisi ve coin ile BTC arasındaki fark. Haberin piyasadan bağımsız etkisi. |
| `yayindan_sinyale` | Haber yayınlandığı andan botun karar verdiği ana kadar fiyat ne kadar oynadı |

Sonuçlar `data/calibration.csv` dosyasında. Telegram'dan `/kalibrasyon` ile özetini, sunucuda `python3 analiz.py` ile
detaylı tabloyu (puana, olay türüne, rejime, kaynağa göre) görürsün.

**Hacim tarayıcı ve listeleme duyuruları** de aynı dosyaya kaydedilir (kaynak: "Hacim tarayıcı", "Upbit",
"Coinbase", "Binance duyuru"). Puan tablolarına karışmazlar; `/kalibrasyon` ve `analiz.py` bunları ayrı bölümde gösterir.
İlk hafta bu sinyallerle **alım yapılmaz**, sadece Telegram'a bildirim gelir. Veri iyi çıkarsa `env.sh`'e
`export ALT_SIGNALS_TRADE="True"` ekleyerek alımı açarız.

Telegram'a gelecek yeni mesajlar:
- `📡 HACİM PATLAMASI` — bir coin 15 dk'da +%2'den fazla yükseldi, hacmi 3 katına çıktı ve son 6 saatte onunla ilgili haber var.
- `📢 ... LİSTELEME DUYURUSU` — Upbit/Binance yeni listeleme duyurdu veya Coinbase yeni çift ekledi.

**1-2 hafta sonra bana göndermen gerekenler:** Telegram'a `/dosyalar` yaz. Gelen 4 dosyayı bana ilet:
`calibration.csv`, `signals.csv`, `trades.csv` ve son rapor. Bunlarla eşikleri, kâr al ve stop
seviyelerini tahminle değil verilerle ayarlarız.

---

## 9.2 Telegram haber kanalları (isteğe bağlı ama önerilir)

Watcher.Guru, Tree News, BWEnews gibi Telegram kanalları haberi RSS sitelerinden genelde **dakikalar önce** verir.
Bot bu kanalları **senin Telegram hesabınla** okur:
- **Sadece aşağıdaki listedeki** herkese açık kanalları okur. Özel sohbetlerin, grupların ve diğer kanallar okunmaz.
- Mesaj göndermez, kanallara katılmaz.

**Okunan kanallar (varsayılan):**

| Kanal | Neden |
|---|---|
| `@WatcherGuru` | En hızlı büyük kripto/makro manşet kanalı ("JUST IN") |
| `@TreeNewsFeed` | Borsa duyuruları + 2000'den fazla X hesabından süzülmüş manşetler |
| `@BWEnews` | Çok hızlı, Asya borsaları ve listelemeler |
| `@wublockchainenglish` | Wu Blockchain: az ama kaliteli; Asya, madencilik, zincir üstü |
| `@binance_announcements` | Binance resmi duyuruları (listeleme, yeni çiftler) |

Listeyi değiştirmek için `env.sh`'e şunu ekle: `export TG_NEWS_CHANNELS="WatcherGuru,TreeNewsFeed,BWEnews"`.

### Kurulum (bir kez, ~5 dakika)

1. **API anahtarı al:**
   - Bilgisayarından https://my.telegram.org adresine gir. Telefon numaranı uluslararası biçimde yaz (+905…).
   - Telegram uygulamana gelen kodu gir (SMS değil, Telegram içinde "Telegram" hesabından gelir).
   - **API development tools**'a tıkla. Formu doldur: App title: `newsbot`, Short name: `newsbot`, Platform: `Other`. Diğer alanlar boş kalabilir.
   - Çıkan **App api_id** (sayı) ve **App api_hash** (uzun yazı) değerlerini kopyala.

2. **env.sh'e ekle:**
```bash
nano ~/newbots/env.sh
# en alta ekle:
export TG_API_ID="12345678"
export TG_API_HASH="0123456789abcdef0123456789abcdef"
```

3. **Botu durdur ve giriş yap** (screen içinde Ctrl + C):
```bash
cd ~/newbots && source env.sh && source venv/bin/activate
pip install --upgrade pip setuptools wheel && pip install -r requirements.txt
python3 tg_login.py
```
   Sorular İngilizce gelir:
   - `Please enter your phone`: telefon numaran (+905…)
   - `Please enter the code you received`: Telegram uygulamana gelen kod
   - `Please enter your password`: sadece iki adımlı doğrulama (bulut şifresi) açıksa sorulur

   Sonunda her kanal için `✅ @WatcherGuru: son mesaj 2 dk önce` gibi satırlar görmelisin.

4. **Botu başlat:** `./start.sh`. Başlangıç mesajında "Telegram kanalları: @WatcherGuru, …" yazar.

> 🔐 **Güvenlik:** Giriş bilgisi `data/tg_news.session` dosyasında durur; bu dosya hesabına erişim sağlar, kimseyle paylaşma.
> İstediğin an iptal edebilirsin: Telegram → Ayarlar → Cihazlar → bu oturumu sonlandır.
> İstersen ikinci bir telefon numarasıyla açtığın ayrı bir Telegram hesabını da kullanabilirsin.
> `tg_login.py` ve `check.py`'yi bot **durdurulmuşken** çalıştır (aynı oturum dosyasını aynı anda iki program kullanamaz).

---

## 9.3 Piyasa Nabzı ve testnet öğrenme modu

**Piyasa Nabzı** 2 saatte bir piyasanın genel resmini toplar ve Gemini'ye yorumlatır:
- CoinGecko trend coinleri ve sektörleri
- Korku & Açgözlülük endeksi
- Binance'te en çok yükselenler
- hacim patlamaları
- haberlerde en çok adı geçen coinler

Sonuç bir **izleme listesi**:
- Listedeki coinlerin olumlu haberlerine **+1 puan** eklenir.
- "Uzak dur" listesindekilere **-1 puan** eklenir.
- Hacim patlaması değerlendirmesinde de bu bilgi kullanılır.

Kısa özet 4 saatte bir Telegram'a gelir. İstediğin an `/nabiz` yazabilirsin.

**Hacim patlamaları** Gemini'ye soruluyor: "Arkasında gerçek bir hikâye var mı?" Gemini'ye o coinin son 24 saatlik haberleri (Telegram dahil), trend bilgisi ve nabız yorumu gidiyor. Sadece onaylananlar Telegram'a gelir ve alım adayı olur. Hiç haberi olmayan, trendde ve izleme listesinde de olmayan patlamalar Gemini'ye sorulmaz (veride Gemini bunların neredeyse hepsini zaten reddetti; boşa maliyet).

**Testnet öğrenme modu** (testnette varsayılan açık): Para sahte olduğu için bot daha rahat alım yapar, böylece işlem örnekleri birikir:
- rejim eşikleri 1 puan düşük (en az 7)
- ikinci görüş güveni 50
- hacim ve listeleme sinyalleriyle alım açık

Kapatmak için `env.sh`'e `export TESTNET_OGRENME="False"` ekle. Gerçek hesapta (`TEST_MODE="False"`) bu mod hiçbir zaman devreye girmez.

**Hızlı yol** (verilere göre eklendi):
- **Listelemeler:** Upbit/Coinbase listeleme duyuruları ve resmi, birinci lig listeleme haberleri (puan 9-10) ikinci görüş beklemeden alınır. "Tren kaçtı" sınırı %3 yerine %30, çıkış izleyen stopla yapılır. Örnek: NMR'nin Upbit listelemesi haber anında +%27'deydi, sonra 1 saatte +%24,5 daha gitti.
- **Hacim patlamaları:** Gemini'nin "gerçek hikâye var" dediği hacim patlamalarına ikinci görüş sorulmaz. Örnek: ikinci görüş bunların 6'sını da reddetmişti, oysa 4'ü 1 saatte +%2'nin üstüne çıktı.
- **Haberler:** Normal haberlerde ikinci görüş aynen devam eder; veriler orada haklı olduğunu gösteriyor.

Kapatmak için: `export LISTING_FAST_PATH="False"` / `export SPIKE_SKIP_REVIEW="False"`.

**Gerçek piyasa K/Z'si:** Testnet fiyatları büyük coinlerde gerçek piyasayı takip ediyor, ama küçük coinlerin ani hareketlerinde farklı gidebilir. Bu yüzden her işlemde giriş ve çıkış anındaki gerçek Binance fiyatı da kaydedilir. Kapanış mesajında ve gece raporunda "Gerçek piyasada: +X%" satırı olarak, `trades.csv`'de `gercek_*` sütunları olarak görünür.

---

## 9.4 Sanal işlemler: gerçek fiyatla "almış gibi yap"

Sinyal gelen coin Binance testnette yoksa bot artık sinyali atmıyor:
- Coini **almış gibi yapar**, gerçek fiyatını takip eder ve testnetle **aynı kurallarla** satar (-%2 stop, izleyen stop / sabit kâr al, time-stop, süre).
- Gerçek fiyat şu sırayla aranır: **Binance gerçek piyasa → Gate.io → MEXC**. Hepsi anahtarsız, herkese açık fiyat servisleri.
- Para harcanmaz. Ayrı bir **sanal bütçe** (100 USDT) kullanılır, testnet bütçesine dokunulmaz.
- Telegram mesajları 🧪 ile başlar.

Örnek: Upbit, Binance'te olmayan bir coini listeledi → Gate.io fiyatıyla sanal alım → izleyen stopla sanal satış → sonuç `data/sanal_islemler.csv` dosyasına yazılır.

**Ayna (🪞):** Her testnet alımının bir kopyası da gerçek Binance fiyatlarıyla takip edilir. Testnette küçük coinlerin fiyatı gerçek piyasadan çok farklı gidebiliyor. Örnek: RSR testnette -%0,25 ile kapandı, aynı anda gerçek piyasada +%35'teydi. Stratejinin gerçek sonucunu ayna gösterir; gece raporu testnet ve ayna sonuçlarını yan yana yazar.

**Gerçekçilik için:**
- Alım satış fiyatından (ask), satış alış fiyatından (bid) yapılır.
- Her yönde %0,1 komisyon düşülür.
- Fiyat 20 sn'de bir kontrol edilir. Bu yüzden hızlı düşüşte çıkış, borsadaki gerçek bir stop emrinden biraz daha kötü yazılabilir; sonuçlar temkinli tarafta kalır.
- 24 saatlik hacmi 100 bin $'ın altındaki coinler sanal alınmaz (fiyatı güvenilir değil).

**Nereden takip edilir:**
- `/sanal`: açık sanal pozisyonlar, bugünkü ve son 7 günün sonuçları, fiyat kaynaklarının durumu
- `/durum`: sanal bütçe ve açık pozisyonlar
- Gece raporu: "Sanal işlemler" bölümü
- `/dosyalar`: `sanal_islemler.csv` dosyası da gelir
- `python3 analiz.py`: sanal işlemler tablosu

Kalibrasyon da artık Binance'te olmayan coinleri Gate.io / MEXC mumlarıyla ölçüyor. `calibration.csv`'nin sembol sütununda `XYZUSDT@gateio` gibi görünür.

**Ayarlar** (`env.sh`, hepsi isteğe bağlı):

| Ayar | Varsayılan | Ne yapar |
|---|---|---|
| `PAPER_ENABLED` | True | Sanal işlemleri açar / kapatır |
| `PAPER_MIRROR` | True | Testnet alımlarının gerçek fiyat aynası |
| `PAPER_BUDGET_USDT` | 100 | Sanal bütçe |
| `PAPER_MAX_OPEN` | 5 | En fazla açık sanal pozisyon |
| `PAPER_CHECK_SECONDS` | 20 | Fiyat kontrol sıklığı (sn) |
| `PAPER_FEE_PCT` | 0.1 | Her yöndeki komisyon (%) |
| `PAPER_MIN_VOL_USDT` | 100000 | En düşük 24 saatlik hacim ($) |
| `PAPER_VENUES` | binance,gateio,mexc | Fiyat kaynakları ve sırası |

`check.py`'nin "Sanal işlem fiyat kaynakları" satırı üç kaynağın sunucundan erişilebilir olduğunu gösterir. İleride Gate.io API anahtarı eklersek bu sanal işlemler gerçek emirlere dönüşebilir; altyapı hazır.

---

## 9.5 Gemini maliyeti ve "Gemini çalışmıyor" uyarısı

**Neden önemli:** Gemini 7 Ekim 12:40'tan beri hiç yanıt vermedi. O tarihten beri haber analizi, hacim yorumu ve nabız tamamen durdu, sadece listeleme hızlı yolu çalıştı. Eski sürüm bu durumu Telegram'a bildirmiyordu. Haberler de kayda geçmeden atlanıyordu, raporda "14 haberin 14'ü filtrelendi" görünmesinin sebebi buydu.

**Artık:**
- Gemini art arda 5 kez yanıt vermezse Telegram'a **gerçek hata mesajı ve ne yapman gerektiğiyle** birlikte uyarı gelir. Anahtar veya kredi hatası gibi kalıcı sorunlarda uyarı ilk hatada gelir.
- Gemini düzelince "✅ Gemini tekrar çalışıyor" mesajı gelir.
- Art arda 6 hatada bot Gemini'ye 5 dk mola verir; döngü boşuna beklemez.
- `/durum` ve gece raporunda Gemini durumu (son başarılı yanıt veya son hata) ve harcama yazar.
- Gemini'nin analiz edemediği haberler `AI_YOK` koduyla kaydedilir.
- Model listesi 6 saatte bir kendiliğinden yenilenir.

**Maliyet kontrolü:**

| İş | Model | Sıklık |
|---|---|---|
| Haber olguları | flash-lite (en ucuz) | her haber |
| Hacim patlaması yorumu | flash | sadece son 24 saatte haberi olan, trend veya izleme listesindeki coinler, saatte en fazla 12 |
| Piyasa Nabzı | flash (eskiden pro) | 2 saatte bir (eskiden saatte bir) |
| İkinci görüş | pro | sadece tüm kontrolleri geçen haber adayları |
| Gece raporu | flash | günde 1 |

**Günlük bütçe:** `GEMINI_GUNLUK_BUTCE_USD` (varsayılan 0,15 $ ≈ 200 TL/ay). Tahmini harcama:
- bütçenin %70'ine gelince Piyasa Nabzı,
- %100'üne gelince hacim yorumu gece yarısına kadar durur.
- Haber analizi, ikinci görüş ve gece raporu devam eder.

Harcama diske yazılır, botu yeniden başlatmak bütçeyi sıfırlamaz. Rapordaki "Dağılım" satırı paranın hangi işe gittiğini gösterir. TL karşılığı `USD_TRY` (varsayılan 45) ile hesaplanır.

**Kredini kontrol et:** aistudio.google.com → **Billing** (Faturalandırma) sayfası: kalan kredi ve projenin ücretli katmanda olup olmadığı. Kullanım: aistudio.google.com/usage. Bot "tahmini" harcamayı kendi hesaplar; kesin rakam AI Studio'dadır.

---

## 10. Kod güncellendiğinde

```bash
screen -r haberbot        # bota bağlan
# Ctrl + C ile durdur
cd ~/newbots
git pull
source venv/bin/activate && pip install -r requirements.txt
./start.sh
# Ctrl + A, D ile ayrıl
```

`env.sh` ve `data/` klasörü güncellemede **silinmez** (git bunları takip etmez).

---

## 11. Sunucu yeniden başlarsa

`screen` sunucu yeniden başlayınca kapanır. Tekrar 8. adımı yap. İleride otomatik başlasın istersen `systemd` servisi ekleriz.

---

## 🧯 Sorun Giderme

| Hata | Çözüm |
|---|---|
| `Eksik ortam değişkenleri` | `source env.sh` yapmadın veya env.sh'de bir tırnak boş. |
| `ModuleNotFoundError: google` | `source venv/bin/activate` yapmadın. `start.sh` bunu otomatik yapar. |
| Gemini **503 UNAVAILABLE** | Google tarafında anlık yoğunluk; senin hesabınla ilgili değil. Bot 2-4 sn bekleyip tekrar dener, olmazsa yedek modele geçer ve yoğun modeli 10 dk dinlendirir. Haber kaybolmaz, sonraki turda tekrar denenir. |
| Gemini **429 RESOURCE_EXHAUSTED** | Kota ya da kredi bitti. "prepayment credits are depleted" veya "free_tier" yazıyorsa ücretli katman kredisi bitmiştir: AI Studio → Billing'den kredi yükle. Dakikalık sınırsa ("PerMinute") kendiliğinden düzelir. |
| Telegram'a **"⚠️ Gemini çalışmıyor"** geldi | Mesajdaki "Son hata" ve altındaki ipucunu uygula. Sunucuda `python3 check.py` aynı hatayı gösterir. Bot bu sürede çalışmaya devam eder. |
| Gemini **Model bulunamadı (404)** | Google eski modeli kaldırmış. Bot, anahtarının erişebildiği en yeni flash modellerini otomatik seçer; `check.py` erişilebilir modelleri listeler. Belirli bir model istersen: `export GEMINI_MODELS="model-adi"` |
| Gemini **400 / 403 API key not valid** | Anahtar yanlış kopyalanmış veya silinmiş. Yeni anahtar oluştur. |
| Binance **-2015 Invalid API-key** | Testnet yerine gerçek hesap anahtarı girilmiş (veya tersi). `TEST_MODE` ile anahtar türü uyumlu olmalı. |
| Binance **-1021 Timestamp** | Sunucu saati kayık. `sudo timedatectl set-ntp true` |
| `XYZUSDT testnet üzerinde işlem görmüyor` | Testnette sadece belli coinler var. Bot bu coinleri artık sanal işlemle (gerçek fiyatla) dener, bkz. 9.4. |
| Sanal işlem: "fiyatı da bulunamadı" | Coin Binance, Gate.io ve MEXC'nin hiçbirinde USDT çiftiyle işlem görmüyor. `check.py`'de fiyat kaynakları satırına bak. |
| Telegram kanalları: "giriş yapılmamış" | Botu durdur, `python3 tg_login.py` çalıştır (9.2. adım 3). |
| Telegram kanalları: "telethon kurulu değil" | `pip install --upgrade pip setuptools wheel && pip install -r requirements.txt` |
| `database is locked` (tg_news.session) | Bot çalışırken `tg_login.py`/`check.py` çalıştırılmış. Önce botu durdur. |
| Piyasa Nabzı: "CoinGecko hata (HTTP 429)" | CoinGecko'nun ücretsiz sınırı anlık doldu; bot bir sonraki saatte tekrar dener. İstersen coingecko.com'dan ücretsiz "Demo API key" alıp `export COINGECKO_API_KEY="..."` ekle. |
| Telegram mesajı gelmiyor | Bota Telegram'dan önce bir kez `/start` yazmış olmalısın; chat id doğru mu kontrol et. |
| `Permission denied: ./start.sh` | `chmod +x start.sh` |

---

## 💰 Maliyet notu

- Önceki sürümde Piyasa Nabzı saatte bir pahalı **pro** modelle çalışıyordu. Hacim patlamalarının hepsi (günde ~300) ve haber analizleri de **flash** modelle yapılıyordu. Kaba tahminle günde ~1 $ (~45 TL) ediyordu; 250 TL'lik kredinin birkaç günde bitmesi bununla uyumlu. Eski nottaki "ayda 2-5 $" tahmini yanlıştı.
- Yeni düzen (9.5): haberler flash-lite ile, nabız 2 saatte bir flash ile, hacim yorumu sadece kanıtı olan patlamalarda. Üstüne **günlük bütçe sınırı** var (0,15 $ ≈ 200 TL/ay).
- Gerçek harcama her 20 dakikalık özette, `/durum`'da ve gece raporunda amaca göre dağılımıyla yazar. Birkaç gün sonra bu rakamlara bakıp bütçeyi birlikte ayarlarız.
- Daha da düşürmek için: `export PULSE_ENABLED="False"` (nabız kapalı) veya `export SPIKE_AI_MAX_PER_HOUR="6"`.
