# drone.py
import time

try:
    from simulator import global_simulator
    SIMULATOR_AVAILABLE = True
except ImportError:
    SIMULATOR_AVAILABLE = False

try:
    from pymavlink import mavutil
    MAVLINK_AVAILABLE = True
except ImportError:
    MAVLINK_AVAILABLE = False

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
        self.checklist_completed = False
        self._battery_debt = 0.0  # kesirli tüketim birikimi
        self.sim = global_simulator if SIMULATOR_AVAILABLE else None

        if drone_config and "battery_drain_per_second" in drone_config:
            self.drain_rate = float(drone_config["battery_drain_per_second"])
        else:
            self.drain_rate = 0.5

        if drone_config and "simulated_wind_speed" in drone_config:
            self.wind_speed = float(drone_config["simulated_wind_speed"])
        else:
            self.wind_speed = 15.0

        self.mavlink_enabled = drone_config.get("mavlink_enabled", False) if drone_config else False
        self.mavlink_conn = None
        if self.mavlink_enabled:
            if MAVLINK_AVAILABLE:
                connection_string = drone_config.get("mavlink_connection_string", "udpin:localhost:14540")
                try:
                    print(f"🔗 [MAVLINK] {connection_string} adresine bağlanılıyor...")
                    self.mavlink_conn = mavutil.mavlink_connection(connection_string)
                    self.mavlink_conn.wait_heartbeat(timeout=2.0)
                    print("✅ [MAVLINK] Bağlantı başarılı! Kalp atışı (heartbeat) alındı.")
                except Exception as e:
                    print(f"⚠️ [MAVLINK BAĞLANTI UYARISI]: {e}. Yerel simülasyona geçildi.")
                    self.mavlink_enabled = False
            else:
                print("⚠️ [MAVLINK UYARISI]: 'pymavlink' kütüphanesi yüklü değil! Yerel simülasyona geçildi.")
                self.mavlink_enabled = False

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

    def _recv_mavlink_telemetry(self):
        if not (self.mavlink_enabled and self.mavlink_conn):
            return
        try:
            while True:
                msg = self.mavlink_conn.recv_msg()
                if not msg:
                    break
                msg_type = msg.get_type()
                if msg_type == "GLOBAL_POSITION_INT":
                    self.altitude = float(msg.relative_alt) / 1000.0
                elif msg_type == "HEARTBEAT":
                    self.in_air = self.altitude > 0.5
                elif msg_type == "SYS_STATUS":
                    self.battery = msg.battery_remaining
                elif msg_type == "LOCAL_POSITION_NED":
                    self.y = float(msg.x)  # North
                    self.x = float(msg.y)  # East
        except Exception:
            pass

    def get_telemetry(self):
        if self.mavlink_enabled:
            self._recv_mavlink_telemetry()
        else:
            if self.sim:
                # Sync simulated physics state to local attributes
                self.x = self.sim.x
                self.y = 0.0  # Yatay kuzey/güney 2B simülatörde kullanılmıyor
                self.altitude = self.sim.y
                self.in_air = self.sim.in_air

                # Sync control states back to the simulator
                self.sim.battery = float(self.battery)
                self.sim.checklist_completed = self.checklist_completed
                self.sim.failsafe = self.failsafe_active
                self.sim.mode = self.mode
                self.sim.wind_speed = self.wind_speed

        self._update_battery_consumption()
        return {
            "x": self.x,
            "y": self.y,
            "altitude": self.altitude,
            "mode": self.mode,
            "battery": self.battery,
            "in_air": self.in_air,
            "failsafe": self.failsafe_active,
            "checklist_completed": self.checklist_completed,
            "wind_speed": self.wind_speed
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
        self.checklist_completed = False
        self.mode = "DISARMED"
        self.battery = 100
        self.takeoff_time = None
        self._battery_debt = 0.0
        return "Sistem başarıyla yeniden başlatıldı (REBOOT). Kilit kaldırıldı. Kontrol listesi sıfırlandı."

    def takeoff(self, target_altitude):
        if self.failsafe_active: return "Hata: Sistem Failsafe modunda kilitli!"
        
        if self.in_air:
            self.altitude = target_altitude
            if not self.mavlink_enabled and self.sim:
                self.sim.target_y = float(target_altitude)
            self.battery = max(0, self.battery - 5)
            if self.battery <= 0 and not self.failsafe_active:
                self.emergency_stop()
                return "[FAILSAFE AKTİF] İrtifa güncellemesi esnasında batarya tükendi, sistem kilitlendi."
            return f"Başarılı: İrtifa {target_altitude} metreye güncellendi."
            
        if self.mavlink_enabled and self.mavlink_conn:
            try:
                # ARM & TAKEOFF
                self.mavlink_conn.mav.command_long_send(
                    self.mavlink_conn.target_system, self.mavlink_conn.target_component,
                    mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 0,
                    1, 0, 0, 0, 0, 0, 0)
                self.mavlink_conn.mav.command_long_send(
                    self.mavlink_conn.target_system, self.mavlink_conn.target_component,
                    mavutil.mavlink.MAV_CMD_NAV_TAKEOFF, 0,
                    0, 0, 0, 0, 0, 0, float(target_altitude))
            except Exception as e:
                print(f"[MAVLINK HATA] Takeoff paketi gönderilemedi: {e}")

        if not self.mavlink_enabled and self.sim:
            self.sim.target_y = float(target_altitude)
            self.sim.in_air = True

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
        if self.mavlink_enabled and self.mavlink_conn:
            try:
                self.mavlink_conn.mav.command_long_send(
                    self.mavlink_conn.target_system, self.mavlink_conn.target_component,
                    mavutil.mavlink.MAV_CMD_NAV_LAND, 0,
                    0, 0, 0, 0, 0, 0, 0)
            except Exception as e:
                print(f"[MAVLINK HATA] Land paketi gönderilemedi: {e}")

        if not self.mavlink_enabled and self.sim:
            self.sim.target_y = 0.0
            self.sim.target_x = 0.0

        self.battery = max(0, self.battery - 3)
        self.altitude = 0.0
        self.in_air = False
        self.mode = "LAND"
        self.takeoff_time = None
        self._battery_debt = 0.0
        self.checklist_completed = False

        if self.battery <= 0:
            print("\n[KRİTİK GÜVENLİK SİSTEMİ] İNİŞ ESNASINDA BATARYA %0! MOTOR KESİLDİ!")
            self.emergency_stop()
            return "Başarılı: İniş gerçekleştirildi ancak batarya tamamen tükendi (Motor Kesildi). Kontrol listesi sıfırlandı."

        return "Başarılı: İniş gerçekleştirildi. Bir sonraki kalkış için kontrol listesini tekrar onaylamalısınız."

    def return_to_home(self):
        if self.failsafe_active: return "Hata: Sistem Failsafe modunda kilitli!"
        self._update_battery_consumption()
        if self.failsafe_active: return "[FAILSAFE AKTİF] Eve dönüş esnasında batarya tükendi, sistem kilitlendi."

        if self.mavlink_enabled and self.mavlink_conn:
            try:
                self.mavlink_conn.mav.command_long_send(
                    self.mavlink_conn.target_system, self.mavlink_conn.target_component,
                    mavutil.mavlink.MAV_CMD_NAV_RETURN_TO_LAUNCH, 0,
                    0, 0, 0, 0, 0, 0, 0)
            except Exception as e:
                print(f"[MAVLINK HATA] RTL paketi gönderilemedi: {e}")

        if not self.mavlink_enabled and self.sim:
            self.sim.target_x = self.home_x
            self.sim.target_y = 0.0

        self.battery = max(0, self.battery - 10)
        self.x = self.home_x
        self.y = self.home_y
        self.altitude = 0.0
        self.in_air = False
        self.mode = "RTL_LAND"
        self.takeoff_time = None
        self._battery_debt = 0.0
        self.checklist_completed = False

        if self.battery <= 0:
            print("\n🚨🚨🚨 [KRİTİK GÜVENLİK SİSTEMİ] EVE DÖNÜŞ ESNASINDA BATARYA %0! MOTOR KESİLDİ!")
            self.emergency_stop()
            return f"Başarılı: Başlangıç konumuna dönüldü ({self.home_x}, {self.home_y}) ancak batarya tamamen tükendi (Sistem Kilitlendi). Kontrol listesi sıfırlandı."

        return f"Başarılı: Başlangıç konumuna dönüldü ({self.x}, {self.y}) ve güvenli iniş tamamlandı. Bir sonraki kalkış için kontrol listesini tekrar onaylamalısınız."

    def move(self, direction, distance):
        if self.failsafe_active: return "Hata: Sistem Failsafe modunda kilitli!"
        self._update_battery_consumption()
        if self.failsafe_active: return "[FAILSAFE AKTİF] Hareket esnasında batarya tükendi, sistem kilitlendi."
        self.battery = max(0, self.battery - 2)
        if self.battery <= 0 and not self.failsafe_active:
            self.emergency_stop()
            return "[FAILSAFE AKTİF] Hareket esnasında batarya tükendi, sistem kilitlendi."

        if self.mavlink_enabled and self.mavlink_conn:
            try:
                n_offset = 0.0
                e_offset = 0.0
                if direction in ["kuzey", "north", "ileri"]: n_offset = distance
                elif direction in ["güney", "south", "geri"]: n_offset = -distance
                elif direction in ["doğu", "east", "sağ"]: e_offset = distance
                elif direction in ["batı", "west", "sol"]: e_offset = -distance
                
                self.mavlink_conn.mav.set_position_target_local_ned_send(
                    0,
                    self.mavlink_conn.target_system, self.mavlink_conn.target_component,
                    mavutil.mavlink.MAV_FRAME_LOCAL_OFFSET_NED,
                    0b110111111000,
                    float(n_offset), float(e_offset), 0.0,
                    0.0, 0.0, 0.0,
                    0.0, 0.0, 0.0,
                    0.0, 0.0
                )
            except Exception as e:
                print(f"[MAVLINK HATA] Move paketi gönderilemedi: {e}")

        if not self.mavlink_enabled and self.sim:
            # 2D düzlemde yatay hareketleri simülatörün x hedefine yönlendir
            if direction in ["kuzey", "north", "ileri", "doğu", "east", "sağ"]:
                self.sim.target_x += float(distance)
            elif direction in ["güney", "south", "geri", "batı", "west", "sol"]:
                self.sim.target_x -= float(distance)

        distance = float(distance)
        direction = direction.lower()

        if direction in ["kuzey", "north", "ileri"]: self.y += distance
        elif direction in ["güney", "south", "geri"]: self.y -= distance
        elif direction in ["doğu", "east", "sağ"]: self.x += distance
        elif direction in ["batı", "west", "sol"]: self.x -= distance
        else: return f"Hata: Geçersiz yön: {direction}"

        return f"Başarılı: {direction.upper()} yönünde {distance} metre ilerlendi."