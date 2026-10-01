"""Alım, koruma emirleri, izleyen stop, time-stop, pozisyon takibi ve özet.

Çıkış kuralları:
  - Her pozisyonda borsaya gerçek bir zarar kes emri girilir (-%HARD_STOP_PCT). Bot çökse bile çalışır.
  - Boğa rejimlerinde "izleyen stop": fiyat puana göre belirlenen kâra ulaşınca stop zirvenin
    belli bir yüzde altından fiyatı takip eder. Bot, borsadaki stop emrini yukarı taşır.
  - Temkinli rejimlerde (yatay / düşüş) OCO: küçük sabit kâr al + zarar kes.
  - Time-stop (7-8 puan): alımdan 20 dk sonra kâr +%0.5'in altındaysa pozisyon kapatılır.
  - Süre dolunca pozisyon kapatılır; izleyen stop aktifse kâr korunarak devam edilir.
Pozisyonlar ayrı bir thread'de MONITOR_SECONDS saniyede bir kontrol edilir.
"""
import json
import os
import threading
import time
import uuid

import config
from binance_api import Binance, BinanceError, ceil_step, floor_step, fmt
from notify import esc, send_telegram
from util import append_csv, day_start_ts, fmt_ts, now_local, pct

POSITIONS_FILE = os.path.join(config.DATA_DIR, "positions.json")
STATE_FILE = os.path.join(config.DATA_DIR, "state.json")
TRADES_CSV = os.path.join(config.DATA_DIR, "trades.csv")
TRADES_HEADER = ["acilis", "kapanis", "sembol", "puan", "rejim", "mod", "giris", "cikis", "maliyet_usdt",
                 "kar_usdt", "kar_yuzde", "zirve_yuzde", "cikis_sebebi", "sure_dk", "olay_turu", "kaynak", "haber"]

STABLES = {"USDT", "USDC", "FDUSD", "DAI", "TUSD", "BUSD", "USDE", "USDP", "PYUSD", "EUR", "TRY", "GENEL", ""}
CLOSED_STATUSES = ("CANCELED", "EXPIRED", "REJECTED", "EXPIRED_IN_MATCH")


def rules_for(score):
    return config.SCORE_RULES[int(min(10, max(7, score)))]


def _filled(order):
    return float(order.get("executedQty", 0) or 0), float(order.get("cummulativeQuoteQty", 0) or 0)


class Trader:
    def __init__(self):
        self.bx = Binance(config.BINANCE_API_KEY, config.BINANCE_SECRET, testnet=config.TEST_MODE)
        self.lock = threading.RLock()
        self.positions = []
        self.state = {"realized_pnl": 0.0, "cooldown": {}, "closed": []}
        self._outbox = []
        self._load()
        self._migrate()

    # ---------- kalıcı durum ----------
    def _load(self):
        try:
            with open(POSITIONS_FILE) as f:
                self.positions = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.positions = []
        try:
            with open(STATE_FILE) as f:
                self.state.update(json.load(f))
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    def _save(self):
        with self.lock:
            for path, data in ((POSITIONS_FILE, self.positions), (STATE_FILE, self.state)):
                tmp = path + ".tmp"
                with open(tmp, "w") as f:
                    json.dump(data, f, indent=1)
                os.replace(tmp, path)

    def _migrate(self):
        """Eski sürümden kalan açık pozisyonları yeni yapıya çevirir."""
        changed = False
        for p in self.positions:
            if "mode" in p:
                continue
            r = rules_for(p.get("score", 7))
            p.update({"mode": "fixed", "regime": "?", "trail_active": False,
                      "trail_act": r["trail_act"], "trail_dist": r["trail_dist"],
                      "time_stop": False, "time_stop_done": True, "event": ""})
            p["stop"] = p.get("sl") or p["entry"] * (1 - config.HARD_STOP_PCT / 100)
            p["hard_stop"] = p["stop"]
            p["peak"] = max(p.get("last_price") or 0, p["entry"])
            p.setdefault("stop_order_id", None)
            changed = True
        if changed:
            self._save()

    # ---------- bildirim kuyruğu (kilit tutulurken ağ beklenmesin) ----------
    def _notify(self, msg):
        with self.lock:
            self._outbox.append(msg)

    def _flush(self):
        while True:
            with self.lock:
                if not self._outbox:
                    return
                msg = self._outbox.pop(0)
            send_telegram(msg)

    def startup(self):
        self.bx.sync_time()
        self.bx.load_symbols(force=True)
        return self.bx.free("USDT")

    # ---------- bütçe ----------
    def invested(self):
        with self.lock:
            return sum(p["cost"] for p in self.positions)

    def bot_cash(self):
        """Sanal bütçe: başlangıç bütçesi + gerçekleşen kâr/zarar - açık pozisyonlara bağlı para."""
        return config.BUDGET_USDT + self.state["realized_pnl"] - self.invested()

    def _amount(self, score, regime, info):
        try:
            real_free = self.bx.free("USDT")
        except Exception as e:
            return None, f"Bakiye okunamadı: {e}"
        available = min(self.bot_cash(), real_free)
        equity = config.BUDGET_USDT + self.state["realized_pnl"]
        min_needed = max(config.MIN_TRADE_USDT, info["min_notional"] * 1.15)
        amount = min(equity * rules_for(score)["alloc"] * regime["alloc"], config.MAX_TRADE_USDT, available)
        if amount < min_needed:
            if available >= min_needed:
                amount = min_needed
            else:
                return None, f"Yetersiz bakiye: kullanılabilir {available:.2f} USDT, gereken en az {min_needed:.2f}."
        return amount, ""

    # ---------- alım ----------
    def precheck(self, coin, score, item, regime):
        """Alım yapılabilir mi? (ok, kod, açıklama, ctx). Ucuz kontroller ikinci görüşten ÖNCE yapılır."""
        coin = (coin or "").upper()
        if coin in STABLES:
            return False, "GENEL", "Belirli bir coin yok, işlem yapılmaz.", {}
        if not config.TRADE_ENABLED:
            return False, "KAPALI", "TRADE_ENABLED=False, sadece bildirim.", {}
        symbol = f"{coin}USDT"
        with self.lock:
            if any(p["symbol"] == symbol for p in self.positions):
                return False, "ENGEL_POZISYON", f"{symbol} için zaten açık pozisyon var.", {}
            cd = self.state["cooldown"].get(symbol, 0)
            if time.time() < cd:
                return False, "ENGEL_BEKLEME", f"{symbol} bekleme süresinde ({int((cd - time.time()) / 60)} dk kaldı).", {}
            if len(self.positions) >= config.MAX_OPEN_POSITIONS:
                return False, "ENGEL_MAKS", f"Maksimum açık pozisyon ({config.MAX_OPEN_POSITIONS}) dolu.", {}
        try:
            self.bx.load_symbols()
        except Exception as e:
            print(f"⚠️ Sembol listesi yenilenemedi: {e}")
        info = self.bx.symbols.get(symbol)
        if not info:
            where = "testnet" if config.TEST_MODE else "Binance"
            return False, "ENGEL_TESTNET", f"{symbol} {where} üzerinde işlem görmüyor.", {}

        ctx = {"symbol": symbol, "coin": coin, "info": info, "late_move": None}
        # Geç kalma kontrolü: haber yayınlandığından beri gerçek piyasada fiyat ne kadar gitti?
        try:
            p_news = self.bx.real_price_at(symbol, item["published"])
            ctx["p_news"] = p_news
            if p_news:
                move = pct(self.bx.real_price(symbol), p_news)
                ctx["late_move"] = move
                if move >= config.LATE_MOVE_PCT:
                    return False, "ENGEL_TREN", f"Tren kaçtı: haberden sonra fiyat zaten %{move:.2f} yükselmiş.", ctx
        except Exception as e:
            ctx["late_note"] = f"gerçek fiyat kontrol edilemedi: {getattr(e, 'msg', e)}"
        try:
            t = self.bx.real_ticker24(symbol)
            ctx["coin_ch24"], ctx["coin_volume"] = t["change_pct"], t["quote_volume"]
        except Exception:
            pass

        amount, why = self._amount(score, regime, info)
        if amount is None:
            return False, "ENGEL_BAKIYE", why, ctx
        ctx["amount"] = amount
        return True, "OK", "", ctx

    def execute_buy(self, ctx, res, item, regime, review=None):
        """Market alım + koruma emirleri. (kod, açıklama) döner; kod 'ALINDI' ise işlem açıldı."""
        symbol, info, score = ctx["symbol"], ctx["info"], res["puan"]
        # İkinci görüş beklenirken fiyat kaçtı mı?
        if ctx.get("p_news"):
            try:
                move = pct(self.bx.real_price(symbol), ctx["p_news"])
                ctx["late_move"] = move
                if move >= config.LATE_MOVE_PCT:
                    return "ENGEL_TREN", f"Tren kaçtı (ikinci görüş beklenirken): fiyat %{move:.2f} yükseldi."
            except Exception:
                pass

        with self.lock:
            if any(p["symbol"] == symbol for p in self.positions):
                return "ENGEL_POZISYON", f"{symbol} için zaten açık pozisyon var."
            if len(self.positions) >= config.MAX_OPEN_POSITIONS:
                return "ENGEL_MAKS", f"Maksimum açık pozisyon ({config.MAX_OPEN_POSITIONS}) dolu."
            try:
                order = self.bx.market_buy(symbol, ctx["amount"])
            except BinanceError as e:
                return "ENGEL_HATA", f"Alım emri reddedildi: {e.msg}"
            qty, cost = _filled(order)
            if qty <= 0:
                return "ENGEL_HATA", "Alım emri gerçekleşmedi."
            entry = cost / qty
            # Komisyon coin'den kesildiyse elimizdeki miktar azalır
            fee_in_base = sum(float(f["commission"]) for f in order.get("fills", [])
                              if f.get("commissionAsset") == info["base"])
            rules = rules_for(score)
            mode = regime["exit"]
            hold_min = rules["hold_min"] * regime["hold_mult"]
            stop = float(floor_step(entry * (1 - config.HARD_STOP_PCT / 100), info["tick"]))
            now = time.time()
            pos = {
                "id": uuid.uuid4().hex[:8], "symbol": symbol, "coin": ctx["coin"], "base": info["base"],
                "score": score, "qty": fmt(floor_step(qty - fee_in_base, info["step"])),
                "entry": entry, "cost": cost, "opened_at": now, "deadline": now + hold_min * 60,
                "hold_min": hold_min, "mode": mode, "regime": regime["name"],
                "tp": float(ceil_step(entry * (1 + rules["tp_fixed"] / 100), info["tick"])) if mode == "fixed" else None,
                "stop": stop, "hard_stop": stop, "peak": entry, "trail_active": False,
                "trail_act": rules["trail_act"], "trail_dist": rules["trail_dist"],
                "time_stop": rules["time_stop"], "time_stop_done": False,
                "protection": "soft", "order_list_id": None, "stop_order_id": None, "order_id": None,
                "event": res.get("olay_turu", ""), "title": item["title"], "link": item["link"],
                "source": item["source"],
            }
            prot_note = self._protect_new(pos, info)
            self.positions.append(pos)
            self._save()

        if mode == "trailing":
            exit_txt = (f"<b>İzleyen stop:</b> +%{rules['trail_act']:g} kârda devreye girer, "
                        f"zirvenin %{rules['trail_dist']:g} altından takip eder (sabit hedef yok)")
        else:
            exit_txt = f"<b>Kâr Al:</b> {pos['tp']:.6g} (+%{rules['tp_fixed']:g})"
        ts_txt = (f"\n<b>Time-stop:</b> {config.TIME_STOP_MIN:g} dk'da +%{config.TIME_STOP_MIN_PROFIT:g} altındaysa çıkar"
                  if rules["time_stop"] else "")
        late = ctx.get("late_move")
        rv = (f"\n<b>İkinci görüş:</b> onay (güven {review['guven']:.0f}) — {esc(review['sebep'])}"
              if review else "")
        self._notify(
            f"✅ <b>İşlem Açıldı, Emirler Girildi</b>{' (TESTNET)' if config.TEST_MODE else ''}\n\n"
            f"<b>Çift:</b> {symbol} | <b>Puan:</b> {score:.0f}/10\n"
            f"<b>Rejim:</b> {regime['ad']}\n"
            f"<b>Tutar:</b> {cost:.2f} USDT | <b>Miktar:</b> {pos['qty']}\n"
            f"<b>Giriş:</b> {entry:.6g}\n{exit_txt}\n"
            f"<b>Zarar Kes:</b> {stop:.6g} (-%{config.HARD_STOP_PCT:g})"
            f"{ts_txt}\n<b>Maks. süre:</b> {hold_min:g} dk\n"
            f"<b>Koruma:</b> {pos['protection'].upper()}"
            + (f"\n<b>Haberden beri fiyat:</b> {late:+.2f}%" if late is not None else "")
            + (f"\n{prot_note}" if prot_note else "")
            + f"\n\n<b>Haber:</b> {esc(item['title'])}\n"
              f"<b>Olay:</b> {esc(res.get('olay_turu', ''))}/{esc(res.get('kesinlik', ''))}/{esc(res.get('aktor', ''))}\n"
              f"<b>Sebep:</b> {esc(res.get('sebep', ''))}{rv}")
        self._flush()
        return "ALINDI", f"{symbol} {cost:.2f} USDT @ {entry:.6g}"

    # ---------- koruma emirleri ----------
    def _protect_new(self, pos, info):
        note = ""
        if pos["mode"] == "fixed" and info.get("oco"):
            try:
                sl_limit = floor_step(pos["stop"] * (1 - config.STOP_LIMIT_GAP_PCT / 100), info["tick"])
                res = self.bx.oco_sell(pos["symbol"], pos["qty"], fmt(ceil_step(pos["tp"], info["tick"])),
                                       fmt(floor_step(pos["stop"], info["tick"])), fmt(sl_limit))
                pos["order_list_id"] = res["orderListId"]
                pos["protection"] = "oco"
                return ""
            except BinanceError as e:
                note = f"⚠️ OCO kurulamadı ({esc(e.msg)}), kâr al bot tarafından takip edilecek. "
        ok, err = self._place_stop(pos, pos["stop"])
        if not ok:
            note += f"⚠️ Stop emri kurulamadı ({esc(err)}), stop bot tarafından takip edilecek."
        return note.strip()

    def _place_stop(self, pos, stop_price):
        info = self.bx.symbols.get(pos["symbol"], {})
        tick = info.get("tick", "0.00000001")
        stop_d = floor_step(stop_price, tick)
        limit_d = floor_step(float(stop_d) * (1 - config.STOP_LIMIT_GAP_PCT / 100), tick)
        pos["stop"] = float(stop_d)
        try:
            res = self.bx.stop_sell(pos["symbol"], pos["qty"], fmt(stop_d), fmt(limit_d))
            pos["stop_order_id"] = res["orderId"]
            pos["protection"] = "stop"
            return True, ""
        except BinanceError as e:
            pos["stop_order_id"] = None
            pos["protection"] = "soft"
            return False, str(e.msg)

    def _move_stop(self, pos, new_stop):
        """İzleyen stopu yukarı taşır: eski stop emrini iptal edip yenisini koyar."""
        if pos["protection"] == "stop" and pos.get("stop_order_id"):
            try:
                self.bx.cancel_order(pos["symbol"], pos["stop_order_id"])
            except BinanceError as e:
                print(f"⚠️ {pos['symbol']} stop iptal edilemedi ({e.msg}), doldu mu diye sonraki turda bakılacak.")
                return
            pos["stop_order_id"] = None
            pos["protection"] = "soft"
        ok, err = self._place_stop(pos, new_stop)
        if not ok:
            if "immediately" in err.lower():
                self._sell_now(pos, "İZLEYEN STOP")
                return
            print(f"⚠️ {pos['symbol']} stop taşınamadı ({err}), bot takip edecek.")
        self._save()

    # ---------- pozisyon takibi ----------
    def monitor_forever(self, stop_event):
        while not stop_event.is_set():
            t0 = time.time()
            try:
                self.manage_positions()
            except Exception as e:
                print(f"⚠️ Pozisyon takibi hatası: {e}")
            stop_event.wait(max(1.0, config.MONITOR_SECONDS - (time.time() - t0)))

    def manage_positions(self):
        with self.lock:
            symbols = [p["symbol"] for p in self.positions]
        if not symbols:
            return
        prices = self.bx.prices(symbols)
        with self.lock:
            for pos in list(self.positions):
                try:
                    self._manage_one(pos, prices.get(pos["symbol"]))
                except BinanceError as e:
                    print(f"⚠️ Pozisyon kontrol hatası {pos['symbol']}: {e}")
                except Exception as e:
                    print(f"⚠️ Pozisyon kontrol hatası {pos['symbol']}: {e}")
        self._flush()

    def _check_orders(self, pos):
        """Borsadaki koruma emirleri doldu mu? Pozisyon kapandıysa True."""
        prot = pos["protection"]
        if prot == "oco" and pos.get("order_list_id") is not None:
            ol = self.bx.get_order_list(pos["order_list_id"])
            if ol.get("listOrderStatus") == "ALL_DONE":
                for o in ol.get("orders", []):
                    od = self.bx.get_order(pos["symbol"], o["orderId"])
                    q, quote = _filled(od)
                    if q > 0:
                        reason = "KÂR AL" if od.get("type") in ("LIMIT_MAKER", "LIMIT") else "ZARAR KES"
                        self._close(pos, quote / q, reason)
                        return True
                # Hiçbiri dolmadı (elle iptal edilmiş olabilir): tekrar korumaya al
                pos["order_list_id"] = None
                pos["protection"] = "soft"
                self._place_stop(pos, pos["stop"])
                self._save()
        elif prot == "stop" and pos.get("stop_order_id"):
            od = self.bx.get_order(pos["symbol"], pos["stop_order_id"])
            if od.get("status") == "FILLED":
                q, quote = _filled(od)
                self._close(pos, quote / q, "İZLEYEN STOP" if pos["trail_active"] else "ZARAR KES")
                return True
            if od.get("status") in CLOSED_STATUSES:
                pos["stop_order_id"] = None
                pos["protection"] = "soft"
                self._place_stop(pos, pos["stop"])
                self._save()
        elif prot == "limit" and pos.get("order_id"):   # eski sürümden kalan kâr al emri
            od = self.bx.get_order(pos["symbol"], pos["order_id"])
            if od.get("status") == "FILLED":
                q, quote = _filled(od)
                self._close(pos, quote / q, "KÂR AL")
                return True
            if od.get("status") in CLOSED_STATUSES:
                pos["order_id"] = None
                pos["protection"] = "soft"
                self._save()
        return False

    def _manage_one(self, pos, price):
        if self._check_orders(pos) or price is None:
            return
        now = time.time()
        changed = False
        pos["last_price"] = price
        if price > pos["peak"]:
            pos["peak"] = price
            changed = True
        gain = pct(price, pos["entry"])
        peak_gain = pct(pos["peak"], pos["entry"])

        # 1) İzleyen stop
        if pos["mode"] == "trailing":
            if not pos["trail_active"] and peak_gain >= pos["trail_act"]:
                pos["trail_active"] = True
                changed = True
                self._notify(f"📈 <b>{pos['symbol']}</b> izleyen stop devrede: zirve +{peak_gain:.2f}%, "
                             f"stop zirvenin %{pos['trail_dist']:g} altından takip ediyor.")
            if pos["trail_active"]:
                tick = self.bx.symbols.get(pos["symbol"], {}).get("tick", "0.00000001")
                new_stop = float(floor_step(pos["peak"] * (1 - pos["trail_dist"] / 100), tick))
                if new_stop > pos["stop"] * (1 + config.TRAIL_UPDATE_MIN_PCT / 100):
                    if price <= new_stop:
                        return self._sell_now(pos, "İZLEYEN STOP")
                    self._move_stop(pos, new_stop)
                    if pos not in self.positions:
                        return
                    changed = True

        # 2) Yedek kontroller (borsadaki emir yoksa veya dolmadıysa bot satar)
        locked = pos["trail_active"] and pos["stop"] > pos["entry"]
        stop_reason = "İZLEYEN STOP" if locked else "ZARAR KES"
        prot = pos["protection"]
        if prot in ("soft", "limit") and price <= pos["stop"]:
            return self._sell_now(pos, f"{stop_reason} (bot)")
        if prot in ("oco", "stop") and price <= pos["stop"] * (1 - (config.STOP_LIMIT_GAP_PCT + 0.3) / 100):
            return self._sell_now(pos, f"{stop_reason} (acil: stop emri dolmadı)")
        if prot in ("soft", "stop") and pos.get("tp") and price >= pos["tp"]:
            return self._sell_now(pos, "KÂR AL (bot)")

        # 3) Time-stop: beklenen sıçrama gelmediyse çık (sadece 7-8 puan)
        if pos["time_stop"] and not pos["time_stop_done"] and now - pos["opened_at"] >= config.TIME_STOP_MIN * 60:
            pos["time_stop_done"] = True
            changed = True
            if gain < config.TIME_STOP_MIN_PROFIT and not pos["trail_active"]:
                return self._sell_now(pos, f"TIME-STOP ({config.TIME_STOP_MIN:g} dk'da beklenen sıçrama yok)")

        # 4) Süre doldu
        if now >= pos["deadline"]:
            if not pos["trail_active"]:
                return self._sell_now(pos, "SÜRE DOLDU")
            if not pos.get("overtime_notified"):
                pos["overtime_notified"] = True
                changed = True
                self._notify(f"⏰ <b>{pos['symbol']}</b> süresi doldu ama izleyen stop aktif "
                             f"(stop +{pct(pos['stop'], pos['entry']):.2f}%), kâr korunarak devam ediliyor.")
        if changed:
            self._save()

    def _sell_now(self, pos, reason):
        """Koruma emirlerini iptal edip kalan miktarı piyasadan satar."""
        pre_q = pre_quote = 0.0
        try:
            if pos["protection"] == "oco" and pos.get("order_list_id") is not None:
                r = self.bx.cancel_order_list(pos["symbol"], pos["order_list_id"])
                for rep in r.get("orderReports", []):
                    q, quote = _filled(rep)
                    pre_q, pre_quote = pre_q + q, pre_quote + quote
            elif pos["protection"] == "stop" and pos.get("stop_order_id"):
                q, quote = _filled(self.bx.cancel_order(pos["symbol"], pos["stop_order_id"]))
                pre_q, pre_quote = q, quote
            elif pos["protection"] == "limit" and pos.get("order_id"):
                q, quote = _filled(self.bx.cancel_order(pos["symbol"], pos["order_id"]))
                pre_q, pre_quote = q, quote
        except BinanceError as e:
            print(f"⚠️ {pos['symbol']} emir iptal edilemedi ({e.msg}), muhtemelen doldu; sonraki turda kontrol edilecek.")
            return
        pos.update({"protection": "soft", "order_list_id": None, "stop_order_id": None, "order_id": None})

        info = self.bx.symbols.get(pos["symbol"], {})
        price = pos.get("last_price") or pos["entry"]
        try:
            free = self.bx.free(pos["base"])
        except Exception:
            free = float(pos["qty"])
        qty = floor_step(max(0.0, min(float(pos["qty"]) - pre_q, free)), info.get("step", "0.00000001"))
        if float(qty) <= 0 or float(qty) * price < info.get("min_notional", 5):
            if pre_q > 0:
                self._close(pos, pre_quote / pre_q, reason)
            else:
                self._close(pos, price, reason + " (miktar satılamadı, tahmini)")
            return
        try:
            order = self.bx.market_sell(pos["symbol"], fmt(qty))
        except BinanceError as e:
            pos["sell_fails"] = pos.get("sell_fails", 0) + 1
            if pos["sell_fails"] in (1, 30) or pos["sell_fails"] % 180 == 0:
                self._notify(f"❌ <b>{pos['symbol']} satılamadı:</b> {esc(e.msg)} (tekrar denenecek)")
            self._place_stop(pos, pos["stop"])
            self._save()
            return
        q, quote = _filled(order)
        total_q, total_quote = pre_q + q, pre_quote + quote
        self._close(pos, total_quote / total_q if total_q else price, reason)

    def _close(self, pos, exit_price, reason):
        # Kâr/zarar fiyat üzerinden: borsanın miktar yuvarlamasıyla cüzdanda kalan "toz" zarar sayılmaz
        pnl_pct = pct(exit_price, pos["entry"])
        pnl = pos["cost"] * pnl_pct / 100
        peak_pct = pct(pos["peak"], pos["entry"])
        minutes = int((time.time() - pos["opened_at"]) / 60)
        with self.lock:
            self.state["realized_pnl"] += pnl
            self.state["cooldown"][pos["symbol"]] = time.time() + config.COIN_COOLDOWN_MIN * 60
            self.state["closed"].append({
                "symbol": pos["symbol"], "score": pos["score"], "regime": pos.get("regime", "?"),
                "mode": pos["mode"], "pnl": pnl, "pct": pnl_pct, "peak_pct": peak_pct, "reason": reason,
                "opened_at": pos["opened_at"], "closed_at": time.time(), "minutes": minutes,
                "title": pos["title"][:120], "event": pos.get("event", "")})
            self.state["closed"] = self.state["closed"][-500:]
            self.positions = [p for p in self.positions if p["id"] != pos["id"]]
            self._save()
        append_csv(TRADES_CSV, TRADES_HEADER, [
            fmt_ts(pos["opened_at"]), fmt_ts(time.time()), pos["symbol"], int(pos["score"]),
            pos.get("regime", "?"), pos["mode"], f"{pos['entry']:.8g}", f"{exit_price:.8g}", f"{pos['cost']:.2f}",
            f"{pnl:.4f}", f"{pnl_pct:.2f}", f"{peak_pct:.2f}", reason, minutes, pos.get("event", ""),
            pos.get("source", ""), pos["title"]])
        icon = "🟢" if pnl >= 0 else "🔴"
        self._notify(
            f"{icon} <b>Pozisyon Kapandı</b> — {esc(reason)}\n\n<b>Çift:</b> {pos['symbol']} "
            f"({int(pos['score'])}/10, {'izleyen stop' if pos['mode'] == 'trailing' else 'sabit hedef'})\n"
            f"<b>Giriş → Çıkış:</b> {pos['entry']:.6g} → {exit_price:.6g}\n"
            f"<b>Kâr/Zarar:</b> {pnl:+.2f} USDT ({pnl_pct:+.2f}%) | <b>Zirve:</b> +{peak_pct:.2f}%\n"
            f"<b>Süre:</b> {minutes} dk\n"
            f"<b>Toplam gerçekleşen:</b> {self.state['realized_pnl']:+.2f} USDT")

    # ---------- özet ----------
    def closed_today(self):
        start = day_start_ts()
        return [c for c in self.state["closed"] if c["closed_at"] >= start]

    def position_lines(self):
        lines, open_value = [], 0.0
        with self.lock:
            positions = [dict(p) for p in self.positions]
        for p in positions:
            price = p.get("last_price") or p["entry"]
            value = float(p["qty"]) * price
            open_value += value
            left = (p["deadline"] - time.time()) / 60
            left_txt = "süre doldu" if left < 0 else (f"{left:.0f} dk kaldı" if left < 120 else f"{left / 60:.1f} sa kaldı")
            if p["mode"] == "trailing":
                guard = (f"izleyen stop {pct(p['stop'], p['entry']):+.2f}%" if p["trail_active"]
                         else f"stop -%{config.HARD_STOP_PCT:g}, izleyen +%{p['trail_act']:g}'de")
            else:
                guard = f"TP +{pct(p['tp'], p['entry']):.1f}% / stop {pct(p['stop'], p['entry']):+.1f}%" if p.get("tp") \
                    else f"stop {pct(p['stop'], p['entry']):+.1f}%"
            lines.append(f"• {p['symbol']} {pct(price, p['entry']):+.2f}% | {value:.2f}$ | {guard} | {left_txt}")
        return lines, open_value

    def summary_text(self, regime_text, ai_stats=None, news_stats=None):
        lines = [f"📊 <b>Durum Özeti</b>{' (TESTNET)' if config.TEST_MODE else ''} — {now_local().strftime('%H:%M')}",
                 f"<b>BTC rejimi:</b> {esc(regime_text)}"]
        try:
            real_usdt = f"{self.bx.free('USDT'):.2f}"
        except Exception:
            real_usdt = "okunamadı"
        pos_lines, open_value = self.position_lines()
        equity = self.bot_cash() + open_value
        lines.append(f"\n<b>Bot bütçesi:</b> {equity:.2f} USDT (başlangıç {config.BUDGET_USDT:g})")
        lines.append(f"<b>Boşta:</b> {self.bot_cash():.2f} USDT | <b>Pozisyonda:</b> {open_value:.2f} USDT")
        lines.append(f"<b>Cüzdandaki USDT:</b> {real_usdt}")
        lines.append(f"<b>Gerçekleşen K/Z:</b> {self.state['realized_pnl']:+.2f} USDT")
        today = self.closed_today()
        if today:
            wins = sum(1 for c in today if c["pnl"] > 0)
            lines.append(f"<b>Bugün:</b> {len(today)} işlem, {wins} kârlı, {sum(c['pnl'] for c in today):+.2f} USDT")
        lines.append(f"\n<b>Açık pozisyonlar ({len(pos_lines)}):</b>")
        lines.extend(pos_lines or ["• yok"])
        if news_stats:
            lines.append(f"\n<b>Haber:</b> {news_stats}")
        if ai_stats:
            lines.append(f"<b>Gemini:</b> {ai_stats['calls']} çağrı, {ai_stats['errors']} hata, "
                         f"{ai_stats['fallbacks']} yedek model | tahmini maliyet ${ai_stats['cost_usd']:.3f}")
        return "\n".join(lines)
