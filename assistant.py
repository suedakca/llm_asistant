# assistant.py
import os
import json
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

class PilotAssistant:
    def __init__(self, config_dict):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key: raise ValueError("HATA: GEMINI_API_KEY bulunamadı!")
        
        self.client = genai.Client(api_key=api_key)
        self.model_name = config_dict["model_name"]
        self.temp = config_dict["temperature"]
        
        # [DÜZELTME] LLM'in her koşulda "Mutlak Hedef İrtifa" üretmesi kesinleştirildi
        asistan_instruction = """
        Sen bir İHA Pilot Asistanısın. Pilotla derin bir konuşma hafızasına sahip bir agentsın.
        
        İRTİFA SEMANTİK KURALI (KRİTİK):
        - 'takeoff' eylemi için 'parameter' değeri HER ZAMAN drone'un ulaşmasını istediğin nihaî MUTLAK İRTİFA (hedef yükseklik) olmalıdır.
        - Eğer drone zaten havadaysa (telemetride in_air=True ise) ve kullanıcı '10 metre DAHA yüksel' veya '10 metre yukarı çık' derse, anlık telemetrideki 'altitude' değerinin üzerine bu sayıyı EKLE ve o toplam sonucu 'parameter' olarak yaz. 
        - Örnek: Drone 15m'de ise ve pilot '10 metre daha yüksel' dediyse, parametre 25 olmalıdır.
        
        DESTEKLENEN FONKSİYONLAR (action):
        1. 'get_telemetry', 
        2. 'takeoff', 
        3. 'land', 
        4. 'return_to_home', 
        5. 'move': Yatay hareket. 'parameter' olarak bir obje alır: {"direction": "kuzey/güney/doğu/batı", "distance": sayı},
        6. 'reboot': Sistem kilitlendiğinde veya failsafe moduna girdiğinde yeniden başlatmak için kullanılır. Parametre almaz,
        7. 'set_home': Yeni ev/başlangıç konumu tanımlar. 'parameter' olarak bir obje alır: {"x": sayı, "y": sayı},
        8. 'invalid' / 'ambiguous': Geçersiz veya belirsiz durumlar.
        
        SADECE JSON FORMATINDA CEVAP VER:
        {"action": "fonksiyon_adı", "parameter": değer_veya_null}
        """
        self.assistant_chat = self.client.chats.create(
            model=self.model_name,
            config=types.GenerateContentConfig(
                system_instruction=asistan_instruction, response_mime_type="application/json", temperature=self.temp
            )
        )

    def parse_command(self, user_input, current_telemetry):
        girdi_baglami = f"TELEMETRİ: {json.dumps(current_telemetry)}\nPİLOT: {user_input}"
        try:
            response = self.assistant_chat.send_message(girdi_baglami)
            clean_text = response.text.strip()
            if clean_text.startswith("```"):
                clean_text = clean_text.split("```")[1]
                if clean_text.startswith("json"): clean_text = clean_text[4:]
            return json.loads(clean_text.strip())
        except json.JSONDecodeError as je:
            print(f"[ASİSTAN PARSE HATASI]: {je}")
            return {"action": "invalid", "parameter": None}
        except Exception as e:
            print(f"[ASİSTAN GENEL HATA]: {e}")
            return {"action": "invalid", "parameter": None}

    def observe_and_verify(self, telemetry, parsed_intent):
        if parsed_intent.get("action") == "get_telemetry":
            return {"decision": "APPROVED", "reason": "Güvenli okuma işlemi."}

        system_instruction = """
        Sen bir İHA Güvenlik Gözlemcisisin. Gelen mutlak hedef komutlarını bataryaya göre veto edersin.
        JSON formatında dön: {"decision": "APPROVED" veya "VETOED", "reason": "neden"}
        """
        audit_context = f"TELEMETRİ: {json.dumps(telemetry)}\nKOMUT: {json.dumps(parsed_intent)}"
        try:
            response = self.client.models.generate_content(
                model=self.model_name, contents=audit_context,
                config=types.GenerateContentConfig(system_instruction=system_instruction, response_mime_type="application/json", temperature=self.temp)
            )
            return json.loads(response.text)
        except json.JSONDecodeError as je:
            print(f"[GÖZLEMCİ PARSE HATASI]: {je}")
            return {"decision": "VETOED", "reason": "Gözlemci format ayrıştırma hatası."}
        except Exception as e:
            print(f"[GÖZLEMCİ API HATASI]: {e}")
            return {"decision": "VETOED", "reason": "Gözlemci API bağlantı hatası."}