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
    try:
        mic = sr.Microphone()
    except (AttributeError, OSError) as e:
        # PyAudio yüklü değil veya mikrofon bulunamadı — programı çökertmeden geç
        print(f"❌ [SİSTEM] Sesli komut kullanılamıyor: {e}")
        print("   'pip3 install pyaudio' ile kurabilirsiniz. Şimdilik klavye (K) kullanın.")
        return ""

    with mic as source:
        print("\n🎤 [MİKROFON] Dinleniyor... Konuşun...")
        # Ortam gürültüsünü otomatik dengeler
        r.adjust_for_ambient_noise(source, duration=0.5)
        try:
            # En fazla 5 saniye sessizlik bekler, 10 saniyelik komut alabilir
            audio = r.listen(source, timeout=5, phrase_time_limit=20)
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

def run_command_loop(drone, security, assistant, logger, config, session_id, simulator=None):
    """ Pilot komutlarını okuyan ve işleyen ana döngü. Simülatör varsa ana thread'de
        pygame penceresi çalışırken bu döngü arka thread'de çalışır. """
    emergency_words = config["safety_settings"]["emergency_keywords"]
    high_risk_list = config["llm_settings"]["high_risk_actions"]

    print(f"=== SİSTEM AKTİF | OTURUM ID: {session_id} ===")
    print("⌨️  Klavyeden yazmak için komut satırını kullanın.")
    print("🎙️  Sesli komut moduna geçmek için mikrofona konuşma tetiklerini kullanabilirsiniz.")

    while True:
        # Giriş yöntemi seç
        giriş_tipi = input("\nGiriş Yöntemi [K: Klavye / S: Sesli Komut / Ç: Çıkış]: ").lower().strip()

        if giriş_tipi in ["ç", "çıkış", "exit"]:
            logger.print_session_summary(session_id, drone.get_telemetry())
            if simulator is not None:
                simulator.running = False  # Pygame penceresini de kapat
            break

        if giriş_tipi == "s":
            user_command = get_voice_input()
            if not user_command:
                continue
        elif giriş_tipi == "k":
            user_command = input("Pilot Mesajı (Klavye): ")
        else:
            print("⚠️ Geçersiz seçim. Lütfen K, S veya Ç girin.")
            continue

        if not user_command.strip():
            continue

        # Komut alındıktan sonra güncel telemetriyi çek
        current_telemetry = drone.get_telemetry()

        # Batarya tükenme failsafe'ini bir kez logla, modu kilitle
        if current_telemetry["failsafe"] and drone.mode == "EMERGENCY_LAND":
            logger.log_action(session_id, "SİSTEM_OTOMATİK_BATARYA_KAYBI", "EMERGENCY_STOP", None, True, "Otomatik batarya tükenme failsafe tetiklendi.")
            drone.mode = "CRASHED_LOCKED"

        # Acil durdurma — LLM'i bypass eder
        if user_command.upper() in emergency_words:
            sonuc = drone.emergency_stop()
            print(sonuc)
            logger.log_action(session_id, user_command, "EMERGENCY_STOP", None, True, sonuc)
            continue

        # Failsafe kilitliyse yalnızca reboot'a izin ver
        if current_telemetry["failsafe"]:
            print("Asistan Yanıtı: Sistem Failsafe modunda kilitlidir. Lütfen önce 'reboot' yapın.")
            if user_command.lower() in ["sistemi yeniden başlat", "reboot"]:
                sonuc = drone.reboot()
                print(sonuc)
                logger.log_action(session_id, user_command, "reboot", None, True, sonuc)
            continue

        print("[LLM 1] Çoklu görev zinciri analiz ediliyor...")
        parsed_intent_list = assistant.parse_command(user_command, current_telemetry)
        print(f"-> LLM 1 Kararı: {len(parsed_intent_list)} adet ardışık alt görev planlandı.")

        if parsed_intent_list and parsed_intent_list[0].get("action") in ["ambiguous", "invalid"]:
            print("Asistan Yanıtı: Komut anlaşılamadı.")
            logger.log_action(session_id, user_command, "Hata", None, False, "Geçersiz")
            continue

        # LLM 2: Zincirde yüksek riskli eylem varsa gözlemciye gönder
        has_high_risk = any(cmd.get("action") in high_risk_list for cmd in parsed_intent_list)
        if has_high_risk:
            print("[LLM 2] Zincirde yüksek riskli eylem saptandı, denetleniyor...")
            observer_audit = assistant.observe_and_verify(current_telemetry, parsed_intent_list)
            if observer_audit.get("decision") == "VETOED":
                print(f"🚨 GÖZLEMCİ VETOSU: {observer_audit.get('reason')}")
                logger.log_action(session_id, user_command, "MULTI_ACTION", None, False, "LLM 2 Vetosu")
                continue
        else:
            print("[SİSTEM] Düşük riskli zincir, Gözlemci LLM bypass edildi.")

        # Ardışık görev yürütme motoru (Dinamik Yeniden Planlama Destekli)
        zincir_basarili = True
        gecici_sonuclar = []
        max_replans = 2
        replan_count = 0
        idx = 0

        while idx < len(parsed_intent_list):
            siradaki_gorev = parsed_intent_list[idx]
            act = siradaki_gorev.get("action")
            param = siradaki_gorev.get("parameter")
            print(f"➡️  Alt Görev İşleniyor: Action='{act}' | Parameter={param}")

            if act == "reboot":
                if drone.in_air:
                    print("   🚨 [GÜVENLİK ENGELİ]: Havada iken reboot yapılamaz. Önce iniş yapın.")
                    logger.log_action(session_id, user_command, "reboot", None, False, "Güvenlik reddi: havada reboot isteği")
                    zincir_basarili = False
                    break
                sonuc = drone.reboot()
                print(sonuc)
                logger.log_action(session_id, user_command, "reboot", None, True, sonuc)
                zincir_basarili = False  # reboot özel durum, genel başarı mesajı basma
                break

            guncel_telemetri = drone.get_telemetry()
            onay, sonuc = security.validate_and_execute(drone, act, param, telemetri=guncel_telemetri)
            if onay:
                print(f"   [ONAYLANDI]: {sonuc}")
                gecici_sonuclar.append(sonuc)
                logger.log_action(session_id, user_command, act, param, True, sonuc)
                idx += 1
            else:
                print(f"   🚨 [GÜVENLİK ENGELİ]: {sonuc}")
                logger.log_action(session_id, user_command, act, param, False, f"Engellendi: {sonuc}")
                
                if replan_count < max_replans:
                    replan_count += 1
                    print(f"🔄 [DİNAMİK YENİDEN PLANLAMA] Asistan alternatif güvenli rota planlıyor... (Deneme {replan_count}/{max_replans})")
                    
                    # LLM'e engeli ve güncel telemetriyi bildirerek yeni bir rota istiyoruz
                    replan_prompt = f"GÜVENLİK ENGELİ: '{act}' eylemi '{sonuc}' nedeniyle güvenlik katmanına takıldı. Lütfen bu engeli aşacak veya en yakın güvenli alternatif rotayı/eylemi çizecek yeni bir görev zinciri planla. Sadece yeni komut listesini JSON array formatında dön."
                    
                    try:
                        new_intent_list = assistant.parse_command(replan_prompt, drone.get_telemetry())
                        if new_intent_list and new_intent_list[0].get("action") not in ["invalid", "ambiguous"]:
                            print(f"   [YENİ ÖNERİLEN ROTA]: {new_intent_list}")
                            parsed_intent_list = new_intent_list
                            idx = 0  # Yeni rota zincirini baştan başlat
                            continue
                    except Exception as e:
                        print(f"   [YENİDEN PLANLAMA HATASI]: {e}")
                
                print("   🚨 [PLANLAMA BAŞARISIZ]: Güvenli alternatif bulunamadı veya limit aşıldı. Görev zinciri KESİLDİ!")
                zincir_basarili = False
                break

        if zincir_basarili:
            print(f"Asistan Yanıtı (TÜM ZİNCİR BAŞARILI): Toplam {len(gecici_sonuclar)} eylem uygulandı.")

        t = drone.get_telemetry()
        print(f"-> [Son Durum] İrtifa: {t['altitude']}m | Batarya: %{t['battery']} | Konum: ({t['x']},{t['y']}) | Kilitli: {t['failsafe']}")


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

    # MAVLink kapalıysa görsel Pygame fizik simülatörünü kullan.
    # macOS'ta pygame/SDL penceresi ANA thread'de açılmalıdır; bu yüzden
    # komut döngüsünü arka thread'e alıp pencereyi ana thread'de çalıştırıyoruz.
    if not drone.mavlink_enabled:
        import threading
        from simulator import global_simulator

        loop_thread = threading.Thread(
            target=run_command_loop,
            args=(drone, security, assistant, logger, config, session_id, global_simulator),
            daemon=True,
        )
        loop_thread.start()
        print("🎮 [SİSTEM] Pygame 2B Fizik Simülatörü başlatıldı (ana thread).")
        global_simulator.run_pygame()  # Ana thread'de bloke eder (pencere kapanınca döner)
    else:
        run_command_loop(drone, security, assistant, logger, config, session_id, simulator=None)


if __name__ == "__main__":
    main()