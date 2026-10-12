"""Gemini: haberden olgu çıkarma (puanı kod hesaplar), ikinci görüş ve gece raporu yorumu.

Neden olgu? Yapay zekaya doğrudan "puan ver" denince fazla iyimser oluyor (gereksiz 8/10'lar).
Bu yüzden Gemini sadece haberin ne olduğunu söylüyor (olay türü, kesinlik, yenilik, aktör...),
puanı aşağıdaki sabit tablo hesaplıyor. Alım adayları ayrıca güçlü bir modele
"bu haber neden fiyatı yükseltmez?" diye soruluyor.

Model seçimi: 503/429 gelirse bekleyip tekrar dener, olmazsa yedek modele geçer; yoğun modeli
10 dk dinlendirir, son başarılı modeli hep önce dener, kullanımdan kalkmış modeli listeden atar.
Maliyet: haber olguları ucuz "lite" modelle, hacim/nabız/rapor "flash" ile, ikinci görüş "pro" ile yapılır.
Günlük bütçe dolunca hacim yorumu ve nabız durur. Gemini art arda hata verirse Telegram'a sebebiyle uyarı gider.
"""
import html
import json
import os
import re
import time

from google import genai
from google.genai import errors, types

import config
from util import fmt_ts, today_str

MODEL_COOLDOWN_SEC = 600
_SKIP_WORDS = ("image", "tts", "audio", "live", "embedding", "robotics", "computer", "exp", "learnlm",
               "customtools", "transcribe", "omni")
STABLES = {"USDT", "USDC", "FDUSD", "DAI", "TUSD", "BUSD", "USDE", "USDP", "PYUSD", "EUR", "TRY"}

# ==========================================
# PUAN TABLOSU (olgulardan puan)
# ==========================================
TIER_BASE = {   # aktöre göre taban puan
    "listeleme":         {"birinci_lig": 9, "orta": 6, "kucuk": 4, "yok": 4},
    "etf_onay":          {"birinci_lig": 9, "orta": 8, "kucuk": 6, "yok": 7},
    "etf_basvuru":       {"birinci_lig": 7, "orta": 6, "kucuk": 5, "yok": 5},
    "kurumsal_alim":     {"birinci_lig": 8, "orta": 7, "kucuk": 5, "yok": 5},
    "ortaklik":          {"birinci_lig": 7, "orta": 6, "kucuk": 4, "yok": 4},
    "entegrasyon":       {"birinci_lig": 7, "orta": 6, "kucuk": 4, "yok": 4},
    "regulasyon_olumlu": {"birinci_lig": 8, "orta": 6, "kucuk": 5, "yok": 5},
    "yatirim_fon":       {"birinci_lig": 6, "orta": 5, "kucuk": 4, "yok": 4},
}
FLAT_BASE = {
    "ana_ag_lansman": 6, "token_yakim": 7, "geri_alim": 7, "hack_geri_odeme": 7,
    "teknik_gelisme": 4, "genel_piyasa": 4, "diger": 4, "fiyat_analizi": 3, "yorum": 3,
    "regulasyon_olumsuz": 2, "hack": 1, "dava": 2, "delist": 1, "token_kilit_acilimi": 2, "satis_baskisi": 2,
}
EVENT_TYPES = set(TIER_BASE) | set(FLAT_BASE)
ENUMS = {
    "kesinlik": ("resmi", "guvenilir_kaynak", "soylenti", "spekulasyon"),
    "yenilik": ("yeni", "zaten_biliniyor"),
    "aktor": ("birinci_lig", "orta", "kucuk", "yok"),
    "olcek": ("buyuk", "orta", "kucuk"),
    "yon": ("olumlu", "olumsuz", "notr"),
}
DEFAULTS = {"kesinlik": "spekulasyon", "yenilik": "zaten_biliniyor", "aktor": "yok", "olcek": "kucuk", "yon": "notr"}


def clean_coin(raw):
    coin = str(raw or "GENEL").upper().replace("$", "").strip()
    coin = re.split(r"[\s,/|]+", coin)[0] if coin else "GENEL"
    coin = re.sub(r"[^A-Z0-9]", "", coin)
    if coin.endswith("USDT") and len(coin) > 4:
        coin = coin[:-4]
    return coin or "GENEL"


def compute_score(f):
    """Olgulardan 1-10 puan hesaplar. (puan, açıklama listesi) döner."""
    ev = f["olay_turu"]
    if ev in TIER_BASE:
        score = TIER_BASE[ev][f["aktor"]]
    else:
        score = FLAT_BASE.get(ev, 4)
    notes = [f"taban {score} ({ev}/{f['aktor']})"]

    def cap(limit, why):
        nonlocal score
        if score > limit:
            score = limit
            notes.append(f"{why} → en fazla {limit}")

    if score >= 5:
        if f["olcek"] == "buyuk":
            score += 1
            notes.append("büyük ölçek +1")
        elif f["olcek"] == "kucuk":
            score -= 1
            notes.append("küçük ölçek -1")
    if f["kesinlik"] == "soylenti":
        score -= 2
        notes.append("söylenti -2")
        cap(6, "söylenti")
    elif f["kesinlik"] == "spekulasyon":
        cap(4, "spekülasyon")
    if f["yenilik"] == "zaten_biliniyor":
        score -= 2
        notes.append("zaten biliniyor -2")
        cap(6, "eski haber")
    if not f["coin_ozel"]:
        cap(6, "coine özel değil")
    if f["fiyat_zaten_hareket_etti"]:
        cap(5, "fiyat zaten hareket etmiş")
    if f["yon"] == "olumsuz":
        cap(3, "olumsuz haber")
    elif f["yon"] == "notr":
        cap(5, "nötr haber")
    coin = f["hedef_coin"]
    if coin == "GENEL" or coin in STABLES:
        cap(6, "belirli coin yok")
    elif coin in ("BTC", "ETH") and ev != "etf_onay":
        score -= 1
        notes.append("dev coin -1")
    return max(1, min(10, int(round(score)))), notes


# ==========================================
# PROMPTLAR
# ==========================================
FACTS_PROMPT = """Sen bir kripto haber analistisin. Görevin PUAN VERMEK DEĞİL, haberden OLGULARI doğru çıkarmak.
Abartma, iyimser olma. Emin olmadığın her alanda temkinli seçeneği seç.

Kaynak: {source} | Yayınlanalı: {age} dk
Başlık: "{title}"
Özet: "{summary}"
Kategoriler: {categories}

Alanlar:
- hedef_coin: Haberin DOĞRUDAN konusu olan TEK coinin Binance sembolü (SOL, XRP, PEPE...). Coin haberde açıkça
  geçmiyorsa ya da haber şirket/hisse/genel piyasa haberiyse "GENEL". Tahmin yürütme. Stablecoin olamaz.
- olay_turu: şunlardan biri:
  listeleme (bir borsada YENİ spot listeleme) | etf_onay (ETF onayı / işlem başlaması) | etf_basvuru (ETF başvurusu, süreç ilerlemesi) |
  kurumsal_alim (şirket/fon/devletin coin alması, hazine) | ortaklik (somut iş birliği) | entegrasyon (ödeme/ürün entegrasyonu, gerçek kullanım) |
  ana_ag_lansman (mainnet, büyük ağ yükseltmesi) | teknik_gelisme (küçük güncelleme, testnet, yol haritası) |
  token_yakim | geri_alim (buyback) | hack_geri_odeme | yatirim_fon (fonlama turu) |
  regulasyon_olumlu (davanın düşmesi/kazanılması, olumlu düzenleme) | regulasyon_olumsuz | hack | dava | delist |
  token_kilit_acilimi (unlock) | satis_baskisi (büyük satış/transfer/likidasyon) |
  fiyat_analizi (fiyat yorumu, tahmin, teknik analiz) | yorum (görüş, röportaj, analist sözü) | genel_piyasa (makro, tüm piyasa) | diger
- kesinlik: resmi (resmi açıklama) | guvenilir_kaynak (büyük medya, resmi değil) | soylenti (iddia, "reportedly", belirsiz kaynak) | spekulasyon (olasılık, tahmin)
- yenilik: yeni (ilk kez duyuruluyor) | zaten_biliniyor (önceden bilinen gelişmenin detayı/tekrarı/hatırlatması)
- aktor: birinci_lig (Binance, Coinbase, Upbit, Robinhood, BlackRock, Fidelity, Visa, Mastercard, PayPal, büyük bankalar,
  ABD/AB hükümetleri, SEC, Fortune 500) | orta (tanınmış ikinci derece kurum/borsa) | kucuk (küçük, az bilinen) | yok
- olcek: buyuk (projeyi ciddi etkiler, ör. yüz milyonlarca $) | orta | kucuk (pilot, küçük tutar, sembolik)
- coin_ozel: true = haber ağırlıkla bu coini ilgilendiriyor | false = birçok coini veya tüm piyasayı ilgilendiriyor
- fiyat_zaten_hareket_etti: metin fiyatın zaten belirgin yükseldiğini söylüyorsa true
- yon: olumlu | olumsuz | notr (coin fiyatı açısından)
- sebep: Türkçe en fazla 2 cümle, olguları özetle

Örnekler:
"Egrag Crypto Projects $60 and $180 for XRP" -> olay_turu fiyat_analizi, kesinlik spekulasyon
"Citigroup teams up with Coinbase to offer stablecoin payments" -> hedef_coin GENEL (konu şirketler), olay_turu ortaklik
"Upbit lists SUI for KRW trading" -> hedef_coin SUI, listeleme, birinci_lig, resmi, yeni

Sadece JSON döndür:
{{"hedef_coin": "SOL", "olay_turu": "ortaklik", "kesinlik": "resmi", "yenilik": "yeni", "aktor": "orta", "olcek": "orta",
"coin_ozel": true, "fiyat_zaten_hareket_etti": false, "yon": "olumlu", "sebep": "..."}}"""

REVIEW_PROMPT = """Sen temkinli bir kripto risk yöneticisisin. Görevin bir alım fikrini ELEŞTİRMEK.

HABER ({source}, {age} dk önce): "{title}"
Özet: "{summary}"
İlk analiz: olay={olay_turu}, kesinlik={kesinlik}, yenilik={yenilik}, aktör={aktor}, ölçek={olcek} -> puan {puan}/10
Hedef coin: {coin}

GERÇEK PİYASA VERİSİ:
- {coin} son 24 saat: {ch24} | 24 saatlik işlem hacmi: {vol}
- Haber yayınlandığından beri {coin}: {since}
- BTC rejimi: {regime}

PLAN: Alım yapılırsa hedef 1-4 saat içinde en az +%2, zarar kes -%2.

ÖNEMLİ - STRATEJİYİ DOĞRU YORUMLA:
- Bot haberleri yayınlandıktan birkaç dakika sonra yakalar. Amaç, fiyat hareketi BAŞLAMADAN veya yeni başlamışken girmek.
- "Haber yayınlandığından beri" hareketin küçük olması (ör. -%1 ile +%1 arası) OLUMSUZ DEĞİLDİR, aksine fırsatın
  henüz kaçmadığını gösterir. Bunu "zayıf tepki" diye red gerekçesi yapma.
- Asıl riskler: fiyat haberden önce veya sonra zaten çok yükselmişse (son 24 saatte büyük yükseliş), haber eski/tekrar ise,
  aktör küçükse, coin tek bir haberle hareket edemeyecek kadar büyükse, söylenti ise.

1) Bu haberin fiyatı YÜKSELTMEMESİ için en güçlü 3 nedeni yaz (zaten fiyatlanmış olması, aktörün küçüklüğü, belirsizlik,
   coinin büyüklüğü veya düşük hacmi, son 24 saatteki hareket, piyasa ortamı...).
2) Bu nedenlere rağmen alım mantıklı mı? Şüphe varsa HAYIR de. Sadece net, somut ve yeni katalizörlerde EVET de.
guven: Fiyatın plandaki hedefe (+%2) ulaşacağına güvenin (0-100).

Sadece JSON döndür:
{{"karsi_nedenler": ["...", "...", "..."], "onay": false, "guven": 40, "sebep": "Türkçe en fazla 2 cümle"}}"""

REPORT_PROMPT = """Sen bir kripto haber-trading botunun performans analistisin. Aşağıda botun bugünkü verileri var.

Botun mantığı: RSS haberleri -> kural filtresi -> Gemini olgu çıkarma -> tabloyla puan -> BTC rejimine göre puan eşiği
-> güçlü modelden ikinci görüş -> Binance testnet alımı.
Çıkışlar: -%{stop} sabit stop; boğa rejimlerinde izleyen stop; yatay/düşüşte küçük sabit kâr al; 7-8 puanda {ts} dk time-stop;
puana göre maksimum süre. Kalibrasyon: her haberden sonra fiyatın 15 dk / 1 saat / 4 saat sonra ne yaptığı ölçülüyor.

VERİLER:
{data}

Türkçe, detaylı ama net bir gün sonu değerlendirmesi yaz. Bölümler:
1. Günün özeti (2-3 cümle)
2. Piyasa yorumu (BTC rejimi ve alımlara etkisi)
3. İşlemlerin değerlendirmesi (neden kazandırdı/kaybettirdi, çıkış kuralları doğru çalıştı mı)
4. Puanlama kalitesi (yüksek puanlılar gerçekten yükseldi mi, kaçırılan fırsatlar, yanlış alarmlar)
5. Eksikler ve riskler (veri, haber kaynakları, filtreler, kurallar)
6. Somut öneriler (hangi ayar neye değişmeli, sayılarla; veri yetersizse bunu söyle)
7. Yarın için dikkat edilecekler
Kurallar: Sadece verilere dayan, uydurma. Veri azsa açıkça söyle. Markdown kullanma (*, #, ** yok); bölüm başlıklarını
emoji ile yaz. En fazla 3500 karakter."""


PULSE_PROMPT = """Sen bir kripto piyasa stratejistisin. Aşağıda son saatlerin piyasa verileri var. Görevin piyasanın nabzını
tutmak: hangi anlatılar (AI, meme, DeFi, L2, RWA, oyun...) ısınıyor, para nereye akıyor, hangi coinlerin arkasında GERÇEK
bir hikâye var.

VERİLER:
{data}

Kurallar:
- Sadece verilere dayan; veride olmayan haber veya olay uydurma.
- izleme_listesi: en fazla 8 coin. Sadece hem fiyat/hacim tarafında hem de haber/trend tarafında kanıtı olan coinler.
  Sadece yükseldiği için listeye koyma. 24 saatte zaten +%30'dan fazla yükselmişse geç kalınmış olabilir, guc düşük ver.
- guc: 1 = zayıf, 2 = orta, 3 = güçlü (birden fazla bağımsız kanıt: haber + trend + hacim aynı yönde).
- uzak_dur: olumsuz haber, aşırı ısınma veya manipülasyon şüphesi olan coinler.
- coin alanına sadece Binance sembolü yaz (FET, PUMP, SUI...).

Sadece JSON döndür:
{{"ozet": "3-4 cümle Türkçe", "duygu": "olumlu", "sicak_anlatilar": ["AI", "meme"],
"izleme_listesi": [{{"coin": "FET", "guc": 2, "neden": "kısa Türkçe"}}], "uzak_dur": [{{"coin": "XYZ", "neden": "kısa Türkçe"}}]}}"""

SPIKE_PROMPT = """Sen kripto piyasasında haber ve trend avcısısın. Bir coinde ani hacim patlaması oldu. Görevin: bu hareketin
arkasında GERÇEK bir hikâye (somut katalizör veya güçlü sektör trendi) var mı, yoksa sebepsiz/manipülatif bir sıçrama mı?

ÖNEMLİ: Botun kendi verisine göre sebepsiz hacim patlamaları çoğunlukla geri döner (1 saatte ortalama -%0,6, yarısı -%2
görüyor). Bu yüzden sadece somut kanıt varsa onay ver.

COIN: {coin}
- Son 15 dk: +{move:.1f}% | hacim önceki saatin {ratio:.1f} katı ({vol}) | son 24 saat: {ch24}
- CoinGecko trend listesinde: {trending}
- Piyasa Nabzı izleme listesinde: {watch}
- Piyasa Nabzı son yorumu: {pulse}
- BTC rejimi: {regime}

SON 24 SAATTE BU COINLE İLGİLİ HABERLER (kaynak, kaç dk önce):
{headlines}

Değerlendir:
- Haberler yeni ve somut mu (listeleme, ortaklık, ürün lansmanı, büyük alım, yakım...)? Fiyat analizi ve yorum hikâye sayılmaz.
- Haber hareketin SEBEBİ mi, yoksa zaten olmuş yükselişi mi anlatıyor?
- Coin sıcak bir anlatının (sektör trendinin) parçası mı?
- Son 24 saatte zaten çok yükselmişse (+%25 üstü) geç kalınmış olabilir.
guc: hikâyenin fiyatı önümüzdeki saatlerde yukarı taşıma gücü (1-10).

Sadece JSON döndür:
{{"hikaye_var": false, "guc": 4, "katalizor": "kısa", "risk": "kısa", "sebep": "Türkçe en fazla 2 cümle"}}"""


def _version(name):
    m = re.search(r"gemini-(\d+(?:\.\d+)?)", name)
    return float(m.group(1)) if m else 0.0


def _price(model):
    if "lite" in model:
        return 0.10, 0.40
    if "pro" in model:
        return 2.00, 12.00
    if model.startswith("gemini-2.5-flash"):
        return 0.30, 2.50
    return 0.50, 3.00


def _newest(names, count):
    # En yeni sürüm önce; aynı sürümde kararlı (preview olmayan) önce
    return sorted(names, key=lambda n: (_version(n), "preview" not in n), reverse=True)[:count]


def _as_bool(v):
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("true", "evet", "yes", "1", "onay")


def _dur(seconds):
    m = int(max(0, seconds) // 60)
    if m < 60:
        return f"{m} dk"
    h, m = divmod(m, 60)
    if h < 24:
        return f"{h} sa {m} dk"
    d, h = divmod(h, 24)
    return f"{d} gün {h} sa"


def _esc(text):
    return html.escape(str(text or ""), quote=False)


def _err_text(e):
    """API hatasının okunur özeti: kod, durum, mesaj ve varsa kota kimliği (teşhis için)."""
    code = getattr(e, "code", "") or ""
    status = getattr(e, "status", "") or ""
    msg = (getattr(e, "message", None) or str(e)).replace("\n", " ")
    quota = sorted(set(re.findall(r"quotaId['\"]?\s*:\s*['\"]([\w-]+)", str(e))))
    return (f"{code} {status}: {msg}" + (f" [kota: {', '.join(quota)}]" if quota else "")).strip()[:500]


# Hangi iş hangi model zinciriyle yapılır. Haber olguları basit bir sınıflandırma, ucuz "lite" model yeter;
# en pahalı "pro" modeller sadece nadir ve önemli ikinci görüşte kullanılır.
PURPOSE_CHAIN = {"haber": "cheap", "hacim": "main", "nabiz": "main", "rapor": "main", "ikinci_gorus": "review"}
PURPOSE_NAMES = {"haber": "haber analizi", "hacim": "hacim yorumu", "nabiz": "piyasa nabzı",
                 "ikinci_gorus": "ikinci görüş", "rapor": "gece raporu"}
BUDGET_STOP = {"nabiz": 0.7, "hacim": 1.0}   # günlük bütçenin bu oranı harcanınca bu işler gece yarısına kadar durur
FATAL_KINDS = ("anahtar", "fatura", "konum")
MAX_MODELS_PER_CALL = 4
ALERT_REPEAT_SEC = 6 * 3600
REDISCOVER_SEC = 6 * 3600
SPEND_FILE = os.path.join(config.DATA_DIR, "gemini_harcama.json")


class GeminiAnalyzer:
    def __init__(self):
        self.client = genai.Client(api_key=config.GEMINI_API_KEY)
        self.stats = {"calls": 0, "errors": 0, "cost_usd": 0.0, "fallbacks": 0, "skipped": 0}
        self.day = dict(self.stats)
        self.day_date = today_str()
        self.last_fatal_error = None
        self.no_thinking_cfg = set()
        self.dead = set()
        self.cooldown = {}
        self.last_good = {}
        self.available = []
        # Sağlık: art arda kaç çağrı başarısız, son hata ne, ne zamandan beri
        self.health = {"fails": 0, "since": 0.0, "last_ok": 0.0, "last_model": "", "last_err": "", "kind": "",
                       "free_tier": False}
        self.paused_until = 0.0
        self._alerted = {"active": False, "sent": 0.0}
        self._recovered = None
        self.spend = self._load_spend()
        self.chains = self._resolve_chains() or self._default_chains()
        self.discovered_at = time.time()
        self.models = self.chains["main"]

    # ---------- model seçimi ----------
    @staticmethod
    def _default_chains():
        main = config.GEMINI_MODELS or ["gemini-flash-latest", "gemini-flash-lite-latest"]
        cheap = main if config.GEMINI_MODELS else ["gemini-flash-lite-latest", "gemini-flash-latest"]
        return {"main": main, "cheap": cheap, "review": (config.REVIEW_MODELS or ["gemini-pro-latest"]) + main}

    def _resolve_chains(self):
        """Anahtarın erişebildiği modellerden zincirleri kurar. Liste alınamazsa None."""
        try:
            names = []
            for m in self.client.models.list():
                actions = m.supported_actions or []
                if actions and "generateContent" not in actions:
                    continue
                names.append(m.name.replace("models/", ""))
        except Exception as e:
            print(f"⚠️ Model listesi alınamadı ({e}).")
            return None
        self.available = names
        usable = [n for n in names if n.startswith("gemini") and not any(w in n for w in _SKIP_WORDS)]
        flash = [n for n in usable if "flash" in n and "latest" not in n]
        full_flash = [n for n in flash if "lite" not in n]
        lite = [n for n in flash if "lite" in n]
        pro = [n for n in usable if "pro" in n and "latest" not in n]

        def alias(name):
            return [name] if name in names else []

        def build(*groups):
            out = []
            for g in groups:
                out.extend(m for m in g if m not in out)
            return out

        # En yeni modeller önce; "-latest" takma adları en sonda yedek (yeni çıkan bir model çalışmazsa hepsi düşmesin)
        user_main = [m for m in config.GEMINI_MODELS if m in names]
        main = build(user_main, _newest(full_flash, 2), _newest(lite, 1),
                     alias("gemini-flash-latest"), alias("gemini-flash-lite-latest"))
        if not main:
            main = list(config.GEMINI_MODELS) or names[:1]
        cheap = build(user_main, _newest(lite, 2), alias("gemini-flash-lite-latest"), main)
        review = build([m for m in config.REVIEW_MODELS if m in names], _newest(pro, 2),
                       alias("gemini-pro-latest"), [m for m in main if "lite" not in m], main)

        for env_name, wanted in (("GEMINI_MODELS", config.GEMINI_MODELS), ("REVIEW_MODELS", config.REVIEW_MODELS)):
            missing = [m for m in wanted if m not in names]
            if missing:
                print(f"⚠️ {env_name} içindeki bu modeller erişilebilir değil: {', '.join(missing)}")
        print(f"🤖 Hacim/nabız/rapor modelleri: {', '.join(main)}")
        print(f"💸 Haber analizi (ucuz) modelleri: {', '.join(cheap)}")
        print(f"🧐 İkinci görüş modelleri: {', '.join(review)}")
        return {"main": main, "cheap": cheap, "review": review}

    def rediscover(self):
        """Model listesini yeniden alır (yeni çıkan / kaldırılan modeller için yeniden başlatmaya gerek kalmasın)."""
        self.discovered_at = time.time()
        chains = self._resolve_chains()
        if chains:
            self.chains = chains
            self.models = chains["main"]
            self.dead.clear()

    def _config(self, model, kind):
        deep = kind in ("deep", "text")
        kwargs = dict(
            temperature=0.4 if kind == "text" else 0.2,
            max_output_tokens={"fast": 1500, "pulse": 3000, "deep": 4000, "text": 8000}[kind],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True))
        if kind != "text":
            kwargs["response_mime_type"] = "application/json"
        if model not in self.no_thinking_cfg:
            v = _version(model)
            if 0 < v < 3:
                if "pro" not in model:   # 2.5 pro düşünmeyi kapatamaz, varsayılanda kalsın
                    kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=1024 if deep else 0)
            elif "pro" in model or deep:
                kwargs["thinking_config"] = types.ThinkingConfig(thinking_level="LOW")
            else:
                kwargs["thinking_config"] = types.ThinkingConfig(thinking_level="MINIMAL")
        return types.GenerateContentConfig(**kwargs)

    # ---------- sayaçlar, harcama ve bütçe ----------
    def _roll(self):
        """Gün / ay değişince sayaçları sıfırlar (gece yarısı, yerel saat)."""
        today = today_str()
        if self.day_date != today:
            self.day = {k: 0 if k != "cost_usd" else 0.0 for k in self.day}
            self.day_date = today
        s = self.spend
        if s.get("date") != today:
            s.update(date=today, usd=0.0, by={}, calls={})
        if s.get("month") != today[:7]:
            s.update(month=today[:7], month_usd=0.0)

    def _inc(self, key, val=1):
        self._roll()
        self.stats[key] += val
        self.day[key] += val

    def reset_day(self):
        self._roll()   # sayaçlar artık gece yarısı kendiliğinden sıfırlanıyor

    @staticmethod
    def _load_spend():
        try:
            with open(SPEND_FILE) as f:
                s = json.load(f)
            if isinstance(s, dict):
                return {"date": s.get("date", ""), "usd": float(s.get("usd", 0)), "by": dict(s.get("by", {})),
                        "calls": dict(s.get("calls", {})), "month": s.get("month", ""),
                        "month_usd": float(s.get("month_usd", 0))}
        except (FileNotFoundError, json.JSONDecodeError, TypeError, ValueError):
            pass
        return {"date": "", "usd": 0.0, "by": {}, "calls": {}, "month": "", "month_usd": 0.0}

    def _save_spend(self):
        try:
            tmp = SPEND_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self.spend, f)
            os.replace(tmp, SPEND_FILE)
        except OSError as e:
            print(f"⚠️ Gemini harcama kaydı yazılamadı: {e}")

    def _track_cost(self, model, response, purpose):
        um = getattr(response, "usage_metadata", None)
        if not um:
            return
        pin, pout = _price(model)
        tin = getattr(um, "prompt_token_count", 0) or 0
        tout = (getattr(um, "candidates_token_count", 0) or 0) + (getattr(um, "thoughts_token_count", 0) or 0)
        cost = tin / 1e6 * pin + tout / 1e6 * pout
        self._inc("cost_usd", cost)
        s = self.spend
        s["usd"] += cost
        s["month_usd"] += cost
        s["by"][purpose] = s["by"].get(purpose, 0.0) + cost
        s["calls"][purpose] = s["calls"].get(purpose, 0) + 1
        self._save_spend()

    def over_budget(self):
        self._roll()
        return config.GEMINI_GUNLUK_BUTCE_USD > 0 and self.spend["usd"] >= config.GEMINI_GUNLUK_BUTCE_USD

    def allowed(self, purpose):
        """Bu iş için şu an Gemini çağrılabilir mi? (ok, sebep)"""
        now = time.time()
        if now < self.paused_until:
            return False, (f"art arda {self.health['fails']} başarısız çağrı, "
                           f"{int((self.paused_until - now) / 60) + 1} dk mola")
        frac, budget = BUDGET_STOP.get(purpose), config.GEMINI_GUNLUK_BUTCE_USD
        if frac and budget > 0:
            self._roll()
            if self.spend["usd"] >= budget * frac:
                return False, (f"günlük Gemini bütçesinin %{frac * 100:.0f}'i harcandı "
                               f"(${self.spend['usd']:.3f} / ${budget:g})")
        return True, ""

    # ---------- sağlık ----------
    def _ok(self, model):
        h = self.health
        if h["fails"] and self._alerted["active"]:
            self._recovered = (time.time() - h["since"], model)
        h.update(fails=0, last_ok=time.time(), last_model=model, kind="")
        self.paused_until = 0.0
        self.last_fatal_error = None

    def _fail(self, kind, err):
        now = time.time()
        h = self.health
        if h["fails"] == 0:
            h["since"] = now
        h["fails"] += 1
        h["kind"], h["last_err"] = kind, err[:500]
        if kind in FATAL_KINDS or kind == "model_yok":
            self.last_fatal_error = err[:300]
        if h["fails"] >= config.AI_PAUSE_AFTER_FAILS:
            # Art arda hata: her çağrıda modelleri tek tek deneyip döngüyü bekletmesin, kısa mola ver
            self.paused_until = now + config.AI_PAUSE_MIN * 60

    def hint(self):
        h = self.health
        if h["kind"] == "anahtar":
            return ("🔑 API anahtarı geçersiz, süresi dolmuş ya da Google tarafından kapatılmış olabilir (anahtar herkese "
                    "açık bir yerde görünürse Google otomatik kapatır). aistudio.google.com/apikey adresinden yeni anahtar "
                    "oluştur, env.sh içindeki GEMINI_API_KEY'i değiştir ve botu yeniden başlat.")
        if h["kind"] == "fatura" or h["free_tier"]:
            return ("💳 Büyük ihtimalle kredi / faturalandırma sorunu: ücretli katman kredisi bitmiş olabilir. "
                    "aistudio.google.com → Billing (Faturalandırma) sayfasında kalan krediyi ve projenin ücretli katmanda "
                    "olduğunu kontrol et. Kullanım: aistudio.google.com/usage")
        if h["kind"] == "konum":
            return "🌍 Google, sunucunun bulunduğu ülkeden Gemini API kullanımına izin vermiyor (sunucu konumu)."
        if h["kind"] == "model_yok":
            return "🤖 Zincirdeki modellerin hiçbiri kullanılamıyor; bot model listesini 30 dk içinde kendisi yeniler."
        if h["kind"] == "baglanti":
            return "🌐 Sunucu Google'a bağlanamıyor (ağ / DNS sorunu) ya da Gemini kütüphanesi hata veriyor."
        return ("⏳ Kota veya yoğunluk sınırı. Saatlerce sürüyorsa kota/kredi bitmiş olabilir: aistudio.google.com/usage "
                "ve Billing sayfalarına bak.")

    def health_alert(self):
        """Bot döngüsü çağırır. Gönderilmesi gereken bir Telegram uyarısı varsa metnini döner, yoksa None."""
        now = time.time()
        h = self.health
        if self._recovered:
            dur, model = self._recovered
            self._recovered = None
            self._alerted = {"active": False, "sent": 0.0}
            return f"✅ <b>Gemini tekrar çalışıyor</b> ({_dur(dur)} süren kesintiden sonra, model: {_esc(model)})."
        fatal = h["kind"] in FATAL_KINDS
        if h["fails"] == 0 or (not fatal and h["fails"] < config.AI_ALERT_AFTER_FAILS):
            return None
        if self._alerted["active"] and now - self._alerted["sent"] < ALERT_REPEAT_SEC:
            return None
        self._alerted = {"active": True, "sent": now}
        return (f"⚠️ <b>Gemini çalışmıyor</b>\n"
                f"{fmt_ts(h['since'])} saatinden beri yanıt yok ({_dur(now - h['since'])}, art arda {h['fails']} "
                f"başarısız çağrı).\n<b>Son hata:</b> {_esc(h['last_err'][:400])}\n\n{self.hint()}\n\n"
                "Bot çalışmaya devam ediyor: listeleme duyuruları Gemini'siz alınır; haber analizi, hacim yorumu ve "
                "Piyasa Nabzı Gemini dönene kadar çalışmaz. Düzelince haber vereceğim.")

    def status_line(self):
        h = self.health
        if h["fails"]:
            return (f"❌ {fmt_ts(h['since'])} saatinden beri yanıt yok ({h['fails']} başarısız çağrı) — "
                    f"son hata: {h['last_err'][:160]}")
        if h["last_ok"]:
            return f"✅ çalışıyor (son yanıt {fmt_ts(h['last_ok'], with_date=False)}, {h['last_model']})"
        return "henüz çağrı yapılmadı"

    def spend_line(self):
        self._roll()
        s, budget, rate = self.spend, config.GEMINI_GUNLUK_BUTCE_USD, config.USD_TRY
        out = (f"bugün ${s['usd']:.3f}" + (f" / ${budget:g} bütçe" if budget > 0 else "")
               + f" (≈{s['usd'] * rate:.1f} TL) | bu ay ${s['month_usd']:.2f} (≈{s['month_usd'] * rate:.0f} TL)")
        by = sorted(s["by"].items(), key=lambda kv: -kv[1])
        if by:
            out += "\nDağılım: " + ", ".join(f"{PURPOSE_NAMES.get(k, k)} ${v:.3f} ({s['calls'].get(k, 0)} çağrı)"
                                             for k, v in by)
        if self.over_budget():
            out += "\n⏸️ Günlük bütçe doldu: hacim yorumu ve Piyasa Nabzı gece yarısına kadar duraklatıldı."
        elif budget > 0 and s["usd"] >= budget * BUDGET_STOP["nabiz"]:
            out += (f"\n⏸️ Bütçenin %{BUDGET_STOP['nabiz'] * 100:.0f}'i harcandı: Piyasa Nabzı gece yarısına kadar "
                    "duraklatıldı.")
        return out

    # ---------- çağrı ----------
    def _call(self, chain, prompt, kind, purpose):
        """Zincirdeki modelleri sırayla dener. (metin, model) veya (None, None) döner."""
        ok, why = self.allowed(purpose)
        if not ok:
            self._inc("skipped")
            print(f"⏸️ Gemini çağrısı atlandı ({PURPOSE_NAMES.get(purpose, purpose)}): {why}")
            return None, None
        now = time.time()
        if now - self.discovered_at > REDISCOVER_SEC or (self.health["fails"] >= 10 and now - self.discovered_at > 1800):
            self.rediscover()
        retries = config.GEMINI_RETRIES_PER_MODEL if chain != "review" else 1
        order = [m for m in (self.chains.get(chain) or self.chains["main"]) if m not in self.dead]
        order.sort(key=lambda m: self.cooldown.get(m, 0) > now)   # dinlenen modeller sona
        good = self.last_good.get(chain)
        if good in order:
            order.remove(good)
            order.insert(0, good)
        if not order:
            self._fail("model_yok", "Hiçbir Gemini modeli kullanılamıyor (hepsi 404/400 ya da kota 0 verdi).")
            return None, None

        err_kind, last_err = "yogun", ""
        for mi, model in enumerate(order[:MAX_MODELS_PER_CALL]):
            if mi > 0:
                print(f"🔁 Yedek modele geçiliyor: {model}")
            attempts, delay, cool = 0, 2, 0
            while attempts < retries:
                try:
                    cfg = self._config(model, kind)
                except Exception as e:   # eski kütüphane yeni ayarı tanımıyorsa düşünme ayarı olmadan dene
                    if model in self.no_thinking_cfg:
                        print(f"❌ {model} için istek ayarı kurulamadı ({e}), listeden çıkarıldı.")
                        self.dead.add(model)
                        err_kind, last_err = "baglanti", f"istek ayarı kurulamadı: {e}"[:500]
                        break
                    print(f"ℹ️ {model} için ayar kurulamadı ({e}), düşünme ayarı olmadan denenecek.")
                    self.no_thinking_cfg.add(model)
                    continue
                try:
                    self._inc("calls")
                    resp = self.client.models.generate_content(model=model, contents=prompt, config=cfg)
                    self._track_cost(model, resp, purpose)
                    text = resp.text
                    if not text or (kind != "text" and not re.search(r"\{.*\}", text, re.DOTALL)):
                        attempts += 1
                        err_kind, last_err = "yogun", f"{model} boş/JSON olmayan yanıt verdi"
                        print(f"⚠️ {last_err}.")
                        continue
                    if mi > 0:
                        self._inc("fallbacks")
                    self.cooldown.pop(model, None)
                    self.last_good[chain] = model
                    self._ok(model)
                    return text, model
                except errors.APIError as e:
                    self._inc("errors")
                    code = getattr(e, "code", 0) or 0
                    low = str(e).lower()
                    last_err = _err_text(e)
                    if "free_tier" in low:
                        self.health["free_tier"] = True
                    fatal = None
                    if code in (401, 403) or "api key" in low or "api_key" in low:
                        fatal = "anahtar"
                    elif "location is not supported" in low or "not available in your country" in low:
                        fatal = "konum"
                    elif (any(w in low for w in ("prepay", "credit", "billing account", "spending cap", "spend cap"))
                          or (code == 400 and "billing" in low)):
                        fatal = "fatura"
                    if fatal:
                        # Anahtar / fatura / konum sorunu: başka modeli denemek de boşuna
                        print(f"❌ GEMINI API HATASI ({fatal}) {last_err}")
                        self._fail(fatal, last_err)
                        return None, None
                    if code == 404:
                        print(f"❌ Model artık kullanılamıyor, listeden çıkarıldı: {model}")
                        self.dead.add(model)
                        err_kind = "model_yok"
                        break
                    if code == 429 and re.search(r"limit\W{0,3}0\b", low):
                        print(f"❌ {model} bu anahtarın katmanında kullanılamıyor (kota 0), listeden çıkarıldı.")
                        self.dead.add(model)
                        err_kind = "kota"
                        break
                    if code == 400:
                        if model not in self.no_thinking_cfg:
                            self.no_thinking_cfg.add(model)
                            print(f"ℹ️ {model} ayarları kabul etmedi, düşünme ayarı olmadan tekrar deneniyor.")
                            continue
                        print(f"❌ {model} isteği reddetti (400), listeden çıkarıldı: {last_err[:150]}")
                        self.dead.add(model)
                        err_kind = "model_yok"
                        break
                    attempts += 1
                    if code == 429:
                        # Kota: aynı modeli hemen tekrar denemek boşuna; günlük kota ise daha uzun dinlendir
                        err_kind = "kota"
                        cool = max(cool, 3600 if ("perday" in low or "per_day" in low) else MODEL_COOLDOWN_SEC)
                        attempts = retries
                        print(f"⏳ Gemini {model} kota sınırı (429): {last_err[:200]}")
                        continue
                    if code in (500, 502, 503, 504):
                        err_kind = "yogun"
                        cool = max(cool, MODEL_COOLDOWN_SEC)
                    if attempts < retries:
                        print(f"⏳ Gemini {model} hata ({code}). {delay} sn sonra tekrar ({attempts}/{retries})")
                        time.sleep(delay)
                        delay = min(delay * 2, 15)
                    else:
                        print(f"⏳ Gemini {model} hata ({code}): {last_err[:200]}")
                except Exception as e:
                    self._inc("errors")
                    attempts += 1
                    err_kind, last_err = "baglanti", f"{type(e).__name__}: {e}"[:500]
                    print(f"❌ Gemini bağlantı hatası ({model}): {e}")
                    if attempts < retries:
                        time.sleep(delay)
                        delay = min(delay * 2, 15)
            if cool:
                self.cooldown[model] = time.time() + cool
                print(f"😴 {model} {cool // 60} dk dinlendiriliyor, bu sürede yedek model öncelikli.")
        self._fail(err_kind, last_err or "bilinmeyen hata")
        return None, None

    @staticmethod
    def _json(text):
        m = re.search(r"\{.*\}", text or "", re.DOTALL)
        return json.loads(m.group()) if m else None

    # ---------- 1) haber analizi ----------
    def analyze(self, item):
        """Olguları çıkarır ve puanı hesaplar. Başarısızsa None (haber sonraki turda tekrar denenir)."""
        age = max(0, int((time.time() - item["published"]) / 60))
        prompt = FACTS_PROMPT.format(source=item["source"], age=age, title=item["title"],
                                     summary=item["summary"] or "-", categories=item["categories"] or "-")
        print(f"🧠 Gemini -> [{item['source']}] {item['title'][:70]}")
        text, model = self._call("cheap", prompt, "fast", "haber")
        if text is None:
            return None
        try:
            raw = self._json(text)
        except (json.JSONDecodeError, ValueError) as e:
            print(f"⚠️ JSON çözümlenemedi: {e}")
            return None
        if not isinstance(raw, dict):
            return None
        return self.build_result(raw, model)

    @staticmethod
    def build_result(raw, model=""):
        f = {"hedef_coin": clean_coin(raw.get("hedef_coin")),
             "olay_turu": str(raw.get("olay_turu", "diger")).strip().lower(),
             "coin_ozel": _as_bool(raw.get("coin_ozel", False)),
             "fiyat_zaten_hareket_etti": _as_bool(raw.get("fiyat_zaten_hareket_etti", False)),
             "sebep": str(raw.get("sebep", "")).strip()}
        if f["olay_turu"] not in EVENT_TYPES:
            f["olay_turu"] = "diger"
        for key, allowed in ENUMS.items():
            val = str(raw.get(key, "")).strip().lower()
            f[key] = val if val in allowed else DEFAULTS[key]
        score, notes = compute_score(f)
        coin_ok = f["hedef_coin"] != "GENEL" and f["hedef_coin"] not in STABLES
        f.update({
            "puan": float(score),
            "puan_notu": "; ".join(notes),
            "karar": "BUY" if score >= config.BUY_MIN_SCORE and f["yon"] == "olumlu" and coin_ok else "PASS",
            "model": model,
        })
        print(f"🤖 [{model}] {f['karar']} | Puan: {score}/10 | Coin: {f['hedef_coin']} | "
              f"{f['olay_turu']}/{f['kesinlik']}/{f['yenilik']}/{f['aktor']}\n📝 {f['sebep']}")
        return f

    # ---------- 2) ikinci görüş ----------
    def review(self, item, res, ctx, regime_text):
        """Şeytanın avukatı. {"onay", "guven", "sebep", "karsi", "model"} veya None döner."""
        age = max(0, int((time.time() - item["published"]) / 60))
        ch24 = ctx.get("coin_ch24")
        vol = ctx.get("coin_volume")
        since = ctx.get("late_move")
        prompt = REVIEW_PROMPT.format(
            source=item["source"], age=age, title=item["title"], summary=item["summary"] or "-",
            olay_turu=res["olay_turu"], kesinlik=res["kesinlik"], yenilik=res["yenilik"],
            aktor=res["aktor"], olcek=res["olcek"], puan=int(res["puan"]), coin=res["hedef_coin"],
            ch24=f"{ch24:+.2f}%" if ch24 is not None else "bilinmiyor",
            vol=f"{vol / 1e6:,.1f} milyon USDT" if vol else "bilinmiyor",
            since=f"{since:+.2f}%" if since is not None else "bilinmiyor",
            regime=regime_text)
        print(f"🧐 İkinci görüş isteniyor: {res['hedef_coin']} ({int(res['puan'])}/10)")
        text, model = self._call("review", prompt, "deep", "ikinci_gorus")
        if text is None:
            return None
        try:
            raw = self._json(text) or {}
        except (json.JSONDecodeError, ValueError):
            return None
        try:
            guven = float(raw.get("guven", 0))
        except (TypeError, ValueError):
            guven = 0.0
        karsi = raw.get("karsi_nedenler") or []
        if isinstance(karsi, str):
            karsi = [karsi]
        out = {"onay": _as_bool(raw.get("onay", False)) and guven >= config.REVIEW_MIN_CONFIDENCE,
               "model_onay": _as_bool(raw.get("onay", False)), "guven": guven,
               "sebep": str(raw.get("sebep", "")).strip(), "karsi": [str(k) for k in karsi][:3], "model": model}
        print(f"🧐 [{model}] {'ONAY' if out['onay'] else 'RED'} (güven {guven:.0f}) — {out['sebep']}")
        return out

    # ---------- 3) piyasa nabzı ----------
    def pulse_analysis(self, data_text):
        """Saatlik piyasa yorumu + izleme listesi. dict veya None döner."""
        prompt = PULSE_PROMPT.format(data=data_text)
        text, model = self._call("main", prompt, "pulse", "nabiz")
        try:
            raw = self._json(text) if text else None
        except (json.JSONDecodeError, ValueError):
            raw = None
        if not isinstance(raw, dict):
            return None

        def coins(items, with_guc):
            out = []
            for it in items or []:
                if not isinstance(it, dict):
                    continue
                coin = clean_coin(it.get("coin"))
                if coin in ("GENEL", "") or coin in STABLES:
                    continue
                entry = {"coin": coin, "neden": str(it.get("neden", "")).strip()[:160]}
                if with_guc:
                    try:
                        entry["guc"] = max(1, min(3, int(float(it.get("guc", 1)))))
                    except (TypeError, ValueError):
                        entry["guc"] = 1
                out.append(entry)
            return out[:8]
        duygu = str(raw.get("duygu", "notr")).lower()
        return {"ozet": str(raw.get("ozet", "")).strip(), "duygu": duygu if duygu in ENUMS["yon"] else "notr",
                "anlatilar": [str(x) for x in (raw.get("sicak_anlatilar") or [])][:6],
                "izleme": coins(raw.get("izleme_listesi"), True), "uzak_dur": coins(raw.get("uzak_dur"), False),
                "model": model}

    # ---------- 4) hacim patlaması yorumu ----------
    def judge_spike(self, coin, move, ratio, vol, ch24, trending, watch, pulse, regime, headlines):
        prompt = SPIKE_PROMPT.format(coin=coin, move=move, ratio=ratio, vol=vol, ch24=ch24, trending=trending,
                                     watch=watch, pulse=pulse, regime=regime, headlines=headlines)
        text, model = self._call("main", prompt, "fast", "hacim")
        try:
            raw = self._json(text) if text else None
        except (json.JSONDecodeError, ValueError):
            raw = None
        if not isinstance(raw, dict):
            return None
        try:
            guc = max(0.0, min(10.0, float(raw.get("guc", 0))))
        except (TypeError, ValueError):
            guc = 0.0
        out = {"hikaye_var": _as_bool(raw.get("hikaye_var", False)), "guc": guc,
               "katalizor": str(raw.get("katalizor", "")).strip()[:200], "risk": str(raw.get("risk", "")).strip()[:200],
               "sebep": str(raw.get("sebep", "")).strip()[:300], "model": model}
        print(f"🔎 [{model}] {coin} hacim patlaması: {'HİKÂYE VAR' if out['hikaye_var'] else 'hikâye yok'} "
              f"(güç {guc:.0f}) — {out['sebep']}")
        return out

    # ---------- 5) gece raporu yorumu ----------
    def commentary(self, data_text):
        prompt = REPORT_PROMPT.format(data=data_text, stop=f"{config.HARD_STOP_PCT:g}",
                                      ts=f"{config.TIME_STOP_MIN:g}")
        text, _ = self._call("main", prompt, "text", "rapor")
        return text
