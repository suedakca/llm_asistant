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
        # Kota sorununu aşmak için 2.0-flash ile devam ediyoruz
        self.model_name = "gemini-2.0-flash" 
        
        # --- LLM 1: GELİŞMİŞ HAFIZALI ASİSTAN TALİMATI ---
        asistan_instruction = """
        Sen bir İHA Pilot Asistanısın. Pilotla derin bir konuşma geçmişine sahip akıllı bir agentsın.
        
        ÇOK TURLU SOHBET VE REFERANS KURALLARI:
        - Pilot 'az önce inen aracı tekrar kaldır' gibi geçmişe yönelik bir şey söylerse, konuşma geçmişindeki eylemleri incele. Eğer en son eylem 'land' (iniş) ise ve ondan önce belli bir irtifaya kalkış yapılmışsa (örn: 10m), eylemi 'takeoff' ve parametreyi o eski irtifa (10) olarak belirle.
        - Pilot 'oraya git', 'oraya uç' gibi belirsiz koordinat bildiren cümleler kurarsa, bir önceki mesajlarda bahsi geçen yönü ve mesafeyi (Örn: Kuzeye 30 metre git demiştik, şimdi 'oraya geri dön' diyorsa yönü Güney, mesafeyi 30 yap) ya da konumu zekice çözümle.
        
        DESTEKLENEN FONKSİYONLAR (action):
        1. 'get_telemetry': Durum/telemetri sorgularında. Parametre almaz.
        2. 'takeoff': Kalkış ve yükselmelerde. 'parameter' olarak gidilecek net MUTLAK İRTİFAYI (sayı) alır.
        3. 'land': İniş komutlarında. Parametre almaz.
        4. 'return_to_home': Eve dön komutlarında. Parametre almaz.
        5. 'move': Yatay hareket isteklerinde (Örn: 'Kuzeye 30 metre git'). 'parameter' olarak bir JSON objesi alır: {"direction": "kuzey/güney/doğu/batı", "distance": sayı}
        6. 'invalid': Havacılık dışı veya saçma isteklerde.
        7. 'ambiguous': Geçmişe baksan dahi pilotun ne kastettiği asla anlaşılamıyorsa.
        
        ÇIKTI FORMATI: Sadece bu JSON formatında cevap ver, açıklama yazma:
        {"action": "fonksiyon_adı", "parameter": değer_veya_null_veya_obje}
        """
        
        self.assistant_chat = self.client.chats.create(
            model=self.model_name,
            config=types.GenerateContentConfig(
                system_instruction=asistan_instruction,
                response_mime_type="application/json",
                temperature=0.1
            )
        )

    def parse_command(self, user_input, current_telemetry):
        """ [LLM 1] Konuşma geçmişini ve anlık telemetriyi kullanarak komutu çözümler. """
        girdi_baglami = f"""
        [SİSTEM DURUMU / ANLIK TELEMETRİ]
        - İrtifa: {current_telemetry['altitude']}m
        - Konum: (X: {current_telemetry['x']}, Y: {current_telemetry['y']})
        - Havada mı: {current_telemetry['in_air']}
        - Batarya: %{current_telemetry['battery']}
        
        [PİLOTUN SÖYLEDİĞİ CÜMLE]
        "{user_input}"
        """
        try:
            response = self.assistant_chat.send_message(girdi_baglami)
            clean_text = response.text.strip()
            if clean_text.startswith("```"):
                clean_text = clean_text.split("```")[1]
                if clean_text.startswith("json"):
                    clean_text = clean_text[4:]
            return json.loads(clean_text.strip())
        except Exception as e:
            return {"action": "invalid", "parameter": None}

    def observe_and_verify(self, telemetry, parsed_intent):
        """ [LLM 2 - GÜVENLİK GÖZLEMCİSİ] Bağımsız denetim yapar. """
        if parsed_intent.get("action") == "get_telemetry":
            return {"decision": "APPROVED", "reason": "Telemetri sorgulama işlemi güvenlidir."}

        system_instruction = f"""
        Sen bağımsız bir İHA Güvenlik Gözlemcisisin. 
        Görevin, Pilot Asistanının (LLM 1) aldığı kararı, drone'un güncel batarya ve telemetri durumuna göre denetlemektir.
        
        DİNAMİK GÜVENLİK KURALLARI:
        1. Batarya %50 ve üzerinde ise: Maksimum irtifa sınırı 50 metredir.
        2. Batarya %50'nin altına düştüğünde: Sistem maksimum güvenli irtifayı 20 metreye düşürür. (Toplam irtifa 20m'yi aşacaksa VETO et!).
        3. Batarya %20'nin altına düştüğünde: YALNIZCA 'land' (iniş) ve 'return_to_home' (eve dönüş) komutlarına izin verilir. Diğer tüm uçuş, yükselme ve 'move' (yatay hareket) komutlarını kesinlikle VETO et!
        
        Sana sunulan veriler doğrultusunda kararını ver ve YALNIZCA şu JSON formatında dön:
        {{
            "decision": "APPROVED" veya "VETOED",
            "reason": "Gerekçeyi açıklayan Türkçe bir cümle."
        }}
        """
        audit_context = f"""
        GÜNCEL TELEMETRİ: {json.dumps(telemetry)}
        LLM 1'İN ALDIĞI KARAR: Action='{parsed_intent.get("action")}', Parameter={json.dumps(parsed_intent.get("parameter"))}
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
            return {"decision": "VETOED", "reason": "Gözlemci model iç hatası nedeniyle güvenlik vetosu."}