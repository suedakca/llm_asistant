# security.py

class SecurityLayer:
    def __init__(self, max_altitude=50.0, min_battery=20):
        self.max_altitude = max_altitude
        self.min_battery = min_battery

    def validate_and_execute(self, drone, action, parameter=None):
        telemetri = drone.get_telemetry()
        
        hata, mesaj = self._check_safety_rules(telemetri, action, parameter)
        if hata:
            return False, f"GÜVENLİK REDDİ: {mesaj}"

        return True, self._execute_action(drone, action, parameter)

    def _check_safety_rules(self, telemetri, action, parameter):        
        if telemetri["battery"] <= self.min_battery and action == "takeoff":
            return True, f"Batarya kritik seviyede (%{telemetri['battery']}). Kalkış engellendi."

        if action == "takeoff":
            if parameter is None:
                return True, "Kalkış için hedef irtifa belirtilmedi."
            
            target_alt = float(parameter)
            if target_alt <= 0:
                return True, f"Geçersiz irtifa ({target_alt}m). Değer pozitif olmalı."
            if target_alt > self.max_altitude:
                return True, f"Maksimum güvenli uçuş sınırı ({self.max_altitude}m) aşılamaz."

        if action in ["land", "return_to_home"] and not telemetri["in_air"]:
            return True, f"Araç zaten havada değil, {action} işlemi yapılamaz."

        return False, None

    def _execute_action(self, drone, action, parameter):
        fonksiyon_haritasi = {
            "takeoff": lambda: drone.takeoff(parameter),
            "land": drone.land,
            "return_to_home": drone.return_to_home,
            "get_telemetry": lambda: f"Güncel Telemetri: {drone.get_telemetry()}"
        }

        if action not in fonksiyon_haritasi:
            return f"Tanımsız/Hatalı araç fonksiyonu isteği: '{action}'."

        return fonksiyon_haritasi[action]()