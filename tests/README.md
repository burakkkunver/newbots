# Çevrimdışı testler

Botun mantığını internete çıkmadan sınar. `sim.py` sahte bir Binance (testnet + gerçek piyasa verisi) ve sahte saat
sağlar, sahte Gate.io/MEXC ve yapay zeka yardımcıları da burada. Her test kendi sahte Gemini / Google News / CoinGecko
yanıtlarını kurar. Hiçbir test gerçek emir göndermez, gerçek anahtar kullanmaz.

```bash
cd ~/newbots && source venv/bin/activate
bash tests/run_all.sh          # hepsi
python3 tests/test_paper.py    # tek bir set
```

| Dosya | Ne sınar |
|---|---|
| `test_trading.py` | alım, -%2 stop, izleyen stop, OCO, time-stop, süre sınırı |
| `test_rest.py` | BTC rejimi, Gemini model zinciri, kalibrasyon, ana akış, rapor, komutlar |
| `test_alt.py` | hacim tarayıcı ve listeleme duyuruları |
| `test_new.py` | Telegram kanalları, Piyasa Nabzı, Gemini hacim yorumu, öğrenme modu |
| `test_fast.py` | listeleme / hacim hızlı yolu, gerçek piyasa gölge K/Z |
| `test_paper.py` | sanal işlemler (Binance / Gate.io / MEXC fiyatı) ve testnet aynası |
| `test_aihealth.py` | Gemini hata uyarıları, mola, günlük bütçe, amaca göre model |
| `test_watchnews.py` | izleme listesi haberleri (Google News araması) |
| `test_legacy*.py`, `test_guard.py`, `test_noticker.py`, `smoke_check.py` | eski veri uyumu, hata dayanıklılığı, check.py |

Yeni sürümde varsayılan bir ayar değişince eski setler eski davranışı test etmeye devam etsin diye o ayarı
dosyanın başındaki `os.environ.update(...)` satırında sabitler (ör. `PAPER_ENABLED="False"`).
Testlerin oluşturduğu `tests/data_*` klasörleri ve `tests/out_*.txt` dosyaları git'e girmez.
