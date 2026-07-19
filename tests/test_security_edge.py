# tests/test_security_edge.py
""" Güvenlik katmanının sınır durumları ve hatalı LLM çıktılarına karşı dayanıklılığı.

    LLM çıktısı GÜVENİLMEYEN girdidir: tip, aralık ve eylem adı doğrulanmadan
    hiçbir komut drone'a ulaşmamalıdır.
"""
import pytest


# === 1. TANINMAYAN EYLEMLER (REGRESYON) ===
@pytest.mark.parametrize("action", ["do_a_flip", "self_destruct", "", "TAKEOFF", "shell"])
def test_unknown_action_is_rejected(drone, security_layer, action):
    """ Haritalanamayan eylemlerin ONAYLANMADIĞINI doğrular.

    Regresyon: eskiden bilinmeyen eylemler onay=True + hata metni dönüyordu;
    bu da loglara "güvenlik onaylı" olarak yazılmasına yol açıyordu.
    """
    onay, mesaj = security_layer.validate_and_execute(drone, action, None)
    assert onay is False
    assert "Tanınmayan eylem" in mesaj


def test_all_documented_actions_are_recognized(drone, security_layer):
    """ Asistanın üretebildiği tüm eylemlerin güvenlik katmanınca tanındığını doğrular """
    from security import ALLOWED_ACTIONS
    for action in ALLOWED_ACTIONS:
        _, mesaj = security_layer.validate_and_execute(drone, action, None)
        assert "Tanınmayan eylem" not in (mesaj or "")


# === 2. HATALI TİPTEKİ PARAMETRELER (REGRESYON) ===
@pytest.mark.parametrize("bad_param", ["yüksek", "on metre", [], {}, "abc"])
def test_non_numeric_takeoff_parameter_is_rejected_not_crashed(drone, security_layer, bad_param):
    """ Sayısal olmayan irtifanın çökme yerine güvenlik reddi ürettiğini doğrular.

    Regresyon: float("yüksek") yakalanmamış ValueError fırlatıp ana döngüyü
    çökertiyordu.
    """
    drone.checklist_completed = True
    onay, mesaj = security_layer.validate_and_execute(drone, "takeoff", bad_param)
    assert onay is False
    assert "Geçersiz irtifa" in mesaj
    assert drone.in_air is False


@pytest.mark.parametrize("bad_distance", ["biraz", None, [], "10m"])
def test_non_numeric_move_distance_is_rejected_not_crashed(drone, security_layer, bad_distance):
    """ Sayısal olmayan mesafenin çökme yerine güvenlik reddi ürettiğini doğrular """
    drone.in_air = True
    onay, mesaj = security_layer.validate_and_execute(
        drone, "move", {"direction": "kuzey", "distance": bad_distance})
    assert onay is False
    assert drone.y == 0.0


@pytest.mark.parametrize("bad_param", ["kuzeye", 42, None, ["kuzey", 10]])
def test_malformed_move_parameter_is_rejected(drone, security_layer, bad_param):
    """ Sözlük olmayan move parametresinin TypeError yerine reddedildiğini doğrular """
    drone.in_air = True
    onay, mesaj = security_layer.validate_and_execute(drone, "move", bad_param)
    assert onay is False
    assert "eksik" in mesaj


def test_non_numeric_set_home_coordinates_are_rejected(drone, security_layer):
    """ Sayısal olmayan ev koordinatlarının reddedildiğini doğrular """
    onay, mesaj = security_layer.validate_and_execute(drone, "set_home", {"x": "sol", "y": 5})
    assert onay is False
    assert "Geçersiz koordinat" in mesaj
    assert drone.home_x == 0.0


# === 3. GEOFENCE SINIR DEĞERLERİ ===
@pytest.mark.parametrize("direction,distance,beklenen_onay", [
    ("doğu", 50, True),    # tam sınırda — izinli
    ("doğu", 51, False),   # sınırın 1m dışı — engelli
    ("batı", 50, True),
    ("batı", 51, False),
    ("kuzey", 50, True),
    ("kuzey", 51, False),
    ("güney", 51, False),
])
def test_geofence_boundary_is_inclusive(drone, security_layer, direction, distance, beklenen_onay):
    """ Geofence'in tam sınırda izin verip sınırı aşınca engellediğini doğrular """
    drone.in_air = True
    onay, _ = security_layer.validate_and_execute(
        drone, "move", {"direction": direction, "distance": distance})
    assert onay is beklenen_onay


def test_north_south_geofence_enforced_with_simulator_active(sim_drone, security_layer):
    """ Fizik simülatörü BAĞLIYKEN kuzey/güney geofence'inin çalıştığını doğrular.

    Regresyon: get_telemetry() drone.y'yi 0'a sabitlediği için kuzey/güney
    geofence'i gerçek çalışma koşulunda hiç tetiklenmiyordu — araç sınırsız
    kuzeye uçabiliyordu. Testler sim'i kapattığı için bu hata gizli kalmıştı.
    """
    if sim_drone.sim is None:
        pytest.skip("Simülatör mevcut değil")

    sim_drone.checklist_completed = True
    security_layer.validate_and_execute(sim_drone, "takeoff", 10)

    onay1, _ = security_layer.validate_and_execute(
        sim_drone, "move", {"direction": "kuzey", "distance": 40})
    assert onay1 is True

    # 40 + 40 = 80m > 50m geofence -> engellenmeli
    onay2, mesaj = security_layer.validate_and_execute(
        sim_drone, "move", {"direction": "kuzey", "distance": 40})
    assert onay2 is False
    assert "GEOFENCE İHLALİ" in mesaj
    assert sim_drone.y == 40.0


def test_geofence_uses_target_not_current_position(drone, security_layer):
    """ Kontrolün mevcut konuma değil HEDEF konuma bakarak yapıldığını doğrular """
    drone.in_air = True
    drone.x = 45.0
    onay, mesaj = security_layer.validate_and_execute(
        drone, "move", {"direction": "doğu", "distance": 10})
    assert onay is False
    assert "55" in mesaj  # hedef 55m olarak raporlanmalı


# === 4. GEÇERSİZ YÖNLER ===
@pytest.mark.parametrize("direction", ["yukarı", "aşağı", "kuzeydoğu", "up", "xyz"])
def test_invalid_direction_is_rejected(drone, security_layer, direction):
    """ Desteklenmeyen yönlerin drone'a ulaşmadan reddedildiğini doğrular """
    drone.in_air = True
    onay, mesaj = security_layer.validate_and_execute(
        drone, "move", {"direction": direction, "distance": 10})
    assert onay is False
    assert "Geçersiz yön" in mesaj
    assert (drone.x, drone.y) == (0.0, 0.0)


def test_direction_matching_is_case_insensitive(drone, security_layer):
    """ Büyük harfli yönlerin de kabul edildiğini doğrular """
    drone.in_air = True
    onay, _ = security_layer.validate_and_execute(
        drone, "move", {"direction": "KUZEY", "distance": 10})
    assert onay is True


# === 5. MESAFE VE İRTİFA ARALIKLARI ===
@pytest.mark.parametrize("distance", [0, -5, -0.1])
def test_non_positive_distance_is_rejected(drone, security_layer, distance):
    """ Sıfır veya negatif mesafenin reddedildiğini doğrular """
    drone.in_air = True
    onay, mesaj = security_layer.validate_and_execute(
        drone, "move", {"direction": "kuzey", "distance": distance})
    assert onay is False
    assert "pozitif" in mesaj


@pytest.mark.parametrize("altitude", [0, -10])
def test_non_positive_altitude_is_rejected(drone, security_layer, altitude):
    """ Sıfır veya negatif hedef irtifanın reddedildiğini doğrular """
    drone.checklist_completed = True
    onay, mesaj = security_layer.validate_and_execute(drone, "takeoff", altitude)
    assert onay is False
    assert "pozitif" in mesaj


def test_takeoff_missing_parameter_is_rejected(drone, security_layer):
    """ İrtifa belirtilmeden kalkışın reddedildiğini doğrular """
    drone.checklist_completed = True
    onay, mesaj = security_layer.validate_and_execute(drone, "takeoff", None)
    assert onay is False
    assert "belirtilmedi" in mesaj


# === 6. BATARYA EŞİK SINIRLARI ===
def test_battery_exactly_at_critical_threshold_is_allowed(drone, security_layer):
    """ Tam eşikteki (%20) bataryanın kritik SAYILMADIĞINI doğrular (kural: < 20) """
    drone.battery = 20
    drone.checklist_completed = True
    onay, _ = security_layer.validate_and_execute(drone, "takeoff", 15)
    assert onay is True


def test_battery_one_below_critical_blocks_takeoff(drone, security_layer):
    """ Eşiğin 1 birim altındaki bataryanın kalkışı engellediğini doğrular """
    drone.battery = 19
    drone.checklist_completed = True
    onay, mesaj = security_layer.validate_and_execute(drone, "takeoff", 15)
    assert onay is False
    assert "kritik" in mesaj


def test_telemetry_readable_at_critical_battery(drone, security_layer):
    """ Kritik bataryada bile telemetri okumasına izin verildiğini doğrular """
    drone.battery = 5
    onay, _ = security_layer.validate_and_execute(drone, "get_telemetry", None)
    assert onay is True


def test_rth_allowed_at_critical_battery(drone, security_layer):
    """ Kritik bataryada eve dönüşe izin verildiğini doğrular """
    drone.battery = 5
    drone.in_air = True
    onay, _ = security_layer.validate_and_execute(drone, "return_to_home", None)
    assert onay is True


def test_move_blocked_at_critical_battery(drone, security_layer):
    """ Kritik bataryada yatay hareketin engellendiğini doğrular """
    drone.battery = 10
    drone.in_air = True
    onay, mesaj = security_layer.validate_and_execute(
        drone, "move", {"direction": "kuzey", "distance": 5})
    assert onay is False
    assert "kritik" in mesaj


# === 7. DİNAMİK İRTİFA SINIRI EŞİKLERİ ===
@pytest.mark.parametrize("battery,altitude,beklenen_onay", [
    (50, 50, True),    # tam %50 -> yüksek limit (kural: < 50 düşük sayılır)
    (50, 51, False),
    (49, 20, True),    # %50 altı -> 20m limit
    (49, 21, False),
    (100, 50, True),
    (100, 50.1, False),
])
def test_dynamic_altitude_limit_thresholds(drone, security_layer, battery, altitude, beklenen_onay):
    """ Batarya seviyesine göre irtifa limitinin doğru daraldığını doğrular """
    drone.battery = battery
    drone.checklist_completed = True
    onay, _ = security_layer.validate_and_execute(drone, "takeoff", altitude)
    assert onay is beklenen_onay


# === 8. RÜZGAR EŞİKLERİ ===
@pytest.mark.parametrize("wind,beklenen_onay", [
    (29.9, True), (30.0, True), (30.1, False), (100.0, False),
])
def test_wind_limit_threshold(drone, security_layer, wind, beklenen_onay):
    """ Rüzgar limitinin tam eşikte izin verip aşınca engellediğini doğrular """
    drone.checklist_completed = True
    drone.wind_speed = wind
    onay, _ = security_layer.validate_and_execute(drone, "takeoff", 10)
    assert onay is beklenen_onay


def test_landing_allowed_in_high_wind(drone, security_layer):
    """ Şiddetli rüzgarda kalkış yasakken inişe izin verildiğini doğrular """
    drone.in_air = True
    drone.wind_speed = 80.0
    onay, _ = security_layer.validate_and_execute(drone, "land", None)
    assert onay is True


# === 9. DURUM GEÇERLİLİĞİ ===
def test_land_blocked_when_already_on_ground(drone, security_layer):
    """ Yerdeyken iniş komutunun anlamsız olduğu için reddedildiğini doğrular """
    onay, mesaj = security_layer.validate_and_execute(drone, "land", None)
    assert onay is False
    assert "zaten havada değil" in mesaj


def test_checklist_blocked_while_airborne(drone, security_layer):
    """ Havadayken kalkış öncesi kontrol listesinin onaylanamadığını doğrular """
    drone.in_air = True
    onay, mesaj = security_layer.validate_and_execute(drone, "complete_checklist", None)
    assert onay is False
    assert "zaten havada" in mesaj


def test_altitude_change_in_air_skips_checklist_requirement(drone, security_layer):
    """ Zaten havadayken irtifa değişiminin checklist istemediğini doğrular """
    drone.in_air = True
    drone.checklist_completed = False
    onay, _ = security_layer.validate_and_execute(drone, "takeoff", 30)
    assert onay is True


# === 10. FAILSAFE ÖNCELİĞİ ===
@pytest.mark.parametrize("action,param", [
    ("takeoff", 10), ("land", None), ("move", {"direction": "kuzey", "distance": 5}),
    ("return_to_home", None), ("get_telemetry", None),
    ("set_home", {"x": 1, "y": 1}), ("complete_checklist", None),
])
def test_failsafe_blocks_every_action(drone, security_layer, action, param):
    """ Failsafe kilidinin istisnasız TÜM eylemleri engellediğini doğrular """
    drone.emergency_stop()
    onay, mesaj = security_layer.validate_and_execute(drone, action, param)
    assert onay is False
    assert "Failsafe" in mesaj


# === 11. TELEMETRİ ENJEKSİYONU ===
def test_supplied_telemetry_is_used_instead_of_live_read(drone, security_layer):
    """ Dışarıdan verilen telemetrinin canlı okuma yerine kullanıldığını doğrular.

    Ana döngü zincir boyunca tek bir anlık görüntü geçirdiği için, kararların
    o görüntüye göre verilmesi gerekir.
    """
    drone.battery = 100
    donuk_telemetri = drone.get_telemetry()
    donuk_telemetri["battery"] = 5  # kritik seviyeyi zorla

    onay, mesaj = security_layer.validate_and_execute(
        drone, "takeoff", 10, telemetri=donuk_telemetri)
    assert onay is False
    assert "kritik" in mesaj
