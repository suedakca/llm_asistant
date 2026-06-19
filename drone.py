# drone.py
import time

class Drone:
    def __init__(self, drone_config=None):
        self.x = 0.0          
        self.y = 0.0          
        self.altitude = 0.0   
        self.mode = "DISARMED"
        self.battery = 100    
        self.in_air = False   
        self.home_x = 0.0
        self.home_y = 0.0
        self.takeoff_time = None 
        self.failsafe_active = False
        self._battery_debt = 0.0  # kesirli tüketim birikimi

        if drone_config and "battery_drain_per_second" in drone_config:
            self.drain_rate = float(drone_config["battery_drain_per_second"])
        else:
            self.drain_rate = 0.5

    def _update_battery_consumption(self):
        if self.in_air and self.takeoff_time is not None:
            gecen_sure = time.time() - self.takeoff_time
            self.takeoff_time = time.time()

            self._battery_debt += gecen_sure * self.drain_rate
            tam_tuketim = int(self._battery_debt)
            if tam_tuketim > 0:
                self._battery_debt -= tam_tuketim
                self.battery = max(0, self.battery - tam_tuketim)

                if self.battery <= 0 and not self.failsafe_active:
                    print("\n🚨🚨🚨 [KRİTİK GÜVENLİK SİSTEMİ] BATARYA %0! MOTOR KESİLDİ!")
                    self.emergency_stop()

    def get_telemetry(self):
        self._update_battery_consumption()
        return {
            "x": self.x,
            "y": self.y,
            "altitude": self.altitude,
            "mode": self.mode,
            "battery": self.battery,
            "in_air": self.in_air,
            "failsafe": self.failsafe_active
        }

    def set_home(self, new_x, new_y):
        """ [DÜZELTME 1] Pilotun yeni kalkış/ev noktası belirlemesini sağlar """
        if self.failsafe_active: return "Hata: Sistem Failsafe modunda kilitli!"
        if self.in_air: return "Hata: Havada iken ev konumu (Home) değiştirilemez! Önce inmeniz gerekir."
        
        self.home_x = float(new_x)
        self.home_y = float(new_y)
        return f"Başarılı: Yeni ev konumu (Home) ayarlandı -> (X: {self.home_x}, Y: {self.home_y})"

    def emergency_stop(self):
        self.failsafe_active = True
        self.altitude = 0.0
        self.in_air = False
        self.mode = "EMERGENCY_LAND"
        self._battery_debt = 0.0
        return "[FAILSAFE AKTİF] Motor kesildi! İHA yere indirildi ve sistem kilitlendi."

    def reboot(self):
        if self.in_air:
            return "Hata: Havada iken yeniden başlatma (reboot) yapılamaz!"
        self.failsafe_active = False
        self.mode = "DISARMED"
        self.battery = 100 
        return "Sistem başarıyla yeniden başlatıldı (REBOOT). Kilit kaldırıldı."

    def takeoff(self, target_altitude):
        if self.failsafe_active: return "Hata: Sistem Failsafe modunda kilitli!"
        
        if self.in_air:
            self.altitude = target_altitude
            return f"Başarılı: İrtifa {target_altitude} metreye güncellendi."
            
        self.in_air = True 
        self.altitude = target_altitude
        self.mode = "GUIDED" 
        self.battery = max(0, self.battery - 5) 
        self.takeoff_time = time.time() 
        return f"Başarılı: {target_altitude} metreye ilk kalkış yapıldı."

    def land(self):
        if self.failsafe_active: return "Hata: Sistem Failsafe modunda kilitli!"
        self._update_battery_consumption()
        if self.failsafe_active: return "[FAILSAFE AKTİF] İniş esnasında batarya tükendi, sistem kilitlendi."
        self.battery = max(0, self.battery - 3)
        self.altitude = 0.0
        self.in_air = False
        self.mode = "LAND"
        self.takeoff_time = None
        self._battery_debt = 0.0

        if self.battery <= 0:
            print("\n[KRİTİK GÜVENLİK SİSTEMİ] İNİŞ ESNASINDA BATARYA %0! MOTOR KESİLDİ!")
            self.emergency_stop()
            return "Başarılı: İniş gerçekleştirildi ancak batarya tamamen tükendi (Motor Kesildi)."

        return "Başarılı: İniş gerçekleştirildi."

    def return_to_home(self):
        if self.failsafe_active: return "Hata: Sistem Failsafe modunda kilitli!"
        self._update_battery_consumption()
        if self.failsafe_active: return "[FAILSAFE AKTİF] Eve dönüş esnasında batarya tükendi, sistem kilitlendi."

        self.battery = max(0, self.battery - 10)
        self.x = self.home_x
        self.y = self.home_y
        self.altitude = 0.0
        self.in_air = False
        self.mode = "RTL_LAND"
        self.takeoff_time = None
        self._battery_debt = 0.0

        if self.battery <= 0:
            print("\n🚨🚨🚨 [KRİTİK GÜVENLİK SİSTEMİ] EVE DÖNÜŞ ESNASINDA BATARYA %0! MOTOR KESİLDİ!")
            self.emergency_stop()
            return f"Başarılı: Başlangıç konumuna dönüldü ({self.home_x}, {self.home_y}) ancak batarya tamamen tükendi (Sistem Kilitlendi)."

        return f"Başarılı: Başlangıç konumuna dönüldü ({self.x}, {self.y}) ve güvenli iniş tamamlandı."

    def move(self, direction, distance):
        if self.failsafe_active: return "Hata: Sistem Failsafe modunda kilitli!"
        self._update_battery_consumption()
        if self.failsafe_active: return "[FAILSAFE AKTİF] Hareket esnasında batarya tükendi, sistem kilitlendi."
        self.battery = max(0, self.battery - 2)
        
        distance = float(distance)
        direction = direction.lower()

        if direction in ["kuzey", "north", "ileri"]: self.y += distance
        elif direction in ["güney", "south", "geri"]: self.y -= distance
        elif direction in ["doğu", "east", "sağ"]: self.x += distance
        elif direction in ["batı", "west", "sol"]: self.x -= distance
        else: return f"Hata: Geçersiz yön: {direction}"

        return f"Başarılı: {direction.upper()} yönünde {distance} metre ilerlendi."