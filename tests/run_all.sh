#!/usr/bin/env bash
# Tüm çevrimdışı testleri çalıştırır (internet gerekmez; Binance, Gemini, Gate.io/MEXC, Google News sahte).
# Kullanım: cd ~/newbots && source venv/bin/activate && bash tests/run_all.sh
cd "$(dirname "$0")"
fail=0
for t in test_trading test_rest test_alt test_new test_fast test_legacy test_legacy2 test_noticker test_guard \
         test_paper test_aihealth test_watchnews smoke_check; do
    if timeout 300 python3 "$t.py" > "out_$t.txt" 2>&1; then
        echo "✅ $t  $(grep -E 'geçti|hata mesajı sayısı|RSS:' "out_$t.txt" | tail -1)"
    else
        echo "❌ $t  (ayrıntı: tests/out_$t.txt)"; fail=1
    fi
done
exit $fail
