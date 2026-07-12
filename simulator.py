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
        self.kd_alt = 8.0
        self.alt_integral = 0.0
        self.last_alt_error = 0.0

        # 2. Konum PID (Yatay Pozisyon -> Hedef Eğim Açısı üretir)
        self.kp_pos = 0.15
        self.ki_pos = 0.0
        self.kd_pos = 0.4
        self.pos_integral = 0.0
        self.last_pos_error = 0.0

        # 3. Açı PID (Eğim Açısı -> Motor Diferansiyel İtkisi üretir)
        self.kp_ang = 8.0
        self.ki_ang = 0.0
        self.kd_ang = 0.5
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

        # GUI & Kontrol Arayüzü Değişkenleri
        self.drone = None
        self.security = None
        self.assistant = None
        self.logger = None
        self.config = None
        self.session_id = None
        
        self.input_text = ""
        self.input_mode = "keyboard"  # 'keyboard' veya 'voice'
        self.status_message = "HAZIR"
        self.gui_logs = []
        self.is_textbox_focused = False
        self.cursor_timer = 0.0
        
        self.emergency_words = []
        self.high_risk_list = []
        self.trail_history = []
        self.propeller_angle = 0.0

    def init_gui_control(self, drone, security, assistant, logger, config, session_id):
        self.drone = drone
        self.security = security
        self.assistant = assistant
        self.logger = logger
        self.config = config
        self.session_id = session_id
        
        if config:
            self.emergency_words = config.get("safety_settings", {}).get("emergency_keywords", ["ABORT", "MOTORU KES", "ACİL DURDURMA", "STOP"])
            self.high_risk_list = config.get("llm_settings", {}).get("high_risk_actions", ["takeoff", "move", "set_home"])
        else:
            self.emergency_words = ["ABORT", "MOTORU KES", "ACİL DURDURMA", "STOP"]
            self.high_risk_list = ["takeoff", "move", "set_home"]
            
        self.add_gui_log("Sistem Kontrol Paneli Aktif.")

    def add_gui_log(self, text):
        print(f"[LOG] {text}")
        self.gui_logs.append(text)
        if len(self.gui_logs) > 30:
            self.gui_logs.pop(0)

    def execute_command_async(self, command_text):
        if not command_text.strip():
            return
        self.status_message = "Isleniyor..."
        self.add_gui_log(f"Pilot: {command_text}")
        threading.Thread(target=self._execute_command_worker, args=(command_text,), daemon=True).start()

    def _execute_command_worker(self, user_command):
        try:
            # Acil durdurma — LLM'i bypass eder
            if user_command.upper() in self.emergency_words:
                sonuc = self.drone.emergency_stop()
                self.add_gui_log(f"Sistem: {sonuc}")
                self.logger.log_action(self.session_id, user_command, "EMERGENCY_STOP", None, True, sonuc)
                self.status_message = "HAZIR"
                return

            # Failsafe kilitliyse yalnızca reboot'a izin ver
            current_telemetry = self.drone.get_telemetry()
            if current_telemetry["failsafe"]:
                self.add_gui_log("Asistan: Sistem kilitli! reboot yapın.")
                if user_command.lower() in ["sistemi yeniden başlat", "reboot"]:
                    sonuc = self.drone.reboot()
                    self.add_gui_log(f"Sistem: {sonuc}")
                    self.logger.log_action(self.session_id, user_command, "reboot", None, True, sonuc)
                self.status_message = "HAZIR"
                return

            self.status_message = "LLM Analiz..."
            parsed_intent_list = self.assistant.parse_command(user_command, current_telemetry)
            self.add_gui_log(f"Asistan: {len(parsed_intent_list)} gorev planlandi.")

            if parsed_intent_list and parsed_intent_list[0].get("action") in ["ambiguous", "invalid"]:
                self.add_gui_log("Asistan: Komut anlasilamadi.")
                self.logger.log_action(self.session_id, user_command, "Hata", None, False, "Gecersiz")
                self.status_message = "HAZIR"
                return

            # LLM 2: Gözlemci
            has_high_risk = any(cmd.get("action") in self.high_risk_list for cmd in parsed_intent_list)
            if has_high_risk:
                self.status_message = "Denetleniyor..."
                observer_audit = self.assistant.observe_and_verify(current_telemetry, parsed_intent_list)
                if observer_audit.get("decision") == "VETOED":
                    veto_reason = observer_audit.get('reason')
                    self.add_gui_log(f"Gozlemci Vetosu: {veto_reason}")
                    self.logger.log_action(self.session_id, user_command, "MULTI_ACTION", None, False, "LLM 2 Vetosu")
                    self.status_message = "HAZIR"
                    return

            # Yürütme motoru
            zincir_basarili = True
            gecici_sonuclar = []
            max_replans = 2
            replan_count = 0
            idx = 0

            while idx < len(parsed_intent_list):
                siradaki_gorev = parsed_intent_list[idx]
                act = siradaki_gorev.get("action")
                param = siradaki_gorev.get("parameter")
                self.add_gui_log(f"Islem: {act}")
                self.status_message = f"Eylem: {act}"

                if act == "reboot":
                    if self.drone.in_air:
                        self.add_gui_log("Guvenlik: Havada reboot yapilamaz!")
                        self.logger.log_action(self.session_id, user_command, "reboot", None, False, "Havada reboot")
                        zincir_basarili = False
                        break
                    sonuc = self.drone.reboot()
                    self.add_gui_log(f"Sistem: {sonuc}")
                    self.logger.log_action(self.session_id, user_command, "reboot", None, True, sonuc)
                    zincir_basarili = False
                    break

                guncel_telemetri = self.drone.get_telemetry()
                onay, sonuc = self.security.validate_and_execute(self.drone, act, param, telemetri=guncel_telemetri)
                
                # Visual feedback delay
                time.sleep(1.0)

                if onay:
                    self.add_gui_log(f"Basarili: {sonuc}")
                    gecici_sonuclar.append(sonuc)
                    self.logger.log_action(self.session_id, user_command, act, param, True, sonuc)
                    idx += 1
                else:
                    self.add_gui_log(f"Reddedildi: {sonuc}")
                    self.logger.log_action(self.session_id, user_command, act, param, False, f"Engellendi: {sonuc}")
                    
                    if replan_count < max_replans:
                        replan_count += 1
                        self.status_message = "Yeniden Planl..."
                        self.add_gui_log(f"Asistan yeni rota deniyor ({replan_count}/{max_replans})")
                        replan_prompt = f"GUVENLIK ENGELI: '{act}' eylemi '{sonuc}' nedeniyle guvenlik katmanina takildi. Lutfen bu engeli asacak veya en yakin guvenli alternatif rotayi/eylemi cizecek yeni bir gorev zinciri planla. Sadece yeni komut listesini JSON array formatinda don."
                        
                        try:
                            new_intent_list = self.assistant.parse_command(replan_prompt, self.drone.get_telemetry())
                            if new_intent_list and new_intent_list[0].get("action") not in ["invalid", "ambiguous"]:
                                self.add_gui_log("Yeni rota listesi alindi.")
                                parsed_intent_list = new_intent_list
                                idx = 0
                                continue
                        except Exception as re_err:
                            self.add_gui_log(f"Hata: {re_err}")
                    
                    self.add_gui_log("Planlama limitine ulasildi, zincir kesildi.")
                    zincir_basarili = False
                    break

            if zincir_basarili:
                self.add_gui_log("Asistan: Gorev zinciri tamamlandi.")
            
        except Exception as e:
            self.add_gui_log(f"Calistirma hatasi: {e}")
        finally:
            self.status_message = "HAZIR"

    def get_voice_input_async(self):
        self.status_message = "DINLENIYOR..."
        self.add_gui_log("Sistem: Mikrofon dinleniyor...")
        threading.Thread(target=self._voice_input_worker, daemon=True).start()

    def _voice_input_worker(self):
        try:
            import speech_recognition as sr
        except ImportError:
            self.add_gui_log("Hata: speech_recognition yuklu degil!")
            self.status_message = "HAZIR"
            return
            
        r = sr.Recognizer()
        try:
            mic = sr.Microphone()
        except Exception as e:
            self.add_gui_log(f"Mikrofon Hatasi: {e}")
            self.status_message = "HAZIR"
            return

        with mic as source:
            r.adjust_for_ambient_noise(source, duration=0.5)
            try:
                audio = r.listen(source, timeout=5, phrase_time_limit=15)
                self.status_message = "Ses isleniyor..."
                text = r.recognize_google(audio, language="tr-TR")
                self.execute_command_async(text)
            except sr.WaitTimeoutError:
                self.add_gui_log("Sistem: Zaman asimi (Ses algilanmadi)")
                self.status_message = "HAZIR"
            except sr.UnknownValueError:
                self.add_gui_log("Sistem: Ses anlasilmadi")
                self.status_message = "HAZIR"
            except sr.RequestError as e:
                self.add_gui_log(f"Sistem STT Hatasi: {e}")
                self.status_message = "HAZIR"

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
        # Hız bazlı sönümleme (D terimi için gürültüyü önler)
        alt_derivative = -self.vy
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
        # Hız bazlı sönümleme
        pos_derivative = -self.vx
        self.last_pos_error = pos_error

        # Hedef eğim açısını (radyan) hesapla ve sınırla (Maksimum ±18 derece)
        target_theta = -(self.kp_pos * pos_error + self.ki_pos * self.pos_integral + self.kd_pos * pos_derivative)
        target_theta = max(-0.3, min(0.3, target_theta))

        # Havada değilse eğim yapma
        if not self.in_air:
            target_theta = 0.0

        # 3. AÇI KONTROLÜ (Motor diferansiyel itkisi / tork hesaplama)
        ang_error = target_theta - self.theta
        self.ang_integral += ang_error * dt
        self.ang_integral = max(-1.0, min(1.0, self.ang_integral))
        # Açısal hız bazlı sönümleme (omega)
        ang_derivative = -self.omega
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
        ax = (-net_thrust * math.sin(self.theta) + self.wind_force_x) / self.m
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

        # Rota geçmişi ve pervane dönüş açısı güncelleme
        if not hasattr(self, "trail_history"):
            self.trail_history = []
        if not hasattr(self, "propeller_angle"):
            self.propeller_angle = 0.0

        # Pervaneleri döndür (eğer havada veya motorlar çalışıyorsa)
        # failsafe kilitliyken motorlar kapandığı için dönmez
        if (self.in_air or self.target_y > 0.0) and not self.failsafe:
            self.propeller_angle = (self.propeller_angle + 35.0 * dt) % (2.0 * math.pi)

        # Havada ise rota geçmişine konum ekle (maksimum 150 nokta)
        if self.in_air and self.y > 0.0:
            self.trail_history.append((self.x, self.y))
            if len(self.trail_history) > 150:
                self.trail_history.pop(0)

    def run_pygame(self):
        pygame.init()
        screen = pygame.display.set_mode((1200, 600))
        pygame.display.set_caption("2B Fizik Motorlu İHA Simülatörü ve Kontrol Paneli")
        clock = pygame.time.Clock()

        # Renkler
        BG_COLOR = (30, 30, 40)
        WHITE = (240, 240, 240)
        GREEN = (46, 204, 113)
        RED = (231, 76, 60)
        BLUE = (52, 152, 219)
        ORANGE = (230, 126, 34)
        
        # Sidebar Renkleri
        SIDEBAR_BG = (20, 20, 28)
        SIDEBAR_BORDER = (45, 45, 60)
        BTN_ACTIVE_BG = (52, 152, 219)
        BTN_INACTIVE_BG = (44, 62, 80)
        TEXTBOX_BG = (12, 12, 18)
        TEXTBOX_BORDER_FOCUSED = (52, 152, 219)
        TEXTBOX_BORDER_UNFOCUSED = (60, 60, 80)
        LOG_CONSOLE_BG = (10, 10, 14)

        # Fonts
        try:
            title_font = pygame.font.SysFont("Arial", 18, bold=True)
            status_font = pygame.font.SysFont("Arial", 14, bold=True)
            btn_font = pygame.font.SysFont("Arial", 13, bold=True)
            txt_font = pygame.font.SysFont("Arial", 14)
            telemetry_font = pygame.font.SysFont("Courier", 15, bold=True)
            log_font = pygame.font.SysFont("Courier", 12)
        except Exception:
            title_font = pygame.font.SysFont("Courier", 18, bold=True)
            status_font = pygame.font.SysFont("Courier", 14, bold=True)
            btn_font = pygame.font.SysFont("Courier", 13, bold=True)
            txt_font = pygame.font.SysFont("Courier", 14)
            telemetry_font = pygame.font.SysFont("Courier", 15, bold=True)
            log_font = pygame.font.SysFont("Courier", 12)

        # Button Rects
        btn_sesli = pygame.Rect(25, 90, 165, 38)
        btn_klavye = pygame.Rect(200, 90, 165, 38)
        textbox_rect = pygame.Rect(20, 170, 280, 38)
        btn_gonder = pygame.Rect(308, 170, 70, 38)
        btn_reboot = pygame.Rect(20, 498, 360, 34)
        btn_abort = pygame.Rect(20, 540, 360, 38)

        def draw_button(rect, text, base_color, text_color, hover=False, border_color=None):
            bg = tuple(max(0, min(255, c + 25)) for c in base_color) if hover else base_color
            pygame.draw.rect(screen, bg, rect, border_radius=6)
            if border_color or hover:
                b_color = border_color if border_color else (100, 180, 255)
                pygame.draw.rect(screen, b_color, rect, 2, border_radius=6)
            txt_sf = btn_font.render(text, True, text_color)
            txt_rect = txt_sf.get_rect(center=rect.center)
            screen.blit(txt_sf, txt_rect)

        # GCS Modern Colors
        DARK_BG = (10, 10, 14)
        CARD_BG = (20, 20, 28)
        CARD_BORDER = (45, 45, 60)
        NEON_CYAN = (0, 229, 255)
        NEON_GREEN = (0, 230, 118)
        NEON_RED = (255, 23, 68)
        NEON_ORANGE = (255, 145, 0)
        GRID_COLOR = (20, 20, 28)

        while self.running:
            dt = clock.tick(60) / 1000.0  # 60 FPS
            if dt > 0.1: dt = 0.1 # Aşırı gecikme koruması
            
            # Cursor blink timer
            self.cursor_timer = (self.cursor_timer + dt) % 1.0

            # Mouse positions
            mouse_pos = pygame.mouse.get_pos()
            hover_sesli = btn_sesli.collidepoint(mouse_pos)
            hover_klavye = btn_klavye.collidepoint(mouse_pos)
            hover_gonder = btn_gonder.collidepoint(mouse_pos)
            hover_reboot = btn_reboot.collidepoint(mouse_pos)
            hover_abort = btn_abort.collidepoint(mouse_pos)

            # Pygame olaylarını işle
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                elif event.type == pygame.MOUSEBUTTONDOWN:
                    if event.button == 1: # Left click
                        if btn_sesli.collidepoint(event.pos):
                            self.input_mode = "voice"
                            self.is_textbox_focused = False
                            self.get_voice_input_async()
                        elif btn_klavye.collidepoint(event.pos):
                            self.input_mode = "keyboard"
                            self.is_textbox_focused = True
                        elif textbox_rect.collidepoint(event.pos):
                            if self.input_mode == "keyboard":
                                self.is_textbox_focused = True
                        elif btn_gonder.collidepoint(event.pos):
                            if self.input_mode == "keyboard" and self.input_text.strip():
                                self.execute_command_async(self.input_text)
                                self.input_text = ""
                        elif btn_reboot.collidepoint(event.pos):
                            threading.Thread(target=self._run_reboot_worker, daemon=True).start()
                        elif btn_abort.collidepoint(event.pos):
                            sonuc = self.drone.emergency_stop()
                            self.add_gui_log(f"Sistem: {sonuc}")
                            self.logger.log_action(self.session_id, "ABORT", "EMERGENCY_STOP", None, True, sonuc)
                        else:
                            self.is_textbox_focused = False
                elif event.type == pygame.KEYDOWN:
                    if self.input_mode == "keyboard" and self.is_textbox_focused:
                        if event.key == pygame.K_RETURN:
                            if self.input_text.strip():
                                self.execute_command_async(self.input_text)
                                self.input_text = ""
                        elif event.key == pygame.K_BACKSPACE:
                            self.input_text = self.input_text[:-1]
                        else:
                            if event.unicode and event.unicode.isprintable():
                                self.input_text += event.unicode

            # Fiziği Güncelle
            self.update_physics(dt)

            # Ekranı temizle
            screen.fill(DARK_BG)

            # =================== L E F T   S I D E B A R   (GUI) ===================
            # Background
            pygame.draw.rect(screen, (15, 15, 22), (0, 0, 400, 600))
            pygame.draw.line(screen, (40, 40, 55), (400, 0), (400, 600), 2)

            # Card 1: Connection & Link Status
            card_1 = pygame.Rect(12, 12, 376, 126)
            pygame.draw.rect(screen, CARD_BG, card_1, border_radius=8)
            pygame.draw.rect(screen, CARD_BORDER, card_1, 1, border_radius=8)

            # Heartbeat flash LED
            heartbeat_flash = (time.time() * 3.0) % 2 < 1.0
            heartbeat_c = NEON_GREEN if heartbeat_flash else (0, 100, 40)
            pygame.draw.circle(screen, heartbeat_c, (32, 32), 5)
            if heartbeat_flash:
                pygame.draw.circle(screen, NEON_GREEN, (32, 32), 8, 1)

            title_lbl = title_font.render("İHA PİLOT BAĞLANTI LİNKİ", True, WHITE)
            screen.blit(title_lbl, (48, 22))

            # Signal strength bars
            for s_bar in range(4):
                pygame.draw.rect(screen, NEON_GREEN if s_bar < 3 else (60, 70, 60), (345 + s_bar*5, 33 - s_bar*3, 3, 3 + s_bar*3))

            status_title = status_font.render("DURUM:", True, (150, 150, 160))
            screen.blit(status_title, (28, 55))
            
            status_color = NEON_GREEN if self.status_message == "HAZIR" else (52, 152, 219)
            if "DINLENIYOR" in self.status_message or "Ses" in self.status_message:
                status_color = NEON_ORANGE
            elif "Hata" in self.status_message or "Reddedildi" in self.status_message:
                status_color = NEON_RED
                
            status_lbl = status_font.render(self.status_message, True, status_color)
            screen.blit(status_lbl, (84, 55))

            v_color = BTN_ACTIVE_BG if self.input_mode == "voice" else BTN_INACTIVE_BG
            draw_button(btn_sesli, "🎙️ Sesli Giriş", v_color, WHITE, hover_sesli, border_color=(255, 255, 255) if self.input_mode == "voice" else None)
            
            k_color = BTN_ACTIVE_BG if self.input_mode == "keyboard" else BTN_INACTIVE_BG
            draw_button(btn_klavye, "⌨️ Klavye Girişi", k_color, WHITE, hover_klavye, border_color=(255, 255, 255) if self.input_mode == "keyboard" else None)

            # Card 2: Command console input card
            card_2 = pygame.Rect(12, 150, 376, 68)
            pygame.draw.rect(screen, CARD_BG, card_2, border_radius=8)
            pygame.draw.rect(screen, CARD_BORDER, card_2, 1, border_radius=8)

            tb_border = NEON_CYAN if self.is_textbox_focused else CARD_BORDER
            pygame.draw.rect(screen, TEXTBOX_BG, textbox_rect, border_radius=6)
            pygame.draw.rect(screen, tb_border, textbox_rect, 1 if not self.is_textbox_focused else 2, border_radius=6)

            if self.input_text:
                disp_text = self.input_text
                if len(disp_text) > 28:
                    disp_text = "..." + disp_text[-25:]
                txt_color = WHITE if self.input_mode == "keyboard" else (130, 130, 140)
                txt_sf = txt_font.render(disp_text, True, txt_color)
                screen.blit(txt_sf, (30, 180))
                
                if self.is_textbox_focused and self.cursor_timer < 0.5:
                    cursor_x = 30 + txt_sf.get_width() + 2
                    pygame.draw.line(screen, WHITE, (cursor_x, 182), (cursor_x, 196), 2)
            else:
                placeholder = "Buraya komut girin..." if self.input_mode == "keyboard" else "(Klavye moduna geçin)"
                placeholder_lbl = txt_font.render(placeholder, True, (90, 90, 110))
                screen.blit(placeholder_lbl, (30, 180))
                
                if self.is_textbox_focused and self.cursor_timer < 0.5:
                    pygame.draw.line(screen, WHITE, (30, 182), (30, 196), 2)

            send_color = NEON_GREEN if self.input_mode == "keyboard" else (40, 50, 45)
            draw_button(btn_gonder, "Gönder", send_color, WHITE, hover_gonder and self.input_mode == "keyboard")

            # Card 3: Logs box
            card_3 = pygame.Rect(12, 230, 376, 216)
            pygame.draw.rect(screen, CARD_BG, card_3, border_radius=8)
            pygame.draw.rect(screen, CARD_BORDER, card_3, 1, border_radius=8)

            logs_title = title_font.render("TELSİZ VE SİSTEM EVENT GÜNLÜĞÜ", True, (150, 150, 170))
            screen.blit(logs_title, (25, 240))
            pygame.draw.rect(screen, LOG_CONSOLE_BG, (20, 265, 360, 170), border_radius=6)
            pygame.draw.rect(screen, (35, 35, 45), (20, 265, 360, 170), 1, border_radius=6)

            log_lines_to_show = []
            for raw_line in self.gui_logs:
                limit = 38
                if len(raw_line) > limit:
                    for i in range(0, len(raw_line), limit):
                        log_lines_to_show.append(raw_line[i:i+limit])
                else:
                    log_lines_to_show.append(raw_line)
            
            log_y = 272
            for wl in log_lines_to_show[-7:]:
                wl_color = (200, 200, 210)
                if wl.startswith("Pilot:"):
                    wl_color = (52, 152, 219)
                elif wl.startswith("Asistan:"):
                    wl_color = (241, 196, 15)
                elif wl.startswith("Sistem:") or wl.startswith("Reddedildi:") or wl.startswith("Hata:"):
                    wl_color = NEON_RED
                elif wl.startswith("Başarılı:") or wl.startswith("Onaylandı:"):
                    wl_color = NEON_GREEN

                lbl = log_font.render(wl, True, wl_color)
                screen.blit(lbl, (30, log_y))
                log_y += 22

            # Card 4: Failsafe actions
            card_4 = pygame.Rect(12, 458, 376, 130)
            pygame.draw.rect(screen, (28, 16, 20), card_4, border_radius=8)
            e_border = NEON_RED if self.failsafe else CARD_BORDER
            pygame.draw.rect(screen, e_border, card_4, 1, border_radius=8)

            danger_lbl = title_font.render("CRITICAL ACTION CONSOLE", True, NEON_RED)
            screen.blit(danger_lbl, (25, 468))

            draw_button(btn_reboot, "🔄 SİSTEMİ YENİDEN BAŞLAT (REBOOT)", (41, 128, 185), WHITE, hover_reboot)
            draw_button(btn_abort, "🚨 ACİL KİLİTLE / DURDUR (ABORT)", NEON_RED, WHITE, hover_abort)

            # =================== R I G H T   S I M U L A T O R   ===================
            # HUD coordinates factors
            scale_x = 5.0
            scale_y = 8.0
            
            drone_px = 800 + int(self.x * scale_x)
            drone_py = 500 - int(self.y * scale_y)

            target_px = 800 + int(self.target_x * scale_x)
            target_py = 500 - int(self.target_y * scale_y)

            # 1. HUD/CAD Grid Background
            for grid_x in range(400, 1200, 50):
                pygame.draw.line(screen, GRID_COLOR, (grid_x, 0), (grid_x, 600), 1)
            for grid_y in range(0, 600, 50):
                pygame.draw.line(screen, GRID_COLOR, (400, grid_y), (1200, grid_y), 1)

            # 2. Advanced Instruments: Top Navigation Compass Tape
            pygame.draw.rect(screen, (18, 18, 26), (460, 15, 680, 30), border_radius=4)
            pygame.draw.rect(screen, CARD_BORDER, (460, 15, 680, 30), 1, border_radius=4)
            
            center_nav_val = int(self.x)
            for nav_val in range(center_nav_val - 12, center_nav_val + 13):
                tick_px = 800 + int((nav_val - self.x) * 20) # 20px spacing per unit
                if 470 < tick_px < 1130:
                    # Tick line
                    pygame.draw.line(screen, (80, 80, 100), (tick_px, 15), (tick_px, 23), 1)
                    if nav_val % 2 == 0:
                        t_lbl = log_font.render(str(nav_val), True, (150, 150, 170))
                        t_rect = t_lbl.get_rect(center=(tick_px, 32))
                        screen.blit(t_lbl, t_rect)
            # Compass cursor indicator
            pygame.draw.polygon(screen, NEON_CYAN, [(800, 10), (795, 3), (805, 3)])

            # 3. Advanced Instruments: Left Altitude Tape Gauge
            pygame.draw.rect(screen, (18, 18, 26), (420, 80, 28, 380), border_radius=4)
            pygame.draw.rect(screen, CARD_BORDER, (420, 80, 28, 380), 1, border_radius=4)
            
            center_alt_val = int(self.y)
            for alt_val in range(max(0, center_alt_val - 15), center_alt_val + 16):
                tick_py = 270 - int((alt_val - self.y) * 12) # 12px per meter
                if 90 < tick_py < 450:
                    pygame.draw.line(screen, (80, 80, 100), (420, tick_py), (428, tick_py), 1)
                    if alt_val % 2 == 0:
                        alt_lbl = log_font.render(str(alt_val), True, (150, 150, 170))
                        screen.blit(alt_lbl, (430, tick_py - 6))
            # Altitude level indicator pointer
            pygame.draw.polygon(screen, NEON_CYAN, [(413, 270), (418, 266), (418, 274)])

            # 4. Advanced Instruments: Right Battery Tape Gauge
            pygame.draw.rect(screen, (18, 18, 26), (1152, 80, 28, 380), border_radius=4)
            pygame.draw.rect(screen, CARD_BORDER, (1152, 80, 28, 380), 1, border_radius=4)
            
            fill_h = int(372 * (self.battery / 100.0))
            bat_c = NEON_GREEN if self.battery > 50 else (NEON_ORANGE if self.battery > 20 else NEON_RED)
            if fill_h > 0:
                pygame.draw.rect(screen, bat_c, (1155, 80 + 376 - fill_h, 22, fill_h), border_radius=2)
            
            for bat_tick in [25, 50, 75, 100]:
                tick_py = 80 + 376 - int(376 * (bat_tick / 100.0))
                pygame.draw.line(screen, (100, 100, 120), (1152, tick_py), (1160, tick_py), 1)
                bat_lbl = log_font.render(f"{bat_tick}%", True, (130, 130, 150))
                screen.blit(bat_lbl, (1114, tick_py - 6))

            # 5. Advanced Instruments: Central Cockpit Pitch Ladder / Attitude Indicator
            ladder_center_x = 800
            ladder_center_y = 270
            
            # Draw fixed aircraft cockpit reticle cross
            pygame.draw.line(screen, NEON_CYAN, (ladder_center_x - 20, ladder_center_y), (ladder_center_x - 6, ladder_center_y), 2)
            pygame.draw.line(screen, NEON_CYAN, (ladder_center_x + 6, ladder_center_y), (ladder_center_x + 20, ladder_center_y), 2)
            pygame.draw.line(screen, NEON_CYAN, (ladder_center_x - 6, ladder_center_y), (ladder_center_x - 6, ladder_center_y + 4), 2)
            pygame.draw.line(screen, NEON_CYAN, (ladder_center_x + 6, ladder_center_y), (ladder_center_x + 6, ladder_center_y + 4), 2)
            pygame.draw.circle(screen, NEON_CYAN, (ladder_center_x, ladder_center_y), 2)

            # Draw roll scale arc
            pygame.draw.arc(screen, (60, 60, 80), (ladder_center_x - 55, ladder_center_y - 55, 110, 110), math.radians(30), math.radians(150), 1)
            for bank_angle in [-30, -15, 0, 15, 30]:
                ang_rad = math.radians(-bank_angle) - self.theta - math.pi/2
                t_x = ladder_center_x + int(55 * math.cos(ang_rad))
                t_y = ladder_center_y + int(55 * math.sin(ang_rad))
                pygame.draw.circle(screen, (100, 100, 120), (t_x, t_y), 2)

            # Draw rotating pitch lines
            pitch_deg = math.degrees(self.theta)
            for pitch_line in [-20, -10, 0, 10, 20]:
                y_offset = (pitch_line - pitch_deg) * 3.5 # vertical spacing
                cos_t = math.cos(-self.theta)
                sin_t = math.sin(-self.theta)
                
                p_lx = -25
                p_rx = 25
                
                l_rot_x = int(p_lx * cos_t - y_offset * sin_t) + ladder_center_x
                l_rot_y = int(p_lx * sin_t + y_offset * cos_t) + ladder_center_y
                r_rot_x = int(p_rx * cos_t - y_offset * sin_t) + ladder_center_x
                r_rot_y = int(p_rx * sin_t + y_offset * cos_t) + ladder_center_y
                
                l_color = (0, 200, 255) if pitch_line == 0 else (100, 110, 130)
                pygame.draw.line(screen, l_color, (l_rot_x, l_rot_y), (r_rot_x, r_rot_y), 1 if pitch_line != 0 else 2)
                
                # Draw vertical brackets indicators at pitch lines extremities
                tick_len = 5 if pitch_line >= 0 else -5
                l_tick_x = l_rot_x + int(tick_len * sin_t)
                l_tick_y = l_rot_y - int(tick_len * cos_t)
                r_tick_x = r_rot_x + int(tick_len * sin_t)
                r_tick_y = r_rot_y - int(tick_len * cos_t)
                pygame.draw.line(screen, l_color, (l_rot_x, l_rot_y), (l_tick_x, l_tick_y), 1)
                pygame.draw.line(screen, l_color, (r_rot_x, r_rot_y), (r_tick_x, r_tick_y), 1)
                
                # Label value next to extremities
                val_sf = log_font.render(str(abs(pitch_line)), True, l_color)
                screen.blit(val_sf, (r_rot_x + 6, r_rot_y - 6))

            # 6. Runway Ground Concrete Layout & Neon Marking Strip
            pygame.draw.rect(screen, (15, 15, 20), (400, 500, 800, 100))
            pygame.draw.line(screen, (52, 152, 219), (400, 500), (1200, 500), 3) # Neon Blue edge
            for mark_x in range(425, 1200, 80):
                pygame.draw.line(screen, (100, 110, 120), (mark_x, 500), (mark_x + 30, 500), 1)

            # 7. Draw Geofence boundaries
            fence_pulse = int(3 * math.sin(time.time() * 4.0))
            sol_fence_x = 800 - int(50*scale_x)
            sag_fence_x = 800 + int(50*scale_x)
            
            pygame.draw.line(screen, (231, 76, 60), (sol_fence_x, 50), (sol_fence_x, 500), 2)
            pygame.draw.line(screen, (231, 76, 60), (sag_fence_x, 50), (sag_fence_x, 500), 2)
            pygame.draw.line(screen, (200, 50, 50), (sol_fence_x + 5 + fence_pulse, 50), (sol_fence_x + 5 + fence_pulse, 500), 1)
            pygame.draw.line(screen, (200, 50, 50), (sag_fence_x - 5 - fence_pulse, 50), (sag_fence_x - 5 - fence_pulse, 500), 1)

            # 8. Glowing Flight Path Trail
            if hasattr(self, "trail_history") and len(self.trail_history) > 1:
                num_points = len(self.trail_history)
                for i in range(1, num_points):
                    p1_sim_x, p1_sim_y = self.trail_history[i-1]
                    p2_sim_x, p2_sim_y = self.trail_history[i]
                    
                    p1_px = 800 + int(p1_sim_x * scale_x)
                    p1_py = 500 - int(p1_sim_y * scale_y)
                    p2_px = 800 + int(p2_sim_x * scale_x)
                    p2_py = 500 - int(p2_sim_y * scale_y)
                    
                    factor = i / num_points
                    r = int(10 + (0 - 10) * factor)
                    g = int(20 + (229 - 20) * factor)
                    b = int(30 + (255 - 30) * factor)
                    
                    pygame.draw.line(screen, (r, g, b), (p1_px, p1_py), (p2_px, p2_py), 3)

            # 9. Altimeter vertical projection guide
            if self.in_air or self.y > 0.0:
                for proj_y in range(drone_py, 500, 10):
                    if (proj_y // 5) % 2 == 0:
                        pygame.draw.line(screen, (150, 150, 170), (drone_px, proj_y), (drone_px, min(500, proj_y + 6)), 1)
                
                alt_txt = f"ALT: {self.y:.1f}m"
                alt_sf = log_font.render(alt_txt, True, NEON_ORANGE)
                screen.blit(alt_sf, (drone_px + 12, drone_py + (500 - drone_py) // 2))

            # 10. HUD Target Lock Reticle
            if self.in_air or self.target_y > 0.0:
                pulse = int(4 * math.sin(time.time() * 6.0))
                pygame.draw.circle(screen, NEON_GREEN, (target_px, target_py), 12 + pulse, 1)
                pygame.draw.circle(screen, NEON_GREEN, (target_px, target_py), 2)
                size = 8
                # Top-Left
                pygame.draw.line(screen, NEON_GREEN, (target_px - size, target_py - size), (target_px - size + 4, target_py - size), 2)
                pygame.draw.line(screen, NEON_GREEN, (target_px - size, target_py - size), (target_px - size, target_py - size + 4), 2)
                # Top-Right
                pygame.draw.line(screen, NEON_GREEN, (target_px + size, target_py - size), (target_px + size - 4, target_py - size), 2)
                pygame.draw.line(screen, NEON_GREEN, (target_px + size, target_py - size), (target_px + size, target_py - size + 4), 2)
                # Bottom-Left
                pygame.draw.line(screen, NEON_GREEN, (target_px - size, target_py + size), (target_px - size + 4, target_py + size), 2)
                pygame.draw.line(screen, NEON_GREEN, (target_px - size, target_py + size), (target_px - size, target_py + size - 4), 2)
                # Bottom-Right
                pygame.draw.line(screen, NEON_GREEN, (target_px + size, target_py + size), (target_px + size - 4, target_py + size), 2)
                pygame.draw.line(screen, NEON_GREEN, (target_px + size, target_py + size), (target_px + size, target_py + size - 4), 2)

            # 11. High-Fidelity Quadcopter Render
            cos_t = math.cos(-self.theta)
            sin_t = math.sin(-self.theta)
            
            left_arm_x = drone_px - int(35 * cos_t)
            left_arm_y = drone_py - int(35 * sin_t)
            right_arm_x = drone_px + int(35 * cos_t)
            right_arm_y = drone_py + int(35 * sin_t)

            # Landing gear skids
            pygame.draw.line(screen, (108, 122, 137), (drone_px - 8, drone_py + 4), (drone_px - 10, drone_py + 12), 2)
            pygame.draw.line(screen, (108, 122, 137), (drone_px + 8, drone_py + 4), (drone_px + 10, drone_py + 12), 2)
            pygame.draw.line(screen, (108, 122, 137), (drone_px - 14, drone_py + 12), (drone_px + 14, drone_py + 12), 2)

            # Metallic structural arms
            pygame.draw.line(screen, (149, 165, 166), (left_arm_x, left_arm_y), (right_arm_x, right_arm_y), 3)

            # Fuselage body capsule
            pygame.draw.ellipse(screen, (44, 62, 80), (drone_px - 12, drone_py - 6, 24, 12))
            pygame.draw.ellipse(screen, (52, 73, 94), (drone_px - 9, drone_py - 4, 18, 8))

            # Blinking center Status LED
            center_led_flash = (time.time() * 4) % 2 < 1
            if self.failsafe:
                led_c = NEON_RED if center_led_flash else (100, 0, 0)
            elif self.in_air:
                led_c = NEON_GREEN if center_led_flash else (0, 100, 0)
            else:
                led_c = BLUE
            pygame.draw.circle(screen, led_c, (drone_px, drone_py), 3)

            # Navigation lights blinking on arm tips
            nav_light_flash = (time.time() * 2.5) % 2 < 1
            if nav_light_flash and (self.in_air or self.target_y > 0.0) and not self.failsafe:
                pygame.draw.circle(screen, RED, (left_arm_x, left_arm_y), 4)
                pygame.draw.circle(screen, NEON_GREEN, (right_arm_x, right_arm_y), 4)

            # Motor mounts at arm tips
            pygame.draw.rect(screen, (30, 30, 30), (left_arm_x - 3, left_arm_y - 6, 6, 8), border_radius=1)
            pygame.draw.rect(screen, (30, 30, 30), (right_arm_x - 3, right_arm_y - 6, 6, 8), border_radius=1)

            # Rotor sweep outline rings (gives a sleek CAD/aerodynamics blueprint look)
            pygame.draw.circle(screen, (80, 80, 90), (left_arm_x, left_arm_y - 6), 18, 1)
            pygame.draw.circle(screen, (80, 80, 90), (right_arm_x, right_arm_y - 6), 18, 1)

            # Propellers drawing
            prop_len = 18
            p1_x = int(prop_len * math.cos(self.propeller_angle))
            p1_y = int(prop_len * math.sin(self.propeller_angle) * 0.3)
            p2_x = int(prop_len * math.cos(self.propeller_angle + 0.4))
            p2_y = int(prop_len * math.sin(self.propeller_angle + 0.4) * 0.3)
            
            motor_l_top = (left_arm_x, left_arm_y - 6)
            pygame.draw.line(screen, (220, 220, 220), (motor_l_top[0] - p1_x, motor_l_top[1] - p1_y), (motor_l_top[0] + p1_x, motor_l_top[1] + p1_y), 2)
            pygame.draw.line(screen, (150, 150, 150), (motor_l_top[0] - p2_x, motor_l_top[1] - p2_y), (motor_l_top[0] + p2_x, motor_l_top[1] + p2_y), 1)

            p3_x = int(prop_len * math.cos(-self.propeller_angle))
            p3_y = int(prop_len * math.sin(-self.propeller_angle) * 0.3)
            p4_x = int(prop_len * math.cos(-self.propeller_angle + 0.4))
            p4_y = int(prop_len * math.sin(-self.propeller_angle + 0.4) * 0.3)

            motor_r_top = (right_arm_x, right_arm_y - 6)
            pygame.draw.line(screen, (220, 220, 220), (motor_r_top[0] - p3_x, motor_r_top[1] - p3_y), (motor_r_top[0] + p3_x, motor_r_top[1] + p3_y), 2)
            pygame.draw.line(screen, (150, 150, 150), (motor_r_top[0] - p4_x, motor_r_top[1] - p4_y), (motor_r_top[0] + p4_x, motor_r_top[1] + p4_y), 1)

            # 12. Draw Live Telemetry GCS dashboard elements
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
                f"Rüzgar Hızı : {self.wind_speed:.1f} km/s",
                f"Failsafe    : {'KİLİTLİ' if self.failsafe else 'PASİF'}"
            ]

            y_offset = 60
            for text_line in texts:
                img = telemetry_font.render(text_line, True, WHITE)
                # Render semi-transparent backing panel for telemetry
                screen.blit(img, (470, y_offset))
                y_offset += 20

            pygame.display.flip()

        pygame.quit()

    def _run_reboot_worker(self):
        self.status_message = "Reboot..."
        self.trail_history = []
        self.propeller_angle = 0.0
        sonuc = self.drone.reboot()
        self.add_gui_log(f"Sistem: {sonuc}")
        self.logger.log_action(self.session_id, "reboot", "reboot", None, True, sonuc)
        self.status_message = "HAZIR"

# Global simülatör nesnesi
global_simulator = DroneSimulator()

def start_simulator_thread():
    t = threading.Thread(target=global_simulator.run_pygame, daemon=True)
    t.start()
    return global_simulator
