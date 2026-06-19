# logger.py
import json
import os
from datetime import datetime

class ProjectLogger:
    def __init__(self, filename="uclus_loglari.json"):
        self.filename = filename
        if not os.path.exists(self.filename):
            with open(self.filename, "w", encoding="utf-8") as f:
                json.dump([], f, ensure_ascii=False, indent=4)

    def log_action(self, user_input, parsed_action, parameter, security_approved, result):
        log_entry = {
            "zaman_damgasi": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "kullanici_komutu": user_input,
            "llm_yorumu": {"action": parsed_action, "parameter": parameter},
            "guvenlik_onayi": security_approved,
            "sonuc_mesaji": result
        }
        try:
            with open(self.filename, "r", encoding="utf-8") as f: logs = json.load(f)
            logs.append(log_entry)
            with open(self.filename, "w", encoding="utf-8") as f: json.dump(logs, f, ensure_ascii=False, indent=4)
        except Exception as e: print(f"Loglama hatası: {e}")

    def print_session_summary(self, final_telemetry):
        """ 2. OTURUM SONU ÖZETİ RAPORLAYICI """
        try:
            with open(self.filename, "r", encoding="utf-8") as f: logs = json.load(f)
            
            total = len(logs)
            approved = sum(1 for log in logs if log["guvenlik_onayi"] == True)
            rejected = total - approved

            print("\n" + "="*50)
            print("📊 === MİSYON SONU UÇUŞ ÖZET RAPORU ===")
            print("="*50)
            print(f"🔹 Toplam Gönderilen Komut : {total}")
            print(f"✅ Onaylanan Eylemler     : {approved}")
            print(f"❌ Reddedilen Güvensiz    : {rejected}")
            print(f"📈 Ulaşılan Son İrtifa    : {final_telemetry['altitude']}m")
            print(f"📍 Son Konum Koordinatı   : (X: {final_telemetry['x']}, Y: {final_telemetry['y']})")
            print(f"🔋 Kalan Batarya Seviyesi : %{final_telemetry['battery']}")
            print("="*50 + "\n")
        except Exception as e:
            print(f"Özet raporlama hatası: {e}")