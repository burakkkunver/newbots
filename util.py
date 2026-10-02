"""Ortak yardımcılar: saat dilimi ve CSV yazma."""
import csv
import os
import time
from datetime import datetime, timezone

import config

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo(config.TIMEZONE)
except Exception:   # tzdata yoksa sunucu saatine düş
    TZ = None


def now_local():
    return to_local(time.time())


def to_local(ts):
    return datetime.fromtimestamp(ts, TZ) if TZ else datetime.fromtimestamp(ts)


def fmt_ts(ts, with_date=True):
    """Unix zamanını 'YYYY-MM-DD HH:MM:SS' (yerel saat) olarak yazar."""
    return to_local(ts).strftime("%Y-%m-%d %H:%M:%S" if with_date else "%H:%M")


def parse_ts(text):
    """fmt_ts ile yazılmış zamanı tekrar unix zamanına çevirir."""
    dt = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    if TZ:
        dt = dt.replace(tzinfo=TZ)
    return dt.timestamp()


def today_str():
    return now_local().strftime("%Y-%m-%d")


def day_start_ts():
    d = now_local().replace(hour=0, minute=0, second=0, microsecond=0)
    return d.timestamp()


# Alternatif sinyal kaynaklarının adları (CSV'lerde "kaynak" sütunu)
SRC_SCANNER = "Hacim tarayıcı"
SRC_UPBIT = "Upbit"
SRC_COINBASE = "Coinbase"
SRC_BINANCE = "Binance duyuru"
ALT_SOURCES = (SRC_SCANNER, SRC_UPBIT, SRC_COINBASE, SRC_BINANCE)

_checked_headers = set()


def migrate_csv(path, header):
    """Dosyanın başlığı eski sürümden kalmaysa dosyayı '_eski_' ekiyle kenara alır (veri kaybolmaz)."""
    if path in _checked_headers:
        return
    if os.path.exists(path):
        with open(path, newline="") as f:
            first = next(csv.reader(f), None)
        if first != header:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            os.replace(path, path.replace(".csv", f"_eski_{stamp}.csv"))
            print(f"ℹ️ Eski formattaki {os.path.basename(path)} kenara alındı.")
    _checked_headers.add(path)


def append_csv(path, header, row):
    """CSV'ye satır ekler (başlık eskiyse önce migrate_csv ile kenara alınır)."""
    migrate_csv(path, header)
    new_file = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(header)
        w.writerow(row)


def read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def pct(a, b):
    """a'nın b'ye göre yüzde değişimi."""
    return (a / b - 1) * 100 if b else 0.0


def ago(ts):
    return time.time() - ts
