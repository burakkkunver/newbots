#!/usr/bin/env bash
# Botu başlatır: ayarları yükler, sanal ortamı açar, çıktıyı hem ekrana hem data/bot.log'a yazar.
cd "$(dirname "$0")"
if [ ! -f env.sh ]; then echo "env.sh bulunamadı! Önce: cp env.sh.example env.sh && nano env.sh"; exit 1; fi
source env.sh
source venv/bin/activate
mkdir -p data
python3 -u bot.py 2>&1 | tee -a data/bot.log
