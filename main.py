# main.py
import os
from drone import Drone
from security import SecurityLayer
from assistant import PilotAssistant
from logger import ProjectLogger # Yeni ekledik

def main():
    print("========================================================")
    print("=== UÇTAN UCA YAPAY ZEKA TABANLI İHA PİLOT ASİSTANI ===")
    print("========================================================\n")

    # Sistem bileşenlerini başlatıyoruz
    drone = Drone()
    security = SecurityLayer(max_altitude=50.0, min_battery=20)
    logger = ProjectLogger() # Loglayıcıyı çalıştırdık
    
    try:
        assistant = PilotAssistant()
    except ValueError as e:
        print(e)
        return

    print("Asistan ve Kayıt Sistemi hazır! Çıkmak için 'çıkış' yazabilirsiniz.\n")

    while True:
        user_command = input("\nPilot Mesajı: ")
        if user_command.lower() in ["çıkış", "exit", "quit"]:
            print("Sistem kapatılıyor...")
            break

        if not user_command.strip():
            continue

        print("[LLM] Komut analiz ediliyor...")
        parsed_intent = assistant.parse_command(user_command)
        action = parsed_intent.get("action")
        parameter = parsed_intent.get("parameter")
        
        print(f"[LLM ÇIKTISI] Anlaşılan Eylem: '{action}' | Parametre: {parameter}")

        # Belirsiz veya Geçersiz komut durumlarını yakalayalım ve loglayalım
        if action in ["ambiguous", "invalid"]:
            mesaj = "Komut belirsiz veya geçersiz olduğu için işlenmedi."
            if action == "ambiguous":
                mesaj = "Komut belirsiz. Net hedef irtifa istendi."
            print(f"Asistan Yanıtı: {mesaj}")
            
            # Güvenliğe gitmeden reddedilenleri de günlüğe yazıyoruz
            logger.log_action(user_command, action, parameter, False, mesaj)
            continue

        # 3. Güvenlik Katmanı Doğrulaması ve Çalıştırma
        onay, sonuc = security.validate_and_execute(drone, action, parameter)
        
        # 4. Sonucu Ekrana Bas
        if onay:
            print(f"Asistan Yanıtı (BAŞARILI): {sonuc}")
        else:
            print(f"Asistan Yanıtı (REDDEDİLDİ): {sonuc}")
            
        # 5. Her şeyi JSON dosyasına kaydet
        logger.log_action(user_command, action, parameter, onay, sonuc)
            
        # Güncel durumu göster
        t = drone.get_telemetry()
        print(f"-> [Anlık Durum] İrtifa: {t['altitude']}m | Batarya: %{t['battery']} | Havada: {t['in_air']}")

if __name__ == "__main__":
    main()