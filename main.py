
import os
from drone import Drone
from security import SecurityLayer
from assistant import PilotAssistant

def main():

    print("========================================================")
    print("=== UÇTAN UCA YAPAY ZEKA TABANLI İHA PİLOT ASİSTANI ===")
    print("========================================================\n")

    drone = Drone()
    security = SecurityLayer(max_altitude=50.0, min_battery=20)
    
    try:
        assistant = PilotAssistant()
    except ValueError as e:
        print(e)
        return

    print("Asistan hazır! Çıkmak için 'çıkış' yazabilirsiniz.\n")

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

        if action == "ambiguous":
            print("Asistan Yanıtı: Komutunuz belirsiz. Lütfen net bir hedef irtifa belirtin (Örn: '10 metreye kalk').")
            continue
        elif action == "invalid":
            print("Asistan Yanıtı: İstenen işlem geçersiz veya desteklenmeyen bir araç fonksiyonu içeriyor.")
            continue

        onay, sonuc = security.validate_and_execute(drone, action, parameter)
        
        if onay:
            print(f"Asistan Yanıtı (BAŞARILI): {sonuc}")
        else:
            print(f"Asistan Yanıtı (REDDEDİLDİ): {sonuc}")
            
        t = drone.get_telemetry()
        print(f"-> [Anlık Durum] İrtifa: {t['altitude']}m | Batarya: %{t['battery']} | Havada: {t['in_air']}")

if __name__ == "__main__":
    main()