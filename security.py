# security.py

class SecurityLayer:
    def __init__(self, config_dict):
        # 1. Kural sınırları tamamen config.yaml'dan bağlanıyor
        self.base_max_altitude = config_dict["base_max_altitude"]
        self.low_battery_max_altitude = config_dict["low_battery_max_altitude"]
        self.critical_battery = config_dict["critical_battery"]
        self.geofence_boundary = config_dict["geofence_boundary"]

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

        # Batarya Sınır Kontrolü
        if current_battery < self.critical_battery:
            if action not in ["land", "return_to_home", "get_telemetry"]:
                return True, f"Batarya kritik seviyede (%{current_battery}). Yalnızca iniş veya RTH yapabilirsiniz!"

        # Dinamik İrtifa Sınırı Belirleme
        if current_battery < 50:
            aktif_maks_irtifa = self.low_battery_max_altitude  
        else:
            aktif_maks_irtifa = self.base_max_altitude         

        # İrtifa Kontrolleri
        if action == "takeoff":
            if parameter is None: return True, "Hedef irtifa belirtilmedi."
            val_param = float(parameter)
            if val_param <= 0: return True, "Değer pozitif olmalı."
            
            if telemetri["in_air"]:
                if (telemetri["altitude"] + val_param) > aktif_maks_irtifa: return True, "Maksimum irtifa sınırı aşılıyor!"
            else:
                if val_param > aktif_maks_irtifa: return True, "Kalkış isteği sınırı aşmaktadır."

        # 3. GEOFENCE GÜVENLİK KURALI EKLEMESİ
        if action == "move":
            if not telemetri["in_air"]: return True, "Yerdeyken yatay hareket yapılamaz."
            if parameter is None or "direction" not in parameter or "distance" not in parameter:
                return True, "Yön veya mesafe eksik."
            
            dist = float(parameter["distance"])
            target_x, target_y = telemetri["x"], telemetri["y"]
            direct = parameter["direction"].lower()
            
            if direct in ["kuzey", "north", "yukarı", "ileri"]: target_y += dist
            elif direct in ["güney", "south", "aşağı", "geri"]: target_y -= dist
            elif direct in ["doğu", "east", "sağ"]: target_x += dist
            elif direct in ["batı", "west", "sol"]: target_x -= dist

            # config.yaml'dan okunan geofence_boundary ile kontrol sağlanıyor
            if abs(target_x) > self.geofence_boundary or abs(target_y) > self.geofence_boundary:
                return True, f"GEOFENCE İHLALİ! Hedef konum (X: {target_x}, Y: {target_y}) sanal sınır kutusunu ({self.geofence_boundary}m) aşmaktadır."

        if action in ["land", "return_to_home"] and not telemetri["in_air"]:
            return True, f"Araç zaten havada değil."

        return False, None

    def _execute_action(self, drone, action, parameter):
        if action == "takeoff":
            target_val = float(parameter)
            if drone.in_air:
                drone.altitude += target_val
                return f"Mevcut irtifaya {target_val}m eklenerek {drone.altitude}m seviyesine yükselindi."
            else:
                return drone.takeoff(target_val)

        if action == "move":
            return drone.move(parameter["direction"], parameter["distance"])

        fonksiyon_haritasi = {
            "land": drone.land,
            "return_to_home": drone.return_to_home,
            "get_telemetry": lambda: f"Güncel Telemetri: {drone.get_telemetry()}"
        }
        return fonksiyon_haritasi[action]()