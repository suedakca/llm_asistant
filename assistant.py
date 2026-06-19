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
        self.model_name = "gemini-1.5" 
        
        # --- LLM 1: ASİSTAN SOHBET TALİMATI ---
        asistan_instruction = """
        Sen bir İHA Pilot Asistanısın. Pilotla gerçek bir sohbet geçmişine sahipsin.
        Görevin, pilotun doğal dildeki cümlelerini analiz edip drone komutlarına dönüştürmektir.
        
        BAĞLAM VE HAFIZA KURALLARI:
        - Pilot 'biraz daha yüksel' veya 'yukarı çık' derse, sana gönderilen ANLIK TELEMETRİDEKİ 'altitude' (irtifa) değerine bak. Mevcut irtifanın üzerine mantıklı bir miktar (örneğin 5 veya 10 metre) EKLEYEREK yeni bir hedef mutlak irtifa belirle ve 'takeoff' eylemi üret. Sakın 'ambiguous' deme!
        - Pilot 'oraya git', 'oraya iniş yap' gibi kelimeler kullanırsa konuşma geçmişini incele. Eğer daha önce kalkış yapılan yerden veya evden bahsediyorsa bunu 'return_to_home' veya 'land' olarak çözebilirsin.
        
        DESTEKLENEN FONKSİYONLAR (action):
        1. 'get_telemetry': Durum, batarya, konum sorgularında. Parametre almaz.
        2. 'takeoff': Kalkış ve yükselmelerde. 'parameter' olarak her zaman net GİDİLECEK MUTLAK İRTİFAYI (sayı) üretir.
        3. 'land': İniş komutlarında. Parametre almaz.
        4. 'return_to_home': Eve dön komutlarında. Parametre almaz.
        5. 'invalid': Tamamen anlamsız, uçuşla ilgisiz komutlarda.
        6. 'ambiguous': Geçmişe ve telemetriye baksan dahi pilotun ne istediği hiç anlaşılamıyorsa.
        
        ÇIÇTI FORMATI: Sadece bu JSON formatında cevap ver, başka hiçbir yazı yazma:
        {"action": "fonksiyon_adı", "parameter": sayı_veya_null}
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
            
            # Gemini'ın kafasının karışmaması için girdiyi çok daha net ve yapılandırılmış hale getiriyoruz
            girdi_baglami = f"""
            [SİSTEM DURUMU / ANLIK TELEMETRİ]
            - İrtifa (altitude): {current_telemetry['altitude']}m
            - Havada mı (in_air): {current_telemetry['in_air']}
            - Batarya (battery): %{current_telemetry['battery']}
            
            [PİLOTUN SÖYLEDİĞİ CÜMLE]
            "{user_input}"
            """
            
            try:
                # send_message kullanarak geçmişi otomatik biriktiriyoruz
                response = self.assistant_chat.send_message(girdi_baglami)
                
                # Gelen cevabın içindeki gereksiz boşlukları temizleyelim
                clean_text = response.text.strip()
                
                # Bazen model ```json ... ``` içinde dönebilir, onu temizleyelim
                if clean_text.startswith("```"):
                    clean_text = clean_text.split("```")[1]
                    if clean_text.startswith("json"):
                        clean_text = clean_text[4:]
                
                return json.loads(clean_text.strip())
            except Exception as e:
                # Hatanın ne olduğunu terminalde görmek için buraya print ekledik (Raporda silersin)
                print(f"[LLM 1 PARSE HATASI]: {e} | Gelen Ham Metin: {response.text if 'response' in locals() else 'Yok'}")
                return {"action": "invalid", "parameter": None}

    def observe_and_verify(self, telemetry, parsed_intent):
        """ [LLM 2 - GÜVENLİK GÖZLEMCİSİ] Bağımsız denetim yapar. """
        
        # KRİTİK DÜZELTME: Eğer komut sadece telemetri okumak ise gözlemciyi yormadan direkt onayla
        if parsed_intent.get("action") == "get_telemetry":
            return {"decision": "APPROVED", "reason": "Telemetri sorgulama işlemi herhangi bir güvenlik riski barındırmaz."}

        system_instruction = f"""
        Sen bağımsız bir İHA Güvenlik Gözlemcisisin (Safety Watchdog). 
        Görevin, Pilot Asistanının (LLM 1) aldığı kararı, drone'un güncel batarya ve telemetri durumuna göre denetlemektir.
        
        DİNAMİK GÜVENLİK KURALLARI:
        1. Batarya %50 ve üzerinde ise: Maksimum irtifa sınırı 50 metredir.
        2. Batarya %50'nin altına düştüğünde: Sistem maksimum güvenli irtifayı OTOMATİK OLARAK 20 metreye düşürür. (Hedef irtifa 20m'yi aşacaksa VETO et!).
        3. Batarya %20'nin altına düştüğünde: YALNIZCA 'land' (iniş) ve 'return_to_home' (eve dönüş) komutlarına izin verilir. Diğer tüm uçuş/yükselme komutlarını kesinlikle VETO et!
        
        Sana sunulan veriler doğrultusunda kararını ver ve YALNIZCA şu JSON formatında dön:
        {{
            "decision": "APPROVED" veya "VETOED",
            "reason": "Kararının gerekçesini açıklayan, batarya durumuna ve dinamik sınırlara değinen Türkçe bir cümle."
        }}
        """

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
        except Exception as e:
            # Buradaki hatayı terminalde görebilmek için print ekledik
            print(f"[GÖZLEMCİ İÇ HATASI]: {e}")
            return {"decision": "VETOED", "reason": "Gözlemci model iç hatası nedeniyle güvenlik vetosu."}