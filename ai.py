"""Gemini analizi: 503/429 hatalarında bekle-tekrar dene, olmazsa yedek modele geç."""
import json
import re
import time

from google import genai
from google.genai import errors, types

import config

# Yaklaşık fiyatlar ($ / 1M token) -> sadece özet mesajındaki maliyet tahmini için
PRICES = {
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-flash-lite": (0.10, 0.40),
}

PROMPT = """Sen agresif ama disiplinli bir kripto haber-trader'ısın. Amacın: haberin, yayınlandıktan
sonraki birkaç saat içinde ilgili coinin SPOT fiyatını YUKARI itip itmeyeceğini tahmin etmek.

Haber kaynağı: {source}
Yayınlanalı: {age} dakika
Başlık: "{title}"
Özet: "{summary}"
Kategoriler: {categories}

Puanlama kuralları (1-10):
- 9-10: Nadir ve güçlü katalizör. Örn: Binance/Coinbase/Upbit listelemesi, spot ETF onayı,
  dev şirket/devlet ile somut entegrasyon, büyük hack'in geri ödenmesi, token yakımı/arz şoku.
- 7-8: Belirgin olumlu, somut haber (ortaklık, ana ağ lansmanı, büyük kurumsal alım, ETF başvurusu ilerlemesi).
- 5-6: Hafif olumlu / belirsiz etki.
- 1-4: Olumsuz haber (hack, dava, delist, satış baskısı) VEYA fiyatı hareket ettirmeyecek içerik.
- Fiyat tahmini/analist yorumu/teknik analiz makaleleri ("X coin $100'e gidebilir", "fiyat analizi") en fazla 5 alır.
- Haber zaten gerçekleşmiş bir yükselişi anlatıyorsa ("XRP %15 yükseldi") fırsat kaçmıştır, en fazla 5 alır.
- Sadece büyük coin (BTC/ETH) hakkındaki genel makro haberler zor hareket ettirir, temkinli puanla.

hedef_coin: Haberden en çok etkilenecek TEK coinin Binance ticker sembolü (ör. SOL, XRP, DOGE, PEPE).
Belirli bir coin yoksa veya genel piyasa haberi ise "GENEL" yaz. Stablecoin (USDT, USDC) hedef olamaz.
karar: puan >= 7 ve hedef_coin belirliyse "BUY", aksi halde "PASS".
sebep: Türkçe, en fazla 2 cümle.

Sadece şu JSON'u döndür:
{{"karar": "BUY", "puan": 8, "hedef_coin": "SOL", "sebep": "..."}}"""


class GeminiAnalyzer:
    def __init__(self):
        self.client = genai.Client(api_key=config.GEMINI_API_KEY)
        self.stats = {"calls": 0, "errors": 0, "cost_usd": 0.0, "fallbacks": 0}
        self.last_fatal_error = None

    def _config_for(self, model):
        kwargs = dict(temperature=0.2, response_mime_type="application/json", max_output_tokens=400)
        # 2.5 serisinde "düşünme" kapatılır: daha hızlı ve daha ucuz yanıt.
        if "2.5-flash" in model:
            kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
        return types.GenerateContentConfig(**kwargs)

    def _track_cost(self, model, response):
        um = getattr(response, "usage_metadata", None)
        if not um:
            return
        pin, pout = PRICES.get(model, (0.30, 2.50))
        tin = um.prompt_token_count or 0
        tout = (um.candidates_token_count or 0) + (getattr(um, "thoughts_token_count", 0) or 0)
        self.stats["cost_usd"] += tin / 1e6 * pin + tout / 1e6 * pout

    @staticmethod
    def _parse(text):
        m = re.search(r"\{.*\}", text or "", re.DOTALL)
        if not m:
            return None
        data = json.loads(m.group())
        try:
            puan = float(data.get("puan", 0))
        except (TypeError, ValueError):
            puan = 0.0
        coin = str(data.get("hedef_coin") or "GENEL").upper()
        coin = re.split(r"[\s,/|]+", coin.replace("$", "").strip())[0] if coin.strip() else "GENEL"
        coin = re.sub(r"[^A-Z0-9]", "", coin)
        if coin.endswith("USDT") and len(coin) > 4:
            coin = coin[:-4]
        return {
            "karar": str(data.get("karar", "PASS")).upper().strip(),
            "puan": max(0.0, min(10.0, puan)),
            "hedef_coin": coin or "GENEL",
            "sebep": str(data.get("sebep", "")).strip(),
        }

    def analyze(self, item):
        """Başarılıysa sonuç dict'i, tüm denemeler başarısızsa None döner (haber sonraki turda tekrar denenir)."""
        age = max(0, int((time.time() - item["published"]) / 60))
        prompt = PROMPT.format(source=item["source"], age=age, title=item["title"],
                               summary=item["summary"] or "-", categories=item["categories"] or "-")
        print(f"🧠 Gemini -> [{item['source']}] {item['title'][:70]}")

        for mi, model in enumerate(config.GEMINI_MODELS):
            delay = 2
            for attempt in range(config.GEMINI_RETRIES_PER_MODEL):
                try:
                    self.stats["calls"] += 1
                    resp = self.client.models.generate_content(
                        model=model, contents=prompt, config=self._config_for(model))
                    self._track_cost(model, resp)
                    result = self._parse(resp.text)
                    if result is None:
                        print("⚠️ Gemini yanıtı JSON değil, tekrar deneniyor.")
                        continue
                    if mi > 0:
                        self.stats["fallbacks"] += 1
                    self.last_fatal_error = None
                    print(f"🤖 [{model}] {result['karar']} | Puan: {result['puan']:.0f}/10 | "
                          f"Coin: {result['hedef_coin']}\n📝 {result['sebep']}")
                    return result
                except errors.APIError as e:
                    self.stats["errors"] += 1
                    code = getattr(e, "code", 0) or 0
                    if code in (429, 500, 502, 503, 504):
                        print(f"⏳ Gemini {model} yoğun ({code}). {delay} sn sonra tekrar "
                              f"({attempt + 1}/{config.GEMINI_RETRIES_PER_MODEL})")
                        time.sleep(delay)
                        delay = min(delay * 2, 15)
                        continue
                    if code == 404:
                        print(f"❌ Model bulunamadı: {model}. Sonraki modele geçiliyor.")
                        break
                    # 400/401/403: anahtar veya faturalandırma sorunu -> tekrar denemek boşuna
                    self.last_fatal_error = f"{code}: {str(e)[:300]}"
                    print(f"❌ GEMINI API HATASI {self.last_fatal_error}")
                    return None
                except (json.JSONDecodeError, ValueError) as e:
                    print(f"⚠️ JSON çözümlenemedi: {e}")
                except Exception as e:
                    self.stats["errors"] += 1
                    print(f"❌ Gemini bağlantı hatası: {e}")
                    time.sleep(delay)
                    delay = min(delay * 2, 15)
            if mi + 1 < len(config.GEMINI_MODELS):
                print(f"🔁 Yedek modele geçiliyor: {config.GEMINI_MODELS[mi + 1]}")
        return None
