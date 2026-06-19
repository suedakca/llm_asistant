# main.py
import os
from drone import Drone
from security import SecurityLayer
from assistant import PilotAssistant
from logger import ProjectLogger

def main():
    print("========================================================")
    print("===  DUAL-LLM (ÇİFT MODEL) MİMARİLİ İHA PİLOT ASİSTANI ===")
    print("========================================================\n")

    drone = Drone()
    security = SecurityLayer(max_altitude=50.0, min_battery=20)
    logger = ProjectLogger()
    
    try:
        assistant = PilotAssistant()
    except ValueError as e:
        print(e)
        return

    print("Sistem ve Güvenlik Gözlemcisi Aktif!\n")

    while True:
        user_command = input("\nPilot Mesajı: ")
        if user_command.lower() in ["çıkış", "exit", "quit"]:
            break

        if user_command == "bataryayi_tuket":
            drone.battery = 24
            print("-> [TEST] Drone bataryası yapay olarak %24'e düşürüldü!")
            continue

        if not user_command.strip():
            continue

        # --- ADIM 1: İlk LLM Komutu Yorumluyor ---
        print("[LLM 1 - ASİSTAN] Komut analiz ediliyor...")
        parsed_intent = assistant.parse_command(user_command)
        action = parsed_intent.get("action")
        parameter = parsed_intent.get("parameter")
        print(f"-> LLM 1 Kararı: Eylem='{action}' | Parametre={parameter}")

        if action in ["ambiguous", "invalid"]:
            print(f"Asistan Yanıtı: Komut işlenemedi (Durum: {action}).")
            logger.log_action(user_command, action, parameter, False, "Geçersiz/Belirsiz komut.")
            continue

        # --- ADIM 2: İkinci LLM Kararı Denetliyor (Gözlemci) ---
        print("[LLM 2 - GÖZLEMCİ] Karar bağımsız olarak denetleniyor...")
        current_telemetry = drone.get_telemetry()
        observer_audit = assistant.observe_and_verify(current_telemetry, parsed_intent)
        
        decision = observer_audit.get("decision")
        reason = observer_audit.get("reason")
        print(f"🔍 [GÖZLEMCİ RAPORU] Karar: {decision} | Gerekçe: {reason}")

        # Eğer Gözlemci LLM veto ettiyse süreci durduruyoruz
        if decision == "VETOED":
            print(f"🚨 Asistan Yanıtı (GÖZLEMCİ VETOSU): Komut reddedildi! Nedeni: {reason}")
            logger.log_action(user_command, action, parameter, False, f"Gözlemci Vetosu: {reason}")
            continue

        # --- ADIM 3: Kod Seviyesinde Güvenlik ve Çalıştırma ---
        onay, sonuc = security.validate_and_execute(drone, action, parameter)
        
        if onay:
            print(f"Asistan Yanıtı (BAŞARILI): {sonuc}")
        else:
            print(f"Asistan Yanıtı (YAZILIMSAL RED): {sonuc}")
            
        logger.log_action(user_command, action, parameter, onay, sonuc)
        
        t = drone.get_telemetry()
        print(f"-> [Anlık Durum] İrtifa: {t['altitude']}m | Batarya: %{t['battery']} | Havada: {t['in_air']}")

if __name__ == "__main__":
    main()