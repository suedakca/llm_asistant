# tests/test_faults.py
""" Arıza enjeksiyonu ve bozulmuş donanım koşullarındaki güvenlik davranışı.

    Arızalar deterministiktir (sabit sapma değerleri), bu yüzden testler
    tekrarlanabilir.
"""
import pytest

import faults as f
from faults import FaultInjector


@pytest.fixture
def injector():
    return FaultInjector()


TEMIZ_TELEMETRI = {"x": 10.0, "y": 20.0, "altitude": 30.0, "battery": 80,
                   "in_air": True, "mode": "GUIDED", "failsafe": False,
                   "checklist_completed": True, "wind_speed": 3.0}


# === 1. ARIZA YÖNETİMİ ===
def test_no_faults_active_by_default(injector):
    """ Varsayılan durumda hiçbir arızanın aktif olmadığını doğrular """
    assert injector.any_active is False
    assert injector.motor_health == 1.0
    assert injector.battery_drain_multiplier == 1.0
    assert injector.altitude_drift == 0.0


@pytest.mark.parametrize("fault_type", f.FAULT_TYPES)
def test_inject_and_clear_each_fault(injector, fault_type):
    """ Her arıza tipinin enjekte edilip temizlenebildiğini doğrular """
    injector.inject(fault_type)
    assert injector.is_active(fault_type) is True

    injector.clear(fault_type)
    assert injector.is_active(fault_type) is False


def test_unknown_fault_type_raises(injector):
    """ Bilinmeyen arıza tipinin sessizce yok sayılmadığını doğrular """
    with pytest.raises(ValueError, match="Bilinmeyen arıza tipi"):
        injector.inject("uzayli_saldirisi")


def test_clear_all_removes_every_fault(injector):
    """ Toplu temizlemenin tüm arızaları kaldırdığını doğrular """
    for t in f.FAULT_TYPES:
        injector.inject(t)
    assert injector.any_active is True

    injector.clear()
    assert injector.any_active is False


def test_motor_health_is_clamped(injector):
    """ Motor sağlığının 0-1 aralığına kırpıldığını doğrular """
    injector.inject(f.MOTOR_DEGRADATION, health=5.0)
    assert injector.motor_health == 1.0

    injector.inject(f.MOTOR_DEGRADATION, health=-3.0)
    assert injector.motor_health == 0.0


def test_battery_multiplier_cannot_reduce_drain(injector):
    """ Batarya arızasının tüketimi AZALTAMAYACAĞINI doğrular (çarpan >= 1) """
    injector.inject(f.BATTERY_FAULT, drain_multiplier=0.1)
    assert injector.battery_drain_multiplier == 1.0


# === 2. TELEMETRİ BOZULMASI ===
def test_health_fields_present_even_without_faults(injector):
    """ Sağlık alanlarının arıza yokken de döndüğünü doğrular (tek sözleşme) """
    t = injector.apply_to_telemetry(TEMIZ_TELEMETRI)
    assert t["gps_healthy"] is True
    assert t["motor_health"] == 1.0
    assert t["active_faults"] == []


def test_clean_telemetry_is_unchanged(injector):
    """ Arıza yokken telemetri değerlerinin bozulmadığını doğrular """
    t = injector.apply_to_telemetry(TEMIZ_TELEMETRI)
    for anahtar in ("x", "y", "altitude", "battery"):
        assert t[anahtar] == TEMIZ_TELEMETRI[anahtar]


def test_gps_loss_freezes_position(injector):
    """ GPS kaybında konumun son bilinen değerde donduğunu doğrular """
    injector.apply_to_telemetry(TEMIZ_TELEMETRI)  # son iyi konum: (10, 20)

    injector.inject(f.GPS_LOSS)
    hareketli = dict(TEMIZ_TELEMETRI, x=45.0, y=48.0)
    t = injector.apply_to_telemetry(hareketli)

    assert t["gps_healthy"] is False
    assert t["x"] == 10.0  # gerçek 45.0 ama sensör donmuş
    assert t["y"] == 20.0


def test_sensor_drift_offsets_reported_altitude(injector):
    """ Sensör sapmasının raporlanan irtifayı kaydırdığını doğrular """
    injector.inject(f.SENSOR_DRIFT, drift_m=7.5)
    t = injector.apply_to_telemetry(TEMIZ_TELEMETRI)

    assert t["altitude"] == 37.5  # gerçek 30.0 + 7.5 sapma
    assert t["altitude_drift"] == 7.5


def test_active_faults_are_listed_in_telemetry(injector):
    """ Aktif arızaların telemetride listelendiğini doğrular """
    injector.inject(f.GPS_LOSS)
    injector.inject(f.MOTOR_DEGRADATION, health=0.3)

    t = injector.apply_to_telemetry(TEMIZ_TELEMETRI)
    assert set(t["active_faults"]) == {f.GPS_LOSS, f.MOTOR_DEGRADATION}
    assert t["motor_health"] == 0.3


# === 3. ENGELLEME KURALLARI ===
@pytest.mark.parametrize("action", ["move", "return_to_home", "set_home"])
def test_gps_loss_blocks_navigation(injector, action):
    """ GPS kaybında navigasyon gerektiren komutların engellendiğini doğrular """
    injector.inject(f.GPS_LOSS)
    gerekce = injector.blocking_reason(action, TEMIZ_TELEMETRI)

    assert gerekce is not None
    assert "GPS SİNYAL KAYBI" in gerekce


@pytest.mark.parametrize("fault_type", f.FAULT_TYPES)
def test_landing_is_always_permitted(injector, fault_type):
    """ HANGİ arıza olursa olsun inişin asla engellenmediğini doğrular.

    Kritik güvenlik ilkesi: arıza hâlinde pilotun elinden aracı indirme
    imkânı alınamaz.
    """
    injector.inject(fault_type, **({"health": 0.0} if fault_type == f.MOTOR_DEGRADATION else {}))
    assert injector.blocking_reason("land", TEMIZ_TELEMETRI) is None


@pytest.mark.parametrize("fault_type", f.FAULT_TYPES)
def test_telemetry_read_is_always_permitted(injector, fault_type):
    """ Arıza hâlinde telemetri okumanın engellenmediğini doğrular """
    injector.inject(fault_type)
    assert injector.blocking_reason("get_telemetry", TEMIZ_TELEMETRI) is None


def test_severe_motor_degradation_blocks_takeoff_and_move(injector):
    """ Ciddi motor güç kaybında kalkış ve manevranın yasaklandığını doğrular """
    injector.inject(f.MOTOR_DEGRADATION, health=0.3)

    assert "MOTOR GÜÇ KAYBI" in injector.blocking_reason("takeoff", TEMIZ_TELEMETRI)
    assert "MOTOR GÜÇ KAYBI" in injector.blocking_reason("move", TEMIZ_TELEMETRI)


def test_mild_motor_degradation_is_tolerated(injector):
    """ Eşiğin üstündeki hafif güç kaybının uçuşu engellemediğini doğrular """
    injector.inject(f.MOTOR_DEGRADATION, health=0.9)
    assert injector.blocking_reason("takeoff", TEMIZ_TELEMETRI) is None


def test_large_sensor_drift_blocks_takeoff(injector):
    """ Büyük irtifa sapmasında kalkışın engellendiğini doğrular """
    injector.inject(f.SENSOR_DRIFT, drift_m=10.0)
    assert "SENSÖRÜ SAPMASI" in injector.blocking_reason("takeoff", TEMIZ_TELEMETRI)


def test_small_sensor_drift_is_tolerated(injector):
    """ Küçük sapmanın kalkışı engellemediğini doğrular """
    injector.inject(f.SENSOR_DRIFT, drift_m=1.0)
    assert injector.blocking_reason("takeoff", TEMIZ_TELEMETRI) is None


def test_negative_drift_is_evaluated_by_magnitude(injector):
    """ Aşağı yönlü sapmanın da büyüklüğüne göre değerlendirildiğini doğrular """
    injector.inject(f.SENSOR_DRIFT, drift_m=-10.0)
    assert injector.blocking_reason("takeoff", TEMIZ_TELEMETRI) is not None


# === 4. CONFIG'TEN EŞİK AYARI ===
def test_thresholds_are_configurable():
    """ Güvenlik eşiklerinin config'ten ezilebildiğini doğrular """
    sikı = FaultInjector({"min_safe_motor_health": 0.95, "max_safe_altitude_drift": 0.5})

    sikı.inject(f.MOTOR_DEGRADATION, health=0.9)  # varsayılanda serbest olurdu
    assert sikı.blocking_reason("takeoff", TEMIZ_TELEMETRI) is not None

    sikı.clear()
    sikı.inject(f.SENSOR_DRIFT, drift_m=1.0)      # varsayılanda serbest olurdu
    assert sikı.blocking_reason("takeoff", TEMIZ_TELEMETRI) is not None


# === 5. DRONE VE GÜVENLİK KATMANIYLA ENTEGRASYON ===
def test_drone_telemetry_exposes_fault_state(drone):
    """ Arıza durumunun drone telemetrisine yansıdığını doğrular """
    drone.faults.inject(f.MOTOR_DEGRADATION, health=0.4)
    t = drone.get_telemetry()

    assert t["motor_health"] == 0.4
    assert f.MOTOR_DEGRADATION in t["active_faults"]


def test_security_layer_blocks_move_on_gps_loss(drone, security_layer):
    """ Güvenlik katmanının GPS kaybında hareketi reddettiğini doğrular """
    drone.in_air = True
    drone.faults.inject(f.GPS_LOSS)

    onay, mesaj = security_layer.validate_and_execute(
        drone, "move", {"direction": "kuzey", "distance": 10})

    assert onay is False
    assert "GPS SİNYAL KAYBI" in mesaj
    assert drone.y == 0.0  # hareket uygulanmadı


def test_security_layer_allows_landing_on_gps_loss(drone, security_layer):
    """ GPS kaybında inişe izin verildiğini doğrular """
    drone.in_air = True
    drone.altitude = 20.0
    drone.faults.inject(f.GPS_LOSS)

    onay, _ = security_layer.validate_and_execute(drone, "land", None)
    assert onay is True
    assert drone.in_air is False


def test_security_layer_blocks_takeoff_on_motor_fault(drone, security_layer):
    """ Motor arızasında kalkışın reddedildiğini doğrular """
    drone.checklist_completed = True
    drone.faults.inject(f.MOTOR_DEGRADATION, health=0.2)

    onay, mesaj = security_layer.validate_and_execute(drone, "takeoff", 10)
    assert onay is False
    assert "MOTOR GÜÇ KAYBI" in mesaj
    assert drone.in_air is False


def test_failsafe_takes_priority_over_fault_message(drone, security_layer):
    """ Failsafe kilidinin arıza mesajından önce geldiğini doğrular """
    drone.faults.inject(f.GPS_LOSS)
    drone.emergency_stop()

    onay, mesaj = security_layer.validate_and_execute(
        drone, "move", {"direction": "kuzey", "distance": 5})
    assert onay is False
    assert "Failsafe" in mesaj


def test_battery_fault_accelerates_drain(drone):
    """ Batarya arızasının tüketimi hızlandırdığını doğrular """
    import time
    drone.takeoff(10)
    baslangic = drone.battery

    drone.faults.inject(f.BATTERY_FAULT, drain_multiplier=10.0)
    drone.takeoff_time = time.time() - 2  # 2 sn * 0.5 * 10 = 10 birim

    drone.get_telemetry()
    assert baslangic - drone.battery == 10


def test_clearing_fault_restores_normal_operation(drone, security_layer):
    """ Arıza giderildiğinde sistemin normale döndüğünü doğrular """
    drone.checklist_completed = True
    drone.faults.inject(f.MOTOR_DEGRADATION, health=0.2)
    assert security_layer.validate_and_execute(drone, "takeoff", 10)[0] is False

    drone.faults.clear(f.MOTOR_DEGRADATION)
    onay, mesaj = security_layer.validate_and_execute(drone, "takeoff", 10)
    assert onay is True, f"Arıza giderildikten sonra hâlâ engelli: {mesaj}"


# === 6. FİZİK MOTORU ETKİSİ ===
def test_motor_degradation_prevents_altitude_hold():
    """ Ciddi güç kaybında aracın irtifasını koruyamadığını doğrular """
    from simulator import DroneSimulator

    s = DroneSimulator()
    s.wind_speed = 0.0
    s.in_air = True
    s.target_y = 20.0
    for _ in range(3000):
        s.update_physics(0.01)
    saglikli_irtifa = s.y
    assert saglikli_irtifa == pytest.approx(20.0, abs=0.5)

    # Motorlar ağırlığı taşıyamayacak seviyeye düşürülür
    s.motor_health = 0.3
    for _ in range(2000):
        s.update_physics(0.01)

    assert s.y < saglikli_irtifa - 1.0, "Güç kaybına rağmen irtifa korunuyor"
