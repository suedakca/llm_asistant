# simulator.py
import pygame
import math
import time
import threading

class DroneSimulator:
    def __init__(self):
        # Durum Değişkenleri (Fiziksel)
        self.x = 0.0          # Yatay Konum (metre)
        self.y = 0.0          # Dikey Konum / İrtifa (metre)
        self.vx = 0.0
        self.vy = 0.0
        self.theta = 0.0      # Eğim açısı (radyan, + saat yönü)
        self.omega = 0.0      # Açısal hız (rad/sn)

        # Hedef Değerler (Setpoints)
        self.target_x = 0.0
        self.target_y = 0.0

        # Sistem Parametreleri
        self.m = 1.5          # Kütle (kg)
        self.g = 9.81         # Yerçekimi ivmesi (m/s^2)
        self.I = 0.015        # Eylemsizlik momenti (kg*m^2)
        self.d = 0.25         # Rotor-merkez mesafesi (metre)

        # PID Parametreleri
        # 1. İrtifa PID (Yükseklik)
        self.kp_alt = 15.0
        self.ki_alt = 0.1
        self.kd_alt = 12.0
        self.alt_integral = 0.0
        self.last_alt_error = 0.0

        # 2. Konum PID (Yatay Pozisyon -> Hedef Eğim Açısı üretir)
        self.kp_pos = 0.12
        self.ki_pos = 0.0
        self.kd_pos = 0.35
        self.pos_integral = 0.0
        self.last_pos_error = 0.0

        # 3. Açı PID (Eğim Açısı -> Motor Diferansiyel İtkisi üretir)
        self.kp_ang = 6.0
        self.ki_ang = 0.0
        self.kd_ang = 4.5
        self.ang_integral = 0.0
        self.last_ang_error = 0.0

        # İletişim ve Kontrol Bayrakları
        self.in_air = False
        self.failsafe = False
        self.checklist_completed = False
        self.battery = 100.0
        self.mode = "DISARMED"
        self.wind_speed = 15.0
        self.running = True

        # Rüzgar Simülasyonu
        self.wind_force_x = 0.0

    def update_physics(self, dt):
        if self.failsafe:
            # Failsafe durumunda motorlar kesilir, yerçekimi etkisinde düşer
            ay = -self.g
            ax = self.wind_force_x / self.m
            alpha = 0.0
            self.vy += ay * dt
            self.vx += ax * dt
            self.y = max(0.0, self.y + self.vy * dt)
            self.x += self.vx * dt
            self.theta += self.omega * dt
            self.omega += alpha * dt
            if self.y == 0.0:
                self.vy = 0.0
                self.vx = 0.0
                self.omega = 0.0
                self.theta = 0.0
            return

        # Araç yerde ve kalkış komutu yoksa: park halinde tut.
        # Aksi halde rüzgar kuvveti motorlar kapalıyken bile aracı sürükler.
        if not self.in_air and self.target_y <= 0.0 and self.y <= 0.0:
            self.y = 0.0
            self.vx = 0.0
            self.vy = 0.0
            self.omega = 0.0
            self.theta = 0.0
            self.wind_force_x = 0.0
            return

        # Rüzgarın İHA'ya yatay etkisi (basit kuvvet)
        self.wind_force_x = (self.wind_speed * 0.05) * math.sin(time.time() * 0.5)

        # 1. İRTİFA KONTROLÜ (Dikey itki hesaplama)
        alt_error = self.target_y - self.y
        self.alt_integral += alt_error * dt
        self.alt_integral = max(-10.0, min(10.0, self.alt_integral))
        alt_derivative = (alt_error - self.last_alt_error) / dt if dt > 0 else 0.0
        self.last_alt_error = alt_error

        # Yerçekimini dengeleyecek temel itki (Feedforward) + PID düzeltmesi
        total_thrust = (self.m * self.g) + (self.kp_alt * alt_error + self.ki_alt * self.alt_integral + self.kd_alt * alt_derivative)
        total_thrust = max(0.0, min(30.0, total_thrust)) # Motor itiş limiti (Maks 30 Newton)

        # Havada değilse ve hedef yükseklik sıfırsa motorları tamamen kapat
        if not self.in_air and self.target_y == 0.0:
            total_thrust = 0.0

        # 2. YATAY KONUM KONTROLÜ (Hedef Eğim Açısı)
        pos_error = self.target_x - self.x
        self.pos_integral += pos_error * dt
        self.pos_integral = max(-5.0, min(5.0, self.pos_integral))
        pos_derivative = (pos_error - self.last_pos_error) / dt if dt > 0 else 0.0
        self.last_pos_error = pos_error

        # Hedef eğim açısını (radyan) hesapla ve sınırla (Maksimum ±18 derece)
        target_theta = self.kp_pos * pos_error + self.ki_pos * self.pos_integral + self.kd_pos * pos_derivative
        target_theta = max(-0.3, min(0.3, target_theta))

        # Havada değilse eğim yapma
        if not self.in_air:
            target_theta = 0.0

        # 3. AÇI KONTROLÜ (Motor diferansiyel itkisi / tork hesaplama)
        ang_error = target_theta - self.theta
        self.ang_integral += ang_error * dt
        self.ang_integral = max(-1.0, min(1.0, self.ang_integral))
        ang_derivative = (ang_error - self.last_ang_error) / dt if dt > 0 else 0.0
        self.last_ang_error = ang_error

        torque = self.kp_ang * ang_error + self.ki_ang * self.ang_integral + self.kd_ang * ang_derivative
        torque = max(-5.0, min(5.0, torque)) # Maks tork sınırı

        # Motor İtme Kuvvetlerinin Ayrıştırılması
        # T_L: Sol Motor, T_R: Sağ Motor
        T_L = total_thrust / 2.0 - torque / (2.0 * self.d)
        T_R = total_thrust / 2.0 + torque / (2.0 * self.d)

        # Negatif itkiyi engelle
        T_L = max(0.0, T_L)
        T_R = max(0.0, T_R)

        # Net Kuvvet ve İvmeler
        net_thrust = T_L + T_R
        ax = (net_thrust * math.sin(self.theta) + self.wind_force_x) / self.m
        ay = (net_thrust * math.cos(self.theta) - self.m * self.g) / self.m
        alpha = (T_R - T_L) * self.d / self.I

        # Euler İntegrasyonu ile durum güncelleme
        self.vx += ax * dt
        self.vy += ay * dt
        self.omega += alpha * dt

        self.x += self.vx * dt
        self.y += self.vy * dt
        self.theta += self.omega * dt

        # Sınır Kontrolleri (Yere çarpma)
        if self.y <= 0.0:
            self.y = 0.0
            self.vy = 0.0
            self.vx = 0.0
            self.theta = 0.0
            self.omega = 0.0

    def run_pygame(self):
        pygame.init()
        screen = pygame.display.set_mode((800, 600))
        pygame.display.set_caption("2B Fizik Motorlu İHA Simülatörü")
        clock = pygame.time.Clock()

        # Renkler
        BG_COLOR = (30, 30, 40)
        WHITE = (240, 240, 240)
        GREEN = (46, 204, 113)
        RED = (231, 76, 60)
        BLUE = (52, 152, 219)
        ORANGE = (230, 126, 34)

        font = pygame.font.SysFont("Courier", 16)

        while self.running:
            # Pygame olaylarını işle
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False

            dt = clock.tick(60) / 1000.0  # 60 FPS
            if dt > 0.1: dt = 0.1 # Aşırı gecikme koruması

            # Fiziği Güncelle
            self.update_physics(dt)

            # Ekranı temizle
            screen.fill(BG_COLOR)

            # 1. Koordinat Dönüşümleri (Metre -> Piksel)
            # Simülasyon x: [-60, 60] -> Ekran x: [400 - 300, 400 + 300] (5 piksel/metre)
            # Simülasyon y: [0, 55] -> Ekran y: [500'den yukarıya] (8 piksel/metre)
            scale_x = 5.0
            scale_y = 8.0
            
            drone_px = 400 + int(self.x * scale_x)
            drone_py = 500 - int(self.y * scale_y)

            target_px = 400 + int(self.target_x * scale_x)
            target_py = 500 - int(self.target_y * scale_y)

            # Yer çizgisi (Ground)
            pygame.draw.line(screen, WHITE, (50, 500), (750, 500), 3)

            # Geofence sanal sınırları (Maks ±50m)
            pygame.draw.line(screen, RED, (400 - int(50*scale_x), 100), (400 - int(50*scale_x), 500), 2) # Sol sınır
            pygame.draw.line(screen, RED, (400 + int(50*scale_x), 100), (400 + int(50*scale_x), 500), 2) # Sağ sınır

            # Hedef Konum Göstergesi (Target Cross)
            if self.in_air or self.target_y > 0.0:
                pygame.draw.line(screen, GREEN, (target_px - 8, target_py), (target_px + 8, target_py), 2)
                pygame.draw.line(screen, GREEN, (target_px, target_py - 8), (target_px, target_py + 8), 2)
                pygame.draw.circle(screen, GREEN, (target_px, target_py), 10, 1)

            # 2. Drone'u Çiz (Açıya Göre Döndürülmüş Gövde)
            # Drone kol genişliği: 2 * d (yaklaşık 50 piksel)
            arm_length = int(self.d * 2.0 * scale_x)
            
            # Eğim açısı (theta) ile uç noktaları hesapla
            cos_t = math.cos(-self.theta) # Pygame y-ekseni ters olduğu için eksi alıyoruz
            sin_t = math.sin(-self.theta)

            left_x = drone_px - int(arm_length * cos_t)
            left_y = drone_py - int(arm_length * sin_t)
            right_x = drone_px + int(arm_length * cos_t)
            right_y = drone_py + int(arm_length * sin_t)

            # Gövdeyi çiz
            pygame.draw.line(screen, BLUE, (left_x, left_y), (right_x, right_y), 4) # Ana kol
            pygame.draw.circle(screen, WHITE, (drone_px, drone_py), 8) # Merkez gövde

            # Motorları/Pervaneleri çiz
            pygame.draw.line(screen, ORANGE, (left_x - 12, left_y - 4), (left_x + 12, left_y - 4), 2) # Sol pervane
            pygame.draw.line(screen, ORANGE, (right_x - 12, right_y - 4), (right_x + 12, right_y - 4), 2) # Sağ pervane
            pygame.draw.circle(screen, RED, (left_x, left_y), 4)
            pygame.draw.circle(screen, RED, (right_x, right_y), 4)

            # 3. Bilgi Panelini Çiz
            texts = [
                f"=== İHA CANLI FİZİK TELEMETRİSİ ===",
                f"Modu        : {self.mode}",
                f"Konum X     : {self.x:.2f} m",
                f"İrtifa (Y)  : {self.y:.2f} m",
                f"Yatay Hız   : {self.vx:.2f} m/s",
                f"Dikey Hız   : {self.vy:.2f} m/s",
                f"Açı (Theta) : {math.degrees(self.theta):.1f}°",
                f"Batarya     : %{self.battery:.1f}",
                f"Checklist   : {'TAMAM' if self.checklist_completed else 'BEKLİYOR'}",
                f"Rüzgar Hızı : {self.wind_speed:.1f} km/s (Yönü Değişken)",
                f"Failsafe    : {'KİLİTLİ' if self.failsafe else 'AKTİF DEĞİL'}"
            ]

            y_offset = 20
            for text_line in texts:
                img = font.render(text_line, True, WHITE)
                screen.blit(img, (20, y_offset))
                y_offset += 20

            pygame.display.flip()

        pygame.quit()

# Global simülatör nesnesi
global_simulator = DroneSimulator()

def start_simulator_thread():
    t = threading.Thread(target=global_simulator.run_pygame, daemon=True)
    t.start()
    return global_simulator
