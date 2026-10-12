"""Sanal işlemler: gerçek fiyatlarla "almış gibi yap", testnetle aynı kurallarla sat. Para harcanmaz, kayıt tutulur.

İki tür sanal işlem var:
  - SANAL: sinyal gelen coin Binance testnette (ya da hiç Binance'te) yoksa. Gerçek fiyat Binance'in gerçek
    piyasasından, orada da yoksa Gate.io veya MEXC'den okunur. Ayrı bir sanal bütçe kullanılır (PAPER_BUDGET_USDT).
  - AYNA: her testnet alımının gerçek Binance fiyatlarıyla kopyası. Testnette küçük coinlerin fiyatı gerçek
    piyasadan çok farklı gidebiliyor (RSR: testnet -%0,25, aynı anda gerçek piyasa +%35); stratejinin gerçek
    sonucunu ayna gösterir.
Kurallar testnetle aynı: -%HARD_STOP_PCT stop, izleyen stop veya sabit kâr al, time-stop, süre sınırı.
Gerçekçi olsun diye alım satış fiyatından (ask), satış alış fiyatından (bid) yapılır ve her yönde PAPER_FEE_PCT
komisyon düşülür. Fiyat PAPER_CHECK_SECONDS saniyede bir okunur: borsadaki gerçek bir stop emrine göre çıkış birkaç
saniye gecikebilir, hızlı düşüşte sonuç biraz daha kötü yazılır (temkinli tarafta kalır).
"""
import json
import os
import threading
import time
import uuid

import config
from notify import esc, send_telegram
from prices import VENUE_NAMES
from trader import rules_for
from util import append_csv, day_start_ts, fmt_ts, pct

PAPER_FILE = os.path.join(config.DATA_DIR, "paper.json")
PAPER_CSV = os.path.join(config.DATA_DIR, "sanal_islemler.csv")
PAPER_HEADER = ["tur", "acilis", "kapanis", "coin", "borsa", "puan", "rejim", "mod", "giris", "cikis",
                "maliyet_usdt", "kar_usdt", "kar_yuzde", "zirve_yuzde", "dip_yuzde", "cikis_sebebi", "sure_dk",
                "olay_turu", "kaynak", "testnet_kar_yuzde", "haber"]
STABLES = {"USDT", "USDC", "FDUSD", "DAI", "TUSD", "BUSD", "USDE", "USDP", "PYUSD", "EUR", "TRY", "GENEL", ""}
STALE_SWITCH_SEC = 15 * 60      # bu kadar süre fiyat alınamazsa başka borsaya geçilir
GIVE_UP_SEC = 60 * 60           # süre dolduktan sonra bu kadar süre fiyat yoksa son fiyatla kapatılır


def venue_name(v):
    return VENUE_NAMES.get(v, v)


class PaperTrader:
    def __init__(self, prices, testnet_result=None):
        self.px = prices
        self.testnet_result = testnet_result   # testnet pozisyon kimliği -> kapandıysa K/Z yüzdesi (ayna mesajı için)
        self.lock = threading.RLock()
        self.positions = []
        self.state = {"closed": [], "realized": {"sanal": 0.0, "ayna": 0.0}, "cooldown": {}}
        self._outbox = []
        self._load()

    @property
    def mirror_enabled(self):
        return config.PAPER_ENABLED and config.PAPER_MIRROR and config.TEST_MODE

    # ---------- kalıcı durum ----------
    def _load(self):
        try:
            with open(PAPER_FILE) as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return
        self.positions = data.get("positions", [])
        for key in ("closed", "realized", "cooldown"):
            if key in data:
                self.state[key] = data[key]

    def _save(self):
        with self.lock:
            tmp = PAPER_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(dict(self.state, positions=self.positions), f, indent=1)
            os.replace(tmp, PAPER_FILE)

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

    # ---------- sanal bütçe ----------
    def _open(self, kind):
        with self.lock:
            return [p for p in self.positions if p["kind"] == kind]

    def equity(self):
        return config.PAPER_BUDGET_USDT + self.state["realized"].get("sanal", 0.0)

    def cash(self):
        return self.equity() - sum(p["cost"] for p in self._open("sanal"))

    def _amount(self, score, regime):
        available = self.cash()
        amount = min(self.equity() * rules_for(score)["alloc"] * regime["alloc"], config.MAX_TRADE_USDT, available)
        if amount < config.MIN_TRADE_USDT:
            if available < config.MIN_TRADE_USDT:
                return None, f"Sanal bütçe yetersiz: boşta {max(0.0, available):.2f} USDT."
            amount = config.MIN_TRADE_USDT
        return amount, ""

    # ---------- sanal alım (Trader.precheck / execute_buy ile aynı arayüz) ----------
    def precheck(self, coin, score, item, regime, late_limit=None):
        coin = (coin or "").upper()
        if coin in STABLES:
            return False, "GENEL", "Belirli bir coin yok, işlem yapılmaz.", {}
        with self.lock:
            if any(p["coin"] == coin for p in self._open("sanal")):
                return False, "SANAL_POZISYON", f"{coin} için zaten açık sanal pozisyon var.", {}
            cd = self.state["cooldown"].get(coin, 0)
            if time.time() < cd:
                return False, "SANAL_BEKLEME", f"{coin} bekleme süresinde ({int((cd - time.time()) / 60)} dk kaldı).", {}
            if len(self._open("sanal")) >= config.PAPER_MAX_OPEN:
                return False, "SANAL_MAKS", f"Maksimum sanal pozisyon ({config.PAPER_MAX_OPEN}) dolu.", {}
        q = self.px.find(coin)
        if not q:
            names = ", ".join(venue_name(v) for v in config.PAPER_VENUES)
            return False, "SANAL_FIYAT_YOK", f"{coin} testnette yok, gerçek fiyatı da bulunamadı ({names}).", {}
        vname = venue_name(q["venue"])
        ctx = {"coin": coin, "symbol": f"{coin}USDT", "venue": q["venue"], "quote": q, "late_move": None,
               "late_limit": config.LATE_MOVE_PCT if late_limit is None else late_limit,
               "coin_ch24": q.get("ch24"), "coin_volume": q.get("vol24")}
        if (q.get("vol24") or 0) < config.PAPER_MIN_VOL_USDT:
            return False, "SANAL_HACIM", (f"{coin} testnette yok; {vname} 24s hacmi {q.get('vol24') or 0:,.0f} $, "
                                          f"sanal işlem için çok düşük."), ctx
        try:
            p_news = self.px.price_at(q["venue"], coin, item["published"])
            ctx["p_news"] = p_news
            if p_news:
                move = pct(q["last"], p_news)
                ctx["late_move"] = move
                if move >= ctx["late_limit"]:
                    return False, "SANAL_TREN", f"Tren kaçtı ({vname}): haberden sonra fiyat zaten %{move:.2f} yükselmiş.", ctx
        except Exception as e:
            ctx["late_note"] = f"haber anındaki fiyat alınamadı: {e}"
        amount, why = self._amount(score, regime)
        if amount is None:
            return False, "SANAL_BAKIYE", why, ctx
        ctx["amount"] = amount
        return True, "OK", "", ctx

    def execute_buy(self, ctx, res, item, regime, review=None, note=""):
        """Sanal alım. ('SANAL_ALINDI', açıklama) veya engel kodu döner."""
        coin, venue = ctx["coin"], ctx["venue"]
        vname = venue_name(venue)
        q = ctx["quote"]
        try:   # ikinci görüş beklenirken fiyat değişmiş olabilir
            q = self.px.quote(venue, coin) or q
        except Exception:
            pass
        if ctx.get("p_news"):
            move = pct(q["last"], ctx["p_news"])
            ctx["late_move"] = move
            if move >= ctx["late_limit"]:
                return "SANAL_TREN", f"Tren kaçtı (ikinci görüş beklenirken, {vname}): fiyat %{move:.2f} yükseldi."
        with self.lock:
            if any(p["coin"] == coin for p in self._open("sanal")):
                return "SANAL_POZISYON", f"{coin} için zaten açık sanal pozisyon var."
            pos = self._new_position("sanal", coin, venue, q["ask"], ctx["amount"], res["puan"], regime,
                                     res.get("olay_turu", ""), item)
            self.positions.append(pos)
            self._save()

        rules = rules_for(pos["score"])
        if pos["mode"] == "trailing":
            exit_txt = (f"<b>İzleyen stop:</b> +%{rules['trail_act']:g} kârda devreye girer, "
                        f"zirvenin %{rules['trail_dist']:g} altından takip eder")
        else:
            exit_txt = f"<b>Kâr Al:</b> {pos['tp']:.6g} (+%{rules['tp_fixed']:g})"
        ts_txt = (f"\n<b>Time-stop:</b> {config.TIME_STOP_MIN:g} dk'da +%{config.TIME_STOP_MIN_PROFIT:g} altındaysa çıkar"
                  if pos["time_stop"] else "")
        late = ctx.get("late_move")
        extra = f"\n<b>İkinci görüş:</b> onay (güven {review['guven']:.0f}) — {esc(review['sebep'])}" if review else ""
        if note:
            extra += f"\n{note}"
        self._notify(
            f"🧪 <b>Sanal İşlem Açıldı</b> (para harcanmadı)\n\n"
            f"<b>Neden sanal:</b> {esc(coin)} Binance testnette yok. <b>Gerçek fiyat kaynağı:</b> {vname}\n"
            f"<b>Coin:</b> {esc(coin)} | <b>Puan:</b> {pos['score']:.0f}/10 | <b>Rejim:</b> {regime.get('ad', regime['name'])}\n"
            f"<b>Tutar:</b> {pos['cost']:.2f} USDT (sanal bütçe) | <b>Giriş:</b> {pos['entry']:.6g} "
            f"(satış fiyatı, +%{config.PAPER_FEE_PCT:g} komisyon)\n{exit_txt}\n"
            f"<b>Zarar Kes:</b> {pos['stop']:.6g} (-%{config.HARD_STOP_PCT:g}){ts_txt}\n"
            f"<b>Maks. süre:</b> {pos['hold_min']:g} dk | <b>24s hacim:</b> {(ctx.get('coin_volume') or 0) / 1e6:,.1f} M$"
            + (f"\n<b>Haberden beri fiyat:</b> {late:+.2f}%" if late is not None else "")
            + f"\n\n<b>Haber:</b> {esc(item['title'])}\n"
              f"<b>Olay:</b> {esc(res.get('olay_turu', ''))}/{esc(res.get('kesinlik', ''))}/{esc(res.get('aktor', ''))}\n"
              f"<b>Sebep:</b> {esc(res.get('sebep', ''))}{extra}")
        self._flush()
        return "SANAL_ALINDI", f"{coin} {pos['cost']:.2f} USDT @ {pos['entry']:.6g} ({vname}, sanal)"

    def mirror(self, tpos):
        """Testnet alımının gerçek Binance fiyatlarıyla kopyası. Testnet pozisyonunun kuralları aynen kullanılır."""
        if not self.mirror_enabled:
            return None
        coin = tpos.get("coin") or tpos["symbol"][:-4]
        try:
            q = self.px.quote("binance", coin)
        except Exception as e:
            print(f"⚠️ Ayna açılamadı ({coin}): {e}")
            return None
        if not q:
            print(f"ℹ️ {coin} gerçek Binance'te yok, ayna açılmadı.")
            return None
        regime = {"name": tpos.get("regime", "?"), "exit": tpos["mode"], "hold_mult": 1}
        item = {"title": tpos.get("title", ""), "link": tpos.get("link", ""), "source": tpos.get("source", "")}
        with self.lock:
            pos = self._new_position("ayna", coin, "binance", q["ask"], tpos["cost"], tpos["score"], regime,
                                     tpos.get("event", ""), item, hold_min=tpos["hold_min"], testnet_id=tpos.get("id"))
            self.positions.append(pos)
            self._save()
        print(f"🪞 Ayna açıldı: {coin} gerçek fiyat {q['ask']:.6g} (testnet {tpos['entry']:.6g})")
        return pos

    def _new_position(self, kind, coin, venue, ask, cost, score, regime, event, item, hold_min=None, testnet_id=None):
        rules = rules_for(score)
        mode = regime["exit"]
        if hold_min is None:
            hold_min = rules["hold_min"] * regime["hold_mult"]
        now = time.time()
        return {
            "id": uuid.uuid4().hex[:8], "kind": kind, "coin": coin, "symbol": f"{coin}USDT", "venue": venue,
            "score": score, "entry": ask, "entry_eff": ask * (1 + config.PAPER_FEE_PCT / 100), "cost": cost,
            "opened_at": now, "deadline": now + hold_min * 60, "hold_min": hold_min, "mode": mode,
            "regime": regime["name"], "tp": ask * (1 + rules["tp_fixed"] / 100) if mode == "fixed" else None,
            "stop": ask * (1 - config.HARD_STOP_PCT / 100), "peak": ask, "trough": ask, "trail_active": False,
            "trail_act": rules["trail_act"], "trail_dist": rules["trail_dist"], "time_stop": rules["time_stop"],
            "time_stop_done": False, "event": event, "title": item.get("title", ""), "link": item.get("link", ""),
            "source": item.get("source", ""), "last_price": ask, "last_quote_at": now, "testnet_id": testnet_id}

    # ---------- takip ----------
    def monitor_forever(self, stop_event):
        while not stop_event.is_set():
            t0 = time.time()
            try:
                self.manage()
            except Exception as e:
                print(f"⚠️ Sanal pozisyon takibi hatası: {e}")
            stop_event.wait(max(2.0, config.PAPER_CHECK_SECONDS - (time.time() - t0)))

    def manage(self):
        with self.lock:
            pairs = sorted({(p["venue"], p["coin"]) for p in self.positions})
        if not pairs:
            return
        quotes = self.px.quotes(pairs)
        now = time.time()
        stale = []
        with self.lock:
            for pos in list(self.positions):
                q = quotes.get((pos["venue"], pos["coin"]))
                try:
                    if q:
                        pos["last_quote_at"] = now
                        self._manage_one(pos, q)
                    elif now - pos.get("last_quote_at", now) > STALE_SWITCH_SEC:
                        stale.append(pos)
                except Exception as e:
                    print(f"⚠️ Sanal pozisyon kontrol hatası {pos['coin']}: {e}")
        for pos in stale:
            self._handle_stale(pos, now)
        self._flush()

    def _handle_stale(self, pos, now):
        """Uzun süre fiyat alınamayan pozisyon: başka borsaya geç, olmazsa süre dolunca son fiyatla kapat."""
        q = None
        if pos["kind"] == "sanal":   # ayna sadece Binance fiyatıyla anlamlı
            q = self.px.find(pos["coin"], [v for v in config.PAPER_VENUES if v != pos["venue"]])
        with self.lock:
            if pos not in self.positions:
                return
            if q:
                print(f"🔁 {pos['coin']} sanal pozisyonu {venue_name(pos['venue'])} yerine "
                      f"{venue_name(q['venue'])} fiyatıyla takip edilecek.")
                pos.update(venue=q["venue"], last_quote_at=now)
                self._save()
            elif now >= pos["deadline"] + GIVE_UP_SEC:
                self._close(pos, pos.get("last_price") or pos["entry"], "FİYAT ALINAMADI (son fiyatla kapatıldı)")

    def _manage_one(self, pos, q):
        now = time.time()
        price = q.get("bid") or q["last"]   # hemen satılsa alınacak fiyat
        pos["last_price"] = price
        changed = False
        if price > pos["peak"]:
            pos["peak"] = price
            changed = True
        if price < pos.get("trough", pos["entry"]):
            pos["trough"] = price
            changed = True
        gain = pct(price, pos["entry"])
        peak_gain = pct(pos["peak"], pos["entry"])

        # 1) İzleyen stop
        if pos["mode"] == "trailing":
            if not pos["trail_active"] and peak_gain >= pos["trail_act"]:
                pos["trail_active"] = True
                changed = True
                if pos["kind"] == "sanal":
                    self._notify(f"📈 🧪 <b>{esc(pos['coin'])}</b> (sanal) izleyen stop devrede: zirve +{peak_gain:.2f}%, "
                                 f"stop zirvenin %{pos['trail_dist']:g} altından takip ediyor.")
            if pos["trail_active"]:
                new_stop = pos["peak"] * (1 - pos["trail_dist"] / 100)
                if new_stop > pos["stop"]:
                    pos["stop"] = new_stop
                    changed = True

        # 2) Zarar kes / izleyen stop / kâr al
        if price <= pos["stop"]:
            locked = pos["trail_active"] and pos["stop"] > pos["entry"]
            return self._close(pos, price, "İZLEYEN STOP" if locked else "ZARAR KES")
        if pos.get("tp") and price >= pos["tp"]:
            return self._close(pos, price, "KÂR AL")

        # 3) Time-stop (7-8 puan)
        if pos["time_stop"] and not pos["time_stop_done"] and now - pos["opened_at"] >= config.TIME_STOP_MIN * 60:
            pos["time_stop_done"] = True
            changed = True
            if gain < config.TIME_STOP_MIN_PROFIT and not pos["trail_active"]:
                return self._close(pos, price, f"TIME-STOP ({config.TIME_STOP_MIN:g} dk'da beklenen sıçrama yok)")

        # 4) Süre doldu (izleyen stop aktifse kâr korunarak devam)
        if now >= pos["deadline"] and not pos["trail_active"]:
            return self._close(pos, price, "SÜRE DOLDU")
        if changed:
            self._save()

    def _close(self, pos, price, reason):
        exit_eff = price * (1 - config.PAPER_FEE_PCT / 100)
        pnl_pct = pct(exit_eff, pos["entry_eff"])
        pnl = pos["cost"] * pnl_pct / 100
        peak_pct = pct(pos["peak"], pos["entry"])
        trough_pct = pct(pos.get("trough", pos["entry"]), pos["entry"])
        minutes = int((time.time() - pos["opened_at"]) / 60)
        testnet_pct = None
        if pos["kind"] == "ayna" and self.testnet_result and pos.get("testnet_id"):
            try:
                testnet_pct = self.testnet_result(pos["testnet_id"])
            except Exception:
                pass
        with self.lock:
            realized = self.state["realized"]
            realized[pos["kind"]] = realized.get(pos["kind"], 0.0) + pnl
            if pos["kind"] == "sanal":
                self.state["cooldown"][pos["coin"]] = time.time() + config.COIN_COOLDOWN_MIN * 60
            self.state["closed"].append({
                "id": pos["id"], "kind": pos["kind"], "coin": pos["coin"], "venue": pos["venue"],
                "score": pos["score"], "regime": pos["regime"], "mode": pos["mode"], "pnl": pnl, "pct": pnl_pct,
                "peak_pct": peak_pct, "trough_pct": trough_pct, "reason": reason, "opened_at": pos["opened_at"],
                "closed_at": time.time(), "minutes": minutes, "title": pos["title"][:120], "event": pos["event"],
                "testnet_pct": testnet_pct, "testnet_id": pos.get("testnet_id")})
            self.state["closed"] = self.state["closed"][-500:]
            self.positions = [p for p in self.positions if p["id"] != pos["id"]]
            self._save()
        append_csv(PAPER_CSV, PAPER_HEADER, [
            pos["kind"], fmt_ts(pos["opened_at"]), fmt_ts(time.time()), pos["coin"], venue_name(pos["venue"]),
            int(pos["score"]), pos["regime"], pos["mode"], f"{pos['entry']:.8g}", f"{price:.8g}", f"{pos['cost']:.2f}",
            f"{pnl:.4f}", f"{pnl_pct:.2f}", f"{peak_pct:.2f}", f"{trough_pct:.2f}", reason, minutes, pos["event"],
            pos["source"], f"{testnet_pct:.2f}" if testnet_pct is not None else "", pos["title"]])
        icon = "🟢" if pnl >= 0 else "🔴"
        if pos["kind"] == "ayna":
            tn = f" | testnette aynı işlem: {testnet_pct:+.2f}%" if testnet_pct is not None else " | testnet işlemi hâlâ açık"
            self._notify(f"🪞{icon} <b>Ayna kapandı</b> (gerçek Binance fiyatı) — {pos['symbol']} {esc(reason)}\n"
                         f"{pnl_pct:+.2f}% (zirve +{peak_pct:.1f}%, dip {trough_pct:+.1f}%), {minutes} dk{tn}")
            return
        self._notify(
            f"🧪{icon} <b>Sanal Pozisyon Kapandı</b> — {esc(reason)}\n\n"
            f"<b>Coin:</b> {esc(pos['coin'])} ({int(pos['score'])}/10, "
            f"{'izleyen stop' if pos['mode'] == 'trailing' else 'sabit hedef'}) | <b>Fiyat kaynağı:</b> {venue_name(pos['venue'])}\n"
            f"<b>Giriş → Çıkış:</b> {pos['entry']:.6g} → {price:.6g}\n"
            f"<b>Kâr/Zarar:</b> {pnl:+.2f} USDT ({pnl_pct:+.2f}%, komisyon dahil) | <b>Zirve:</b> +{peak_pct:.1f}% | "
            f"<b>Dip:</b> {trough_pct:+.1f}%\n<b>Süre:</b> {minutes} dk\n"
            f"<b>Sanal bütçe:</b> {self.equity():.2f} USDT (başlangıç {config.PAPER_BUDGET_USDT:g})")

    # ---------- özet ----------
    def closed_today(self):
        start = day_start_ts()
        return [c for c in self.state["closed"] if c["closed_at"] >= start]

    def position_lines(self):
        with self.lock:
            positions = [dict(p) for p in self.positions]
        lines = []
        for p in positions:
            price = p.get("last_price") or p["entry"]
            left = (p["deadline"] - time.time()) / 60
            left_txt = ("süre doldu" if left < 0 else
                        f"{left:.0f} dk kaldı" if left < 120 else f"{left / 60:.1f} sa kaldı")
            if p["mode"] == "trailing":
                guard = (f"izleyen stop {pct(p['stop'], p['entry']):+.2f}%" if p["trail_active"]
                         else f"izleyen +%{p['trail_act']:g}'de")
            else:
                guard = f"TP +{pct(p['tp'], p['entry']):.1f}%"
            tag = "🪞 ayna" if p["kind"] == "ayna" else f"🧪 {venue_name(p['venue'])}"
            lines.append(f"• {p['coin']} [{tag}] {pct(price, p['entry']):+.2f}% | {guard} | {left_txt}")
        return lines

    def summary_lines(self):
        """/durum için kısa özet."""
        r = self.state["realized"]
        open_value = sum(p["cost"] * (1 + pct(p.get("last_price") or p["entry"], p["entry"]) / 100)
                         for p in self._open("sanal"))
        lines = [f"<b>Sanal bütçe:</b> {self.cash() + open_value:.2f} USDT (başlangıç {config.PAPER_BUDGET_USDT:g}) | "
                 f"gerçekleşen {r.get('sanal', 0):+.2f} USDT | ayna toplamı {r.get('ayna', 0):+.2f} USDT"]
        lines += self.position_lines()
        return lines
