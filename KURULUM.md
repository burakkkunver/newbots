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
pip install --upgrade pip
pip install -r requirements.txt
```

Bu 3 kütüphaneyi kurar: `google-genai` (Gemini), `feedparser` (RSS), `requests`.
Başka hiçbir şey yüklemen gerekmez.

---

## 6. Ayar dosyasını (env.sh) hazırla

**Seçenek A – eski env.sh dosyanı kullan** (içi zaten dolu):
```bash
cp /root/env.sh ~/newbots/env.sh      # yolu kendi dosyanın yeriyle değiştir
nano ~/newbots/env.sh
```
- `CRYPTOCOMPARE_API_KEY` satırı artık gereksiz (silebilir veya bırakabilirsin, zararı yok).
- İstersen şu satırları ekle:
```bash
export BUDGET_USDT="100"
export STOP_LOSS_PCT="6"
export SUMMARY_MINUTES="20"
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
| `STOP_LOSS_PCT` | Felaket stopu (%). `0` yaparsan bot hiç zararda satmaz. |
| `SUMMARY_MINUTES` | Telegram'a kaç dakikada bir özet gelsin. |

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
✅ Gemini: {'karar': 'BUY', ...}
✅ Binance: TESTNET | USDT: 10000.00 | ...
✅ RSS: 9/10 kaynak çalışıyor
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
> Bot durunca Binance'teki açık OCO emirleri silinmez, bekler. Bot yeniden başladığında pozisyonları `data/positions.json` dosyasından hatırlar ve takibe devam eder.

---

## 9. Günlük kullanım

| İş | Komut |
|---|---|
| Anlık durum | Telegram'a `/durum` yaz |
| Log'un son 50 satırı | `tail -n 50 ~/newbots/data/bot.log` |
| Canlı log | `tail -f ~/newbots/data/bot.log` (çıkış: Ctrl + C) |
| Kapanan işlemler | `cat ~/newbots/data/trades.csv` |
| Tüm sinyaller | `cat ~/newbots/data/signals.csv` |
| Açık pozisyonlar | `cat ~/newbots/data/positions.json` |

`trades.csv` ve `signals.csv` dosyalarını WinSCP ile bilgisayarına çekip Excel'de açabilirsin.

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
| Gemini **503 UNAVAILABLE** | Google tarafında anlık yoğunluk; senin hesabınla ilgili değil. Bot artık 2-4-8 sn bekleyip tekrar dener, olmazsa otomatik `gemini-2.5-flash-lite` modeline geçer. Haber kaybolmaz, sonraki turda tekrar denenir. |
| Gemini **429 RESOURCE_EXHAUSTED** | Anahtar faturalandırma açık olmayan projeden alınmış. AI Studio → API Keys → anahtarın projesinin yanında *Paid/Tier 1* yazmalı. Yazmıyorsa o projede yeni anahtar oluştur. |
| Gemini **400 / 403 API key not valid** | Anahtar yanlış kopyalanmış veya silinmiş. Yeni anahtar oluştur. |
| Binance **-2015 Invalid API-key** | Testnet yerine gerçek hesap anahtarı girilmiş (veya tersi). `TEST_MODE` ile anahtar türü uyumlu olmalı. |
| Binance **-1021 Timestamp** | Sunucu saati kayık. `sudo timedatectl set-ntp true` |
| `XYZUSDT testnet üzerinde işlem görmüyor` | Testnette sadece belli coinler var. Normal; bot o haberi atlar ve Telegram'a yazar. |
| Telegram mesajı gelmiyor | Bota Telegram'dan önce bir kez `/start` yazmış olmalısın; chat id doğru mu kontrol et. |
| `Permission denied: ./start.sh` | `chmod +x start.sh` |

---

## 💰 Maliyet notu

Gemini 2.5 Flash, düşünme modu kapalı çalışır. Haber başına yaklaşık 0,0004 $ tutar.
Günde ~200-300 haber analiz edilirse aylık yaklaşık **3-4 $** eder. Güncel tahmini maliyeti her 20 dakikalık Telegram özetinde görebilirsin.
Bütçe aşılırsa `env.sh`'e `export GEMINI_MODELS="gemini-2.5-flash-lite"` ekleyerek maliyeti ~5 kat düşürebilirsin.
