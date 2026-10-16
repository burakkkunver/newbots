import os
import shutil
import sys

SP = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(SP, "data_trading")
shutil.rmtree(DATA, ignore_errors=True)
os.environ.update(DATA_DIR=DATA, TELEGRAM_BOT_TOKEN="x", TELEGRAM_CHAT_ID="1", GEMINI_API_KEY="k",
                  BINANCE_API_KEY="a", BINANCE_SECRET="b", TESTNET_OGRENME="False", SPIKE_AI_ENABLED="False", PULSE_ENABLED="False")
sys.path.insert(0, os.path.dirname(SP))
sys.path.insert(0, SP)

import sim as S  # noqa: E402  (saat burada sahteleniyor)
import config  # noqa: E402
import trader as T  # noqa: E402

SENT = []
T.send_telegram = lambda m: SENT.append(m) or True


def regime(name):
    d = dict(config.REGIMES[name])
    d["name"] = name
    return d


def fresh(stop_loss_market=True):
    for fn in ("positions.json", "state.json"):
        p = os.path.join(DATA, fn)
        if os.path.exists(p):
            os.remove(p)
    sim = S.Sim(stop_loss_market=stop_loss_market)
    S.install(sim)
    tr = T.Trader()
    tr.startup()
    SENT.clear()
    return sim, tr


def item(title="Test haber", mins_ago=2):
    return {"title": title, "link": "http://x/" + title, "source": "Test", "published": S.fake_time() - mins_ago * 60}


def res(coin, score, ev="listeleme"):
    return {"hedef_coin": coin, "puan": float(score), "karar": "BUY", "olay_turu": ev, "kesinlik": "resmi",
            "aktor": "birinci_lig", "sebep": "test sebebi"}


def buy(tr, coin, score, reg):
    ok, code, desc, ctx = tr.precheck(coin, score, item(), reg)
    assert ok, (code, desc)
    code, desc = tr.execute_buy(ctx, res(coin, score), item(), reg, {"guven": 75, "sebep": "onay", "onay": True})
    assert code == "ALINDI", (code, desc)
    return tr.positions[-1]


def step(sim, tr, price=None, sym="SOLUSDT", minutes=0):
    if price is not None:
        sim.px[sym] = price
    if minutes:
        S.advance(minutes)
    sim.tick()
    tr.manage_positions()


def last_close():
    return tr_state(TR)["closed"][-1]


def tr_state(tr):
    return tr.state


ok_count = 0


def check(cond, msg):
    global ok_count
    assert cond, msg
    ok_count += 1
    print("  ✓", msg)


# ---------------------------------------------------------------
print("B) BOĞA: izleyen stop devreye girer, yukarı taşınır, stop dolunca kârla kapanır")
sim, TR = fresh()
pos = buy(TR, "SOL", 8, regime("BOGA"))
check(pos["mode"] == "trailing" and pos["protection"] == "stop", "trailing modda borsaya stop emri girildi")
o = sim.orders[pos["stop_order_id"]]
check(o["type"] == "STOP_LOSS" and abs(float(o["stopPrice"]) - 150 * 0.98) < 0.01, "stop -%2'de (STOP_LOSS)")
step(sim, TR, 151.5)
check(not TR.positions[0]["trail_active"], "+%1'de izleyen stop henüz aktif değil")
step(sim, TR, 153.2)   # +2.13% -> aktivasyon (8 puan: +%2)
p = TR.positions[0]
check(p["trail_active"], "+%2.1'de izleyen stop aktif")
check(abs(p["stop"] - 153.2 * (1 - 0.012)) < 0.01, f"stop zirvenin %1.2 altına taşındı ({p['stop']:.4f})")
check(sim.orders[p["stop_order_id"]]["status"] == "NEW", "yeni stop emri borsada")
old_id = p["stop_order_id"]
step(sim, TR, 158.0)
p = TR.positions[0]
check(p["stop_order_id"] != old_id and sim.orders[old_id]["status"] == "CANCELED", "eski stop iptal, yenisi kondu")
check(abs(p["stop"] - 158 * 0.988) < 0.01, f"stop {p['stop']:.4f} (158'in %1.2 altı)")
step(sim, TR, 157.5)
check(abs(TR.positions[0]["stop"] - 158 * 0.988) < 0.01, "fiyat düşünce stop aşağı inmez")
step(sim, TR, 155.9)    # stop (156.10) altı -> borsada dolar
check(not TR.positions, "stop dolunca pozisyon kapandı")
c = TR.state["closed"][-1]
check(c["reason"] == "İZLEYEN STOP" and c["pnl"] > 0, f"sebep İZLEYEN STOP, kâr {c['pct']:+.2f}%")
check(any("İşlem Açıldı" in m for m in SENT) and any("izleyen stop devrede" in m for m in SENT), "Telegram mesajları gitti")

# ---------------------------------------------------------------
print("C) YATAY: OCO (sabit kâr al + stop), kâr alınca kapanır")
sim, TR = fresh()
pos = buy(TR, "SOL", 8, regime("YATAY"))
check(pos["mode"] == "fixed" and pos["protection"] == "oco", "fixed modda OCO kuruldu")
check(abs(pos["tp"] - 150 * 1.02) < 0.01, f"TP +%2 ({pos['tp']})")
step(sim, TR, 153.1)
check(not TR.positions and TR.state["closed"][-1]["reason"] == "KÂR AL", "TP dolunca KÂR AL ile kapandı")

# ---------------------------------------------------------------
print("D) Time-stop: 7 puan, 20 dk'da +%0.5 altı -> kapat")
sim, TR = fresh()
pos = buy(TR, "SOL", 7, regime("BOGA"))
sid = pos["stop_order_id"]
step(sim, TR, 150.3, minutes=10)
check(TR.positions, "10. dakikada pozisyon açık")
step(sim, TR, 150.3, minutes=11)
check(not TR.positions and TR.state["closed"][-1]["reason"].startswith("TIME-STOP"), "21. dakikada TIME-STOP")
check(sim.orders[sid]["status"] == "CANCELED", "borsadaki stop iptal edildi")

print("D2) Time-stop: 20 dk'da +%0.5 üstündeyse devam")
sim, TR = fresh()
buy(TR, "SOL", 8, regime("BOGA"))
step(sim, TR, 151.2, minutes=21)   # +0.8%
check(TR.positions and TR.positions[0]["time_stop_done"], "+%0.8'de time-stop geçildi, pozisyon açık")

print("D3) 9 puanda time-stop yok")
sim, TR = fresh()
buy(TR, "SOL", 9, regime("YATAY"))
step(sim, TR, 150.0, minutes=25)
check(TR.positions, "9 puan: 25. dakikada hâlâ açık")

# ---------------------------------------------------------------
print("E) Süre doldu (izleyen stop aktif değil) -> kapat; çok boğada süre x2")
sim, TR = fresh()
pos = buy(TR, "SOL", 9, regime("YATAY"))
check(abs(pos["hold_min"] - 240) < 1e-6, "9 puan yatay: 240 dk")
step(sim, TR, 150.5, minutes=241)
check(not TR.positions and TR.state["closed"][-1]["reason"] == "SÜRE DOLDU", "240 dk sonra SÜRE DOLDU")
sim, TR = fresh()
pos = buy(TR, "SOL", 9, regime("COK_BOGA"))
check(abs(pos["hold_min"] - 480) < 1e-6, "9 puan çok boğa: 480 dk (x2)")

print("F) Süre doldu ama izleyen stop aktif -> devam")
sim, TR = fresh()
buy(TR, "SOL", 8, regime("BOGA"))
step(sim, TR, 154.0, minutes=5)
step(sim, TR, 154.0, minutes=120)
check(TR.positions and TR.positions[0].get("overtime_notified"), "izleyen stop aktifken süre dolunca satılmadı")

# ---------------------------------------------------------------
print("G) Sabit stop -%2 dolunca ZARAR KES")
sim, TR = fresh()
buy(TR, "SOL", 8, regime("BOGA"))
step(sim, TR, 146.9)
c = TR.state["closed"][-1]
check(not TR.positions and c["reason"] == "ZARAR KES" and -2.2 < c["pct"] < -1.9, f"ZARAR KES {c['pct']:+.2f}%")

print("H) STOP_LOSS_LIMIT dolmadı (hızlı düşüş) -> bot acil satar")
sim, TR = fresh(stop_loss_market=False)
pos = buy(TR, "SOL", 8, regime("BOGA"))
sid = pos["stop_order_id"]
check(sim.orders[sid]["type"] == "STOP_LOSS_LIMIT", "STOP_LOSS yoksa STOP_LOSS_LIMIT")
sim.fill_stop_limits = False
step(sim, TR, 145.0)   # stop 147, limit 145.8 -> limit dolmaz
c = TR.state["closed"][-1] if TR.state["closed"] else {}
check(not TR.positions and "acil" in c.get("reason", ""), f"acil satış: {c.get('reason')} {c.get('pct', 0):+.2f}%")

print("I) Rejim çarpanı ve bütçe: 100$ bütçe, çok düşüşte 10 puan")
sim, TR = fresh()
pos = buy(TR, "SOL", 10, regime("COK_DUSUS"))
check(abs(pos["cost"] - 100 * 0.60 * 0.4) < 0.01, f"10 puan x çok düşüş: {pos['cost']:.2f}$ (100*0.6*0.4=24)")
pos = buy(TR, "XRP", 8, regime("COK_BOGA"))
check(abs(pos["cost"] - min(100 * 0.35 * 1.3, 76)) < 0.01, f"8 puan x çok boğa: {pos['cost']:.2f}$ (45.5)")
ok, code, desc, _ = TR.precheck("ADA", 9, item(), regime("BOGA"))
check(ok and abs(_["amount"] - 30.5) < 0.01, f"kalan bütçe 30.5$ ile sınırlı ({_['amount']:.2f}$)")
ok, code, desc, _ = TR.precheck("SOL", 9, item(), regime("BOGA"))
check(not ok and code == "ENGEL_POZISYON", "aynı coinde ikinci pozisyon açılmaz")
ok, code, desc, _ = TR.precheck("DOGE", 9, item(), regime("BOGA"))
check(not ok and code == "ENGEL_TESTNET", "testnette olmayan coin engellenir")

print("J) Tren kaçtı: haberden sonra gerçek fiyat %3+ yükseldi")
sim, TR = fresh()
sim.kline_fn = lambda s, st, lim: [[st, "1.90", "1.90", "1.90", "1.90"]]
sim.real["XRPUSDT"] = 2.0   # 1.90 -> 2.00 = +%5.3
ok, code, desc, ctx = TR.precheck("XRP", 9, item(), regime("BOGA"))
check(not ok and code == "ENGEL_TREN", desc)

print("K) Eski sürümden kalan pozisyon dönüştürülür")
sim, TR = fresh()
import json  # noqa: E402
legacy = [{"id": "old1", "symbol": "SOLUSDT", "coin": "SOL", "base": "SOL", "score": 8, "qty": "0.100",
           "entry": 150.0, "cost": 15.0, "tp": 155.0, "sl": 141.0, "opened_at": S.fake_time() - 600,
           "deadline": S.fake_time() + 3600, "protection": "soft", "order_list_id": None, "order_id": None,
           "title": "eski", "link": "l", "source": "s"}]
with open(os.path.join(DATA, "positions.json"), "w") as fh:
    json.dump(legacy, fh)
sim.bal["SOL"] = 0.1
TR = T.Trader()
TR.startup()
p = TR.positions[0]
check(p["mode"] == "fixed" and p["stop"] == 141.0 and p["peak"] == 150.0, "eski pozisyon yeni yapıya çevrildi")
step(sim, TR, 140.0)
check(not TR.positions and "ZARAR KES" in TR.state["closed"][-1]["reason"], "eski pozisyonda yazılım stopu çalıştı")

print("L) Özet metni")
sim, TR = fresh()
buy(TR, "SOL", 8, regime("BOGA"))
step(sim, TR, 153.5)
txt = TR.summary_text("📈 Boğa (test)")
print(txt)
check("izleyen stop" in txt and "SOLUSDT" in txt, "özet pozisyon ve izleyen stop bilgisini içeriyor")

print(f"\nTüm işlem testleri geçti ({ok_count} kontrol).")
