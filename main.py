# main.py
import yaml
import uuid
import speech_recognition as sr  # Yeni: Ses tanıma kütüphanesi
from drone import Drone
from security import SecurityLayer
from assistant import PilotAssistant
from logger import ProjectLogger

def get_voice_input():
    """ Mikrofondan ses kaydı alıp Türkçe metne dönüştürür """
    r = sr.Recognizer()
    with sr.Microphone() as source:
        print("\n🎤 [MİKROFON] Dinleniyor... Konuşun...")
        # Ortam gürültüsünü otomatik dengeler
        r.adjust_for_ambient_noise(source, duration=0.5)
        try:
            # En fazla 5 saniye sessizlik bekler, 10 saniyelik komut alabilir
            audio = r.listen(source, timeout=5, phrase_time_limit=10)
            print("⏳ [SİSTEM] Ses işleniyor, metne dökülüyor...")
            
            # Google Speech-to-Text motorunu Türkçe diliyle tetikliyoruz
            text = r.recognize_google(audio, language="tr-TR")
            print(f"🗣️  [SESLİ KOMUT ALGILANDI]: \"{text}\"")
            return text
        except sr.WaitTimeoutError:
            print("❌ [SİSTEM] Zaman aşımı: Herhangi bir ses algılanmadı.")
            return ""
        except sr.UnknownValueError:
            print("❌ [SİSTEM] Ses anlaşılamadı, lütfen tekrar deneyin.")
            return ""
        except sr.RequestError as e:
            print(f"❌ [SİSTEM] Google STT Servis Hatası: {e}")
            return ""

def main():
    session_id = uuid.uuid4()
    
    try:
        with open("config.yaml", "r", encoding="utf-8") as f: 
            config = yaml.safe_load(f)
    except Exception as e:
        print(f"Config yüklenemedi: {e}"); return

    drone = Drone(config["drone_settings"])
    security = SecurityLayer(config["drone_settings"])
    logger = ProjectLogger()

    try:
        assistant = PilotAssistant(config["llm_settings"])
    except ValueError as e:
        print(f"\n❌ [SİSTEM BAŞLATMA HATASI]: {e}"); return

    emergency_words = config["safety_settings"]["emergency_keywords"]
    high_risk_list = config["llm_settings"]["high_risk_actions"]

    print(f"=== SİSTEM AKTİF | OTURUM ID: {session_id} ===")
    print("⌨️  Klavyeden yazmak için komut satırını kullanın.")
    print("🎙️  Sesli komut moduna geçmek için mikrofona konuşma tetiklerini kullanabilirsiniz.")

    while True:
        current_telemetry = drone.get_telemetry()
        
        # Arka plandaki %0 batarya otomatik failsafe kontrolü
        if current_telemetry["failsafe"] and drone.mode == "EMERGENCY_LAND":
            logger.log_action(session_id, "SİSTEM_OTOMATİK_BATARYA_KAYBI", "EMERGENCY_STOP", None, True, "Otomatik batarya tükenme failsafe tetiklendi.")
            drone.mode = "CRASHED_LOCKED" 

        # Giriş Yöntemi Seçimi (Kullanıcı konforu ve hata toleransı için)
        giriş_tipi = input("\nGiriş Yöntemi [K: Klavye / S: Sesli Komut / Ç: Çıkış]: ").lower().strip()
        
        if giriş_tipi in ["ç", "çıkış", "exit"]:
            logger.print_session_summary(session_id, drone.get_telemetry())
            break
            
        if giriş_tipi == "s":
            user_command = get_voice_input()
            if not user_command: 
                continue  # Ses boşsa döngünün başına dön
        elif giriş_tipi == "k":
            user_command = input("Pilot Mesajı (Klavye): ")
        else:
            print("⚠️ Geçersiz seçim. Lütfen K, S veya Ç girin.")
            continue

        # Acil Durdurma Bypass Kontrolü
        if user_command.upper() in emergency_words:
            sonuc = drone.emergency_stop()
            print(sonuc)
            logger.log_action(session_id, user_command, "EMERGENCY_STOP", None, True, sonuc)
            continue

        if not user_command.strip(): continue

        # Sistem kilitliyse LLM çalışmasını engelleme kontrolü
        if current_telemetry["failsafe"]:
            print("Asistan Yanıtı: Sistem Failsafe modunda kilitlidir. Lütfen önce 'reboot' yapın.")
            if user_command.lower() in ["sistemi yeniden başlat", "reboot"]:
                sonuc = drone.reboot()
                print(sonuc)
                logger.log_action(session_id, user_command, "reboot", None, True, sonuc)
            continue

        print("[LLM 1] Komut analiz ediliyor...")
        parsed_intent = assistant.parse_command(user_command, current_telemetry)
        action = parsed_intent.get("action")
        parameter = parsed_intent.get("parameter")
        print(f"-> LLM 1 Kararı: Eylem='{action}' | Parametre={parameter}")

        if action == "reboot":
            sonuc = drone.reboot()
            print(sonuc)
            logger.log_action(session_id, user_command, "reboot", None, True, sonuc)
            continue

        if action in ["ambiguous", "invalid"]:
            print("Asistan Yanıtı: Komut anlaşılamadı.")
            logger.log_action(session_id, user_command, action, parameter, False, "Hata")
            continue

        if action in high_risk_list:
            print("[LLM 2] Yüksek riskli eylem algılandı, denetleniyor...")
            observer_audit = assistant.observe_and_verify(current_telemetry, parsed_intent)
            if observer_audit.get("decision") == "VETOED":
                print(f"🚨 GÖZLEMCİ VETOSU: {observer_audit.get('reason')}")
                logger.log_action(session_id, user_command, action, parameter, False, "LLM 2 Vetosu")
                continue
        else:
            print("[SİSTEM] Düşük riskli eylem, Gözlemci LLM bypass edildi.")

        onay, sonuc = security.validate_and_execute(drone, action, parameter)
        print(f"Asistan Yanıtı: {sonuc}")
        
        logger.log_action(session_id, user_command, action, parameter, onay, sonuc)
        
        t = drone.get_telemetry()
        print(f"-> [Durum] İrtifa: {t['altitude']}m | Batarya: %{t['battery']} | Konum: ({t['x']},{t['y']}) | Kilitli: {t['failsafe']}")

if __name__ == "__main__":
    main()