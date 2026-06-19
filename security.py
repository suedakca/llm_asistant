# security.py

class SecurityLayer:
    def __init__(self, max_altitude=50.0, min_battery=20):
        self.max_altitude = max_altitude
        self.min_battery = min_battery

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
        """ Tüm kuralların insanca ve tek tek incelendiği filtre odası. """
        
        # Kritik Batarya Kontrolü
        if telemetri["battery"] <= self.min_battery and action == "takeoff":
            return True, f"Batarya kritik seviyede (%{telemetri['battery']}). Kalkış engellendi."

        # Kalkış / Yükselme Kuralları
        if action == "takeoff":
            if parameter is None:
                return True, "Kalkış veya yükselme için hedef irtifa belirtilmedi."
            
            val_param = float(parameter)
            if val_param <= 0:
                return True, f"Geçersiz değer ({val_param}m). Değer pozitif olmalı."
            
            # --- YENİ AKILLI MANTIK ---
            # Eğer araç zaten havadaysa, gelen parametreyi "ekstra yükseklik" olarak kabul et
            if telemetri["in_air"]:
                hedef_irtifa = telemetri["altitude"] + val_param
                if hedef_irtifa > self.max_altitude:
                    return True, f"Mevcut irtifa {telemetri['altitude']}m. Üzerine {val_param}m eklenirse güvenli sınır ({self.max_altitude}m) aşılıyor! İstenen toplam: {hedef_irtifa}m."
            else:
                # Araç yerdeyse parametre doğrudan hedef irtifadır
                if val_param > self.max_altitude:
                    return True, f"Mevcut konum yerdedir. Doğrudan {val_param}m'ye kalkış güvenli sınırı ({self.max_altitude}m) aşıyor."

        # Uçuş Durumu Kontrolleri (Zaten yerdeyse yapılacaklar)
        if action in ["land", "return_to_home"] and not telemetri["in_air"]:
            return True, f"Araç zaten havada değil, {action} işlemi yapılamaz."

        return False, None

    def _execute_action(self, drone, action, parameter):
        """ Güvenlikten geçen komutu drone'un anlayacağı dile çeviren harita. """
        telemetri = drone.get_telemetry()

        # --- YENİ AKILLI MANTIK ---
        if action == "takeoff":
            target_val = float(parameter)
            if telemetri["in_air"]:
                # Araç havadaysa mevcut irtifanın üzerine ekle ve drone'u oraya set et
                yeni_irtifa = telemetri["altitude"] + target_val
                drone.altitude = yeni_irtifa
                return f"Araç zaten havadaydı. Mevcut irtifaya {target_val}m eklenerek {yeni_irtifa}m seviyesine yükselindi."
            else:
                # Araç yerdeyse normal kalkış fonksiyonunu çağır
                return drone.takeoff(target_val)

        fonksiyon_haritasi = {
            "land": drone.land,
            "return_to_home": drone.return_to_home,
            "get_telemetry": lambda: f"Güncel Telemetri: {drone.get_telemetry()}"
        }

        if action not in fonksiyon_haritasi:
            return f"Tanımsız/Hatalı araç fonksiyonu isteği: '{action}'."

        return fonksiyon_haritasi[action]()