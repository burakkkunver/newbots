"""Sahte Binance (testnet + data-api) ve sahte saat: botun işlem mantığını internet olmadan test eder."""
import itertools
import json
import time as _time

import binance_api
from binance_api import BinanceError

REAL_TIME = _time.time
CLOCK = {"offset": 0.0}


def fake_time():
    return REAL_TIME() + CLOCK["offset"]


def advance(minutes):
    CLOCK["offset"] += minutes * 60


_time.time = fake_time


class Sim:
    def __init__(self, stop_loss_market=True):
        self.px = {"SOLUSDT": 150.0, "XRPUSDT": 2.0, "BTCUSDT": 84000.0, "ADAUSDT": 0.5}
        self.real = dict(self.px)           # gerçek piyasa (data-api) fiyatları
        self.btc_hist = None                # BTC 5m kapanışları (rejim için)
        self.bal = {"USDT": 10000.0, "BNB": 1.0}
        self.orders = {}
        self.lists = {}
        self.ids = itertools.count(1000)
        self.calls = []
        self.fill_stop_limits = True
        types = ["LIMIT", "LIMIT_MAKER", "MARKET", "STOP_LOSS_LIMIT", "TAKE_PROFIT_LIMIT"]
        if stop_loss_market:
            types.append("STOP_LOSS")
        self.order_types = types
        self.kline_fn = None                # (symbol, start_ms, limit) -> klines
        self.ch24 = {}                      # 24s değişim (tüm semboller isteği için)
        self.spread = {}                    # gerçek piyasada alış-satış farkı (%), sembol başına
        self.vol24 = {}                     # gerçek piyasada 24s hacim (USDT), sembol başına

    # ---------- yardımcılar ----------
    def _fill(self, o, price):
        q = float(o["origQty"])
        o.update(status="FILLED", executedQty=str(q), cummulativeQuoteQty=str(q * price))
        base = o["symbol"].replace("USDT", "")
        self.bal["USDT"] = self.bal.get("USDT", 0) + q * price   # bakiye kilidi basitleştirildi
        self.bal[base] = self.bal.get(base, 0) - q

    def tick(self):
        """Fiyatlara göre bekleyen emirleri tetikler."""
        for ol in self.lists.values():
            if ol["listOrderStatus"] == "ALL_DONE":
                continue
            tp, sl = (self.orders[i] for i in ol["ids"])
            p = self.px[tp["symbol"]]
            if p >= float(tp["price"]):
                self._fill(tp, float(tp["price"]))
                sl["status"] = "EXPIRED"
                ol["listOrderStatus"] = "ALL_DONE"
            elif p <= float(sl["stopPrice"]):
                self._fill(sl, float(sl["price"]))
                tp["status"] = "EXPIRED"
                ol["listOrderStatus"] = "ALL_DONE"
        for o in self.orders.values():
            if o.get("list") or o["status"] != "NEW" or o["type"] not in ("STOP_LOSS", "STOP_LOSS_LIMIT"):
                continue
            p = self.px[o["symbol"]]
            if p <= float(o["stopPrice"]):
                if o["type"] == "STOP_LOSS":
                    self._fill(o, p)
                elif self.fill_stop_limits and p >= float(o["price"]):
                    self._fill(o, p)
                # fill_stop_limits=False -> limit dolmadan bekler (hızlı düşüş senaryosu)

    def book(self, sym):
        """Gerçek piyasada (bid, ask): fiyatın etrafında spread/2 aşağı ve yukarı."""
        p, half = self.real[sym], self.spread.get(sym, 0.0) / 200
        return p * (1 - half), p * (1 + half)

    def klines_5m_btc(self, limit):
        hist = self.btc_hist or [self.px["BTCUSDT"]] * limit
        hist = hist[-limit:]
        t0 = int(fake_time() // 300 * 300 * 1000) - (len(hist) - 1) * 300000
        return [[t0 + i * 300000, str(c), str(c), str(c), str(c)] for i, c in enumerate(hist)]

    # ---------- istek yönlendirici ----------
    def request(self, bx, method, path, params=None, signed=False, base=None, _retry=True):
        params = dict(params or {})
        self.calls.append((method, path, params, base))
        real = base == binance_api.MARKET_DATA_URL
        if path == "/api/v3/time":
            return {"serverTime": int(fake_time() * 1000)}
        if path == "/api/v3/exchangeInfo":
            syms = []
            for s in ("SOLUSDT", "XRPUSDT", "BTCUSDT", "ADAUSDT"):
                syms.append({"symbol": s, "status": "TRADING", "quoteAsset": "USDT", "baseAsset": s[:-4],
                             "ocoAllowed": True, "orderTypes": self.order_types,
                             "filters": [{"filterType": "LOT_SIZE", "stepSize": "0.00100000", "minQty": "0.001"},
                                         {"filterType": "PRICE_FILTER", "tickSize": "0.00010000"},
                                         {"filterType": "NOTIONAL", "minNotional": "5"}]})
            return {"symbols": syms}
        if path == "/api/v3/account":
            return {"balances": [{"asset": a, "free": str(v)} for a, v in self.bal.items()]}
        if path == "/api/v3/ticker/price":
            src = self.real if real else self.px
            if "symbols" in params:
                return [{"symbol": s, "price": str(src[s])} for s in json.loads(params["symbols"]) if s in src]
            if "symbol" not in params:
                return [{"symbol": s, "price": str(v)} for s, v in src.items()]
            if params["symbol"] not in src:
                raise BinanceError(400, -1121, "Invalid symbol.")
            return {"symbol": params["symbol"], "price": str(src[params["symbol"]])}
        if path == "/api/v3/ticker/24hr" and "symbol" not in params:
            return [{"symbol": s, "priceChangePercent": str(self.ch24.get(s, 1.0)), "quoteVolume": "50000000",
                     "lastPrice": str(v)} for s, v in self.real.items()]
        if path == "/api/v3/ticker/24hr":
            sym = params["symbol"]
            if sym not in self.real:
                raise BinanceError(400, -1121, "Invalid symbol.")
            bid, ask = self.book(sym)
            return {"priceChangePercent": "3.5", "quoteVolume": str(self.vol24.get(sym, 123456789)),
                    "lastPrice": str(self.real[sym]), "bidPrice": str(bid), "askPrice": str(ask)}
        if path == "/api/v3/ticker/bookTicker":
            syms = json.loads(params["symbols"])
            if any(x not in self.real for x in syms):
                raise BinanceError(400, -1121, "Invalid symbol.")
            return [{"symbol": x, "bidPrice": str(self.book(x)[0]), "askPrice": str(self.book(x)[1])} for x in syms]
        if path == "/api/v3/klines":
            sym = params["symbol"]
            if sym not in self.real:
                raise BinanceError(400, -1121, "Invalid symbol.")
            if params["interval"] == "5m" and sym == "BTCUSDT":
                return self.klines_5m_btc(params["limit"])
            if self.kline_fn:
                return self.kline_fn(sym, params.get("startTime"), params["limit"])
            p = str(self.real[sym])
            start = params.get("startTime", int(fake_time() * 1000))
            return [[start + i * 60000, p, p, p, p, "0", 0, "1000"] for i in range(params["limit"])]
        if path == "/api/v3/order" and method == "POST":
            sym, side, typ = params["symbol"], params["side"], params["type"]
            oid = next(self.ids)
            p = self.px[sym]
            base_asset = sym[:-4]
            if typ == "MARKET" and side == "BUY":
                quote = float(params["quoteOrderQty"])
                qty = quote / p
                self.bal["USDT"] -= quote
                self.bal[base_asset] = self.bal.get(base_asset, 0) + qty
                o = {"orderId": oid, "symbol": sym, "status": "FILLED", "type": typ, "side": side,
                     "executedQty": str(qty), "cummulativeQuoteQty": str(quote),
                     "fills": [{"commission": "0.0001", "commissionAsset": "BNB"}]}
            elif typ == "MARKET" and side == "SELL":
                qty = float(params["quantity"])
                if qty > self.bal.get(base_asset, 0) + 1e-9:
                    raise BinanceError(400, -2010, "Account has insufficient balance for requested action.")
                self.bal[base_asset] -= qty
                self.bal["USDT"] += qty * p
                o = {"orderId": oid, "symbol": sym, "status": "FILLED", "type": typ, "side": side,
                     "executedQty": str(qty), "cummulativeQuoteQty": str(qty * p)}
            elif typ in ("STOP_LOSS", "STOP_LOSS_LIMIT"):
                if float(params["stopPrice"]) >= p:
                    raise BinanceError(400, -2010, "Stop price would trigger immediately.")
                o = {"orderId": oid, "symbol": sym, "status": "NEW", "type": typ, "side": side,
                     "origQty": params["quantity"], "stopPrice": params["stopPrice"],
                     "price": params.get("price", params["stopPrice"]), "executedQty": "0",
                     "cummulativeQuoteQty": "0"}
            elif typ == "LIMIT":
                o = {"orderId": oid, "symbol": sym, "status": "NEW", "type": typ, "side": side,
                     "origQty": params["quantity"], "price": params["price"], "executedQty": "0",
                     "cummulativeQuoteQty": "0"}
            else:
                raise BinanceError(400, -1116, "Invalid orderType.")
            self.orders[oid] = o
            return dict(o)
        if path == "/api/v3/orderList/oco":
            lid = next(self.ids)
            tp_id, sl_id = next(self.ids), next(self.ids)
            self.orders[tp_id] = {"orderId": tp_id, "symbol": params["symbol"], "status": "NEW", "type": "LIMIT_MAKER",
                                  "origQty": params["quantity"], "price": params["abovePrice"], "list": lid,
                                  "executedQty": "0", "cummulativeQuoteQty": "0"}
            self.orders[sl_id] = {"orderId": sl_id, "symbol": params["symbol"], "status": "NEW",
                                  "type": "STOP_LOSS_LIMIT", "origQty": params["quantity"],
                                  "stopPrice": params["belowStopPrice"], "price": params["belowPrice"], "list": lid,
                                  "executedQty": "0", "cummulativeQuoteQty": "0"}
            self.lists[lid] = {"orderListId": lid, "listOrderStatus": "EXECUTING", "ids": [tp_id, sl_id]}
            return {"orderListId": lid}
        if path == "/api/v3/orderList" and method == "GET":
            ol = self.lists[params["orderListId"]]
            return {"orderListId": ol["orderListId"], "listOrderStatus": ol["listOrderStatus"],
                    "orders": [{"orderId": i} for i in ol["ids"]]}
        if path == "/api/v3/orderList" and method == "DELETE":
            ol = self.lists[params["orderListId"]]
            if ol["listOrderStatus"] == "ALL_DONE":
                raise BinanceError(400, -2011, "Order list already done.")
            ol["listOrderStatus"] = "ALL_DONE"
            reports = []
            for i in ol["ids"]:
                self.orders[i]["status"] = "CANCELED"
                reports.append(dict(self.orders[i]))
            return {"orderReports": reports}
        if path == "/api/v3/order" and method == "GET":
            return dict(self.orders[params["orderId"]])
        if path == "/api/v3/order" and method == "DELETE":
            o = self.orders[params["orderId"]]
            if o["status"] != "NEW":
                raise BinanceError(400, -2011, "Unknown order sent.")
            o["status"] = "CANCELED"
            return dict(o)
        raise AssertionError(f"Beklenmeyen istek: {method} {path} {params}")


def install(sim):
    binance_api.Binance._request = lambda bx, method, path, params=None, signed=False, base=None, _retry=True: \
        sim.request(bx, method, path, params, signed, base, _retry)


class AIStub:
    """Testlerdeki sahte Gemini sınıfları için yeni arayüzün varsayılanları (sağlık, bütçe, harcama)."""
    def health_alert(self):
        return None

    def status_line(self):
        return "✅ çalışıyor (test)"

    def spend_line(self):
        return "bugün $0.000 / $0.15 bütçe"

    def allowed(self, purpose):
        return True, ""

    def over_budget(self):
        return False


class FakeResp:
    def __init__(self, status, data):
        self.status_code, self._data = status, data

    def json(self):
        return self._data


class Venues:
    """Sahte Gate.io ve MEXC (anahtarsız uç noktalar). prices.requests.get yerine geçer."""
    def __init__(self):
        self.px = {"gateio": {}, "mexc": {}}       # coin -> fiyat
        self.vol = {"gateio": {}, "mexc": {}}      # coin -> 24s hacim (USDT)
        self.spread = {"gateio": {}, "mexc": {}}   # coin -> alış-satış farkı (%)
        self.open = {"gateio": {}, "mexc": {}}     # coin -> haber dakikasındaki fiyat (mum)
        self.down = set()                          # erişilemeyen borsalar
        self.calls = []

    def book(self, venue, coin):
        p, half = self.px[venue][coin], self.spread[venue].get(coin, 0.0) / 200
        return p * (1 - half), p * (1 + half)

    def get(self, url, params=None, headers=None, timeout=None):
        params = params or {}
        venue = "gateio" if "gateio" in url else "mexc" if "mexc" in url else None
        self.calls.append((venue, url.rsplit("/", 1)[-1], dict(params)))
        if venue is None:
            raise AssertionError(f"Beklenmeyen istek: {url}")
        if venue in self.down:
            raise ConnectionError(f"{venue} erişilemiyor")
        if venue == "gateio":
            coin = params["currency_pair"].split("_")[0]
            if coin not in self.px["gateio"]:
                return FakeResp(400, {"label": "INVALID_CURRENCY_PAIR", "message": "Invalid currency pair"})
            p = self.px["gateio"][coin]
            if url.endswith("/spot/tickers"):
                bid, ask = self.book("gateio", coin)
                return FakeResp(200, [{"currency_pair": params["currency_pair"], "last": str(p), "lowest_ask": str(ask),
                                       "highest_bid": str(bid), "change_percentage": "12.5",
                                       "quote_volume": str(self.vol["gateio"].get(coin, 5e6))}])
            if url.endswith("/spot/candlesticks"):
                o = self.open["gateio"].get(coin, p)
                rows = []
                for t in range(int(params["from"]), int(params["to"]) + 1, 60):
                    rows.append([str(t), "1000", str(p), str(max(o, p)), str(min(o, p)), str(o), "10", "true"])
                return FakeResp(200, rows)
        else:
            coin = params["symbol"][:-4]
            if coin not in self.px["mexc"]:
                return FakeResp(400, {"code": -1121, "msg": "Invalid symbol."})
            p = self.px["mexc"][coin]
            if url.endswith("/ticker/24hr"):
                bid, ask = self.book("mexc", coin)
                return FakeResp(200, {"symbol": params["symbol"], "lastPrice": str(p), "openPrice": str(p / 1.1),
                                      "bidPrice": str(bid), "askPrice": str(ask), "priceChangePercent": "0.1",
                                      "quoteVolume": str(self.vol["mexc"].get(coin, 5e6))})
            if url.endswith("/klines"):
                o = self.open["mexc"].get(coin, p)
                start, end = int(params["startTime"]), int(params["endTime"])
                return FakeResp(200, [[t, str(o), str(max(o, p)), str(min(o, p)), str(p), "10", t + 59999, "1000"]
                                      for t in range(start, end + 1, 60000)][:int(params["limit"])])
        raise AssertionError(f"Beklenmeyen istek: {url}")


def install_venues(venues):
    import prices
    prices.requests.get = venues.get
