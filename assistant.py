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
            raise ValueError("HATA: Lütfen GEMINI_API_KEY ortam değişkenini ayarlayın!")
        
        self.client = genai.Client(api_key=api_key)
        self.model_name = "gemini-2.5-flash" 

    def parse_command(self, user_input):
        """
        Kullanıcının doğal dil cümlesini analiz eder ve yapılandırılmış JSON döner.
        """
        system_instruction = """
        Sen bir İHA Pilot Asistanısın. Kullanıcının verdiği Türkçe komutları analiz ederek 
        yalnızca ve yalnızca sana verilen JSON formatında çıktı üretmelisiniz.
        
        Desteklenen fonksiyonlar (action) ve kurallar:
        1. 'get_telemetry': Durum, konum veya telemetri sorgulamalarında kullanılır. Parametre almaz.
        2. 'takeoff': Kalkış, yükselme komutlarında kullanılır. 'parameter' olarak hedef irtifayı (sayı) alır.
        3. 'land': İniş yapma komutlarında kullanılır. Parametre almaz.
        4. 'return_to_home': Eve dön, başlangıç noktasına git komutlarında kullanılır. Parametre almaz.
        5. 'invalid': Güvensiz, saçma veya tanımlanmamış fonksiyon isteklerinde kullanılır. (Örn: motorları sonsuza kadar yak)
        6. 'ambiguous': Hedef irtifa belirtilmeden 'kalk' denmesi veya 'biraz yüksel' gibi belirsiz komutlarda kullanılır.
        
        Çıktı Formatı (Sadece bu JSON'u dön, açıklama yazma):
        {
            "action": "fonksiyon_adı",
            "parameter": sayı_veya_null
        }
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
            
        except Exception as e:
            return {"action": "invalid", "parameter": None}