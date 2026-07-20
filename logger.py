# logger.py
import json
import os
from datetime import datetime

class ProjectLogger:
    def __init__(self, filename="uclus_loglari.json"):
        self.filename = filename
        
        if os.path.exists(self.filename):
            try:
                with open(self.filename, "r", encoding="utf-8") as f:
                    first_char = f.read(1)
                if first_char == "[":
                    print("⚠️ [SİSTEM] Eski log formatı algılandı. Dosya JSONLines formatına sıfırlanıyor...")
                    os.remove(self.filename)
            except:
                pass

    def log_action(self, session_id, user_input, parsed_action, parameter, security_approved, result):
        log_entry = {
            "session_id": str(session_id),
            "zaman_damgasi": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "kullanici_komutu": user_input,
            "llm_yorumu": {"action": parsed_action, "parameter": parameter},
            "guvenlik_onayi": security_approved,
            "sonuc_mesaji": result
        }
        try:
            with open(self.filename, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"[LOG HATASI] Yazma başarısız: {e}")

    def print_session_summary(self, session_id, final_telemetry):
        """ Oturum özet raporunu hesaplar ve ekrana yazdırır. """
        try:
            session_logs = []
            max_altitude_reached = 0.0 

            if os.path.exists(self.filename):
                with open(self.filename, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip():
                            try:
                                log_data = json.loads(line.strip())
                                if log_data.get("session_id") == str(session_id):
                                    session_logs.append(log_data)

                                    llm_yorumu = log_data.get("llm_yorumu", {})
                                    if (llm_yorumu.get("action") == "takeoff" and 
                                        log_data.get("guvenlik_onayi") is True and 
                                        llm_yorumu.get("parameter") is not None):
                                        
                                        try:
                                            current_param_alt = float(llm_yorumu["parameter"])
                                            if current_param_alt > max_altitude_reached:
                                                max_altitude_reached = current_param_alt
                                        except ValueError:
                                            pass
                            except json.JSONDecodeError:
                                continue
            
            total = len(session_logs)
            approved = sum(1 for log in session_logs if log["guvenlik_onayi"] == True)
            rejected = total - approved

            print("\n" + "="*50)
            print("📊 === BU OTURUMA AİT UÇUŞ ÖZET RAPORU ===")
            print("="*50)
            print(f"🆔 Oturum Kimliği (UUID)   : {session_id}")
            print(f"🔹 Bu Oturumdaki Komutlar  : {total}")
            print(f"✅ Onaylanan Eylemler     : {approved}")
            print(f"❌ Reddedilen Güvensiz    : {rejected}")
            print(f"📈 Ulaşılan En Yüksek İrtifa: {max_altitude_reached}m ") 
            print(f"📉 Kapanış Anındaki İrtifa : {final_telemetry['altitude']}m")
            print(f"📍 Son Konum Koordinatı   : (X: {final_telemetry['x']}, Y: {final_telemetry['y']})")
            print(f"🔋 Kalan Batarya Seviyesi : %{final_telemetry['battery']}")
            print("="*50 + "\n")
        except Exception as e:
            print(f"Özet raporlama hatası: {e}")