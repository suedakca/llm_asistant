# main.py
import yaml
import uuid
import speech_recognition as sr
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
        print(f"[SİSTEM] Sesli komut kullanılamıyor: {e}")
        print("   'pip3 install pyaudio' ile kurabilirsiniz. Şimdilik klavye (K) kullanın.")
        return ""

    with mic as source:
        print("\n[MİKROFON] Dinleniyor... Konuşun...")
        r.adjust_for_ambient_noise(source, duration=0.5)
        try:
            audio = r.listen(source, timeout=5, phrase_time_limit=20)
            print("[SİSTEM] Ses işleniyor, metne dökülüyor...")

            text = r.recognize_google(audio, language="tr-TR")
            print(f"[SESLİ KOMUT ALGILANDI]: \"{text}\"")
            return text
        except sr.WaitTimeoutError:
            print("[SİSTEM] Zaman aşımı: Herhangi bir ses algılanmadı.")
            return ""
        except sr.UnknownValueError:
            print("[SİSTEM] Ses anlaşılamadı, lütfen tekrar deneyin.")
            return ""
        except sr.RequestError as e:
            print(f"[SİSTEM] Google STT Servis Hatası: {e}")
            return ""

def run_command_loop(drone, security, assistant, logger, config, session_id, simulator=None):
    """ Pilot komutlarını okuyan ve işleyen döngü """
    emergency_words = config["safety_settings"]["emergency_keywords"]
    high_risk_list = config["llm_settings"]["high_risk_actions"]

    print(f"=== SİSTEM AKTİF | OTURUM ID: {session_id} ===")
    print("Klavyeden yazmak için komut satırını kullanın.")
    print("Sesli komut moduna geçmek için mikrofona konuşma tetiklerini kullanabilirsiniz.")

    while True:
        giriş_tipi = input("\nGiriş Yöntemi [K: Klavye / S: Sesli Komut / Ç: Çıkış]: ").lower().strip()

        if giriş_tipi in ["ç", "çıkış", "exit"]:
            logger.print_session_summary(session_id, drone.get_telemetry())
            if simulator is not None:
                simulator.running = False
            break

        if giriş_tipi == "s":
            user_command = get_voice_input()
            if not user_command:
                continue
        elif giriş_tipi == "k":
            user_command = input("Pilot Mesajı (Klavye): ")
        else:
            print("Geçersiz seçim. Lütfen K, S veya Ç girin.")
            continue

        if not user_command.strip():
            continue

        current_telemetry = drone.get_telemetry()

        if current_telemetry["failsafe"] and drone.mode == "EMERGENCY_LAND":
            logger.log_action(session_id, "SİSTEM_OTOMATİK_BATARYA_KAYBI", "EMERGENCY_STOP", None, True, "Otomatik batarya tükenme failsafe tetiklendi.")
            drone.mode = "CRASHED_LOCKED"

        if user_command.upper() in emergency_words:
            sonuc = drone.emergency_stop()
            print(sonuc)
            logger.log_action(session_id, user_command, "EMERGENCY_STOP", None, True, sonuc)
            continue

        if current_telemetry["failsafe"]:
            print("Asistan Yanıtı: Sistem Failsafe modunda kilitlidir. Lütfen önce 'reboot' yapın.")
            if user_command.lower() in ["sistemi yeniden başlat", "reboot"]:
                sonuc = drone.reboot()
                print(sonuc)
                logger.log_action(session_id, user_command, "reboot", None, True, sonuc)
            continue

        print("[Planlama] Komut analiz ediliyor...")
        parsed_intent_list = assistant.parse_command(user_command, current_telemetry)
        print(f"-> {len(parsed_intent_list)} alt görev planlandı.")

        if parsed_intent_list and parsed_intent_list[0].get("action") in ["ambiguous", "invalid"]:
            print("Asistan Yanıtı: Komut anlaşılamadı.")
            logger.log_action(session_id, user_command, "Hata", None, False, "Geçersiz")
            continue

        has_high_risk = any(cmd.get("action") in high_risk_list for cmd in parsed_intent_list)
        if has_high_risk:
            print("[Güvenlik] Riskli eylem denetleniyor...")
            observer_audit = assistant.observe_and_verify(current_telemetry, parsed_intent_list)
            if observer_audit.get("decision") == "VETOED":
                veto_reason = observer_audit.get("reason", "gerekçe belirtilmedi")
                print(f"Gözlemci Reddi: {veto_reason}")
                logger.log_action(session_id, user_command, "MULTI_ACTION", None, False,
                                  f"Gözlemci Reddi: {veto_reason}")
                continue

        zincir_basarili = True
        gecici_sonuclar = []
        max_replans = 2
        replan_count = 0
        idx = 0

        while idx < len(parsed_intent_list):
            siradaki_gorev = parsed_intent_list[idx]
            act = siradaki_gorev.get("action")
            param = siradaki_gorev.get("parameter")
            print(f"➡️ Görev: {act} | Parametre: {param}")

            if act == "reboot":
                if drone.in_air:
                    print("   [Güvenlik Reddi]: Havada reboot yapılamaz.")
                    logger.log_action(session_id, user_command, "reboot", None, False, "Havada reboot isteği")
                    zincir_basarili = False
                    break
                sonuc = drone.reboot()
                print(sonuc)
                logger.log_action(session_id, user_command, "reboot", None, True, sonuc)
                zincir_basarili = False
                break

            guncel_telemetri = drone.get_telemetry()
            onay, sonuc = security.validate_and_execute(drone, act, param, telemetri=guncel_telemetri)
            if onay:
                print(f"   [Onaylandı]: {sonuc}")
                gecici_sonuclar.append(sonuc)
                logger.log_action(session_id, user_command, act, param, True, sonuc)
                idx += 1
            else:
                print(f"   [Güvenlik Reddi]: {sonuc}")
                logger.log_action(session_id, user_command, act, param, False, f"Engellendi: {sonuc}")
                
                if replan_count < max_replans:
                    replan_count += 1
                    print(f"[Yeniden Planlama] Alternatif rota deneniyor ({replan_count}/{max_replans})...")
                    
                    replan_prompt = f"GUVENLIK ENGELI: '{act}' eylemi '{sonuc}' nedeniyle guvenlik katmanina takildi. Lutfen bu engeli asacak veya en yakin guvenli alternatif rotayi/eylemi cizecek yeni bir gorev zinciri planla. Sadece yeni komut listesini JSON array formatinda don."
                    
                    try:
                        new_intent_list = assistant.parse_command(replan_prompt, drone.get_telemetry())
                        if new_intent_list and new_intent_list[0].get("action") not in ["invalid", "ambiguous"]:
                            print(f"   [Yeni Rota]: {new_intent_list}")
                            parsed_intent_list = new_intent_list
                            idx = 0
                            continue
                    except Exception as e:
                        print(f"   [Planlama Hatası]: {e}")
                
                print("   [Planlama Başarısız]: Güvenli alternatif bulunamadı.")
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

    drone = Drone(config["drone_settings"], fault_config=config.get("fault_injection"))
    security = SecurityLayer(config["drone_settings"])
    logger = ProjectLogger()

    try:
        assistant = PilotAssistant(config["llm_settings"])
    except ValueError as e:
        print(f"\n [SİSTEM BAŞLATMA HATASI]: {e}"); return

    from simulator import global_simulator
    global_simulator.init_gui_control(drone, security, assistant, logger, config, session_id)

    print("[SİSTEM] Arayüz Destekli Pygame 2B Fizik Simülatörü başlatıldı (ana thread).")
    global_simulator.run_pygame()


if __name__ == "__main__":
    main()