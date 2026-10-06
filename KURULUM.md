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
```

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

**Piyasa Nabzı** saatte bir piyasanın genel resmini toplar ve Gemini'ye yorumlatır:
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

**Hacim patlamaları** artık Gemini'ye soruluyor: "Arkasında gerçek bir hikâye var mı?" Gemini'ye o coinin son 24 saatlik haberleri (Telegram dahil), trend bilgisi ve nabız yorumu gidiyor. Sadece onaylananlar Telegram'a gelir ve alım adayı olur.

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

**Gerçek piyasa K/Z'si:** Testnet fiyatları büyük coinlerde gerçek piyasayı takip ediyor, ama küçük coinlerin ani hareketlerinde farklı gidebilir. Bu yüzden her işlemde giriş ve çıkış anındaki gerçek Binance fiyatı da kaydedilir. Kapanış mesajında ve gece raporunda "Gerçek piyasada: +X%" satırı olarak, `trades.csv`'de `gercek_*` sütunları olarak görünür. Stratejinin gerçek performansını bu sütunlar gösterir.

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
| Gemini **429 RESOURCE_EXHAUSTED** | Anahtar faturalandırma açık olmayan projeden alınmış. AI Studio → API Keys → anahtarın projesinin yanında *Paid/Tier 1* yazmalı. Yazmıyorsa o projede yeni anahtar oluştur. |
| Gemini **Model bulunamadı (404)** | Google eski modeli kaldırmış. Bot, anahtarının erişebildiği en yeni flash modellerini otomatik seçer; `check.py` erişilebilir modelleri listeler. Belirli bir model istersen: `export GEMINI_MODELS="model-adi"` |
| Gemini **400 / 403 API key not valid** | Anahtar yanlış kopyalanmış veya silinmiş. Yeni anahtar oluştur. |
| Binance **-2015 Invalid API-key** | Testnet yerine gerçek hesap anahtarı girilmiş (veya tersi). `TEST_MODE` ile anahtar türü uyumlu olmalı. |
| Binance **-1021 Timestamp** | Sunucu saati kayık. `sudo timedatectl set-ntp true` |
| `XYZUSDT testnet üzerinde işlem görmüyor` | Testnette sadece belli coinler var. Normal; bot o haberi atlar ve Telegram'a yazar. |
| Telegram kanalları: "giriş yapılmamış" | Botu durdur, `python3 tg_login.py` çalıştır (9.2. adım 3). |
| Telegram kanalları: "telethon kurulu değil" | `pip install --upgrade pip setuptools wheel && pip install -r requirements.txt` |
| `database is locked` (tg_news.session) | Bot çalışırken `tg_login.py`/`check.py` çalıştırılmış. Önce botu durdur. |
| Piyasa Nabzı: "CoinGecko hata (HTTP 429)" | CoinGecko'nun ücretsiz sınırı anlık doldu; bot bir sonraki saatte tekrar dener. İstersen coingecko.com'dan ücretsiz "Demo API key" alıp `export COINGECKO_API_KEY="..."` ekle. |
| Telegram mesajı gelmiyor | Bota Telegram'dan önce bir kez `/start` yazmış olmalısın; chat id doğru mu kontrol et. |
| `Permission denied: ./start.sh` | `chmod +x start.sh` |

---

## 💰 Maliyet notu

- Haber analizi (flash/flash-lite, düşünme en düşükte): haber başına ~0,0002-0,0005 $. Kural filtresine takılan haberler Gemini'ye hiç gitmez.
- İkinci görüş (pro model): sadece tüm kontrolleri geçen adaylarda, günde birkaç kez. Çağrı başına ~0,01 $.
- Gece raporu: günde 1 çağrı, ~0,02-0,05 $.
- Piyasa Nabzı: saatte 1 çağrı, günde ~0,02-0,05 $. Hacim patlaması yorumu: saatte en fazla 30 ucuz çağrı, günde ~0,02 $.
- Telegram kanalları Gemini'ye günde birkaç yüz haber daha gönderir: ucuz modelle günde ~0,05-0,10 $.
- Toplam: ayda yaklaşık **2-5 $**. Güncel tahmini maliyet her 20 dakikalık özette ve gece raporunda yazar.
Bütçe aşılırsa `env.sh`'e sadece lite modeli yazarak (ör. `export GEMINI_MODELS="gemini-3.5-flash-lite"`) ekleyerek maliyeti ~5 kat düşürebilirsin.
