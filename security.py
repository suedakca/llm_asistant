# security.py

class SecurityLayer:
    def __init__(self, base_max_altitude=50.0, low_battery_max_altitude=20.0, critical_battery=20, geofence_boundary=50.0):
        self.base_max_altitude = base_max_altitude          
        self.low_battery_max_altitude = low_battery_max_altitude  
        self.critical_battery = critical_battery            
        self.geofence_boundary = geofence_boundary          # YENİ: Sanal Sınır Kutusu (±50m)

    def validate_and_execute(self, drone, action, parameter=None):
        telemetri = drone.get_telemetry() 
        
        # Eğer cihaz zaten failsafe modundaysa hiçbir şey çalıştırma
        if telemetri["failsafe"]:
            return False, "Sistem Acil Durum (Failsafe) modunda kilitli! Güvenlik nedeniyle hiçbir komut işletilemez."
        
        # 1. Önce Güvenlik Filtreleri
        hata_var_mi, mesaj = self._check_safety_rules(telemetri, action, parameter)
        if hata_var_mi:
            return False, f"GÜVENLİK REDDİ: {mesaj}"

        # 2. Güvenliyse Komutu Çalıştır
        return True, self._execute_action(drone, action, parameter)

    def _check_safety_rules(self, telemetri, action, parameter):
        current_battery = telemetri["battery"]

        # --- KURAL 1: KRİTİK BATARYA KONTROLÜ (%20'nin altı) ---
        if current_battery < self.critical_battery:
            if action not in ["land", "return_to_home", "get_telemetry"]:
                return True, f"Batarya kritik seviyede (%{current_battery}). Yalnızca iniş veya RTH yapabilirsiniz!"

        # --- KURAL 2: DİNAMİK İRTİFA SINIRI BELİRLEME ---
        if current_battery < 50:
            aktif_maks_irtifa = self.low_battery_max_altitude  
            batarya_durumu_notu = f"Batarya %50'nin altında (%{current_battery}) olduğu için maksimum irtifa {aktif_maks_irtifa}m'ye düşürülmüştür."
        else:
            aktif_maks_irtifa = self.base_max_altitude         
            batarya_durumu_notu = f"Maksimum güvenli uçuş sınırı {aktif_maks_irtifa}m'dir."

        # --- KURAL 3: KALKIŞ / YÜKSELME KONTROLLERİ ---
        if action == "takeoff":
            if parameter is None: return True, "Kalkış/yükselme için hedef irtifa belirtilmedi."
            val_param = float(parameter)
            if val_param <= 0: return True, f"Geçersiz değer ({val_param}m). Değer pozitif olmalı."
            
            if telemetri["in_air"]:
                hedef_irtifa = telemetri["altitude"] + val_param
                if hedef_irtifa > aktif_maks_irtifa:
                    return True, f"{batarya_durumu_notu} Mevcut: {telemetri['altitude']}m. Eklenen: {val_param}m. Sınır aşılıyor!"
            else:
                if val_param > aktif_maks_irtifa:
                    return True, f"{batarya_durumu_notu} Doğrudan {val_param}m'ye kalkış isteği sınırı aşmaktadır."

        # --- KURAL 4: YATAY HAREKET VE GEOFENCE KONTROLÜ ---
        if action == "move":
            if not telemetri["in_air"]:
                return True, "Araç havada değil. Yerdeyken yatay hareket yapılamaz."
            if parameter is None or "direction" not in parameter or "distance" not in parameter:
                return True, "Yatay hareket için yön veya mesafe parametreleri eksik."
            
            dist = float(parameter["distance"])
            if dist <= 0: return True, "Hareket mesafesi pozitif olmalıdır."
            
            # Geofence Gelecek Konum Tahmini
            target_x = telemetri["x"]
            target_y = telemetri["y"]
            direct = parameter["direction"].lower()
            
            if direct in ["kuzey", "north", "yukarı", "ileri"]: target_y += dist
            elif direct in ["güney", "south", "aşağı", "geri"]: target_y -= dist
            elif direct in ["doğu", "east", "sağ"]: target_x += dist
            elif direct in ["batı", "west", "sol"]: target_x -= dist

            # Sanal Sınır İhlal Kontrolü (±50m dışı yasak)
            if abs(target_x) > self.geofence_boundary or abs(target_y) > self.geofence_boundary:
                return True, f"GEOFENCE İHLALİ! Planlanan yeni konum (X: {target_x}, Y: {target_y}) sanal uçuş sınır çizgimizi ({self.geofence_boundary}m) aşmaktadır. Hareket engellendi."

        # --- KURAL 5: UÇUŞ DURUMU İSTİSNALARI ---
        if action in ["land", "return_to_home"] and not telemetri["in_air"]:
            return True, f"Araç zaten havada değil, {action} işlemi gerçekleştirilemez."

        return False, None

    def _execute_action(self, drone, action, parameter):
        if action == "takeoff":
            target_val = float(parameter)
            if drone.in_air:
                yeni_irtifa = drone.altitude + target_val
                drone.altitude = yeni_irtifa
                return f"Mevcut irtifaya {target_val}m eklenerek {yeni_irtifa}m seviyesine yükselindi."
            else:
                return drone.takeoff(target_val)

        if action == "move":
            return drone.move(parameter["direction"], parameter["distance"])

        fonksiyon_haritasi = {
            "land": drone.land,
            "return_to_home": drone.return_to_home,
            "get_telemetry": lambda: f"Güncel Telemetri: {drone.get_telemetry()}"
        }

        if action not in fonksiyon_haritasi:
            return f"Tanımsız/Hatalı araç fonksiyonu isteği: '{action}'."

        return fonksiyon_haritasi[action]()