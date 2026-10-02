"""Gemini'ye gönderilmeden önce çalışan ücretsiz kural filtresi.

Fiyat tahmini, spekülasyon, özet/reklam içerikleri ve "fiyat zaten %X yükseldi" başlıkları
burada elenir; bunlar alım sinyali olamaz ve Gemini'ye boşuna para ödenmez.
Elenen haberler yine de kalibrasyona kaydedilir (filtre doğru mu çalışıyor, ölçebilelim diye).
"""
import re

# Bu kelimeler varsa "spekülatif" ve "özet" kuralları uygulanmaz (güçlü katalizör olabilir)
STRONG = re.compile(
    r"\b(lists?|listed|listing|delist\w*|etf|approv\w*|acquir\w*|acquisition|partner\w*|integrat\w*|"
    r"burn\w*|buyback|treasury|mainnet|launch\w*|adopt\w*|dismiss\w*|settle\w*)\b", re.I)

# (ad, açıklama, puan tavanı, güçlü kelime ile geçersiz kılınabilir mi, desenler)
RULES = [
    ("fiyat_tahmini", "Fiyat tahmini / teknik analiz / fiyat yorumu", 3, False, [
        r"\bprice (prediction|forecast|analysis|outlook|update|today)\b",
        r"\b(predicts?|predicted|prediction|forecasts?|forecasted)\b",
        r"\bprojects? \$\d",
        r"\btargets? \$\d",
        r"\$\d[\d,.]*\s?[kKmMbB]?\s+(target|next|incoming|soon|possible|in sight|ahead)\b",
        r"\b(technical analysis|chart patterns?|bull flag|bear flag|head and shoulders|fibonacci|rsi)\b",
        r"\b(support|resistance) (level|zone|line)s?\b",
        r"\bprice (stalls|eyes|holds|tests|struggles|dips|slips|hovers|consolidates|stuck|ranges)\b",
    ]),
    ("spekulatif", "Spekülatif / yorum başlığı", 4, True, [
        r"\b(could|may|might|can|will|set to|poised to|about to|ready to|primed to)\s+(soon\s+)?"
        r"(hit|reach|soar|surge|rally|explode|pump|climb|rise|jump|skyrocket|flip|break|moon|double|"
        r"triple|10x|100x|rebound|recover)\b",
        r"\?",
        r"\b(analysts?|traders?|experts?|whales?|ceo|founder|investors?|economists?)\s+(says?|said|predicts?|"
        r"warns?|expects?|believes?|thinks?|claims?|calls?|sees?)\b",
        r"\b(opinion|op-ed|editorial|commentary)\b",
        r"\b(here'?s why|this is why|reasons? why|what (it|this) means|what to expect|what'?s next)\b",
        r"\bshould you (buy|sell)\b",
    ]),
    ("fiyat_zaten_hareketli", "Fiyat hareketi zaten olmuş (başlık yükselişi anlatıyor)", 5, False, [
        r"\b(surges?|surged|soars?|soared|jumps?|jumped|rall(y|ies|ied)|spikes?|spiked|skyrockets?|"
        r"skyrocketed|pumps?|pumped|climbs?|climbed|rises?|rose|gains?|gained|rockets?|rocketed|"
        r"explodes?|exploded|leaps?|leapt|rebounds?|rebounded)\b[^.]{0,40}?\d+(\.\d+)?\s?%",
        r"\b\d+(\.\d+)?\s?%\s+(surge|rally|jump|gain|pump|spike|rise|climb|leap|increase)\b",
        r"\b(all[- ]time high|new ath|record high)\b",
    ]),
    ("ozet_icerik", "Özet / rehber / reklam içeriği", 3, True, [
        r"\b(weekly|daily|monthly|week'?s|today'?s)\b.{0,20}\b(recap|roundup|round-up|wrap|digest|review|brief)\b",
        r"\b(this week in|week in review|morning (brief|report|minute)|newsletter)\b",
        r"\b(top|best) \d+\b",
        r"\b(how to|what is|what are|explained|guide|tutorial|beginners?)\b",
        r"\b(podcast|interview|webinar|ama)\b",
        r"\b(sponsored|press release|partner content|advertorial|presale|pre-sale)\b",
        r"\bbest (crypto|altcoins?|coins?|tokens?|meme ?coins?) to (buy|watch)\b",
        r"\b(coins?|altcoins?|tokens?) to watch\b",
    ]),
]

_COMPILED = [(name, desc, cap, overridable, [re.compile(p, re.I) for p in pats])
             for name, desc, cap, overridable, pats in RULES]


def prefilter(title):
    """Elenmesi gereken başlıksa {"filtre", "puan", "sebep"} döner, değilse None."""
    strong = bool(STRONG.search(title))
    for name, desc, cap, overridable, pats in _COMPILED:
        if overridable and strong:
            continue
        for p in pats:
            m = p.search(title)
            if m:
                return {"filtre": name, "puan": cap, "sebep": f"Kural filtresi: {desc} (\"{m.group(0).strip()}\")"}
    return None


# ---------- elenen haberlerde coin tahmini (sadece kalibrasyon için) ----------
NAME_MAP = {
    "bitcoin cash": "BCH", "ethereum classic": "ETC", "shiba inu": "SHIB", "near protocol": "NEAR",
    "bitcoin": "BTC", "ethereum": "ETH", "ether": "ETH", "solana": "SOL", "ripple": "XRP",
    "cardano": "ADA", "dogecoin": "DOGE", "polkadot": "DOT", "chainlink": "LINK", "avalanche": "AVAX",
    "litecoin": "LTC", "tron": "TRX", "toncoin": "TON", "polygon": "POL", "aptos": "APT",
    "arbitrum": "ARB", "optimism": "OP", "cosmos": "ATOM", "stellar": "XLM", "hedera": "HBAR",
    "pepe": "PEPE", "bonk": "BONK", "dogwifhat": "WIF", "uniswap": "UNI", "aave": "AAVE",
    "injective": "INJ", "filecoin": "FIL", "monero": "XMR", "kaspa": "KAS", "hyperliquid": "HYPE",
    "ondo": "ONDO", "jupiter": "JUP", "worldcoin": "WLD", "celestia": "TIA", "algorand": "ALGO",
    "vechain": "VET", "floki": "FLOKI", "sui": "SUI", "sei": "SEI",
    "the sandbox": "SAND", "decentraland": "MANA", "axie infinity": "AXS", "lido": "LDO",
    "pendle": "PENDLE", "ethena": "ENA", "starknet": "STRK",
}
_NAME_RE = [(re.compile(r"\b" + re.escape(k) + r"\b", re.I), v)
            for k, v in sorted(NAME_MAP.items(), key=lambda kv: -len(kv[0]))]
_STOP_TICKERS = {"ETF", "SEC", "CEO", "USD", "US", "AI", "NFT", "DEFI", "DAO", "CPI", "FED", "FOMC", "IPO",
                 "API", "UK", "EU", "CFTC", "DOJ", "FBI", "IRS", "GDP", "ATH", "TVL", "KYC", "AML", "OTC",
                 "CEX", "DEX", "USDT", "USDC", "THE", "NEW", "TOP", "NOW", "ALL", "ONE", "WIN", "GAS"}


def extract_coin(title, known_bases):
    """Başlıktan coin sembolü tahmini. Önce BÜYÜK HARFLİ sembol (XRP, SOL), sonra isim (Solana)."""
    for tok in re.findall(r"\$?\b[A-Z0-9]{3,10}\b", title):
        tok = tok.lstrip("$")
        if tok in known_bases and tok not in _STOP_TICKERS:
            return tok
    for rx, sym in _NAME_RE:
        if rx.search(title):
            return sym
    return "GENEL"


def title_mentions(title, coin):
    """Başlıkta bu coin geçiyor mu? Sembol (UNI, $UNI) veya tam adı (Uniswap) aranır."""
    if not coin or coin == "GENEL":
        return False
    if re.search(r"(?<![A-Za-z0-9])\$?" + re.escape(coin) + r"(?![A-Za-z0-9])", title):
        return True
    return any(sym == coin and rx.search(title) for rx, sym in _NAME_RE)
