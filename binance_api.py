"""Küçük ve bağımlılıksız Binance Spot REST istemcisi (testnet + gerçek)."""
import hashlib
import hmac
import time
from decimal import ROUND_DOWN, ROUND_UP, Decimal
from urllib.parse import urlencode

import requests

TESTNET_URL = "https://testnet.binance.vision"
MAINNET_URL = "https://api.binance.com"
# Gerçek piyasa verisi (anahtarsız, coğrafi kısıtlaması yok). "Haberden sonra fiyat
# ne kadar oynadı" kontrolü testnet'in yapay fiyatlarıyla değil gerçek fiyatla yapılır.
MARKET_DATA_URL = "https://data-api.binance.vision"


class BinanceError(Exception):
    def __init__(self, status, code, msg):
        super().__init__(f"HTTP {status} / {code}: {msg}")
        self.status, self.code, self.msg = status, code, msg


def fmt(d):
    """Decimal'i bilimsel gösterim olmadan string'e çevirir."""
    s = format(d.normalize(), "f")
    return s


def floor_step(value, step):
    step = Decimal(step)
    if step == 0:
        return Decimal(str(value))
    return (Decimal(str(value)) / step).to_integral_value(rounding=ROUND_DOWN) * step


def ceil_step(value, step):
    step = Decimal(step)
    if step == 0:
        return Decimal(str(value))
    return (Decimal(str(value)) / step).to_integral_value(rounding=ROUND_UP) * step


class Binance:
    def __init__(self, api_key, secret, testnet=True):
        self.base = TESTNET_URL if testnet else MAINNET_URL
        self.secret = (secret or "").encode()
        self.session = requests.Session()
        self.session.headers["X-MBX-APIKEY"] = api_key or ""
        self.time_offset = 0
        self.symbols = {}
        self._symbols_loaded_at = 0

    # ---------- temel istek ----------
    def _request(self, method, path, params=None, signed=False, base=None, _retry=True):
        params = {k: v for k, v in (params or {}).items() if v is not None}
        if signed:
            params["timestamp"] = int(time.time() * 1000 + self.time_offset)
            params["recvWindow"] = 10000
            query = urlencode(params)
            sig = hmac.new(self.secret, query.encode(), hashlib.sha256).hexdigest()
            query += f"&signature={sig}"
        else:
            query = urlencode(params)
        url = f"{base or self.base}{path}" + (f"?{query}" if query else "")
        r = self.session.request(method, url, timeout=15)
        try:
            data = r.json()
        except ValueError:
            data = {"msg": r.text[:200]}
        if r.status_code >= 400:
            code = data.get("code") if isinstance(data, dict) else None
            if code == -1021 and _retry:   # saat farkı -> senkronla ve bir kez daha dene
                self.sync_time()
                return self._request(method, path, params={k: v for k, v in params.items()
                                     if k not in ("timestamp", "recvWindow", "signature")},
                                     signed=signed, base=base, _retry=False)
            raise BinanceError(r.status_code, code, data.get("msg") if isinstance(data, dict) else data)
        return data

    def sync_time(self):
        server = self._request("GET", "/api/v3/time")["serverTime"]
        self.time_offset = server - int(time.time() * 1000)

    # ---------- sembol bilgileri ----------
    def load_symbols(self, force=False):
        if not force and self.symbols and time.time() - self._symbols_loaded_at < 6 * 3600:
            return
        info = self._request("GET", "/api/v3/exchangeInfo", {"permissions": "SPOT"})
        symbols = {}
        for s in info.get("symbols", []):
            if s.get("status") != "TRADING" or s.get("quoteAsset") != "USDT":
                continue
            f = {flt["filterType"]: flt for flt in s.get("filters", [])}
            min_notional = 5.0
            if "NOTIONAL" in f:
                min_notional = float(f["NOTIONAL"].get("minNotional", 5))
            elif "MIN_NOTIONAL" in f:
                min_notional = float(f["MIN_NOTIONAL"].get("minNotional", 5))
            symbols[s["symbol"]] = {
                "base": s["baseAsset"],
                "step": f.get("LOT_SIZE", {}).get("stepSize", "0.00000001"),
                "min_qty": float(f.get("LOT_SIZE", {}).get("minQty", 0)),
                "tick": f.get("PRICE_FILTER", {}).get("tickSize", "0.00000001"),
                "min_notional": min_notional,
                "oco": s.get("ocoAllowed", False),
            }
        self.symbols = symbols
        self._symbols_loaded_at = time.time()

    # ---------- piyasa verisi ----------
    def price(self, symbol):
        return float(self._request("GET", "/api/v3/ticker/price", {"symbol": symbol})["price"])

    def real_price(self, symbol):
        return float(self._request("GET", "/api/v3/ticker/price", {"symbol": symbol},
                                   base=MARKET_DATA_URL)["price"])

    def real_price_at(self, symbol, ts_seconds):
        """Gerçek piyasada verilen andaki (1 dk mum açılışı) fiyat."""
        kl = self._request("GET", "/api/v3/klines", {
            "symbol": symbol, "interval": "1m", "startTime": int(ts_seconds * 1000), "limit": 1},
            base=MARKET_DATA_URL)
        return float(kl[0][1]) if kl else None

    # ---------- hesap ----------
    def balances(self):
        acc = self._request("GET", "/api/v3/account", {"omitZeroBalances": "true"}, signed=True)
        return {b["asset"]: float(b["free"]) for b in acc.get("balances", [])}

    def free(self, asset):
        return self.balances().get(asset, 0.0)

    # ---------- emirler ----------
    def market_buy(self, symbol, quote_usdt):
        return self._request("POST", "/api/v3/order", {
            "symbol": symbol, "side": "BUY", "type": "MARKET",
            "quoteOrderQty": f"{quote_usdt:.2f}", "newOrderRespType": "FULL"}, signed=True)

    def market_sell(self, symbol, qty):
        return self._request("POST", "/api/v3/order", {
            "symbol": symbol, "side": "SELL", "type": "MARKET",
            "quantity": qty, "newOrderRespType": "FULL"}, signed=True)

    def limit_sell(self, symbol, qty, price):
        return self._request("POST", "/api/v3/order", {
            "symbol": symbol, "side": "SELL", "type": "LIMIT", "timeInForce": "GTC",
            "quantity": qty, "price": price}, signed=True)

    def oco_sell(self, symbol, qty, tp_price, sl_stop, sl_limit):
        """Kâr al (LIMIT_MAKER) + zarar kes (STOP_LOSS_LIMIT). Yeni endpoint olmazsa eskisine düşer."""
        try:
            return self._request("POST", "/api/v3/orderList/oco", {
                "symbol": symbol, "side": "SELL", "quantity": qty,
                "aboveType": "LIMIT_MAKER", "abovePrice": tp_price,
                "belowType": "STOP_LOSS_LIMIT", "belowStopPrice": sl_stop,
                "belowPrice": sl_limit, "belowTimeInForce": "GTC"}, signed=True)
        except BinanceError as e:
            if e.status != 404 and e.code not in (-1100, -1102, -1104):
                raise
        return self._request("POST", "/api/v3/order/oco", {
            "symbol": symbol, "side": "SELL", "quantity": qty, "price": tp_price,
            "stopPrice": sl_stop, "stopLimitPrice": sl_limit,
            "stopLimitTimeInForce": "GTC"}, signed=True)

    def get_order(self, symbol, order_id):
        return self._request("GET", "/api/v3/order", {"symbol": symbol, "orderId": order_id}, signed=True)

    def cancel_order(self, symbol, order_id):
        return self._request("DELETE", "/api/v3/order", {"symbol": symbol, "orderId": order_id}, signed=True)

    def get_order_list(self, order_list_id):
        return self._request("GET", "/api/v3/orderList", {"orderListId": order_list_id}, signed=True)

    def cancel_order_list(self, symbol, order_list_id):
        return self._request("DELETE", "/api/v3/orderList",
                             {"symbol": symbol, "orderListId": order_list_id}, signed=True)
