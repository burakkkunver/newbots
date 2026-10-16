"""Gemini sağlık takibi, hata sınıflandırması, devre kesici, uyarılar, günlük bütçe ve amaca göre model zinciri."""
import os
import shutil
import sys
from types import SimpleNamespace as N

SP = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(SP, "data_aihealth")
shutil.rmtree(DATA, ignore_errors=True)
os.environ.update(DATA_DIR=DATA, TELEGRAM_BOT_TOKEN="x", TELEGRAM_CHAT_ID="1", GEMINI_API_KEY="k",
                  BINANCE_API_KEY="a", BINANCE_SECRET="b")
sys.path.insert(0, os.path.dirname(SP))
sys.path.insert(0, SP)
import sim as S  # noqa: E402
import time  # noqa: E402
time.sleep = lambda s: None
import config  # noqa: E402
from util import now_local, today_str  # noqa: E402

_n = now_local()
S.CLOCK["offset"] += _n.replace(hour=9, minute=0, second=0, microsecond=0).timestamp() - _n.timestamp()

import ai as A  # noqa: E402
from google.genai import errors  # noqa: E402

n_ok = 0


def check(c, m):
    global n_ok
    assert c, m
    n_ok += 1
    print("  ✓", m)


MODELS = ["gemini-3.5-flash", "gemini-3.7-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.1-pro-preview",
          "gemini-flash-latest", "gemini-flash-lite-latest", "gemini-pro-latest", "text-embedding-004",
          "gemini-3.7-flash-tts"]
OK_JSON = ('{"hedef_coin":"SOL","olay_turu":"listeleme","kesinlik":"resmi","yenilik":"yeni","aktor":"birinci_lig",'
           '"olcek":"orta","coin_ozel":true,"fiyat_zaten_hareket_etti":false,"yon":"olumlu","sebep":"x",'
           '"hikaye_var":true,"guc":8,"katalizor":"k","risk":"r","karsi_nedenler":[],"onay":true,"guven":70,'
           '"ozet":"o","duygu":"notr","izleme_listesi":[]}')


def err(cls, code, status, message, details=None):
    body = {"error": {"code": code, "status": status, "message": message}}
    if details:
        body["error"]["details"] = details
    return cls(code, body)


BEHAVIOR = {
    "busy": lambda: err(errors.ServerError, 503, "UNAVAILABLE", "The model is overloaded. Please try again later."),
    "quota": lambda: err(errors.ClientError, 429, "RESOURCE_EXHAUSTED",
                         "You exceeded your current quota, please check your plan and billing details.",
                         [{"@type": "type.googleapis.com/google.rpc.QuotaFailure",
                           "violations": [{"quotaId": "GenerateRequestsPerMinutePerProjectPerModel"}]}]),
    "quota_day": lambda: err(errors.ClientError, 429, "RESOURCE_EXHAUSTED",
                             "You exceeded your current quota, please check your plan and billing details.",
                             [{"@type": "type.googleapis.com/google.rpc.QuotaFailure",
                               "violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}]),
    "limit0": lambda: err(errors.ClientError, 429, "RESOURCE_EXHAUSTED",
                          "You exceeded your current quota. * Quota exceeded for metric: "
                          "generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 0, model: x"),
    "badkey": lambda: err(errors.ClientError, 400, "INVALID_ARGUMENT", "API key not valid. Please pass a valid API key."),
    "leaked": lambda: err(errors.ClientError, 403, "PERMISSION_DENIED",
                          "Your API key was reported as leaked. Please use another API key."),
    "credits": lambda: err(errors.ClientError, 429, "RESOURCE_EXHAUSTED",
                           "Your prepayment credits are depleted. Please go to AI Studio to manage your project and billing."),
    "conn": lambda: ConnectionError("Name or service not known"),
}


class FakeModels:
    def __init__(self):
        self.mode, self.default, self.calls, self.list_calls = {}, "ok", [], 0
        self.tokens = (100000, 10000)

    def list(self):
        self.list_calls += 1
        return [N(name="models/" + n, supported_actions=["generateContent"]) for n in MODELS]

    def generate_content(self, model, contents, config):
        self.calls.append(model)
        b = self.mode.get(model, self.default)
        if b == "ok":
            return N(text=OK_JSON, usage_metadata=N(prompt_token_count=self.tokens[0],
                                                    candidates_token_count=self.tokens[1], thoughts_token_count=0))
        raise BEHAVIOR[b]()


fm = FakeModels()
A.genai.Client = lambda api_key: N(models=fm)
ITEM = {"title": "Upbit lists SOL", "summary": "", "source": "T", "published": S.fake_time() - 60, "categories": ""}


def spike(ai):
    return ai.judge_spike(coin="SOL", move=3, ratio=4, vol="1M", ch24="+5%", trending="hayır", watch="hayır",
                          pulse="-", regime="Boğa", headlines="- yok")


print("1) Amaca göre model zincirleri")
ai = A.GeminiAnalyzer()
check(ai.chains["main"] == ["gemini-3.7-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-flash-latest",
                            "gemini-flash-lite-latest"], f"hacim/nabız/rapor: {ai.chains['main']}")
check(ai.chains["cheap"][:3] == ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-flash-lite-latest"],
      f"haber analizi (ucuz): {ai.chains['cheap']}")
check(ai.chains["review"][:2] == ["gemini-3.1-pro-preview", "gemini-pro-latest"], f"ikinci görüş: {ai.chains['review']}")
check(not any("embedding" in m or "tts" in m for c in ai.chains.values() for m in c), "embedding/tts modelleri yok")

print("2) Başarılı çağrı: harcama amaca göre kaydedilir, dosyaya yazılır")
r = ai.analyze(ITEM)
check(r and fm.calls == ["gemini-3.5-flash-lite"], "haber analizi ucuz lite modelle yapıldı")
cost_lite = 0.1 * 0.10 + 0.01 * 0.40
check(abs(ai.spend["by"]["haber"] - cost_lite) < 1e-9 and ai.spend["calls"]["haber"] == 1, "harcama: haber analizi")
check(ai.status_line().startswith("✅ çalışıyor") and "gemini-3.5-flash-lite" in ai.status_line(), ai.status_line())
again = A.GeminiAnalyzer()
check(abs(again.spend["usd"] - cost_lite) < 1e-9, "yeniden başlatınca bugünkü harcama hatırlanıyor (bütçe sıfırlanmaz)")

print("3) Günlük bütçe: önce nabız (%70), sonra hacim yorumu (%100) durur; haber analizi devam eder")
config.GEMINI_GUNLUK_BUTCE_USD = 0.1
fm.calls.clear()
check(spike(ai) is not None and fm.calls == ["gemini-3.7-flash"], "hacim yorumu flash modelle")
check(not ai.allowed("nabiz")[0] and ai.allowed("hacim")[0], f"harcama ${ai.spend['usd']:.3f}: nabız durdu, hacim sürüyor")
calls = len(fm.calls)
check(ai.pulse_analysis("veri") is None and len(fm.calls) == calls and ai.day["skipped"] == 1,
      "nabız API'ye gitmeden atlandı")
spike(ai)
check(ai.over_budget() and not ai.allowed("hacim")[0], f"harcama ${ai.spend['usd']:.3f}: bütçe doldu, hacim durdu")
check(ai.analyze(ITEM) is not None and ai.review(ITEM, r, {}, "Boğa") is not None, "haber analizi ve ikinci görüş sürüyor")
check("bütçe doldu" in ai.spend_line() and "hacim yorumu" in ai.spend_line() and "TL" in ai.spend_line(), ai.spend_line())
month_before, month_usd = today_str()[:7], ai.spend["month_usd"]
S.advance(24 * 60)
check(not ai.over_budget() and ai.spend["usd"] == 0 and ai.day["calls"] == 0, "gece yarısı günlük sayaçlar sıfırlandı")
if today_str()[:7] == month_before:
    check(abs(ai.spend["month_usd"] - month_usd) < 1e-9, "aylık toplam korunuyor")
config.GEMINI_GUNLUK_BUTCE_USD = 0          # sonraki bölümlerde bütçe sınırı karışmasın

print("4) Art arda kota hatası: 5'te uyarı, 6'da mola, düzelince 'tekrar çalışıyor'")
fm.default = "quota"
fm.calls.clear()
check(ai.analyze(ITEM) is None and ai.health["fails"] == 1 and ai.health["kind"] == "kota", "ilk hata: kota")
check(len(fm.calls) == len(set(fm.calls)) == A.MAX_MODELS_PER_CALL, f"429'da aynı model tekrar denenmedi: {fm.calls}")
check(all(m in ai.cooldown for m in fm.calls), "kota veren modeller dinlendirildi")
check(ai.health_alert() is None, "tek hatada uyarı yok")
for _ in range(4):
    ai.analyze(ITEM)
msg = ai.health_alert()
check(msg and "Gemini çalışmıyor" in msg and "429" in msg and "GenerateRequestsPerMinute" in msg, "5 hatada uyarı (kod + kota kimliği)")
check(ai.health_alert() is None, "aynı kesinti için 6 saat içinde tekrar uyarı yok")
ai.analyze(ITEM)
ok, why = ai.allowed("haber")
check(not ok and "mola" in why, f"6 hatada mola: {why}")
calls = len(fm.calls)
check(ai.analyze(ITEM) is None and len(fm.calls) == calls, "molada API'ye istek gitmiyor")
check(ai.status_line().startswith("❌") and "429" in ai.status_line(), ai.status_line()[:90])
S.advance(6)
fm.default = "ok"
ai.cooldown.clear()
check(ai.analyze(ITEM) is not None, "mola bitince deneme çağrısı başarılı")
msg = ai.health_alert()
check(msg and "tekrar çalışıyor" in msg, "düzelme mesajı")
check(ai.health_alert() is None and ai.health["fails"] == 0, "sayaç sıfırlandı")

print("5) Kalıcı hatalar hemen uyarır: sızdırılmış/geçersiz anahtar, kredi bitti")
for mode, kind, word in (("leaked", "anahtar", "API anahtarı"), ("badkey", "anahtar", "API anahtarı"),
                         ("credits", "fatura", "kredi")):
    a2 = A.GeminiAnalyzer()
    fm.default = mode
    fm.calls.clear()
    check(a2.analyze(ITEM) is None and len(fm.calls) == 1 and a2.health["kind"] == kind,
          f"{mode}: tek denemede durdu ({kind})")
    m2 = a2.health_alert()
    check(m2 and word in m2, f"{mode}: ilk hatada uyarı, ipucu: {word}")
fm.default = "ok"

print("6) Model bazlı sorunlar: 'limit: 0' modeli listeden çıkar, günlük ücretsiz katman kotası, bağlantı hatası")
a3 = A.GeminiAnalyzer()
fm.mode = {"gemini-3.1-pro-preview": "limit0"}
check(a3.review(ITEM, r, {}, "Boğa") is not None and "gemini-3.1-pro-preview" in a3.dead,
      "kota 0 veren pro model çıkarıldı, sıradaki model yanıt verdi")
fm.mode = {m: "quota_day" for m in MODELS}
a3.analyze(ITEM)
check(a3.health["free_tier"] and "Billing" in a3.hint(), "ücretsiz katman kotası -> fatura/kredi ipucu")
check(a3.cooldown["gemini-3.5-flash-lite"] - S.fake_time() > 3000, "günlük kota veren model 1 saat dinlendirildi")
a4 = A.GeminiAnalyzer()
fm.mode = {m: "conn" for m in MODELS}
a4.analyze(ITEM)
check(a4.health["kind"] == "baglanti" and "bağlanamıyor" in a4.hint(), "bağlantı hatası teşhisi")
fm.mode = {}

print("7) Model listesi 6 saatte bir yenilenir; eski kütüphane ayarı tanımazsa ayarsız denenir")
a5 = A.GeminiAnalyzer()
a5.dead.add("gemini-3.7-flash")
before = fm.list_calls
S.advance(6 * 60 + 1)
spike(a5)
check(fm.list_calls == before + 1 and "gemini-3.7-flash" not in a5.dead, "model listesi yenilendi, ölü liste temizlendi")
orig = A.types.ThinkingConfig


def picky(**kw):
    if "thinking_level" in kw:
        raise TypeError("unexpected keyword thinking_level")
    return orig(**kw)


A.types.ThinkingConfig = picky
a6 = A.GeminiAnalyzer()
check(a6.analyze(ITEM) is not None and "gemini-3.5-flash-lite" in a6.no_thinking_cfg, "ayar hatasında düşünme ayarsız denendi")
A.types.ThinkingConfig = orig

print(f"\nTüm Gemini sağlık ve bütçe testleri geçti ({n_ok} kontrol).")
