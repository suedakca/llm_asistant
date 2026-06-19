# assistant.py
import os
import json
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

class PilotAssistant:
    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("HATA: .env dosyasında GEMINI_API_KEY bulunamadı!")
        
        self.client = genai.Client(api_key=api_key)
        self.model_name = "gemini-2.5-flash" 

    def parse_command(self, user_input):
        """ [LLM 1] Kullanıcının doğal dil cümlesini komuta (JSON) çevirir. """
        system_instruction = """
        Sen bir İHA Pilot Asistanısın. Kullanıcının verdiği Türkçe komutları analiz ederek 
        yalnızca verilen JSON formatında çıktı üretmelisin.
        
        Desteklenen fonksiyonlar (action):
        1. 'get_telemetry': Durum veya telemetri sorgulamalarında kullanılır.
        2. 'takeoff': Kalkış, yükselme komutlarında kullanılır. 'parameter' olarak hedef irtifayı (sayı) alır.
        3. 'land': İniş yapma komutlarında kullanılır.
        4. 'return_to_home': Eve dön komutlarında kullanılır.
        5. 'invalid': Güvensiz, saçma isteklerde kullanılır.
        6. 'ambiguous': Hedef belirtilmeyen belirsiz komutlarda kullanılır.
        
        Çıktı Formatı: {"action": "fonksiyon_adı", "parameter": sayı_veya_null}
        """
        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=user_input,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    response_mime_type="application/json",
                    temperature=0.1
                )
            )
            return json.loads(response.text)
        except:
            return {"action": "invalid", "parameter": None}

    def observe_and_verify(self, telemetry, parsed_intent):
        """ 
        [LLM 2 - GÜVENLİK GÖZLEMCİSİ] 
        İlk LLM'in kararını ve telemetriyi bağımsız olarak denetler, gerekçe sunar.
        """
        system_instruction = f"""
        Sen bağımsız bir İHA Güvenlik Gözlemcisisin (Safety Watchdog). 
        Görevin, Pilot Asistanının (LLM 1) aldığı kararı, drone'un güncel durumu ve katı güvenlik kuralları çerçevesinde denetlemektir.
        
        Katı Güvenlik Kuralları:
        - Maksimum İrtifa Sınırı: Drone kesinlikle 50 metrenin üzerine çıkamaz. (Eğer drone havadaysa ve gelen parametre ile toplamı 50'yi aşacaksa VETO et!).
        - Kritik Batarya Sınırı: Batarya %25 veya altındaysa, 'return_to_home' DIŞINDAKİ tüm havada kalma/kalkış komutlarını VETO et!
        
        Sana sunulan veriler doğrultusunda kararını ver ve YALNIZCA şu JSON formatında dön:
        {{
            "decision": "APPROVED" veya "VETOED",
            "reason": "Kararının gerekçesini açıklayan insansı, net bir Türkçe cümle."
        }}
        """

        # Denetlenecek senaryoyu metin haline getiriyoruz
        audit_context = f"""
        GÜNCEL TELEMETRİ: {json.dumps(telemetry)}
        LLM 1'İN ALDIĞI KARAR: Action='{parsed_intent.get("action")}', Parameter={parsed_intent.get("parameter")}
        """

        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=audit_context,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    response_mime_type="application/json",
                    temperature=0.1
                )
            )
            return json.loads(response.text)
        except:
            return {"decision": "VETOED", "reason": "Gözlemci model hatası nedeniyle güvenlik vetosu."}