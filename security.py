# security.py

class SecurityLayer:
    def __init__(self, config_dict):
        self.base_max_altitude = float(config_dict["base_max_altitude"])
        self.low_battery_max_altitude = float(config_dict["low_battery_max_altitude"])
        self.critical_battery = int(config_dict["critical_battery"])
        self.geofence_boundary = float(config_dict["geofence_boundary"])

    def validate_and_execute(self, drone, action, parameter=None):
        telemetri = drone.get_telemetry() 
        if telemetri["failsafe"]:
            return False, "Sistem Failsafe modunda kilitli!"
        
        hata_var_mi, mesaj = self._check_safety_rules(telemetri, action, parameter)
        if hata_var_mi:
            return False, f"GÜVENLİK REDDİ: {mesaj}"

        return True, self._execute_action(drone, action, parameter)

    def _check_safety_rules(self, telemetri, action, parameter):
        current_battery = telemetri["battery"]

        # 1. KRİTİK BATARYA KONTROLÜ
        if current_battery < self.critical_battery:
            if action not in ["land", "return_to_home", "get_telemetry"]:
                return True, f"Batarya kritik seviyede (%{current_battery}). Yalnızca iniş veya RTH yapabilirsiniz!"

        # 2. DİNAMİK İRTİFA SINIRI BELİRLEME
        if current_battery < 50: 
            aktif_maks_irtifa = self.low_battery_max_altitude  
            batarya_notu = f"Batarya %50'nin altında (%{current_battery}) olduğu için limit {aktif_maks_irtifa}m'dir."
        else: 
            aktif_maks_irtifa = self.base_max_altitude         
            batarya_notu = f"Maksimum güvenli uçuş sınırı {aktif_maks_irtifa}m'dir."

        # 3. TAKEOFF / YÜKSELME VALIDASYONU
        if action == "takeoff":
            if parameter is None: return True, "Hedef irtifa belirtilmedi."
            hedef_mutlak_irtifa = float(parameter)
            if hedef_mutlak_irtifa <= 0: return True, "Hedef irtifa pozitif olmalı."
            if hedef_mutlak_irtifa > aktif_maks_irtifa: 
                return True, f"{batarya_notu} İstenen yükseklik ({hedef_mutlak_irtifa}m) sınırı aşmaktadır!"

        # 4. MOVE VE GEOFENCE KONTROLÜ
        if action == "move":
            if not telemetri["in_air"]: return True, "Yerdeyken yatay hareket yapılamaz."
            if parameter is None or "direction" not in parameter or "distance" not in parameter:
                return True, "Yön veya mesafe parametresi eksik."
            
            dist = float(parameter["distance"])
            if dist <= 0: return True, "Mesafe pozitif olmalıdır."
            
            target_x, target_y = telemetri["x"], telemetri["y"]
            direct = parameter["direction"].lower()
            
            if direct in ["kuzey", "north", "yukarı", "ileri"]: target_y += dist
            elif direct in ["güney", "south", "aşağı", "geri"]: target_y -= dist
            elif direct in ["doğu", "east", "sağ"]: target_x += dist
            elif direct in ["batı", "west", "sol"]: target_x -= dist

            if abs(target_x) > self.geofence_boundary or abs(target_y) > self.geofence_boundary:
                return True, f"GEOFENCE İHLALİ! Hedef konum (X: {target_x}, Y: {target_y}) sanal sınırı ({self.geofence_boundary}m) aşmaktadır."

        # 5. SET_HOME VALIDASYONU
        if action == "set_home":
            if telemetri["in_air"]: 
                return True, "Havada iken ev konumu değiştirilemez!"
            if parameter is None or "x" not in parameter or "y" not in parameter:
                return True, "Geçersiz koordinat parametresi."
            
            hx = float(parameter["x"])
            hy = float(parameter["y"])
            if abs(hx) > self.geofence_boundary or abs(hy) > self.geofence_boundary:
                return True, f"Belirlenen ev konumu Geofence sınırlarının ({self.geofence_boundary}m) dışındadır!"

        # 6. UÇUŞ DURUMU İSTİSNALARI
        if action in ["land", "return_to_home"] and not telemetri["in_air"]:
            return True, "Araç zaten havada değil, bu işlem gerçekleştirilemez."

        return False, None

    def _execute_action(self, drone, action, parameter):
        # Gerçek Çalıştırma Kodları Eksiksiz Geri Getirildi
        if action == "takeoff":
            return drone.takeoff(float(parameter))

        if action == "move":
            return drone.move(parameter["direction"], parameter["distance"])

        if action == "set_home":
            return drone.set_home(parameter["x"], parameter["y"])

        fonksiyon_haritasi = {
            "land": drone.land,
            "return_to_home": drone.return_to_home,
            "get_telemetry": lambda: f"Güncel Telemetri: {drone.get_telemetry()}"
        }

        if action not in fonksiyon_haritasi:
            return f"Hata: Güvenlik katmanı '{action}' eylemini haritalayamadı."

        return fonksiyon_haritasi[action]()