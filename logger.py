# logger.py
import json
import os
from datetime import datetime

class ProjectLogger:
    def __init__(self, filename="uclus_loglari.json"):
        self.filename = filename
        # Eğer dosya yoksa boş bir liste ile başlatıyoruz
        if not os.path.exists(self.filename):
            with open(self.filename, "w", encoding="utf-8") as f:
                json.dump([], f, ensure_ascii=False, indent=4)

    def log_action(self, user_input, parsed_action, parameter, security_approved, result):
        """
        Gelen tüm süreci zaman damgasıyla birlikte JSON dosyasına kaydeder.
        """
        log_entry = {
            "zaman_damgasi": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "kullanici_komutu": user_input,
            "llm_yorumu": {
                "action": parsed_action,
                "parameter": parameter
            },
            "guvenlik_onayi": security_approved,
            "sonuc_mesaji": result
        }

        try:
            # Mevcut logları oku
            with open(self.filename, "r", encoding="utf-8") as f:
                logs = json.load(f)
            
            # Yeni logu listeye ekle
            logs.append(log_entry)
            
            # Güncel listeyi dosyaya geri yaz
            with open(self.filename, "w", encoding="utf-8") as f:
                json.dump(logs, f, ensure_ascii=False, indent=4)
                
        except Exception as e:
            print(f"[LOG HATASI] Kayıt yapılamadı: {e}")