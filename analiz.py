"""Kalibrasyon ve işlem analizi. Sunucuda:  python3 analiz.py        (tüm veriler)
                                            python3 analiz.py 7      (son 7 gün)

data/calibration.csv : her haberden sonra fiyatın 15 dk / 1 saat / 4 saat içinde ne yaptığı
data/trades.csv      : açılıp kapanan işlemler
"""
import sys
import time

from calibration import BUCKETS, f, group_stats, load_rows, score_bucket
from trader import TRADES_CSV
from util import parse_ts, read_csv


def p(v, sign=True):
    if v is None:
        return "    -"
    return f"{v:+5.1f}%" if sign else f"{v:4.0f}%"


def table(title, stats):
    print(f"\n=== {title} ===")
    print(f"{'grup':<22}{'n':>5} {'r15dk':>7}{'r1s':>7}{'r4s':>7}{'max1s':>7}{'max4s':>7}"
          f"{'+%2 ulaşan':>11}{'-%2 gören':>10}{'BTC farkı':>10}")
    for s in stats:
        print(f"{str(s['grup'])[:21]:<22}{s['n']:>5} {p(s['r15']):>7}{p(s['r1']):>7}{p(s['r4']):>7}"
              f"{p(s['max1']):>7}{p(s['max4']):>7}{p(s['hit2'], False):>11}{p(s['stop2'], False):>10}"
              f"{p(s['fark1']):>10}")


def main():
    days = float(sys.argv[1]) if len(sys.argv) > 1 else None
    since = time.time() - days * 86400 if days else None
    rows = load_rows(since_ts=since)
    print(f"Kalibrasyon kaydı: {len(rows)}" + (f" (son {days:g} gün)" if days else ""))
    print("r15dk/r1s/r4s: sinyalden 15 dk/1 saat/4 saat sonraki ortalama getiri")
    print("max1s/max4s: o süre içindeki en yüksek noktanın ortalaması | BTC farkı: coin getirisi - BTC getirisi (1 saat)")
    if rows:
        table("PUANA GÖRE", group_stats(rows, score_bucket, [b[0] for b in BUCKETS]))
        table("KARAR / DURUM KODUNA GÖRE", group_stats(rows, lambda r: r.get("durum_kodu") or "?"))
        table("OLAY TÜRÜNE GÖRE", group_stats(rows, lambda r: r.get("olay_turu") or "?"))
        table("KESİNLİĞE GÖRE", group_stats(rows, lambda r: r.get("kesinlik") or "?"))
        table("BTC REJİMİNE GÖRE", group_stats(rows, lambda r: r.get("rejim") or "?"))
        table("KAYNAĞA GÖRE", group_stats(rows, lambda r: r.get("kaynak") or "?"))
        table("İKİNCİ GÖRÜŞE GÖRE", group_stats([r for r in rows if r.get("ikinci_gorus")],
                                                lambda r: r["ikinci_gorus"].split()[0]))

        movers = sorted([r for r in rows if (f(r, "max4s") or 0) >= 2 and r.get("coin") != "GENEL"
                         and r.get("durum_kodu") != "ALINDI"], key=lambda r: -f(r, "max4s"))[:10]
        print("\n=== KAÇIRILAN EN BÜYÜK HAREKETLER (alınmayanlar, 4 saatteki zirve) ===")
        for r in movers:
            print(f"{r['sinyal_zamani'][5:16]} {r['coin']:<7} puan {r['puan']:>2} zirve {p(f(r, 'max4s'))} "
                  f"| {r['durum_kodu']:<16} | {r['baslik'][:70]}")
        bad = sorted([r for r in rows if (f(r, "puan") or 0) >= 7 and (f(r, "r1s") or 0) < 0],
                     key=lambda r: f(r, "r1s"))[:10]
        print("\n=== YÜKSEK PUANLI AMA DÜŞENLER (puan >= 7, 1 saatlik getiri) ===")
        for r in bad:
            print(f"{r['sinyal_zamani'][5:16]} {r['coin']:<7} puan {r['puan']:>2} 1s {p(f(r, 'r1s'))} "
                  f"| {r['durum_kodu']:<16} | {r['baslik'][:70]}")

    trades = read_csv(TRADES_CSV)
    if since:
        trades = [t for t in trades if parse_ts(t["acilis"]) >= since]
    print(f"\n=== İŞLEMLER ({len(trades)}) ===")
    if trades:
        pnl = [float(t["kar_usdt"]) for t in trades]
        wins = sum(1 for v in pnl if v > 0)
        print(f"Toplam K/Z: {sum(pnl):+.2f} USDT | kazanma oranı: %{100 * wins / len(pnl):.0f} | "
              f"ortalama: {sum(float(t['kar_yuzde']) for t in trades) / len(trades):+.2f}%")
        for key, name in (("cikis_sebebi", "Çıkış sebebi"), ("rejim", "Rejim"), ("puan", "Puan"), ("mod", "Mod")):
            groups = {}
            for t in trades:
                groups.setdefault(t.get(key, "?"), []).append(t)
            print(f"\n{name}:")
            for k, ts in sorted(groups.items(), key=lambda kv: -len(kv[1])):
                vals = [float(t["kar_yuzde"]) for t in ts]
                print(f"  {k[:30]:<31} n={len(ts):<3} ort {sum(vals) / len(vals):+.2f}% | "
                      f"kazanan %{100 * sum(1 for v in vals if v > 0) / len(vals):.0f}")


if __name__ == "__main__":
    main()
