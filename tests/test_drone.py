# tests/test_drone.py
""" Drone durum makinesi, batarya tüketimi ve komut davranışlarının birim testleri. """
import time

import pytest

from drone import Drone


# === 1. BAŞLANGIÇ DURUMU ===
def test_initial_state_is_disarmed_on_ground(drone):
    """ Yeni oluşturulan drone'un yerde, silahsız ve dolu batarya ile başladığını doğrular """
    t = drone.get_telemetry()
    assert t["in_air"] is False
    assert t["altitude"] == 0.0
    assert t["battery"] == 100
    assert t["mode"] == "DISARMED"
    assert t["failsafe"] is False
    assert t["checklist_completed"] is False


def test_config_values_are_applied(mock_config):
    """ Config'teki drain ve rüzgar değerlerinin drone'a aktarıldığını doğrular """
    d = Drone(mock_config)
    assert d.drain_rate == 0.5
    assert d.wind_speed == 3.0


def test_defaults_used_when_config_missing():
    """ Config verilmediğinde güvenli varsayılanların kullanıldığını doğrular """
    d = Drone(None)
    assert d.drain_rate == 0.5
    assert d.wind_speed == 5.0
    assert d.mavlink_enabled is False


# === 2. KALKIŞ (TAKEOFF) ===
def test_takeoff_sets_flight_state(drone):
    """ İlk kalkışın irtifa, mod ve uçuş bayrağını doğru ayarladığını doğrular """
    sonuc = drone.takeoff(20)
    assert "Başarılı" in sonuc
    assert drone.in_air is True
    assert drone.altitude == 20.0
    assert drone.mode == "GUIDED"
    assert drone.takeoff_time is not None


def test_takeoff_consumes_battery(drone):
    """ Kalkışın %5 batarya tükettiğini doğrular """
    drone.takeoff(10)
    assert drone.battery == 95


def test_takeoff_while_airborne_updates_altitude(drone):
    """ Havadayken verilen takeoff komutunun irtifayı güncellediğini doğrular """
    drone.takeoff(10)
    sonuc = drone.takeoff(30)
    assert "güncellendi" in sonuc
    assert drone.altitude == 30.0


def test_takeoff_rounds_noisy_altitude(drone):
    """ Gürültülü fizik değerlerinin tek ondalığa yuvarlandığını doğrular """
    drone.takeoff(30.03798123)
    assert drone.altitude == 30.0


def test_takeoff_blocked_in_failsafe(drone):
    """ Failsafe kilidinin drone seviyesinde de kalkışı reddettiğini doğrular """
    drone.emergency_stop()
    sonuc = drone.takeoff(10)
    assert "Failsafe" in sonuc
    assert drone.in_air is False


# === 3. İNİŞ (LAND) ===
def test_land_resets_flight_state(drone):
    """ İnişin irtifayı sıfırlayıp checklist'i temizlediğini doğrular """
    drone.takeoff(20)
    drone.checklist_completed = True
    sonuc = drone.land()
    assert "Başarılı" in sonuc
    assert drone.in_air is False
    assert drone.altitude == 0.0
    assert drone.mode == "LAND"
    assert drone.checklist_completed is False
    assert drone.takeoff_time is None


def test_land_blocked_in_failsafe(drone):
    """ Failsafe modunda iniş komutunun reddedildiğini doğrular """
    drone.emergency_stop()
    assert "Failsafe" in drone.land()


def test_land_with_depleted_battery_triggers_failsafe(drone):
    """ İniş sırasında batarya biterse failsafe'in tetiklendiğini doğrular """
    drone.takeoff(10)
    drone.battery = 2  # iniş 3 birim tüketir -> 0
    sonuc = drone.land()
    assert "batarya tamamen tükendi" in sonuc
    assert drone.failsafe_active is True


# === 4. EVE DÖNÜŞ (RTH) ===
def test_return_to_home_moves_to_home_coordinates(drone):
    """ RTH'nin aracı ev koordinatlarına taşıyıp indirdiğini doğrular """
    drone.set_home(10, -5)
    drone.takeoff(20)
    drone.x, drone.y = 30.0, 40.0
    sonuc = drone.return_to_home()
    assert "Başarılı" in sonuc
    assert (drone.x, drone.y) == (10.0, -5.0)
    assert drone.altitude == 0.0
    assert drone.in_air is False
    assert drone.mode == "RTL_LAND"


def test_return_to_home_consumes_more_battery_than_land(drone):
    """ RTH'nin (%10) inişten (%3) daha maliyetli olduğunu doğrular """
    drone.takeoff(10)
    before = drone.battery
    drone.return_to_home()
    assert before - drone.battery == 10


# === 5. YATAY HAREKET (MOVE) ===
@pytest.mark.parametrize("direction,dx,dy", [
    ("kuzey", 0, 10), ("north", 0, 10), ("ileri", 0, 10),
    ("güney", 0, -10), ("south", 0, -10), ("geri", 0, -10),
    ("doğu", 10, 0), ("east", 10, 0), ("sağ", 10, 0),
    ("batı", -10, 0), ("west", -10, 0), ("sol", -10, 0),
])
def test_move_directions_update_coordinates(drone, direction, dx, dy):
    """ Desteklenen tüm yön eşanlamlılarının doğru eksende hareket ettirdiğini doğrular """
    drone.takeoff(10)
    drone.move(direction, 10)
    assert drone.x == dx
    assert drone.y == dy


def test_move_with_invalid_direction_returns_error(drone):
    """ Tanınmayan yönün hata döndüğünü ve konumu değiştirmediğini doğrular """
    drone.takeoff(10)
    sonuc = drone.move("yukarı", 10)
    assert "Geçersiz yön" in sonuc
    assert (drone.x, drone.y) == (0.0, 0.0)


def test_move_is_case_insensitive(drone):
    """ Büyük harfli yön adlarının da kabul edildiğini doğrular """
    drone.takeoff(10)
    drone.move("KUZEY", 5)
    assert drone.y == 5.0


def test_move_consumes_battery(drone):
    """ Her hareketin %2 batarya tükettiğini doğrular """
    drone.takeoff(10)
    before = drone.battery
    drone.move("kuzey", 5)
    assert before - drone.battery == 2


# === 6. EV KONUMU (SET_HOME) ===
def test_set_home_updates_coordinates(drone):
    """ Yerdeyken ev konumunun güncellendiğini doğrular """
    sonuc = drone.set_home(15, 25)
    assert "Başarılı" in sonuc
    assert (drone.home_x, drone.home_y) == (15.0, 25.0)


def test_set_home_blocked_in_air(drone):
    """ Havadayken ev konumunun değiştirilemediğini doğrular """
    drone.takeoff(10)
    sonuc = drone.set_home(15, 25)
    assert "Hata" in sonuc
    assert (drone.home_x, drone.home_y) == (0.0, 0.0)


# === 7. ACİL DURDURMA VE REBOOT ===
def test_emergency_stop_locks_system(drone):
    """ Acil durdurmanın sistemi kilitleyip aracı indirdiğini doğrular """
    drone.takeoff(30)
    sonuc = drone.emergency_stop()
    assert "FAILSAFE AKTİF" in sonuc
    assert drone.failsafe_active is True
    assert drone.in_air is False
    assert drone.altitude == 0.0
    assert drone.mode == "EMERGENCY_LAND"


def test_reboot_clears_failsafe_and_resets_state(drone):
    """ Reboot'un kilidi kaldırıp tüm durumu sıfırladığını doğrular """
    drone.takeoff(30)
    drone.move("kuzey", 20)
    drone.emergency_stop()

    sonuc = drone.reboot()
    assert "yeniden başlatıldı" in sonuc
    assert drone.failsafe_active is False
    assert drone.battery == 100
    assert (drone.x, drone.y, drone.altitude) == (0.0, 0.0, 0.0)
    assert drone.mode == "DISARMED"
    assert drone.checklist_completed is False


def test_reboot_blocked_in_air(drone):
    """ Havadayken reboot'un reddedildiğini doğrular """
    drone.takeoff(20)
    sonuc = drone.reboot()
    assert "Hata" in sonuc
    assert drone.in_air is True


# === 8. BATARYA TÜKETİM MOTORU ===
def test_battery_drains_over_flight_time(drone):
    """ Uçuş süresine bağlı bataryanın drain_rate ile azaldığını doğrular """
    drone.takeoff(10)  # 100 -> 95
    drone.takeoff_time = time.time() - 10  # 10 saniye uçmuş gibi davran
    drone.get_telemetry()
    assert drone.battery == 90  # 10 sn * 0.5 = 5 birim


def test_battery_does_not_drain_on_ground(drone):
    """ Yerdeyken zamana bağlı tüketim olmadığını doğrular """
    drone.get_telemetry()
    time.sleep(0.01)
    drone.get_telemetry()
    assert drone.battery == 100


def test_fractional_battery_debt_accumulates(drone):
    """ Bir birimin altındaki tüketimin kaybolmayıp biriktiğini doğrular """
    drone.takeoff(10)
    before = drone.battery

    # Tek başına 1 birim etmeyen iki kısa dilim (0.5 sn * 0.5 = 0.25 birim)
    for _ in range(2):
        drone.takeoff_time = time.time() - 0.5
        drone.get_telemetry()
    assert drone.battery == before  # henüz tam birim dolmadı
    assert drone._battery_debt == pytest.approx(0.5, abs=0.05)

    # Toplam borç 1 birimi aşınca batarya düşer
    drone.takeoff_time = time.time() - 1.0
    drone.get_telemetry()
    assert drone.battery == before - 1


def test_battery_depletion_triggers_automatic_failsafe(drone):
    """ Batarya %0'a inince motorun otomatik kesildiğini doğrular """
    drone.takeoff(30)
    drone.battery = 3
    drone.takeoff_time = time.time() - 20  # 20 sn * 0.5 = 10 birim tüketim

    drone.get_telemetry()
    assert drone.battery == 0
    assert drone.failsafe_active is True
    assert drone.in_air is False


def test_battery_never_goes_negative(drone):
    """ Bataryanın negatife düşmediğini doğrular """
    drone.takeoff(10)
    drone.battery = 1
    drone.takeoff_time = time.time() - 60
    drone.get_telemetry()
    assert drone.battery == 0


# === 9. TELEMETRİ SÖZLEŞMESİ ===
def test_telemetry_contains_all_required_keys(drone):
    """ Güvenlik katmanı ve LLM'in beklediği tüm alanların döndüğünü doğrular """
    t = drone.get_telemetry()
    beklenen = {"x", "y", "altitude", "mode", "battery", "in_air",
                "failsafe", "checklist_completed", "wind_speed"}
    assert beklenen <= set(t)


def test_telemetry_rounds_noisy_physics_values(drone):
    """ Fizik motorundan gelen gürültülü değerlerin 2 ondalığa kırpıldığını doğrular """
    drone.x = 12.3456789
    drone.altitude = 30.987654
    t = drone.get_telemetry()
    assert t["x"] == 12.35
    assert t["altitude"] == 30.99
