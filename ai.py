"""Gemini: haberden olgu çıkarma (puanı kod hesaplar), ikinci görüş ve gece raporu yorumu.

Neden olgu? Yapay zekaya doğrudan "puan ver" denince fazla iyimser oluyor (gereksiz 8/10'lar).
Bu yüzden Gemini sadece haberin ne olduğunu söylüyor (olay türü, kesinlik, yenilik, aktör...),
puanı aşağıdaki sabit tablo hesaplıyor. Alım adayları ayrıca güçlü bir modele
"bu haber neden fiyatı yükseltmez?" diye soruluyor.

Model seçimi: 503/429 gelirse bekleyip tekrar dener, olmazsa yedek modele geçer; yoğun modeli
10 dk dinlendirir, son başarılı modeli hep önce dener, kullanımdan kalkmış modeli listeden atar.
"""
import json
import re
import time

from google import genai
from google.genai import errors, types

import config

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


class GeminiAnalyzer:
    def __init__(self):
        self.client = genai.Client(api_key=config.GEMINI_API_KEY)
        self.stats = {"calls": 0, "errors": 0, "cost_usd": 0.0, "fallbacks": 0}
        self.day = dict(self.stats)
        self.last_fatal_error = None
        self.no_thinking_cfg = set()
        self.dead = set()
        self.cooldown = {}
        self.last_good = {}
        self.available = []
        self.chains = self._resolve_chains()
        self.models = self.chains["main"]

    # ---------- model seçimi ----------
    def _resolve_chains(self):
        try:
            names = []
            for m in self.client.models.list():
                actions = m.supported_actions or []
                if actions and "generateContent" not in actions:
                    continue
                names.append(m.name.replace("models/", ""))
            self.available = names
        except Exception as e:
            print(f"⚠️ Model listesi alınamadı ({e}), env'deki modeller kullanılacak.")
            main = config.GEMINI_MODELS or ["gemini-flash-latest", "gemini-flash-lite-latest"]
            return {"main": main, "review": (config.REVIEW_MODELS or ["gemini-pro-latest"]) + main}

        usable = [n for n in names if n.startswith("gemini") and not any(w in n for w in _SKIP_WORDS)]
        flash = [n for n in usable if "flash" in n and "latest" not in n]
        full_flash = [n for n in flash if "lite" not in n]
        lite = [n for n in flash if "lite" in n]
        pro = [n for n in usable if "pro" in n and "latest" not in n]

        main = [m for m in config.GEMINI_MODELS if m in names]
        for m in _newest(full_flash, 2) + _newest(lite, 1):
            if m not in main:
                main.append(m)
        if not main:
            main = list(config.GEMINI_MODELS) or names[:1]

        review = [m for m in config.REVIEW_MODELS if m in names]
        extra = _newest(pro, 2) + (["gemini-pro-latest"] if "gemini-pro-latest" in names else [])
        for m in extra + [m for m in main if "lite" not in m] + main:
            if m not in review:
                review.append(m)

        for env_name, wanted in (("GEMINI_MODELS", config.GEMINI_MODELS), ("REVIEW_MODELS", config.REVIEW_MODELS)):
            missing = [m for m in wanted if m not in names]
            if missing:
                print(f"⚠️ {env_name} içindeki bu modeller erişilebilir değil: {', '.join(missing)}")
        print(f"🤖 Haber analizi modelleri: {', '.join(main)}")
        print(f"🧐 İkinci görüş / rapor modelleri: {', '.join(review)}")
        return {"main": main, "review": review}

    def _config(self, model, kind):
        deep = kind != "fast"
        kwargs = dict(
            temperature=0.4 if kind == "text" else 0.2,
            max_output_tokens={"fast": 1500, "deep": 4000, "text": 8000}[kind],
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

    def _inc(self, key, val=1):
        self.stats[key] += val
        self.day[key] += val

    def reset_day(self):
        self.day = {k: 0 if k != "cost_usd" else 0.0 for k in self.day}

    def _track_cost(self, model, response):
        um = getattr(response, "usage_metadata", None)
        if not um:
            return
        pin, pout = _price(model)
        tin = getattr(um, "prompt_token_count", 0) or 0
        tout = (getattr(um, "candidates_token_count", 0) or 0) + (getattr(um, "thoughts_token_count", 0) or 0)
        self._inc("cost_usd", tin / 1e6 * pin + tout / 1e6 * pout)

    def _call(self, chain, prompt, kind):
        """Zincirdeki modelleri sırayla dener. (metin, model) veya (None, None) döner."""
        retries = config.GEMINI_RETRIES_PER_MODEL if chain == "main" else 1
        now = time.time()
        order = [m for m in self.chains[chain] if m not in self.dead]
        order.sort(key=lambda m: self.cooldown.get(m, 0) > now)   # dinlenen modeller sona
        good = self.last_good.get(chain)
        if good in order:
            order.remove(good)
            order.insert(0, good)
        if not order:
            self.last_fatal_error = "Hiçbir Gemini modeli kullanılamıyor (hepsi 404/400 verdi)."
            return None, None

        for mi, model in enumerate(order):
            if mi > 0:
                print(f"🔁 Yedek modele geçiliyor: {model}")
            attempts, delay, overloaded = 0, 2, False
            while attempts < retries:
                try:
                    self._inc("calls")
                    resp = self.client.models.generate_content(
                        model=model, contents=prompt, config=self._config(model, kind))
                    self._track_cost(model, resp)
                    text = resp.text
                    if not text or (kind != "text" and not re.search(r"\{.*\}", text, re.DOTALL)):
                        attempts += 1
                        print(f"⚠️ {model} boş/JSON olmayan yanıt verdi.")
                        continue
                    if mi > 0:
                        self._inc("fallbacks")
                    self.cooldown.pop(model, None)
                    self.last_good[chain] = model
                    self.last_fatal_error = None
                    return text, model
                except errors.APIError as e:
                    self._inc("errors")
                    code = getattr(e, "code", 0) or 0
                    msg = str(e)
                    low = msg.lower()
                    if code in (401, 403) or "api key" in low or "api_key" in low or "billing" in low:
                        # Anahtar / faturalandırma sorunu: başka modeli denemek de boşuna
                        self.last_fatal_error = f"{code}: {msg[:300]}"
                        print(f"❌ GEMINI API HATASI {self.last_fatal_error}")
                        return None, None
                    if code == 404:
                        print(f"❌ Model artık kullanılamıyor, listeden çıkarıldı: {model}")
                        self.dead.add(model)
                        break
                    if code == 400:
                        if model not in self.no_thinking_cfg:
                            self.no_thinking_cfg.add(model)
                            print(f"ℹ️ {model} ayarları kabul etmedi, düşünme ayarı olmadan tekrar deneniyor.")
                            continue
                        print(f"❌ {model} isteği reddetti (400), listeden çıkarıldı: {msg[:150]}")
                        self.dead.add(model)
                        break
                    overloaded = overloaded or code in (429, 500, 502, 503, 504)
                    attempts += 1
                    if attempts < retries:
                        print(f"⏳ Gemini {model} yoğun ({code}). {delay} sn sonra tekrar ({attempts}/{retries})")
                        time.sleep(delay)
                        delay = min(delay * 2, 15)
                    else:
                        print(f"⏳ Gemini {model} yoğun ({code}).")
                except Exception as e:
                    self._inc("errors")
                    attempts += 1
                    print(f"❌ Gemini bağlantı hatası ({model}): {e}")
                    if attempts < retries:
                        time.sleep(delay)
                        delay = min(delay * 2, 15)
            if overloaded:
                self.cooldown[model] = time.time() + MODEL_COOLDOWN_SEC
                print(f"😴 {model} {MODEL_COOLDOWN_SEC // 60} dk dinlendiriliyor, bu sürede yedek model öncelikli.")
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
        text, model = self._call("main", prompt, "fast")
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
        text, model = self._call("review", prompt, "deep")
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

    # ---------- 3) gece raporu yorumu ----------
    def commentary(self, data_text):
        prompt = REPORT_PROMPT.format(data=data_text, stop=f"{config.HARD_STOP_PCT:g}",
                                      ts=f"{config.TIME_STOP_MIN:g}")
        text, _ = self._call("review", prompt, "text")
        if text is None:
            text, _ = self._call("main", prompt, "text")
        return text
