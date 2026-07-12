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
            # Hedef yer seviyesindeyse (iniş/eve dönüş sonrası) yere değince
            # 'havada' bayrağını temizle — böylece reboot gibi yer komutları çalışır.
            if self.target_y <= 0.0:
                self.in_air = False

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
        WIDTH, HEIGHT = 1400, 800
        screen = pygame.display.set_mode((WIDTH, HEIGHT))
        pygame.display.set_caption("İHA Yer Kontrol İstasyonu — Uçuş Kontrol Merkezi")
        clock = pygame.time.Clock()

        # ============================================================
        #  T A S A R I M   S I S T E M I  (Renk Paleti — Aviation Dark)
        # ============================================================
        BG_DEEP     = (10, 14, 22)     # Ana zemin
        HEADER_BG   = (14, 19, 30)     # Üst başlık çubuğu
        PANEL       = (18, 24, 36)     # Kart zemini
        PANEL_2     = (23, 30, 45)     # İç yüzey / stat tile
        PANEL_INSET = (11, 15, 24)     # Konsol / textbox iç zemin
        BORDER      = (38, 48, 68)     # İnce kenarlık
        BORDER_HI   = (58, 74, 102)    # Vurgulu kenarlık
        TEXT        = (226, 232, 244)  # Ana metin
        TEXT_DIM    = (140, 152, 174)  # İkincil metin
        TEXT_MUTE   = (86, 98, 120)    # Silik metin
        ACCENT      = (56, 189, 248)   # Camgöbeği vurgu
        TEAL        = (45, 212, 191)   # Teal
        OK          = (52, 211, 153)   # Yeşil
        WARN        = (251, 191, 36)   # Amber
        DANGER      = (248, 113, 113)  # Kırmızı
        DANGER_DEEP = (60, 22, 30)     # Koyu kırmızı zemin
        VIOLET      = (167, 139, 250)  # Mor

        def sh(c, d):
            return tuple(max(0, min(255, x + d)) for x in c)

        def lerp(a, b, t):
            return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))

        # ---- Yazı Tipleri ----
        UI = "Helvetica Neue,Segoe UI,Arial"
        MONO = "Menlo,Consolas,Courier New"
        try:
            f_h1      = pygame.font.SysFont(UI, 19, bold=True)
            f_title   = pygame.font.SysFont(UI, 12, bold=True)
            f_body    = pygame.font.SysFont(UI, 14)
            f_body_b  = pygame.font.SysFont(UI, 14, bold=True)
            f_small   = pygame.font.SysFont(UI, 11, bold=True)
            f_stat    = pygame.font.SysFont(MONO, 21, bold=True)
            f_statlbl = pygame.font.SysFont(UI, 10, bold=True)
            f_mono    = pygame.font.SysFont(MONO, 12)
            f_mono_b  = pygame.font.SysFont(MONO, 13, bold=True)
            f_tick    = pygame.font.SysFont(MONO, 10)
        except Exception:
            f_h1 = f_title = f_body = f_body_b = f_small = pygame.font.SysFont("Courier", 14, bold=True)
            f_stat = f_statlbl = f_mono = f_mono_b = f_tick = pygame.font.SysFont("Courier", 12)

        # ---- Layout Sabitleri ----
        HEAD_H = 54
        PANEL_W = 430                 # Sol kontrol paneli genişliği
        VP_X, VP_Y = PANEL_W, HEAD_H  # Simülasyon görüntü alanı
        VP_W, VP_H = WIDTH - PANEL_W, HEIGHT - HEAD_H
        center_x = VP_X + VP_W // 2
        ground_y = 636
        scale_x, scale_y = 6.0, 9.0

        # ---- Buton / Etkileşim Alanları ----
        btn_voice  = pygame.Rect(26, 150, 182, 36)
        btn_key    = pygame.Rect(216, 150, 182, 36)
        textbox_rect = pygame.Rect(28, 246, 300, 34)
        btn_send   = pygame.Rect(334, 246, 68, 34)
        btn_reboot = pygame.Rect(28, 682, 374, 40)
        btn_abort  = pygame.Rect(28, 730, 374, 42)

        # ---- Degrade Gökyüzü (bir kez hesapla) ----
        sky_h = ground_y - VP_Y
        sky_surface = pygame.Surface((VP_W, sky_h))
        for i in range(sky_h):
            sky_surface.fill(lerp((12, 16, 26), (24, 33, 50), i / sky_h), (0, i, VP_W, 1))

        # ---- Vinyet (kenarları karartan sinematik derinlik) ----
        vignette = pygame.Surface((VP_W, VP_H), pygame.SRCALPHA)
        vcx, vcy = VP_W / 2, VP_H * 0.42
        vmax = math.hypot(vcx, vcy)
        # Yumuşak radyal vinyet — köşelere doğru koyulaşan alfa
        for yy in range(0, VP_H, 3):
            d = abs(yy - vcy) / vmax
            a = int(120 * max(0, d - 0.15) ** 1.4)
            if a > 0:
                pygame.draw.rect(vignette, (4, 7, 12, a), (0, yy, VP_W, 3))
        for xx in range(0, VP_W, 3):
            d = abs(xx - vcx) / vmax
            a = int(70 * max(0, d - 0.25) ** 1.5)
            if a > 0:
                pygame.draw.rect(vignette, (4, 7, 12, a), (xx, 0, 3, VP_H))

        # ---- Başlık çubuğu degrade (bir kez hesapla) ----
        header_surface = pygame.Surface((WIDTH, HEAD_H))
        for i in range(HEAD_H):
            header_surface.fill(lerp((20, 27, 42), (13, 18, 28), i / HEAD_H), (0, i, WIDTH, 1))

        # ---- Geofence parlama şeridi (bir kez hesapla) ----
        fence_h = ground_y - 100
        fence_glow = pygame.Surface((22, fence_h), pygame.SRCALPHA)
        for cx in range(22):
            a = int(26 * (1 - abs(cx - 11) / 11) ** 1.8)
            if a > 0:
                pygame.draw.line(fence_glow, (*DANGER, a), (cx, 0), (cx, fence_h))

        # ---- Glow (parlama) — additive yumuşak ışık ----
        _glow_cache = {}
        def glow(cx, cy, radius, color, max_alpha=45):
            key = (radius, color, max_alpha)
            gs = _glow_cache.get(key)
            if gs is None:
                gs = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
                for r in range(radius, 0, -1):
                    a = int(max_alpha * (1 - r / radius) ** 2.4)
                    pygame.draw.circle(gs, (*color, a), (radius, radius), r)
                _glow_cache[key] = gs
            screen.blit(gs, (int(cx - radius), int(cy - radius)), special_flags=pygame.BLEND_RGB_ADD)

        # ---- Yardımcı Çizim Fonksiyonları ----
        _shadow_cache = {}
        def panel_shadow(rect, radius=12):
            key = (rect.width, rect.height, radius)
            s = _shadow_cache.get(key)
            if s is None:
                pad = 16
                s = pygame.Surface((rect.width + pad * 2, rect.height + pad * 2), pygame.SRCALPHA)
                for i, al in enumerate((5, 8, 13, 22)):
                    off = (3 - i) * 3
                    pygame.draw.rect(s, (0, 0, 0, al),
                                     (pad - off, pad - off + 5, rect.width + off * 2, rect.height + off * 2),
                                     border_radius=radius + off)
                _shadow_cache[key] = s
            screen.blit(s, (rect.x - 16, rect.y - 16))

        def draw_panel(rect, fill=PANEL, border=BORDER, radius=12, bw=1, shadow=True):
            if shadow:
                panel_shadow(rect, radius)
            pygame.draw.rect(screen, fill, rect, border_radius=radius)
            # üst iç ışık kenarı (cam etkisi)
            hl = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
            pygame.draw.line(hl, (255, 255, 255, 14), (radius, 1), (rect.width - radius, 1))
            screen.blit(hl, rect.topleft)
            if bw:
                pygame.draw.rect(screen, border, rect, bw, border_radius=radius)

        def panel_header(x, y, text, accent=ACCENT):
            pygame.draw.rect(screen, accent, (x, y + 1, 3, 12), border_radius=2)
            screen.blit(f_title.render(text.upper(), True, TEXT_DIM), (x + 11, y))

        def draw_button(rect, text, base, fg=TEXT, hover=False, accent=None, active=False):
            # dikey degrade dolgu
            grad = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
            top = sh(base, 22 if hover else 12)
            bot = sh(base, -10)
            for i in range(rect.height):
                grad.fill((*lerp(top, bot, i / rect.height), 255), (0, i, rect.width, 1))
            mask = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
            pygame.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(), border_radius=9)
            grad.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
            screen.blit(grad, rect.topleft)
            bcol = accent if accent else sh(base, 40)
            pygame.draw.rect(screen, bcol, rect, 2 if active else 1, border_radius=9)
            t = f_body_b.render(text, True, fg)
            screen.blit(t, t.get_rect(center=rect.center))

        def stat_tile(x, y, w, h, label, value, accent):
            r = pygame.Rect(x, y, w, h)
            pygame.draw.rect(screen, PANEL_2, r, border_radius=9)
            hl = pygame.Surface((w, h), pygame.SRCALPHA)
            pygame.draw.line(hl, (255, 255, 255, 12), (9, 1), (w - 9, 1))
            screen.blit(hl, (x, y))
            pygame.draw.rect(screen, BORDER, r, 1, border_radius=9)
            pygame.draw.rect(screen, accent, (x + 6, y + h - 3, w - 12, 2), border_radius=2)
            screen.blit(f_statlbl.render(label.upper(), True, TEXT_MUTE), (x + 11, y + 10))
            screen.blit(f_stat.render(value, True, accent), (x + 11, y + 26))

        while self.running:
            dt = clock.tick(60) / 1000.0
            if dt > 0.1:
                dt = 0.1
            self.cursor_timer = (self.cursor_timer + dt) % 1.0

            mouse_pos = pygame.mouse.get_pos()
            hover_voice  = btn_voice.collidepoint(mouse_pos)
            hover_key    = btn_key.collidepoint(mouse_pos)
            hover_send   = btn_send.collidepoint(mouse_pos)
            hover_reboot = btn_reboot.collidepoint(mouse_pos)
            hover_abort  = btn_abort.collidepoint(mouse_pos)

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                elif event.type == pygame.MOUSEBUTTONDOWN:
                    if event.button == 1:
                        if btn_voice.collidepoint(event.pos):
                            self.input_mode = "voice"
                            self.is_textbox_focused = False
                            self.get_voice_input_async()
                        elif btn_key.collidepoint(event.pos):
                            self.input_mode = "keyboard"
                            self.is_textbox_focused = True
                        elif textbox_rect.collidepoint(event.pos):
                            if self.input_mode == "keyboard":
                                self.is_textbox_focused = True
                        elif btn_send.collidepoint(event.pos):
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

            self.update_physics(dt)
            screen.fill(BG_DEEP)

            # ============================================================
            #  S I M U L A S Y O N   G O R U N T U   A L A N I
            # ============================================================
            screen.blit(sky_surface, (VP_X, VP_Y))

            # İnce koordinat ızgarası
            grid_c = (24, 32, 48)
            for gx in range(VP_X, WIDTH, 48):
                pygame.draw.line(screen, grid_c, (gx, VP_Y), (gx, ground_y), 1)
            for gy in range(VP_Y, ground_y, 48):
                pygame.draw.line(screen, grid_c, (VP_X, gy), (WIDTH, gy), 1)

            # Sinematik vinyet (sky + grid üzerine, enstrümanların altına)
            screen.blit(vignette, (VP_X, VP_Y))

            drone_px = center_x + int(self.x * scale_x)
            drone_py = ground_y - int(self.y * scale_y)
            target_px = center_x + int(self.target_x * scale_x)
            target_py = ground_y - int(self.target_y * scale_y)

            # --- Pusula bandı (üst) ---
            comp = pygame.Rect(center_x - 400, 68, 800, 26)
            pygame.draw.rect(screen, (14, 20, 32), comp, border_radius=6)
            pygame.draw.rect(screen, BORDER, comp, 1, border_radius=6)
            cnav = int(self.x)
            for nav_val in range(cnav - 12, cnav + 13):
                tx = center_x + int((nav_val - self.x) * 22)
                if comp.left + 8 < tx < comp.right - 8:
                    pygame.draw.line(screen, sh(BORDER_HI, 10), (tx, 70), (tx, 78), 1)
                    if nav_val % 2 == 0:
                        tl = f_tick.render(str(nav_val), True, TEXT_MUTE)
                        screen.blit(tl, tl.get_rect(center=(tx, 87)))
            pygame.draw.polygon(screen, ACCENT, [(center_x, 66), (center_x - 5, 60), (center_x + 5, 60)])

            # --- İrtifa bandı (sol) ---
            alt_g = pygame.Rect(446, 112, 26, 376)
            pygame.draw.rect(screen, (14, 20, 32), alt_g, border_radius=6)
            pygame.draw.rect(screen, BORDER, alt_g, 1, border_radius=6)
            calt = int(self.y)
            for alt_val in range(max(0, calt - 15), calt + 16):
                ty = 300 - int((alt_val - self.y) * 12)
                if alt_g.top + 6 < ty < alt_g.bottom - 6:
                    pygame.draw.line(screen, sh(BORDER_HI, 10), (446, ty), (454, ty), 1)
                    if alt_val % 2 == 0:
                        screen.blit(f_tick.render(str(alt_val), True, TEXT_MUTE), (458, ty - 6))
            pygame.draw.polygon(screen, ACCENT, [(440, 300), (446, 296), (446, 304)])

            # --- Batarya bandı (sağ) ---
            bat_g = pygame.Rect(WIDTH - 40, 112, 26, 376)
            pygame.draw.rect(screen, (14, 20, 32), bat_g, border_radius=6)
            pygame.draw.rect(screen, BORDER, bat_g, 1, border_radius=6)
            fill_h = int(370 * (self.battery / 100.0))
            bat_c = OK if self.battery > 50 else (WARN if self.battery > 20 else DANGER)
            if fill_h > 0:
                pygame.draw.rect(screen, bat_c, (bat_g.x + 3, bat_g.bottom - 3 - fill_h, 20, fill_h), border_radius=3)
                glow(bat_g.centerx, bat_g.bottom - 3 - fill_h, 16, bat_c, max_alpha=40)
            for bt in [25, 50, 75, 100]:
                ty = bat_g.bottom - 3 - int(370 * (bt / 100.0))
                pygame.draw.line(screen, BORDER_HI, (bat_g.x, ty), (bat_g.x + 8, ty), 1)
                lb = f_tick.render(f"{bt}", True, TEXT_MUTE)
                screen.blit(lb, lb.get_rect(right=bat_g.x - 4, centery=ty))

            # --- Attitude / pitch ladder (merkez) ---
            lcx, lcy = center_x, 290
            pygame.draw.line(screen, ACCENT, (lcx - 22, lcy), (lcx - 7, lcy), 2)
            pygame.draw.line(screen, ACCENT, (lcx + 7, lcy), (lcx + 22, lcy), 2)
            pygame.draw.line(screen, ACCENT, (lcx - 7, lcy), (lcx - 7, lcy + 4), 2)
            pygame.draw.line(screen, ACCENT, (lcx + 7, lcy), (lcx + 7, lcy + 4), 2)
            pygame.draw.circle(screen, ACCENT, (lcx, lcy), 2)
            pygame.draw.arc(screen, BORDER_HI, (lcx - 58, lcy - 58, 116, 116), math.radians(30), math.radians(150), 1)
            for bank in [-30, -15, 0, 15, 30]:
                ar = math.radians(-bank) - self.theta - math.pi / 2
                tx = lcx + int(58 * math.cos(ar))
                ty = lcy + int(58 * math.sin(ar))
                pygame.draw.circle(screen, TEXT_MUTE, (tx, ty), 2)
            pitch_deg = math.degrees(self.theta)
            cos_t, sin_t = math.cos(-self.theta), math.sin(-self.theta)
            for pl in [-20, -10, 0, 10, 20]:
                yo = (pl - pitch_deg) * 3.5
                lx = int(-26 * cos_t - yo * sin_t) + lcx
                ly = int(-26 * sin_t + yo * cos_t) + lcy
                rx = int(26 * cos_t - yo * sin_t) + lcx
                ry = int(26 * sin_t + yo * cos_t) + lcy
                lc = ACCENT if pl == 0 else (112, 124, 148)
                pygame.draw.line(screen, lc, (lx, ly), (rx, ry), 2 if pl == 0 else 1)
                vs = f_tick.render(str(abs(pl)), True, lc)
                screen.blit(vs, (rx + 6, ry - 6))

            # --- Zemin / pist ---
            pygame.draw.rect(screen, (16, 21, 30), (VP_X, ground_y, VP_W, HEIGHT - ground_y))
            pygame.draw.line(screen, ACCENT, (VP_X, ground_y), (WIDTH, ground_y), 2)
            for mx in range(VP_X + 25, WIDTH, 80):
                pygame.draw.line(screen, (70, 82, 100), (mx, ground_y), (mx + 34, ground_y), 1)

            # --- Geofence sınırları ---
            fp = int(3 * math.sin(time.time() * 4.0))
            sol_f = center_x - int(50 * scale_x)
            sag_f = center_x + int(50 * scale_x)
            for fx, off in ((sol_f, 1), (sag_f, -1)):
                screen.blit(fence_glow, (fx - 11, 100), special_flags=pygame.BLEND_RGB_ADD)
                pygame.draw.line(screen, DANGER, (fx, 100), (fx, ground_y), 2)
                pygame.draw.line(screen, sh(DANGER_DEEP, 60), (fx + off * (5 + fp), 100), (fx + off * (5 + fp), ground_y), 1)

            # --- Uçuş rota izi (parlayan) ---
            if hasattr(self, "trail_history") and len(self.trail_history) > 1:
                n = len(self.trail_history)
                for i in range(1, n):
                    a = self.trail_history[i - 1]
                    b = self.trail_history[i]
                    p1 = (center_x + int(a[0] * scale_x), ground_y - int(a[1] * scale_y))
                    p2 = (center_x + int(b[0] * scale_x), ground_y - int(b[1] * scale_y))
                    pygame.draw.line(screen, lerp((16, 24, 38), ACCENT, i / n), p1, p2, 3)
                # iz başında yumuşak parlama
                glow(p2[0], p2[1], 14, ACCENT, max_alpha=45)

            # --- İrtifa dikey projeksiyon kılavuzu ---
            if self.in_air or self.y > 0.0:
                for py in range(drone_py, ground_y, 10):
                    if (py // 5) % 2 == 0:
                        pygame.draw.line(screen, (120, 132, 156), (drone_px, py), (drone_px, min(ground_y, py + 6)), 1)
                asf = f_tick.render(f"{self.y:.1f}m", True, WARN)
                screen.blit(asf, (drone_px + 10, drone_py + (ground_y - drone_py) // 2))

            # --- Hedef kilit nişangahı ---
            if self.in_air or self.target_y > 0.0:
                pulse = int(4 * math.sin(time.time() * 6.0))
                glow(target_px, target_py, 22, OK, max_alpha=34)
                pygame.draw.circle(screen, OK, (target_px, target_py), 12 + pulse, 1)
                pygame.draw.circle(screen, OK, (target_px, target_py), 2)
                s = 8
                for dx, dy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
                    cx, cy = target_px + dx * s, target_py + dy * s
                    pygame.draw.line(screen, OK, (cx, cy), (cx - dx * 4, cy), 2)
                    pygame.draw.line(screen, OK, (cx, cy), (cx, cy - dy * 4), 2)

            # --- Quadcopter render ---
            cos_t, sin_t = math.cos(-self.theta), math.sin(-self.theta)
            la_x = drone_px - int(35 * cos_t)
            la_y = drone_py - int(35 * sin_t)
            ra_x = drone_px + int(35 * cos_t)
            ra_y = drone_py + int(35 * sin_t)
            pygame.draw.line(screen, (108, 122, 137), (drone_px - 8, drone_py + 4), (drone_px - 10, drone_py + 12), 2)
            pygame.draw.line(screen, (108, 122, 137), (drone_px + 8, drone_py + 4), (drone_px + 10, drone_py + 12), 2)
            pygame.draw.line(screen, (108, 122, 137), (drone_px - 14, drone_py + 12), (drone_px + 14, drone_py + 12), 2)
            pygame.draw.line(screen, (149, 165, 166), (la_x, la_y), (ra_x, ra_y), 3)
            pygame.draw.ellipse(screen, (44, 62, 80), (drone_px - 12, drone_py - 6, 24, 12))
            pygame.draw.ellipse(screen, (52, 73, 94), (drone_px - 9, drone_py - 4, 18, 8))
            led_flash = (time.time() * 4) % 2 < 1
            if self.failsafe:
                led_c = DANGER if led_flash else (100, 0, 0)
            elif self.in_air:
                led_c = OK if led_flash else (0, 100, 0)
            else:
                led_c = ACCENT
            glow(drone_px, drone_py, 16, led_c, max_alpha=55 if led_flash else 22)
            pygame.draw.circle(screen, led_c, (drone_px, drone_py), 3)
            nav_flash = (time.time() * 2.5) % 2 < 1
            if nav_flash and (self.in_air or self.target_y > 0.0) and not self.failsafe:
                glow(la_x, la_y, 10, DANGER, max_alpha=60)
                glow(ra_x, ra_y, 10, OK, max_alpha=60)
                pygame.draw.circle(screen, DANGER, (la_x, la_y), 4)
                pygame.draw.circle(screen, OK, (ra_x, ra_y), 4)
            pygame.draw.rect(screen, (30, 30, 30), (la_x - 3, la_y - 6, 6, 8), border_radius=1)
            pygame.draw.rect(screen, (30, 30, 30), (ra_x - 3, ra_y - 6, 6, 8), border_radius=1)
            pygame.draw.circle(screen, (80, 80, 90), (la_x, la_y - 6), 18, 1)
            pygame.draw.circle(screen, (80, 80, 90), (ra_x, ra_y - 6), 18, 1)
            pl_len = 18
            p1x = int(pl_len * math.cos(self.propeller_angle))
            p1y = int(pl_len * math.sin(self.propeller_angle) * 0.3)
            p2x = int(pl_len * math.cos(self.propeller_angle + 0.4))
            p2y = int(pl_len * math.sin(self.propeller_angle + 0.4) * 0.3)
            mlt = (la_x, la_y - 6)
            pygame.draw.line(screen, (220, 220, 220), (mlt[0] - p1x, mlt[1] - p1y), (mlt[0] + p1x, mlt[1] + p1y), 2)
            pygame.draw.line(screen, (150, 150, 150), (mlt[0] - p2x, mlt[1] - p2y), (mlt[0] + p2x, mlt[1] + p2y), 1)
            p3x = int(pl_len * math.cos(-self.propeller_angle))
            p3y = int(pl_len * math.sin(-self.propeller_angle) * 0.3)
            p4x = int(pl_len * math.cos(-self.propeller_angle + 0.4))
            p4y = int(pl_len * math.sin(-self.propeller_angle + 0.4) * 0.3)
            mrt = (ra_x, ra_y - 6)
            pygame.draw.line(screen, (220, 220, 220), (mrt[0] - p3x, mrt[1] - p3y), (mrt[0] + p3x, mrt[1] + p3y), 2)
            pygame.draw.line(screen, (150, 150, 150), (mrt[0] - p4x, mrt[1] - p4y), (mrt[0] + p4x, mrt[1] + p4y), 1)

            # ============================================================
            #  A L T   T E L E M E T R I   K O N S O L U
            # ============================================================
            tbar = pygame.Rect(VP_X + 8, 690, VP_W - 24, 102)
            draw_panel(tbar, fill=PANEL, border=BORDER, radius=12)
            panel_header(tbar.x + 12, tbar.y + 10, "Canlı Telemetri")
            fs_ok = not self.failsafe
            tiles = [
                ("İrtifa",     f"{self.y:.1f}",             ACCENT),
                ("Konum X",    f"{self.x:.1f}",             ACCENT),
                ("Yatay Hız",  f"{self.vx:.1f}",            TEAL),
                ("Dikey Hız",  f"{self.vy:.1f}",            TEAL),
                ("Eğim",       f"{math.degrees(self.theta):.0f}°", VIOLET),
                ("Batarya",    f"{self.battery:.0f}%",      bat_c),
                ("Rüzgar",     f"{self.wind_speed:.0f}",    WARN),
                ("Failsafe",   "AKTİF" if fs_ok else "KİLİT", OK if fs_ok else DANGER),
            ]
            tw = (tbar.width - 24 - 7 * 8) // 8
            for i, (lbl, val, acc) in enumerate(tiles):
                stat_tile(tbar.x + 12 + i * (tw + 8), tbar.y + 30, tw, 60, lbl, val, acc)

            # ============================================================
            #  U S T   B A S L I K   C U B U G U
            # ============================================================
            screen.blit(header_surface, (0, 0))
            pygame.draw.line(screen, BORDER, (0, HEAD_H), (WIDTH, HEAD_H), 1)
            pygame.draw.line(screen, sh(ACCENT, -110), (0, HEAD_H + 1), (WIDTH, HEAD_H + 1), 1)
            # Logo işareti (rotor)
            pygame.draw.circle(screen, ACCENT, (26, 27), 9, 2)
            for a in range(4):
                ang = math.radians(a * 90 + 45)
                pygame.draw.circle(screen, ACCENT, (26 + int(11 * math.cos(ang)), 27 + int(11 * math.sin(ang))), 2)
            screen.blit(f_h1.render("İHA YER KONTROL İSTASYONU", True, TEXT), (48, 17))
            # Mod rozeti
            mode_c = DANGER if self.failsafe else (OK if self.in_air else ACCENT)
            mtxt = f_small.render(self.mode, True, mode_c)
            mbadge = pygame.Rect(372, 15, mtxt.get_width() + 26, 24)
            pygame.draw.rect(screen, sh(mode_c, -150), mbadge, border_radius=12)
            pygame.draw.rect(screen, mode_c, mbadge, 1, border_radius=12)
            pygame.draw.circle(screen, mode_c, (mbadge.x + 13, mbadge.centery), 4)
            screen.blit(mtxt, (mbadge.x + 22, mbadge.centery - mtxt.get_height() // 2))
            # Sağ küme: bağlantı + sinyal + saat
            hb_flash = (time.time() * 3.0) % 2 < 1.0
            clock_txt = time.strftime("%H:%M:%S")
            cs = f_mono_b.render(clock_txt, True, TEXT_DIM)
            screen.blit(cs, (WIDTH - cs.get_width() - 18, 19))
            sig_x = WIDTH - cs.get_width() - 62
            for s in range(4):
                pygame.draw.rect(screen, OK if s < 3 else (52, 62, 78), (sig_x + s * 6, 32 - s * 4, 4, 4 + s * 4))
            link_c = OK if hb_flash else sh(OK, -90)
            pygame.draw.circle(screen, link_c, (sig_x - 66, 27), 5)
            if hb_flash:
                pygame.draw.circle(screen, OK, (sig_x - 66, 27), 8, 1)
            screen.blit(f_small.render("BAĞLANTI", True, TEXT_DIM), (sig_x - 54, 20))

            # ============================================================
            #  S O L   K O N T R O L   P A N E L I
            # ============================================================
            pygame.draw.rect(screen, (13, 18, 28), (0, HEAD_H, PANEL_W, HEIGHT - HEAD_H))
            pygame.draw.line(screen, BORDER, (PANEL_W, HEAD_H), (PANEL_W, HEIGHT), 1)

            # --- Kart 1: Giriş modu ---
            card1 = pygame.Rect(14, 66, 402, 132)
            draw_panel(card1)
            panel_header(28, 78, "Komut Giriş Modu")
            status_color = OK if self.status_message == "HAZIR" else ACCENT
            if "DINLENIYOR" in self.status_message or "Ses" in self.status_message:
                status_color = WARN
            elif "Hata" in self.status_message or "Reddedildi" in self.status_message:
                status_color = DANGER
            screen.blit(f_small.render("DURUM", True, TEXT_MUTE), (28, 110))
            pygame.draw.circle(screen, status_color, (32, 130), 4)
            screen.blit(f_body_b.render(self.status_message, True, status_color), (44, 122))
            v_active = self.input_mode == "voice"
            k_active = self.input_mode == "keyboard"
            draw_button(btn_voice, "SESLİ GİRİŞ", ACCENT if v_active else PANEL_2, TEXT if v_active else TEXT_DIM,
                        hover_voice, accent=ACCENT if v_active else None, active=v_active)
            draw_button(btn_key, "KLAVYE", ACCENT if k_active else PANEL_2, TEXT if k_active else TEXT_DIM,
                        hover_key, accent=ACCENT if k_active else None, active=k_active)

            # --- Kart 2: Komut konsolu ---
            card2 = pygame.Rect(14, 208, 402, 82)
            draw_panel(card2)
            panel_header(28, 216, "Komut Konsolu")
            tb_border = ACCENT if self.is_textbox_focused else BORDER_HI
            pygame.draw.rect(screen, PANEL_INSET, textbox_rect, border_radius=8)
            pygame.draw.rect(screen, tb_border, textbox_rect, 2 if self.is_textbox_focused else 1, border_radius=8)
            tb_pad = 10
            tb_avail = textbox_rect.width - tb_pad * 2
            if self.input_text:
                tc = TEXT if self.input_mode == "keyboard" else TEXT_MUTE
                tsf = f_body.render(self.input_text, True, tc)
                # Metin uzadıkça sola kaydır: her zaman sonu (imleci) göster
                scroll = max(0, tsf.get_width() - tb_avail)
                prev_clip = screen.get_clip()
                screen.set_clip(textbox_rect.inflate(-6, -4))
                screen.blit(tsf, (textbox_rect.x + tb_pad - scroll, textbox_rect.y + 9))
                screen.set_clip(prev_clip)
                if self.is_textbox_focused and self.cursor_timer < 0.5:
                    cxp = textbox_rect.x + tb_pad + min(tsf.get_width(), tb_avail) + 1
                    pygame.draw.line(screen, ACCENT, (cxp, textbox_rect.y + 8), (cxp, textbox_rect.y + 26), 2)
            else:
                ph = "Komut girin…" if self.input_mode == "keyboard" else "(Klavye moduna geçin)"
                screen.blit(f_body.render(ph, True, TEXT_MUTE), (textbox_rect.x + tb_pad, textbox_rect.y + 9))
                if self.is_textbox_focused and self.cursor_timer < 0.5:
                    pygame.draw.line(screen, ACCENT, (textbox_rect.x + tb_pad, textbox_rect.y + 8),
                                     (textbox_rect.x + tb_pad, textbox_rect.y + 26), 2)
            send_on = self.input_mode == "keyboard"
            draw_button(btn_send, "GÖNDER", OK if send_on else PANEL_2, TEXT if send_on else TEXT_MUTE,
                        hover_send and send_on, accent=OK if send_on else None)

            # --- Kart 3: Event günlüğü ---
            card3 = pygame.Rect(14, 296, 402, 336)
            draw_panel(card3)
            panel_header(28, 306, "Sistem Event Günlüğü")
            console = pygame.Rect(24, 328, 382, 296)
            pygame.draw.rect(screen, PANEL_INSET, console, border_radius=8)
            pygame.draw.rect(screen, BORDER, console, 1, border_radius=8)
            wrapped = []
            for raw in self.gui_logs:
                if len(raw) > 42:
                    for i in range(0, len(raw), 42):
                        wrapped.append(raw[i:i + 42])
                else:
                    wrapped.append(raw)
            ly = 338
            for wl in wrapped[-12:]:
                c = TEXT_DIM
                if wl.startswith("Pilot:"):
                    c = ACCENT
                elif wl.startswith("Asistan:"):
                    c = WARN
                elif wl.startswith("Sistem:") or wl.startswith("Reddedildi:") or wl.startswith("Hata:"):
                    c = DANGER
                elif wl.startswith("Başarılı:") or wl.startswith("Basarili:") or wl.startswith("Onaylandı:"):
                    c = OK
                screen.blit(f_mono.render(wl, True, c), (34, ly))
                ly += 22

            # --- Kart 4: Kritik eylem konsolu ---
            card4 = pygame.Rect(14, 642, 402, 142)
            fill4 = DANGER_DEEP if self.failsafe else PANEL
            draw_panel(card4, fill=fill4, border=DANGER if self.failsafe else BORDER)
            panel_header(28, 652, "Kritik Eylem Konsolu", accent=DANGER)
            draw_button(btn_reboot, "SİSTEMİ YENİDEN BAŞLAT", PANEL_2, TEXT, hover_reboot, accent=ACCENT)
            draw_button(btn_abort, "ACİL DURDUR — ABORT", sh(DANGER, -140), DANGER, hover_abort, accent=DANGER)

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
