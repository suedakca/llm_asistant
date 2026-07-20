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
        
        asistan_instruction = """
        Sen bir İHA Pilot Asistanısın. Görevin pilotun doğal dildeki komutlarını analiz edip sırasıyla çalıştırılacak komut listesini JSON formatında üretmektir.
        
        Desteklenen Fonksiyonlar:
        - 'takeoff': Kalkış veya irtifa alma ("10 metreye kalk", "10m yüksel", "5 metre tırman"). Parametre: Hedef mutlak irtifa (sayı).
        - 'land': İniş yapma ("in", "iniş yap"). Parametre: null.
        - 'return_to_home': Eve dönüş ("eve dön", "başlangıç noktasına git"). Parametre: null.
        - 'move': Yönlü hareket ("10 metre doğuya git", "5m ileri"). Parametre: {"direction": "doğu/batı/kuzey/güney", "distance": sayı}.
        - 'complete_checklist': Kontrol onayı ("kontroller tamam", "hazırız"). Parametre: null.
        - 'reboot': Yeniden başlatma ("reboot", "sistemi yeniden başlat"). Parametre: null.
        - 'set_home': Ev noktası belirleme. Parametre: {"x": sayı, "y": sayı}.
        - 'get_telemetry': Durum sorgulama ("durum ne", "telemetri"). Parametre: null.
        - 'invalid' / 'ambiguous': Anlaşılamayan komutlar.
        
        İrtifa Kuralları:
        - 'takeoff' için 'parameter' değeri drone'un ulaşmasını istediğin mutlak irtifa olmalıdır.
        - Havada iken "X metre yüksel" dendiğinde, mevcut telemetri irtifasına X ekleyerek mutlak hedefi belirle.
        
        Örnek Girdi ve Çıktı:
        Girdi: "10 metre yüksel, ardından 20 metre doğuya git"
        Çıktı:
        [
          {"action": "takeoff", "parameter": 10},
          {"action": "move", "parameter": {"direction": "doğu", "distance": 20}}
        ]
        
        Çıktı Formatı:
        Yalnızca geçerli bir JSON LİSTESİ (ARRAY) dön. Ek açıklama veya markdown ekleme.
        """
        self.assistant_chat = self.client.chats.create(
            model=self.model_name,
            config=types.GenerateContentConfig(
                system_instruction=asistan_instruction, 
                response_mime_type="application/json", 
                temperature=self.temp
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
            
            parsed_list = json.loads(clean_text.strip())
            if not isinstance(parsed_list, list):
                parsed_list = [parsed_list]
            return parsed_list
        except json.JSONDecodeError as je:
            print(f"[Ayrıştırma Hatası]: {je}")
            return [{"action": "invalid", "parameter": None}]
        except Exception as e:
            print(f"[Asistan Hatası]: {e}")
            return [{"action": "invalid", "parameter": None}]

    def observe_and_verify(self, telemetry, parsed_intent):
        system_instruction = """
        Sen bir İHA Güvenlik Gözlemcisisin. Görevin mevcut batarya seviyesinin komut zincirini tamamlamaya yetip yetmeyeceğini değerlendirmektir.
        
        Yalnızca batarya yeterliliğini denetle ve JSON formatında yanıt dön:
        {"decision": "APPROVED" veya "VETOED", "reason": "neden"}
        """
        audit_context = f"TELEMETRİ: {json.dumps(telemetry)}\nKOMUT_ZİNCİRİ: {json.dumps(parsed_intent)}"
        try:
            response = self.client.models.generate_content(
                model=self.model_name, contents=audit_context,
                config=types.GenerateContentConfig(system_instruction=system_instruction, response_mime_type="application/json", temperature=self.temp)
            )
            return json.loads(response.text)
        except json.JSONDecodeError as je:
            print(f"[Gözlemci Ayrıştırma Hatası]: {je}")
            return {"decision": "VETOED", "reason": "Gözlemci yanıtı ayrıştırılamadı."}
        except Exception as e:
            print(f"[Gözlemci Hatası]: {e}")
            return {"decision": "VETOED", "reason": f"Gözlemci bağlantı hatası: {e}"}