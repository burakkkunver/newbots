"""Alım, OCO/TP-SL kurulumu, pozisyon takibi, süre dolunca kârda çıkış ve özet raporu."""
import csv
import json
import os
import time
import uuid
from datetime import datetime

import config
from binance_api import Binance, BinanceError, ceil_step, floor_step, fmt
from notify import esc, send_telegram

POSITIONS_FILE = os.path.join(config.DATA_DIR, "positions.json")
STATE_FILE = os.path.join(config.DATA_DIR, "state.json")
TRADES_CSV = os.path.join(config.DATA_DIR, "trades.csv")

STABLES = {"USDT", "USDC", "FDUSD", "DAI", "TUSD", "BUSD", "USDE", "USDP", "EUR", "TRY", "GENEL", ""}


def _now():
    return time.time()


def tier_for(score):
    s = int(min(10, max(7, score)))
    return config.TIERS[s]


class Trader:
    def __init__(self):
        self.bx = Binance(config.BINANCE_API_KEY, config.BINANCE_SECRET, testnet=config.TEST_MODE)
        self.positions = []
        self.state = {"realized_pnl": 0.0, "cooldown": {}, "closed": []}
        self._load()

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
        for path, data in ((POSITIONS_FILE, self.positions), (STATE_FILE, self.state)):
            tmp = path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(data, f, indent=1)
            os.replace(tmp, path)

    def startup(self):
        self.bx.sync_time()
        self.bx.load_symbols(force=True)
        return self.bx.free("USDT")

    # ---------- bütçe ----------
    def invested(self):
        return sum(p["cost"] for p in self.positions)

    def bot_cash(self):
        """Sanal bütçe: başlangıç bütçesi + gerçekleşen kâr/zarar - açık pozisyonlara bağlı para."""
        return config.BUDGET_USDT + self.state["realized_pnl"] - self.invested()

    # ---------- alım ----------
    def try_buy(self, coin, score, item, reason):
        """Alım yapmayı dener. Sonucu açıklayan kısa bir metin döndürür."""
        coin = (coin or "").upper()
        if coin in STABLES:
            return "Hedef coin yok/genel haber, işlem yok."
        symbol = f"{coin}USDT"
        if not config.TRADE_ENABLED:
            return "TRADE_ENABLED=False, sadece bildirim."
        if any(p["symbol"] == symbol for p in self.positions):
            return f"{symbol} için zaten açık pozisyon var."
        cd = self.state["cooldown"].get(symbol, 0)
        if _now() < cd:
            return f"{symbol} bekleme süresinde ({int((cd - _now()) / 60)} dk kaldı)."
        if len(self.positions) >= config.MAX_OPEN_POSITIONS:
            return f"Maksimum açık pozisyon ({config.MAX_OPEN_POSITIONS}) dolu."

        self.bx.load_symbols()
        info = self.bx.symbols.get(symbol)
        if not info:
            return f"{symbol} {'testnet' if config.TEST_MODE else 'Binance'} üzerinde işlem görmüyor."

        # --- Geç kalma kontrolü: haberden sonra gerçek piyasada fiyat ne kadar gitti? ---
        late_note = ""
        try:
            p_news = self.bx.real_price_at(symbol, item["published"])
            p_now = self.bx.real_price(symbol)
            if p_news:
                move = (p_now / p_news - 1) * 100
                late_note = f"Haberden beri fiyat: {move:+.2f}%"
                if move >= config.LATE_MOVE_PCT:
                    return f"Tren kaçtı: haberden sonra fiyat zaten %{move:.2f} yükselmiş."
        except BinanceError as e:
            late_note = f"(gerçek fiyat kontrol edilemedi: {e.msg})"
        except Exception as e:
            late_note = f"(gerçek fiyat kontrol edilemedi: {e})"

        # --- Tutar hesabı ---
        tier = tier_for(score)
        try:
            real_free = self.bx.free("USDT")
        except Exception as e:
            return f"Bakiye okunamadı: {e}"
        available = min(self.bot_cash(), real_free)
        min_needed = max(config.MIN_TRADE_USDT, info["min_notional"] * 1.15)
        equity = config.BUDGET_USDT + self.state["realized_pnl"]
        amount = min(equity * tier["alloc"], config.MAX_TRADE_USDT, available)
        if amount < min_needed:
            if available >= min_needed:
                amount = min_needed
            else:
                return f"Yetersiz bakiye: kullanılabilir {available:.2f} USDT, gereken en az {min_needed:.2f}."

        # --- Market alım ---
        try:
            order = self.bx.market_buy(symbol, amount)
        except BinanceError as e:
            return f"Alım emri reddedildi: {e.msg}"
        qty = float(order.get("executedQty", 0))
        cost = float(order.get("cummulativeQuoteQty", 0))
        if qty <= 0:
            return "Alım emri gerçekleşmedi."
        entry = cost / qty
        # Komisyon coin'den kesildiyse elimizdeki miktar azalır
        fee_in_base = sum(float(f["commission"]) for f in order.get("fills", [])
                          if f.get("commissionAsset") == info["base"])
        sell_qty = floor_step(qty - fee_in_base, info["step"])

        tp = ceil_step(entry * (1 + tier["tp"] / 100), info["tick"])
        pos = {
            "id": uuid.uuid4().hex[:8], "symbol": symbol, "coin": coin, "base": info["base"],
            "score": score, "qty": fmt(sell_qty), "entry": entry, "cost": cost,
            "tp": float(tp), "sl": None, "opened_at": _now(),
            "deadline": _now() + tier["hold_h"] * 3600, "protection": "soft",
            "order_list_id": None, "order_id": None,
            "title": item["title"], "link": item["link"], "source": item["source"],
        }

        # --- Koruma emirleri ---
        prot_note = ""
        if config.STOP_LOSS_PCT > 0:
            sl_stop = floor_step(entry * (1 - config.STOP_LOSS_PCT / 100), info["tick"])
            sl_limit = floor_step(float(sl_stop) * 0.995, info["tick"])
            pos["sl"] = float(sl_stop)
            try:
                if not info["oco"]:
                    raise BinanceError(0, None, "Bu çiftte OCO desteklenmiyor")
                res = self.bx.oco_sell(symbol, pos["qty"], fmt(tp), fmt(sl_stop), fmt(sl_limit))
                pos["order_list_id"] = res["orderListId"]
                pos["protection"] = "oco"
            except BinanceError as e:
                prot_note = f"⚠️ OCO kurulamadı ({esc(e.msg)}), TP/SL bot tarafından takip edilecek."
        else:
            try:
                res = self.bx.limit_sell(symbol, pos["qty"], fmt(tp))
                pos["order_id"] = res["orderId"]
                pos["protection"] = "limit"
            except BinanceError as e:
                prot_note = f"⚠️ Kâr al emri kurulamadı ({esc(e.msg)}), bot takip edecek."

        self.positions.append(pos)
        self._save()

        sl_txt = f"{pos['sl']:.6g} (-%{config.STOP_LOSS_PCT:g})" if pos["sl"] else "YOK (zararda satmaz)"
        send_telegram(
            f"✅ <b>İşlem Açıldı, Emirler Girildi</b>{' (TESTNET)' if config.TEST_MODE else ''}\n\n"
            f"<b>Çift:</b> {symbol}\n<b>Puan:</b> {score:.0f}/10\n"
            f"<b>Tutar:</b> {cost:.2f} USDT\n<b>Miktar:</b> {pos['qty']}\n"
            f"<b>Giriş:</b> {entry:.6g}\n"
            f"<b>Kâr Al:</b> {pos['tp']:.6g} (+%{tier['tp']:g})\n<b>Zarar Kes:</b> {sl_txt}\n"
            f"<b>Maks. süre:</b> {tier['hold_h']:g} saat (süre dolunca sadece kârdaysa satar)\n"
            f"<b>Koruma:</b> {pos['protection'].upper()}\n{esc(late_note)}\n{prot_note}\n\n"
            f"<b>Haber:</b> {esc(item['title'])}\n<b>Sebep:</b> {esc(reason)}")
        return f"ALINDI {symbol} {cost:.2f} USDT @ {entry:.6g}"

    # ---------- pozisyon yönetimi ----------
    def _close(self, pos, exit_price, exit_qty_value, reason):
        pnl = exit_qty_value - pos["cost"]
        pct = pnl / pos["cost"] * 100 if pos["cost"] else 0
        self.state["realized_pnl"] += pnl
        self.state["cooldown"][pos["symbol"]] = _now() + config.COIN_COOLDOWN_MIN * 60
        self.state["closed"].append({"symbol": pos["symbol"], "pnl": pnl, "pct": pct,
                                     "closed_at": _now(), "reason": reason})
        self.state["closed"] = self.state["closed"][-500:]
        self.positions = [p for p in self.positions if p["id"] != pos["id"]]
        self._save()

        new_file = not os.path.exists(TRADES_CSV)
        with open(TRADES_CSV, "a", newline="") as f:
            w = csv.writer(f)
            if new_file:
                w.writerow(["acilis", "kapanis", "sembol", "puan", "giris", "cikis", "maliyet",
                            "kar_usdt", "kar_yuzde", "sebep", "sure_dk", "haber"])
            w.writerow([datetime.fromtimestamp(pos["opened_at"]).isoformat(timespec="seconds"),
                        datetime.now().isoformat(timespec="seconds"), pos["symbol"], pos["score"],
                        f"{pos['entry']:.8g}", f"{exit_price:.8g}", f"{pos['cost']:.2f}",
                        f"{pnl:.4f}", f"{pct:.2f}", reason,
                        int((_now() - pos["opened_at"]) / 60), pos["title"]])

        icon = "🟢" if pnl >= 0 else "🔴"
        send_telegram(
            f"{icon} <b>Pozisyon Kapandı</b> ({esc(reason)})\n\n<b>Çift:</b> {pos['symbol']}\n"
            f"<b>Giriş → Çıkış:</b> {pos['entry']:.6g} → {exit_price:.6g}\n"
            f"<b>Kâr/Zarar:</b> {pnl:+.2f} USDT ({pct:+.2f}%)\n"
            f"<b>Süre:</b> {int((_now() - pos['opened_at']) / 60)} dk\n"
            f"<b>Toplam gerçekleşen:</b> {self.state['realized_pnl']:+.2f} USDT")

    def _filled_value(self, order):
        qty = float(order.get("executedQty", 0))
        quote = float(order.get("cummulativeQuoteQty", 0))
        return qty, quote

    def _sell_now(self, pos, reason):
        """Koruma emirlerini iptal edip piyasadan satar."""
        try:
            if pos["protection"] == "oco" and pos["order_list_id"] is not None:
                self.bx.cancel_order_list(pos["symbol"], pos["order_list_id"])
            elif pos["protection"] == "limit" and pos["order_id"] is not None:
                self.bx.cancel_order(pos["symbol"], pos["order_id"])
        except BinanceError as e:
            print(f"⚠️ İptal edilemedi ({pos['symbol']}): {e.msg} -> muhtemelen zaten doldu, sonraki turda kontrol edilecek")
            return
        info = self.bx.symbols.get(pos["symbol"], {})
        free = self.bx.free(pos["base"])
        qty = floor_step(min(float(pos["qty"]), free), info.get("step", "0.00000001"))
        try:
            order = self.bx.market_sell(pos["symbol"], fmt(qty))
        except BinanceError as e:
            send_telegram(f"❌ <b>{pos['symbol']} satılamadı:</b> {esc(e.msg)}")
            pos["protection"] = "soft"
            self._save()
            return
        q, quote = self._filled_value(order)
        self._close(pos, quote / q if q else pos["entry"], quote, reason)

    def manage_positions(self):
        for pos in list(self.positions):
            try:
                self._manage_one(pos)
            except BinanceError as e:
                print(f"⚠️ Pozisyon kontrol hatası {pos['symbol']}: {e}")
            except Exception as e:
                print(f"⚠️ Pozisyon kontrol hatası {pos['symbol']}: {e}")

    def _manage_one(self, pos):
        # 1) Borsadaki emir doldu mu?
        if pos["protection"] == "oco":
            ol = self.bx.get_order_list(pos["order_list_id"])
            if ol.get("listOrderStatus") == "ALL_DONE":
                for o in ol.get("orders", []):
                    od = self.bx.get_order(pos["symbol"], o["orderId"])
                    if od.get("status") in ("FILLED", "PARTIALLY_FILLED") and float(od["executedQty"]) > 0:
                        q, quote = self._filled_value(od)
                        reason = "KÂR AL" if od.get("type") in ("LIMIT_MAKER", "LIMIT") else "ZARAR KES"
                        self._close(pos, quote / q, quote, reason)
                        return
                # Hiçbiri dolmadı (elle iptal edilmiş olabilir) -> bot takibine geç
                pos["protection"] = "soft"
                self._save()
        elif pos["protection"] == "limit":
            od = self.bx.get_order(pos["symbol"], pos["order_id"])
            if od.get("status") == "FILLED":
                q, quote = self._filled_value(od)
                self._close(pos, quote / q, quote, "KÂR AL")
                return
            if od.get("status") in ("CANCELED", "EXPIRED", "REJECTED"):
                pos["protection"] = "soft"
                self._save()

        price = self.bx.price(pos["symbol"])
        pos["last_price"] = price

        # 2) Bot takibindeki pozisyonlarda TP/SL
        if pos["protection"] == "soft":
            if price >= pos["tp"]:
                return self._sell_now(pos, "KÂR AL (bot)")
            if pos["sl"] and price <= pos["sl"]:
                return self._sell_now(pos, "ZARAR KES (bot)")

        # 3) Süre doldu: sadece kârdaysa çık, zarardaysa beklemeye devam
        if _now() >= pos["deadline"]:
            if price >= pos["entry"] * (1 + config.MIN_EXIT_PROFIT_PCT / 100):
                return self._sell_now(pos, "SÜRE DOLDU (kârda)")
            if not pos.get("overtime_notified"):
                pos["overtime_notified"] = True
                self._save()
                send_telegram(f"⏰ <b>{pos['symbol']}</b> süresi doldu ama zararda "
                              f"({(price / pos['entry'] - 1) * 100:+.2f}%). Kâra geçince satılacak.")

    # ---------- özet ----------
    def summary_text(self, ai_stats=None, news_stats=None):
        lines = [f"📊 <b>Durum Özeti</b>{' (TESTNET)' if config.TEST_MODE else ''} — "
                 f"{datetime.now().strftime('%H:%M')}"]
        try:
            real_usdt = self.bx.free("USDT")
        except Exception:
            real_usdt = float("nan")
        open_value = 0.0
        pos_lines = []
        for p in self.positions:
            price = p.get("last_price") or p["entry"]
            value = float(p["qty"]) * price
            open_value += value
            pct = (price / p["entry"] - 1) * 100
            left = (p["deadline"] - _now()) / 3600
            pos_lines.append(f"• {p['symbol']} {pct:+.2f}% | {value:.2f}$ | "
                             f"TP {p['tp']:.6g} | {'süre doldu' if left < 0 else f'{left:.1f} sa kaldı'}")
        equity = self.bot_cash() + open_value
        lines.append(f"\n<b>Bot bütçesi:</b> {equity:.2f} USDT (başlangıç {config.BUDGET_USDT:g})")
        lines.append(f"<b>Boşta:</b> {self.bot_cash():.2f} USDT | <b>Pozisyonda:</b> {open_value:.2f} USDT")
        lines.append(f"<b>Cüzdandaki USDT:</b> {real_usdt:.2f}")
        lines.append(f"<b>Gerçekleşen K/Z:</b> {self.state['realized_pnl']:+.2f} USDT")

        day_start = datetime.now().replace(hour=0, minute=0, second=0).timestamp()
        today = [c for c in self.state["closed"] if c["closed_at"] >= day_start]
        if today:
            wins = sum(1 for c in today if c["pnl"] > 0)
            lines.append(f"<b>Bugün:</b> {len(today)} işlem, {wins} kârlı, "
                         f"{sum(c['pnl'] for c in today):+.2f} USDT")
        lines.append(f"\n<b>Açık pozisyonlar ({len(self.positions)}):</b>")
        lines.extend(pos_lines or ["• yok"])
        if news_stats:
            lines.append(f"\n<b>Haber:</b> {news_stats}")
        if ai_stats:
            lines.append(f"<b>Gemini:</b> {ai_stats['calls']} çağrı, {ai_stats['errors']} hata, "
                         f"{ai_stats['fallbacks']} yedek model | tahmini maliyet ${ai_stats['cost_usd']:.3f}")
        return "\n".join(lines)
