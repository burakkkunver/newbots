"""Telegram haber kanalları için TEK SEFERLİK giriş.

Çalıştırma (sunucuda, bot durdurulmuşken):  source env.sh && source venv/bin/activate && python3 tg_login.py

1. Telefon numaranı uluslararası biçimde gir (ör. +905xxxxxxxxx)
2. Telegram uygulamana gelen kodu gir
3. Hesabında iki adımlı doğrulama (bulut şifresi) varsa onu gir
Oturum data/tg_news.session dosyasına kaydedilir; bot bir daha kod istemez.
Oturumu iptal etmek için: Telegram > Ayarlar > Cihazlar > bu oturumu sonlandır (veya dosyayı sil).
"""
import time

import config


def main():
    if not config.TG_API_ID or not config.TG_API_HASH:
        print("❌ env.sh içinde TG_API_ID ve TG_API_HASH eksik. Önce my.telegram.org'dan alıp ekle, sonra: source env.sh")
        return
    try:
        from telethon.sync import TelegramClient
    except ImportError:
        print("❌ telethon kurulu değil. Önce: pip install --upgrade pip setuptools wheel && pip install -r requirements.txt")
        return
    from tgnews import SESSION_PATH

    print("📱 Telefon numaranı uluslararası biçimde gir (ör. +905xxxxxxxxx).")
    print("   İngilizce sorular gelecek: 'phone' = telefon, 'code' = Telegram'a gelen kod, 'password' = bulut şifresi.")
    client = TelegramClient(SESSION_PATH, config.TG_API_ID, config.TG_API_HASH)
    client.start()
    me = client.get_me()
    print(f"\n✅ Giriş başarılı: {me.first_name or ''} (@{me.username or '-'}). Oturum: {SESSION_PATH}.session\n")
    print("Kanallar kontrol ediliyor:")
    for name in config.TG_NEWS_CHANNELS:
        try:
            ent = client.get_entity(name)
            msgs = client.get_messages(ent, limit=1)
            if msgs:
                age = int((time.time() - msgs[0].date.timestamp()) / 60)
                text = (msgs[0].raw_text or "").replace("\n", " ")[:70]
                print(f"   ✅ @{name} ({getattr(ent, 'title', name)}): son mesaj {age} dk önce | {text}")
            else:
                print(f"   ✅ @{name}: erişildi (henüz mesaj yok)")
        except Exception as e:
            print(f"   ❌ @{name}: {e}")
    client.disconnect()
    print("\nŞimdi botu yeniden başlat: ./start.sh")


if __name__ == "__main__":
    main()
