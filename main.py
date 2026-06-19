# main.py
import os
import yaml
from drone import Drone
from security import SecurityLayer
from assistant import PilotAssistant
from logger import ProjectLogger

def main():
    print("========================================================")
    print("===  GELİŞMİŞ GÜVENLİK SİSTEMLİ İHA PİLOT ASİSTANI  ===")
    print("========================================================\n")

    # 1. Config.yaml Dosyasını Yüklüyoruz
    try:
        with open("config.yaml", "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except Exception as e:
        print(f"Config dosyası okunamadı: {e}")
        return

    # Ayarları config'den çekiyoruz
    d_settings = config["drone_settings"]
    
    drone = Drone()
    security = SecurityLayer(
        base_max_altitude=d_settings["base_max_altitude"],
        low_battery_max_altitude=d_settings["low_battery_max_altitude"],
        critical_battery=d_settings["critical_battery"],
        geofence_boundary=d_settings["geofence_boundary"]
    )
    logger = ProjectLogger()
    
    try:
        assistant = PilotAssistant()
    except ValueError as e:
        print(e)
        return

    print("Sistem konfigürasyonu başarıyla yüklendi ve asistan aktif!\n")

    while True:
        user_command = input("\nPilot Mesajı: ")
        
        if user_command.lower() in ["çıkış", "exit", "quit"]:
            print("Sistem kapatılıyor...")
            # Oturum sonu özetini yazdırıyoruz
            logger.print_session_summary(drone.get_telemetry())
            break

        # Acil Durdurma Bypass Kontrolü
        if user_command.upper() in ["ABORT", "MOTORU KES", "ACİL DURDURMA", "STOP"]:
            sonuc = drone.emergency_stop()
            print(sonuc)
            logger.log_action(user_command, "EMERGENCY_STOP", None, True, sonuc)
            continue

        if user_command == "batarya_45":
            drone.battery = 45; print("-> Batarya %45 yapıldı."); continue
        if user_command == "batarya_15":
            drone.battery = 15; print("-> Batarya %15 yapıldı."); continue

        if not user_command.strip():
            continue

        # Telemetriyi al
        current_telemetry = drone.get_telemetry()

        # --- ETHELEKTRİKSEL/İNTERAKTİF ONAY KATMANI (Kritik İşlem Onayı) ---
        # Eğer batarya %50'nin altındaysa ve pilot kalkış/yükselme istiyorsa ekstra onay alalım
        if current_telemetry["battery"] < 50 and ("kalk" in user_command.lower() or "yüksel" in user_command.lower() or "çık" in user_command.lower()):
            print("⚠️ [DÜŞÜK BATARYA UYARISI] Batarya %50'nin altında iken yükselme komutu verdiniz.")
            teyit = input("🤔 Bu riskli işlemi onaylıyor musunuz? (evet/hayır): ")
            if teyit.lower() not in ["evet", "e", "yes"]:
                print("❌ Komut pilot tarafından iptal edildi.")
                logger.log_action(user_command, "PILOT_CANCELED", None, False, "Pilot riskli işlem onayını reddetti.")
                continue

        # LLM 1: Asistan Çözümlemesi
        print("[LLM 1] Komut analiz ediliyor...")
        parsed_intent = assistant.parse_command(user_command, current_telemetry)
        action = parsed_intent.get("action")
        parameter = parsed_intent.get("parameter")
        print(f"-> LLM 1 Kararı: Eylem='{action}' | Parametre={parameter}")

        if action in ["ambiguous", "invalid"]:
            print(f"Asistan Yanıtı: Komut işlenemedi ({action}).")
            logger.log_action(user_command, action, parameter, False, "Geçersiz/Belirsiz.")
            continue

        # LLM 2: Gözlemci Denetimi
        print("[LLM 2] Karar denetleniyor...")
        observer_audit = assistant.observe_and_verify(current_telemetry, parsed_intent)
        decision = observer_audit.get("decision")
        reason = observer_audit.get("reason")
        print(f"🔍 [GÖZLEMCİ RAPORU] Karar: {decision} | Gerekçe: {reason}")

        if decision == "VETOED":
            print(f"🚨 Asistan Yanıtı (GÖZLEMCİ VETOSU): {reason}")
            logger.log_action(user_command, action, parameter, False, f"Veto: {reason}")
            continue

        # Güvenlik ve Çalıştırma
        onay, sonuc = security.validate_and_execute(drone, action, parameter)
        
        if onay:
            print(f"Asistan Yanıtı (BAŞARILI): {sonuc}")
        else:
            print(f"Asistan Yanıtı (YAZILIMSAL RED): {sonuc}")
            
        logger.log_action(user_command, action, parameter, onay, sonuc)
        
        t = drone.get_telemetry()
        print(f"-> [Anlık Durum] İrtifa: {t['altitude']}m | Batarya: %{t['battery']} | Havada: {t['in_air']} | Konum: ({t['x']},{t['y']})")

if __name__ == "__main__":
    main()