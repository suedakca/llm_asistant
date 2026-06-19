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
        if not api_key:
            raise ValueError("HATA: .env dosyasında GEMINI_API_KEY bulunamadı!")
        
        self.client = genai.Client(api_key=api_key)
        
        # 1. LLM ayarları tamamen config.yaml'dan yükleniyor
        self.model_name = config_dict["model_name"]
        self.temp = config_dict["temperature"]
        
        # 4. ÇOK TURLU SOHBET BELLEĞİ TALİMATI
        asistan_instruction = """
        Sen bir İHA Pilot Asistanısın. Pilotla derin bir konuşma hafızasına sahip bir agentsın.
        Pilot 'az önce inen aracı tekrar kaldır' veya 'oraya geri git' derse, konuşma geçmişindeki komutları inceleyip ne kastettiğini çözmelisin.
        
        DESTEKLENEN FONKSİYONLAR (action):
        1. 'get_telemetry': Durum/telemetri sorguları.
        2. 'takeoff': Kalkış/Yükselme. 'parameter' olarak net MUTLAK İRTİFAYI (sayı) üretir.
        3. 'land': İniş komutu.
        4. 'return_to_home': Eve dönüş komutu.
        5. 'move': Yatay hareket. 'parameter' olarak obje üretir: {"direction": "kuzey/güney/doğu/batı", "distance": sayı}
        6. 'invalid' / 'ambiguous': Belirsiz veya geçersiz durumlar.
        
        SADECE JSON FORMATINDA CEVAP VER:
        {"action": "fonksiyon_adı", "parameter": değer_veya_null}
        """
        
        # Hafızalı sohbet oturumu başlatılıyor
        self.assistant_chat = self.client.chats.create(
            model=self.model_name,
            config=types.GenerateContentConfig(
                system_instruction=asistan_instruction,
                response_mime_type="application/json",
                temperature=self.temp
            )
        )

    def parse_command(self, user_input, current_telemetry):
        girdi_baglami = f"""
        [SİSTEM DURUMU] İrtifa: {current_telemetry['altitude']}m | Konum: ({current_telemetry['x']},{current_telemetry['y']}) | Batarya: %{current_telemetry['battery']}
        [PİLOT MESAJI] "{user_input}"
        """
        try:
            response = self.assistant_chat.send_message(girdi_baglami)
            clean_text = response.text.strip()
            if clean_text.startswith("```"):
                clean_text = clean_text.split("```")[1]
                if clean_text.startswith("json"): clean_text = clean_text[4:]
            return json.loads(clean_text.strip())
        except:
            return {"action": "invalid", "parameter": None}

    def observe_and_verify(self, telemetry, parsed_intent):
        if parsed_intent.get("action") == "get_telemetry":
            return {"decision": "APPROVED", "reason": "Güvenli okuma işlemi."}

        system_instruction = """
        Sen bir İHA Güvenlik Gözlemcisisin. Gelen komutları batarya durumuna göre veto edersin veya onaylarsın.
        JSON formatında dön: {"decision": "APPROVED" veya "VETOED", "reason": "neden"}
        """
        audit_context = f"TELEMETRİ: {json.dumps(telemetry)}\nKOMUT: {json.dumps(parsed_intent)}"
        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=audit_context,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    response_mime_type="application/json",
                    temperature=self.temp
                )
            )
            return json.loads(response.text)
        except:
            return {"decision": "VETOED", "reason": "Sistem iç hatası."}