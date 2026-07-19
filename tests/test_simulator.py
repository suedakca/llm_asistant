# tests/test_simulator.py
""" 2B fizik motoru (PID kaskad kontrolcü) ve GUI log tamponunun testleri.

    Her test kendi DroneSimulator örneğini kurar; global_simulator'a dokunulmaz.
    Rüzgar varsayılan olarak kapatılır — deterministik sonuç için.
"""
import math

import pytest

from simulator import DroneSimulator


DT = 0.01  # 100 Hz simülasyon adımı


@pytest.fixture
def sim():
    s = DroneSimulator()
    s.wind_speed = 0.0  # zaman bağımlı rüzgar gürültüsünü kapat
    return s


def _simule_et(s, saniye, dt=DT):
    """ Verilen süre boyunca fizik motorunu ilerletir """
    for _ in range(int(saniye / dt)):
        s.update_physics(dt)


# === 1. YERDE PARK DURUMU ===
def test_stays_parked_on_ground_without_takeoff_command(sim):
    """ Kalkış komutu yokken aracın yerde sabit kaldığını doğrular """
    _simule_et(sim, 5)
    assert sim.y == 0.0
    assert sim.vx == 0.0 and sim.vy == 0.0
    assert sim.theta == 0.0


def test_wind_does_not_drag_parked_drone(sim):
    """ Motorlar kapalıyken rüzgarın aracı sürüklemediğini doğrular """
    sim.wind_speed = 100.0  # şiddetli rüzgar
    _simule_et(sim, 5)
    assert sim.x == 0.0
    assert sim.wind_force_x == 0.0


# === 2. İRTİFA KONTROLÜ (PID) ===
@pytest.mark.parametrize("hedef", [5.0, 10.0, 30.0, 50.0])
def test_altitude_pid_converges_to_setpoint(sim, hedef):
    """ İrtifa PID'inin hedef yüksekliğe oturduğunu doğrular """
    sim.in_air = True
    sim.target_y = hedef

    _simule_et(sim, 30)
    assert sim.y == pytest.approx(hedef, abs=0.5)
    assert sim.vy == pytest.approx(0.0, abs=0.1)  # kararlı hâle gelmeli


def test_altitude_does_not_overshoot_excessively(sim):
    """ Tırmanışta aşırı aşımın (overshoot) olmadığını doğrular """
    sim.in_air = True
    sim.target_y = 20.0

    en_yuksek = 0.0
    for _ in range(3000):
        sim.update_physics(DT)
        en_yuksek = max(en_yuksek, sim.y)

    assert en_yuksek < 20.0 * 1.25  # %25'ten fazla aşmamalı


def test_descent_to_ground_clamps_at_zero(sim):
    """ İniş hedefinde aracın yere oturup altına geçmediğini doğrular """
    sim.in_air = True
    sim.target_y = 20.0
    _simule_et(sim, 25)

    sim.target_y = 0.0
    _simule_et(sim, 25)

    assert sim.y == 0.0
    assert sim.vy == 0.0
    assert sim.in_air is False  # yere değince uçuş bayrağı temizlenir


def test_thrust_disabled_when_grounded_with_zero_target(sim):
    """ Yerde ve hedef sıfırken motorların kapalı tutulduğunu doğrular """
    sim.in_air = False
    sim.target_y = 0.0
    sim.y = 0.0

    _simule_et(sim, 2)
    assert sim.y == 0.0


# === 3. YATAY KONUM KONTROLÜ ===
def test_position_pid_converges_to_target_x(sim):
    """ Yatay konum PID'inin hedefe oturduğunu doğrular """
    sim.in_air = True
    sim.target_y = 10.0
    _simule_et(sim, 20)

    sim.target_x = 25.0
    _simule_et(sim, 60)

    assert sim.x == pytest.approx(25.0, abs=1.0)
    assert sim.vx == pytest.approx(0.0, abs=0.2)


def test_horizontal_motion_preserves_altitude(sim):
    """ Yatay manevranın irtifayı bozmadığını doğrular """
    sim.in_air = True
    sim.target_y = 15.0
    _simule_et(sim, 25)

    sim.target_x = 20.0
    _simule_et(sim, 60)

    assert sim.y == pytest.approx(15.0, abs=1.0)


def test_tilt_angle_stays_within_limit(sim):
    """ Eğim açısının ±18 derece güvenlik sınırında kaldığını doğrular """
    sim.in_air = True
    sim.target_y = 20.0
    _simule_et(sim, 20)

    sim.target_x = 100.0  # agresif hedef — maksimum eğimi zorlar
    en_buyuk_egim = 0.0
    for _ in range(4000):
        sim.update_physics(DT)
        en_buyuk_egim = max(en_buyuk_egim, abs(sim.theta))

    assert en_buyuk_egim <= math.radians(25)  # 0.3 rad sınırı + kısa geçici aşım payı


def test_no_tilt_while_grounded(sim):
    """ Yerdeyken aracın eğilmediğini doğrular """
    sim.in_air = False
    sim.target_y = 5.0  # motorlar çalışıyor ama henüz havada değil
    sim.target_x = 30.0
    _simule_et(sim, 1)
    assert sim.theta == pytest.approx(0.0, abs=1e-6)


# === 4. FAILSAFE (SERBEST DÜŞÜŞ) ===
def test_failsafe_causes_free_fall(sim):
    """ Failsafe'te motorların kesilip aracın düştüğünü doğrular """
    sim.in_air = True
    sim.target_y = 30.0
    _simule_et(sim, 30)
    baslangic_irtifa = sim.y

    sim.failsafe = True
    _simule_et(sim, 1)

    assert sim.y < baslangic_irtifa
    assert sim.vy < 0  # aşağı yönlü hız


def test_failsafe_fall_matches_gravity(sim):
    """ Düşüşün yerçekimi ivmesine (g) uyduğunu doğrular """
    sim.failsafe = True
    sim.y = 100.0
    sim.vy = 0.0

    _simule_et(sim, 1.0)
    assert sim.vy == pytest.approx(-sim.g, rel=0.05)  # 1 saniyede ~ -9.81 m/s


def test_failsafe_settles_on_ground(sim):
    """ Düşüşün yerde durup hızları sıfırladığını doğrular """
    sim.failsafe = True
    sim.y = 20.0

    _simule_et(sim, 10)
    assert sim.y == 0.0
    assert sim.vy == 0.0
    assert sim.vx == 0.0
    assert sim.theta == 0.0


def test_failsafe_ignores_altitude_setpoint(sim):
    """ Failsafe'te hedef irtifanın yok sayıldığını doğrular """
    sim.failsafe = True
    sim.y = 30.0
    sim.target_y = 50.0  # tırmanma emri

    _simule_et(sim, 5)
    assert sim.y < 30.0  # yine de düşmeli


def test_propellers_stop_in_failsafe(sim):
    """ Failsafe'te pervanelerin dönmediğini doğrular """
    sim.in_air = True
    sim.target_y = 10.0
    _simule_et(sim, 1)

    sim.failsafe = True
    aci = sim.propeller_angle
    _simule_et(sim, 1)
    assert sim.propeller_angle == aci


def test_propellers_spin_while_flying(sim):
    """ Uçuş sırasında pervane açısının ilerlediğini doğrular """
    sim.in_air = True
    sim.target_y = 10.0
    _simule_et(sim, 1)
    assert sim.propeller_angle > 0.0


# === 5. ROTA GEÇMİŞİ ===
def test_trail_history_records_flight_path(sim):
    """ Havadayken rota geçmişinin biriktiğini doğrular """
    sim.in_air = True
    sim.target_y = 10.0
    _simule_et(sim, 5)
    assert len(sim.trail_history) > 0


def test_trail_history_is_capped(sim):
    """ Rota geçmişinin 150 nokta ile sınırlandığını (bellek sızıntısı yok) doğrular """
    sim.in_air = True
    sim.target_y = 10.0
    _simule_et(sim, 60)
    assert len(sim.trail_history) <= 150


# === 6. GUI LOG TAMPONU ===
def test_gui_log_buffer_is_capped(sim):
    """ GUI log tamponunun sınırsız büyümediğini doğrular """
    for i in range(100):
        sim.add_gui_log(f"kayit {i}")

    assert len(sim.gui_logs) <= 30
    assert sim.gui_logs[-1] == "kayit 99"  # en yeni kayıt korunur
    assert "kayit 0" not in sim.gui_logs   # en eski kayıt düşürülür


def test_empty_command_is_ignored(sim):
    """ Boş komutun işleme alınmadığını doğrular """
    sim.execute_command_async("   ")
    assert sim.status_message != "Isleniyor..."


# === 7. GUI KONTROL KURULUMU ===
def test_init_gui_control_reads_config(sim):
    """ Acil durum kelimeleri ve risk listesinin config'ten okunduğunu doğrular """
    config = {
        "safety_settings": {"emergency_keywords": ["DUR", "KES"]},
        "llm_settings": {"high_risk_actions": ["takeoff"]},
    }
    sim.init_gui_control("drone", "security", "assistant", "logger", config, "oturum-1")

    assert sim.emergency_words == ["DUR", "KES"]
    assert sim.high_risk_list == ["takeoff"]
    assert sim.drone == "drone"
    assert sim.session_id == "oturum-1"


def test_init_gui_control_falls_back_to_defaults(sim):
    """ Config yokken güvenli varsayılanların kullanıldığını doğrular """
    sim.init_gui_control(None, None, None, None, None, "oturum-1")

    assert "ABORT" in sim.emergency_words
    assert "takeoff" in sim.high_risk_list
