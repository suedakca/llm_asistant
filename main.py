# main.py
import yaml
import uuid
from drone import Drone
from security import SecurityLayer
from assistant import PilotAssistant
from logger import ProjectLogger

def main():
    # [ÇÖZÜM 6] Benzersiz oturum kimliği oluşturma
    session_id = uuid.uuid4()
    
    try:
        with open("config.yaml", "r", encoding="utf-8") as f: config = yaml.safe_load(f)
    except Exception as e:
        print(f"Config yüklenemedi: {e}"); return

    drone = Drone()
    security = SecurityLayer(config["drone_settings"])
    assistant = PilotAssistant(config["llm_settings"])
    logger = ProjectLogger()

    # [ÇÖZÜM 7] Acil durum kelimelerini config'den okuma
    emergency_words = config["safety_settings"]["emergency_keywords"]
    high_risk_list = config["llm_settings"]["high_risk_actions"]

    print(f"=== SİSTEM AKTİF | OTURUM ID: {session_id} ===")

    while True:
        user_command = input("\nPilot Mesajı: ")
        
        if user_command.lower() in ["çıkış", "exit", "quit"]:
            # [ÇÖZÜM 4 & 6] Sadece bu oturumun ID'siyle özet çıkartılıyor
            logger.print_session_summary(session_id, drone.get_telemetry())
            break

        # [ÇÖZÜM 7] Dinamik Failsafe bypass kontrolü
        if user_command.upper() in emergency_words:
            sonuc = drone.emergency_stop()
            print(sonuc)
            logger.log_action(session_id, user_command, "EMERGENCY_STOP", None, True, sonuc)
            continue

        if not user_command.strip(): continue

        current_telemetry = drone.get_telemetry()
        
        print("[LLM 1] Komut analiz ediliyor...")
        parsed_intent = assistant.parse_command(user_command, current_telemetry)
        action = parsed_intent.get("action")
        parameter = parsed_intent.get("parameter")
        print(f"-> LLM 1 Kararı: Eylem='{action}' | Parametre={parameter}")

        # Özel Manuel Reboot Fonksiyonu Eşleştirmesi
        if action == "reboot":
            sonuc = drone.reboot()
            print(sonuc)
            logger.log_action(session_id, user_command, "reboot", None, True, sonuc)
            continue

        if action in ["ambiguous", "invalid"]:
            print("Asistan Yanıtı: Komut anlaşılamadı.")
            logger.log_action(session_id, user_command, action, parameter, False, "Hata")
            continue

        # [ÇÖZÜM 8] Sadece yüksek riskli eylemlerde Gözlemci LLM çağrılır
        if action in high_risk_list:
            print("[LLM 2] Yüksek riskli eylem algılandı, denetleniyor...")
            observer_audit = assistant.observe_and_verify(current_telemetry, parsed_intent)
            if observer_audit.get("decision") == "VETOED":
                print(f"🚨 GÖZLEMCİ VETOSU: {observer_audit.get('reason')}")
                logger.log_action(session_id, user_command, action, parameter, False, "LLM 2 Vetosu")
                continue
        else:
            print("[SİSTEM] Düşük riskli eylem, Gözlemci LLM bypass edildi (Maliyet tasarrufu).")

        # Güvenlik ve Çalıştırma
        onay, sonuc = security.validate_and_execute(drone, action, parameter)
        print(f"Asistan Yanıtı: {sonuc}")
        
        logger.log_action(session_id, user_command, action, parameter, onay, sonuc)
        
        t = drone.get_telemetry()
        print(f"-> [Durum] İrtifa: {t['altitude']}m | Batarya: %{t['battery']} | Konum: ({t['x']},{t['y']}) | Kilitli: {t['failsafe']}")

if __name__ == "__main__":
    main()