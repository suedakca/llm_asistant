# security.py

# Güvenlik katmanının tanıdığı ve çalıştırabileceği eylemler.
# LLM bunun dışında bir şey üretirse komut zinciri reddedilir.
ALLOWED_ACTIONS = {
    "takeoff",
    "land",
    "return_to_home",
    "move",
    "set_home",
    "get_telemetry",
    "complete_checklist",
}


def _to_float(value):
    """ LLM'den gelen sayısal parametreyi güvenle float'a çevirir.
        Çevrilemiyorsa None döner (çağıran taraf güvenlik reddi üretir). """
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class SecurityLayer:
    def __init__(self, config_dict):
        self.base_max_altitude = float(config_dict["base_max_altitude"])
        self.low_battery_max_altitude = float(config_dict["low_battery_max_altitude"])
        self.critical_battery = int(config_dict["critical_battery"])
        self.geofence_boundary = float(config_dict["geofence_boundary"])
        self.max_wind_speed = float(config_dict.get("max_wind_speed", 30.0))

    def validate_and_execute(self, drone, action, parameter=None, telemetri=None):
        if telemetri is None:
            telemetri = drone.get_telemetry()
        if telemetri["failsafe"]:
            return False, "Sistem Failsafe modunda kilitli!"

        # ARIZA DENETİMİ: bozulmuş sensör/donanım durumunda hangi eylemlerin
        # güvenli olmadığına arıza modülü karar verir (iniş her zaman serbest).
        faults = getattr(drone, "faults", None)
        if faults is not None:
            ariza_engeli = faults.blocking_reason(action, telemetri)
            if ariza_engeli:
                return False, f"GÜVENLİK REDDİ: {ariza_engeli}"

        hata_var_mi, mesaj = self._check_safety_rules(telemetri, action, parameter)
        if hata_var_mi:
            return False, f"GÜVENLİK REDDİ: {mesaj}"

        return True, self._execute_action(drone, action, parameter)

    def _check_safety_rules(self, telemetri, action, parameter):
        current_battery = telemetri["battery"]
        current_wind = telemetri.get("wind_speed", 0.0)

        # -1. TANINMAYAN EYLEM KONTROLÜ
        # Haritalanamayan bir eylem asla "onaylandı" olarak dönmemelidir.
        if action not in ALLOWED_ACTIONS:
            return True, f"Tanınmayan eylem: '{action}'. Desteklenen eylemler: {', '.join(sorted(ALLOWED_ACTIONS))}."

        # 0. RÜZGAR HIZI KONTROLÜ (TAKEOFF VEYA MOVE İÇİN)
        if action in ["takeoff", "move"]:
            if current_wind > self.max_wind_speed:
                return True, f"RÜZGAR ENGELİ: Anlık rüzgar hızı ({current_wind} km/s) güvenli uçuş limitini ({self.max_wind_speed} km/s) aşmaktadır! Uçuş gerçekleştirilemez."

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
            if not telemetri["in_air"] and not telemetri["checklist_completed"]:
                return True, "Kalkış öncesi kontrol listesi (Pre-flight Checklist) onaylanmadı! Kalkış yapabilmek için lütfen kalkış öncesi kontrolleri onaylayın (Örn: 'kontroller tamam').\nKontroller: 1. Pervaneler sağlam mı? 2. GPS kilitlendi mi? 3. Çevre uçuşa güvenli mi?"
            if parameter is None: return True, "Hedef irtifa belirtilmedi."
            hedef_mutlak_irtifa = _to_float(parameter)
            if hedef_mutlak_irtifa is None:
                return True, f"Geçersiz irtifa parametresi: '{parameter}'. Sayısal bir değer bekleniyor."
            if hedef_mutlak_irtifa <= 0: return True, "Hedef irtifa pozitif olmalı."
            if hedef_mutlak_irtifa > aktif_maks_irtifa: 
                return True, f"{batarya_notu} İstenen yükseklik ({hedef_mutlak_irtifa}m) sınırı aşmaktadır!"

        # 4. MOVE VE GEOFENCE KONTROLÜ
        if action == "move":
            if not telemetri["in_air"]: return True, "Yerdeyken yatay hareket yapılamaz."
            if not isinstance(parameter, dict) or "direction" not in parameter or "distance" not in parameter:
                return True, "Yön veya mesafe parametresi eksik."
            if not isinstance(parameter.get("direction"), str):
                return True, f"Geçersiz yön parametresi: '{parameter.get('direction')}'."
            
            dist = _to_float(parameter["distance"])
            if dist is None:
                return True, f"Geçersiz mesafe parametresi: '{parameter['distance']}'. Sayısal bir değer bekleniyor."
            if dist <= 0: return True, "Mesafe pozitif olmalıdır."
            
            target_x, target_y = telemetri["x"], telemetri["y"]
            direct = parameter["direction"].lower()

            VALID_DIRECTIONS = {
                "kuzey", "north", "ileri",
                "güney", "south", "geri",
                "doğu", "east", "sağ",
                "batı", "west", "sol",
            }
            if direct not in VALID_DIRECTIONS:
                return True, f"Geçersiz yön: '{direct}'. Desteklenen yönler: kuzey, güney, doğu, batı."

            if direct in ["kuzey", "north", "ileri"]: target_y += dist
            elif direct in ["güney", "south", "geri"]: target_y -= dist
            elif direct in ["doğu", "east", "sağ"]: target_x += dist
            elif direct in ["batı", "west", "sol"]: target_x -= dist

            if abs(target_x) > self.geofence_boundary or abs(target_y) > self.geofence_boundary:
                return True, f"GEOFENCE İHLALİ! Hedef konum (X: {target_x}, Y: {target_y}) sanal sınırı ({self.geofence_boundary}m) aşmaktadır."

        # 5. SET_HOME VALIDASYONU
        if action == "set_home":
            if telemetri["in_air"]: 
                return True, "Havada iken ev konumu değiştirilemez!"
            if not isinstance(parameter, dict) or "x" not in parameter or "y" not in parameter:
                return True, "Geçersiz koordinat parametresi."

            hx = _to_float(parameter["x"])
            hy = _to_float(parameter["y"])
            if hx is None or hy is None:
                return True, f"Geçersiz koordinat değeri: (x={parameter['x']}, y={parameter['y']}). Sayısal değer bekleniyor."
            if abs(hx) > self.geofence_boundary or abs(hy) > self.geofence_boundary:
                return True, f"Belirlenen ev konumu Geofence sınırlarının ({self.geofence_boundary}m) dışındadır!"

        # 6. UÇUŞ DURUMU İSTİSNALARI
        if action in ["land", "return_to_home"] and not telemetri["in_air"]:
            return True, "Araç zaten havada değil, bu işlem gerçekleştirilemez."

        if action == "complete_checklist":
            if telemetri["in_air"]:
                return True, "Araç zaten havada, kalkış öncesi kontrol listesi onaylanamaz."

        return False, None

    def _execute_action(self, drone, action, parameter):
        # Gerçek Çalıştırma Kodları Eksiksiz Geri Getirildi
        if action == "takeoff":
            return drone.takeoff(float(parameter))

        if action == "move":
            return drone.move(parameter["direction"], parameter["distance"])

        if action == "set_home":
            return drone.set_home(parameter["x"], parameter["y"])

        if action == "complete_checklist":
            drone.checklist_completed = True
            return "Başarılı: Kalkış öncesi kontrol listesi onaylandı. Artık güvenle kalkış yapabilirsiniz (takeoff)."

        fonksiyon_haritasi = {
            "land": drone.land,
            "return_to_home": drone.return_to_home,
            "get_telemetry": lambda: f"Güncel Telemetri: {drone.get_telemetry()}"
        }

        if action not in fonksiyon_haritasi:
            return f"Hata: Güvenlik katmanı '{action}' eylemini haritalayamadı."

        return fonksiyon_haritasi[action]()