# drone.py
import time

class Drone:
    def __init__(self):
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

    def get_telemetry(self):
        """ Bataryayı mükerrer düşürmeyen kararlı zamanlayıcı """
        if self.in_air and self.takeoff_time is not None:
            gecen_sure = time.time() - self.takeoff_time
            zaman_tuketimi = int(gecen_sure * 0.5) 
            if zaman_tuketimi > 0:
                self.battery = max(0, self.battery - zaman_tuketimi)
                # Sadece batarya düştüğünde zamanı güncelle, anlık çağrılar etkilemesin
                self.takeoff_time = time.time() 

        return {
            "x": self.x,
            "y": self.y,
            "altitude": self.altitude,
            "mode": self.mode,
            "battery": self.battery,
            "in_air": self.in_air,
            "failsafe": self.failsafe_active
        }

    def emergency_stop(self):
        self.failsafe_active = True
        self.altitude = 0.0
        self.in_air = False
        self.mode = "EMERGENCY_LAND"
        return "🚨🚨🚨 [FAILSAFE AKTİF] Motor kesildi! Sistem kilitlendi."

    def reboot(self):
        """ [ÇÖZÜM 3] Sistemi yeniden başlatıp kilidi kaldırır """
        if self.in_air:
            return "Hata: Havada iken yeniden başlatma (reboot) yapılamaz!"
        self.failsafe_active = False
        self.mode = "DISARMED"
        self.battery = 100 # Simülasyon gereği batarya yenilensin
        return "🔄 Sistem başarıyla yeniden başlatıldı (REBOOT). Kilit kaldırıldı."

    def takeoff(self, target_altitude):
        if self.failsafe_active: return "Hata: Sistem Failsafe modunda kilitli!"
        self.in_air = True 
        self.altitude = target_altitude
        self.mode = "GUIDED" 
        self.takeoff_time = time.time() 
        return f"Başarılı: {target_altitude} metreye kalkış yapıldı."

    def land(self):
        """ [ÇÖZÜM 2] İçerideki gereksiz in_air kontrolü temizlendi """
        if self.failsafe_active: return "Hata: Sistem Failsafe modunda kilitli!"
        self.get_telemetry()
        self.altitude = 0.0
        self.in_air = False 
        self.mode = "LAND" 
        self.takeoff_time = None 
        return "Başarılı: İniş gerçekleştirildi."

    def return_to_home(self):
        """ [ÇÖZÜM 2] İçerideki gereksiz in_air kontrolü temizlendi """
        if self.failsafe_active: return "Hata: Sistem Failsafe modunda kilitli!"
        self.get_telemetry() 
        self.x = self.home_x
        self.y = self.home_y
        self.mode = "RTL"
        return f"Başarılı: Başlangıç konumuna dönüldü ({self.x}, {self.y})."

    def move(self, direction, distance):
        if self.failsafe_active: return "Hata: Sistem Failsafe modunda kilitli!"
        self.get_telemetry() 
        distance = float(distance)
        direction = direction.lower()

        if direction in ["kuzey", "north", "yukarı", "ileri"]: self.y += distance
        elif direction in ["güney", "south", "aşağı", "geri"]: self.y -= distance
        elif direction in ["doğu", "east", "sağ"]: self.x += distance
        elif direction in ["batı", "west", "sol"]: self.x -= distance
        else: return f"Hata: Geçersiz yön: {direction}"

        return f"Başarılı: {direction.upper()} yönünde {distance} metre ilerlendi."