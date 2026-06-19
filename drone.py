# drone.py

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

    def get_telemetry(self):
        return {
            "x": self.x,
            "y": self.y,
            "altitude": self.altitude,
            "mode": self.mode,
            "battery": self.battery,
            "in_air": self.in_air
        }

    def takeoff(self, target_altitude):
        if self.in_air:
            return "Hata: Araç zaten havada!"
        self.in_air = True
        self.altitude = target_altitude
        self.mode = "GUIDED"
        self.battery = max(0, self.battery - 5) # Asla 0'ın altına düşmez
        return f"Başarılı: {target_altitude} metreye kalkış yapıldı. Mod: {self.mode}"

    def land(self):
        if not self.in_air:
            return "Hata: Araç zaten yerde!"
        self.altitude = 0.0
        self.in_air = False
        self.mode = "LAND"
        self.battery = max(0, self.battery - 3) # Asla 0'ın altına düşmez
        return "Başarılı: İniş gerçekleştirildi. Motorlar durduruldu."

    def return_to_home(self):
        if not self.in_air:
            return "Hata: Yerdeyken RTH yapılamaz!"
        self.x = self.home_x
        self.y = self.home_y
        self.mode = "RTL"
        self.battery = max(0, self.battery - 10) # Asla 0'ın altına düşmez
        return f"Başarılı: Başlangıç konumuna dönüldü ({self.x}, {self.y}). İniş bekleniyor."