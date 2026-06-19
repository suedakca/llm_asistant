# security.py

class SecurityLayer:
    def __init__(self, base_max_altitude=50.0, low_battery_max_altitude=20.0, critical_battery=20):
        self.base_max_altitude = base_max_altitude          # Normal şartlardaki sınır (50m)
        self.low_battery_max_altitude = low_battery_max_altitude  # %50 altındaki sınır (20m)
        self.critical_battery = critical_battery            # Kritik sınır (%20)

    def validate_and_execute(self, drone, action, parameter=None):
        """
        Ana kontrol merkezi: Komutu önce süzer, bir sorun yoksa tetikler.
        """
        telemetri = drone.get_telemetry()
        
        # 1. Önce Güvenlik Filtreleri
        hata_var_mi, mesaj = self._check_safety_rules(telemetri, action, parameter)
        if hata_var_mi:
            return False, f"GÜVENLİK REDDİ: {mesaj}"

        # 2. Güvenliyse Komutu Çalıştır
        return True, self._execute_action(drone, action, parameter)

    def _check_safety_rules(self, telemetri, action, parameter):
        """ Batarya durumuna göre daralan dinamik güvenlik odası. """
        current_battery = telemetri["battery"]

        # --- KURAL 1: KRİTİK BATARYA KONTROLÜ (%20'nin altı) ---
        if current_battery < self.critical_battery:
            # Sadece land ve return_to_home komutlarına izin verilir
            if action not in ["land", "return_to_home", "get_telemetry"]:
                return True, f"Batarya kritik seviyede (%{current_battery}). Bu aşamada yalnızca iniş (land) veya eve dönüş (RTH) yapabilirsiniz!"

        # --- KURAL 2: DİNAMİK İRTİFA SINIRI BELİRLEME (%50'nin altı) ---
        if current_battery < 50:
            aktif_maks_irtifa = self.low_battery_max_altitude  # Sınır otomatik olarak 20m oldu
            batarya_durumu_notu = f"Batarya %50'nin altında (%{current_battery}) olduğu için maksimum irtifa sınırı otomatik olarak {aktif_maks_irtifa}m'ye düşürülmüştür."
        else:
            aktif_maks_irtifa = self.base_max_altitude         # Sınır 50m
            batarya_durumu_notu = f"Maksimum güvenli uçuş sınırı {aktif_maks_irtifa}m'dir."

        # --- KURAL 3: KALKIŞ / YÜKSELME KONTROLLERİ ---
        if action == "takeoff":
            if parameter is None:
                return True, "Kalkış veya yükselme için hedef irtifa belirtilmedi."
            
            val_param = float(parameter)
            if val_param <= 0:
                return True, f"Geçersiz değer ({val_param}m). Değer pozitif olmalı."
            
            # Araç havadaysa (Göreli Yükselme)
            if telemetri["in_air"]:
                hedef_irtifa = telemetri["altitude"] + val_param
                if hedef_irtifa > aktif_maks_irtifa:
                    return True, f"{batarya_durumu_notu} Mevcut irtifa {telemetri['altitude']}m. Üzerine {val_param}m eklenirse sınır aşılıyor! İstenen toplam: {hedef_irtifa}m."
            # Araç yerdeyken kalkış
            else:
                if val_param > aktif_maks_irtifa:
                    return True, f"{batarya_durumu_notu} Doğrudan {val_param}m'ye kalkış isteği bu sınırı aşmaktadır."

        # --- KURAL 4: UÇUŞ DURUMU İSTİSNALARI ---
        if action in ["land", "return_to_home"] and not telemetri["in_air"]:
            return True, f"Araç zaten havada değil, {action} işlemi gerçekleştirilemez."

        return False, None

    def _execute_action(self, drone, action, parameter):
        """ Güvenlikten geçen komutu drone'un anlayacağı dile çeviren harita. """
        telemetri = drone.get_telemetry()

        if action == "takeoff":
            target_val = float(parameter)
            if telemetri["in_air"]:
                yeni_irtifa = telemetri["altitude"] + target_val
                drone.altitude = yeni_irtifa
                return f"Mevcut irtifaya {target_val}m eklenerek {yeni_irtifa}m seviyesine yükselindi."
            else:
                return drone.takeoff(target_val)

        fonksiyon_haritasi = {
            "land": drone.land,
            "return_to_home": drone.return_to_home,
            "get_telemetry": lambda: f"Güncel Telemetri: {drone.get_telemetry()}"
        }

        if action not in fonksiyon_haritasi:
            return f"Tanımsız/Hatalı araç fonksiyonu isteği: '{action}'."

        return fonksiyon_haritasi[action]()