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
        
        # [DÜZELTME] Liste (Array) formatında çıktı üretmesi için instruction güncellendi
        asistan_instruction = """
        Sen bir İHA Pilot Asistanısın. Pilotla derin bir konuşma hafızasına sahip akıllı bir agentsın.
        Görevin, pilotun tekli veya çoklu/zincirleme komutlarını analiz edip sırasıyla çalıştırılacak bir komut listesi üretmektir.
        
        İRTİFA SEMANTİK KURALI:
        - 'takeoff' eylemi için 'parameter' değeri HER ZAMAN drone'un ulaşmasını istediğin nihaî MUTLAK İRTİFA olmalıdır.
        - Eğer bir zincir içinde ardışık yükselmeler varsa, telemetriye ve zincirdeki önceki takeoff adımlarına bakarak mutlak hedefi matematiksel olarak hesapla.
        
        DESTEKLENEN FONKSİYONLAR:
        - 'get_telemetry'
        - 'takeoff'
        - 'land'
        - 'return_to_home'
        - 'move'
        - 'reboot'
        - 'set_home'
        - 'complete_checklist': Pilot kalkış öncesi kontrollerin tamam olduğunu belirttiğinde ("kontroller tamam", "hazırız", "pervaneler ve gps tamam" vb.) çalıştırılır. Parametre almaz.
        - 'invalid'/'ambiguous'
        
        ÇIKTI FORMATI (ÇOK KRİTİK):
        YALNIZCA geçerli bir JSON LİSTESİ (ARRAY) dönmelisin. Tek bir komut dahi olsa liste içinde olmalıdır.
        Açıklama veya markdown kodu ekleme. 
        
        Örnek girdi: "10 metreye yüksel, ardından 20 metre doğuya git ve orada iniş yap."
        Örnek çıktı:
        [
          {"action": "takeoff", "parameter": 10},
          {"action": "move", "parameter": {"direction": "doğu", "distance": 20}},
          {"action": "land", "parameter": null}
        ]
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
            
            # Gelen veriyi liste olarak yüklüyoruz
            parsed_list = json.loads(clean_text.strip())
            if not isinstance(parsed_list, list):
                parsed_list = [parsed_list] # Liste değilse listeye sarmala (Defensive)
            return parsed_list
        except json.JSONDecodeError as je:
            print(f"[ASİSTAN PARSE HATASI]: {je}")
            return [{"action": "invalid", "parameter": None}]
        except Exception as e:
            print(f"[ASİSTAN GENEL HATA]: {e}")
            return [{"action": "invalid", "parameter": None}]

    def observe_and_verify(self, telemetry, parsed_intent):
        """ Gözlemci tüm zinciri bütünsel olarak veya tek tek denetleyebilir """
        system_instruction = """
        Sen bir İHA Güvenlik Gözlemcisisin. Görevin YALNIZCA mevcut batarya seviyesinin komut zincirini tamamlamaya yetip yetmeyeceğini değerlendirmektir.

        KRİTİK KURAL: Aşağıdaki alanlara BAKMA ve bunlara göre veto verme:
        - checklist_completed (kontrol listesi güvenlik katmanı tarafından denetlenir)
        - wind_speed (rüzgar kontrolü güvenlik katmanı tarafından yapılır)
        - in_air durumu (durum geçerliliği güvenlik katmanının görevidir)

        SADECE şu soruyu sor: "Mevcut batarya (%X) bu zinciri tamamlamak için yeterli mi?"
        JSON formatında dön: {"decision": "APPROVED" veya "VETOED", "reason": "neden"}
        """
        audit_context = f"TELEMETRİ: {json.dumps(telemetry)}\nKOMUT_ZİNCİRİ: {json.dumps(parsed_intent)}"
        try:
            response = self.client.models.generate_content(
                model=self.model_name, contents=audit_context,
                config=types.GenerateContentConfig(system_instruction=system_instruction, response_mime_type="application/json", temperature=self.temp)
            )
            return json.loads(response.text)
        except:
            return {"decision": "VETOED", "reason": "Gözlemci bağlantı hatası."}