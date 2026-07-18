# tests/test_integration.py
""" Uçtan uca görev senaryoları: güvenlik katmanı + drone birlikte.

    Birim testler tek kuralı ölçer; buradaki testler çok adımlı görev
    zincirlerinin bütünsel davranışını ölçer.
"""
import pytest


def calistir(security, drone, zincir):
    """ Bir komut zincirini main.py'deki yürütme motoru gibi işler.

    Dönen: (sonuçlar, tamamlandi_mi, engel_mesaji)
    """
    sonuclar = []
    for gorev in zincir:
        onay, sonuc = security.validate_and_execute(
            drone, gorev["action"], gorev.get("parameter"))
        if not onay:
            return sonuclar, False, sonuc
        sonuclar.append(sonuc)
    return sonuclar, True, None


# === 1. BAŞARILI GÖREVLER ===
def test_complete_mission_lifecycle(drone, security_layer):
    """ Tam bir görev döngüsünün baştan sona çalıştığını doğrular """
    zincir = [
        {"action": "complete_checklist", "parameter": None},
        {"action": "takeoff", "parameter": 20},
        {"action": "move", "parameter": {"direction": "kuzey", "distance": 30}},
        {"action": "move", "parameter": {"direction": "doğu", "distance": 20}},
        {"action": "land", "parameter": None},
    ]
    sonuclar, tamamlandi, _ = calistir(security_layer, drone, zincir)

    assert tamamlandi is True
    assert len(sonuclar) == 5
    assert drone.in_air is False
    assert (drone.x, drone.y) == (20.0, 30.0)
    assert drone.checklist_completed is False  # iniş sonrası sıfırlanır


def test_mission_with_custom_home_and_rth(drone, security_layer):
    """ Özel ev noktası belirlenip oraya dönüldüğünü doğrular """
    zincir = [
        {"action": "set_home", "parameter": {"x": 10, "y": 10}},
        {"action": "complete_checklist", "parameter": None},
        {"action": "takeoff", "parameter": 15},
        {"action": "move", "parameter": {"direction": "doğu", "distance": 30}},
        {"action": "return_to_home", "parameter": None},
    ]
    _, tamamlandi, _ = calistir(security_layer, drone, zincir)

    assert tamamlandi is True
    assert (drone.x, drone.y) == (10.0, 10.0)
    assert drone.in_air is False


def test_multi_stage_climb(drone, security_layer):
    """ Ardışık tırmanışların mutlak irtifa olarak uygulandığını doğrular """
    zincir = [
        {"action": "complete_checklist", "parameter": None},
        {"action": "takeoff", "parameter": 10},
        {"action": "takeoff", "parameter": 25},
        {"action": "takeoff", "parameter": 45},
    ]
    _, tamamlandi, _ = calistir(security_layer, drone, zincir)

    assert tamamlandi is True
    assert drone.altitude == 45.0


# === 2. ZİNCİR YARIDA KESİLMESİ ===
def test_chain_stops_at_first_violation(drone, security_layer):
    """ İhlal anında zincirin kesildiğini ve sonraki komutların çalışmadığını doğrular """
    zincir = [
        {"action": "complete_checklist", "parameter": None},
        {"action": "takeoff", "parameter": 20},
        {"action": "move", "parameter": {"direction": "doğu", "distance": 80}},  # geofence ihlali
        {"action": "land", "parameter": None},  # çalışmamalı
    ]
    sonuclar, tamamlandi, engel = calistir(security_layer, drone, zincir)

    assert tamamlandi is False
    assert "GEOFENCE" in engel
    assert len(sonuclar) == 2
    assert drone.in_air is True   # iniş uygulanmadı
    assert drone.x == 0.0         # hareket uygulanmadı


def test_takeoff_without_checklist_stops_chain_immediately(drone, security_layer):
    """ Checklist onaysız zincirin ilk adımda kesildiğini doğrular """
    zincir = [
        {"action": "takeoff", "parameter": 20},
        {"action": "move", "parameter": {"direction": "kuzey", "distance": 10}},
    ]
    sonuclar, tamamlandi, engel = calistir(security_layer, drone, zincir)

    assert tamamlandi is False
    assert sonuclar == []
    assert "kontrol listesi" in engel
    assert drone.in_air is False


def test_partial_state_is_preserved_after_interruption(drone, security_layer):
    """ Zincir kesilse de o ana kadarki geçerli hareketlerin korunduğunu doğrular """
    zincir = [
        {"action": "complete_checklist", "parameter": None},
        {"action": "takeoff", "parameter": 20},
        {"action": "move", "parameter": {"direction": "kuzey", "distance": 40}},
        {"action": "move", "parameter": {"direction": "kuzey", "distance": 40}},  # 80m -> ihlal
    ]
    _, tamamlandi, _ = calistir(security_layer, drone, zincir)

    assert tamamlandi is False
    assert drone.y == 40.0  # ilk hareket geçerli kaldı


# === 3. ACİL DURUM SENARYOLARI ===
def test_emergency_stop_mid_mission_locks_system(drone, security_layer):
    """ Görev ortasında acil durdurmanın sistemi kilitlediğini doğrular """
    calistir(security_layer, drone, [
        {"action": "complete_checklist", "parameter": None},
        {"action": "takeoff", "parameter": 30},
    ])
    assert drone.in_air is True

    drone.emergency_stop()

    _, tamamlandi, engel = calistir(security_layer, drone, [
        {"action": "move", "parameter": {"direction": "kuzey", "distance": 10}}])
    assert tamamlandi is False
    assert "Failsafe" in engel


def test_reboot_restores_operability_after_failsafe(drone, security_layer):
    """ Failsafe sonrası reboot ile sistemin yeniden uçurulabildiğini doğrular """
    calistir(security_layer, drone, [
        {"action": "complete_checklist", "parameter": None},
        {"action": "takeoff", "parameter": 30},
    ])
    drone.emergency_stop()
    drone.reboot()

    _, tamamlandi, engel = calistir(security_layer, drone, [
        {"action": "complete_checklist", "parameter": None},
        {"action": "takeoff", "parameter": 20},
    ])
    assert tamamlandi is True, f"Reboot sonrası uçuş engellendi: {engel}"
    assert drone.in_air is True


def test_battery_depletion_forces_landing_only(drone, security_layer):
    """ Batarya kritiğe düşünce yalnızca iniş/RTH'ye izin verildiğini doğrular """
    calistir(security_layer, drone, [
        {"action": "complete_checklist", "parameter": None},
        {"action": "takeoff", "parameter": 30},
    ])
    drone.battery = 15  # kritik seviye

    _, hareket_ok, _ = calistir(security_layer, drone, [
        {"action": "move", "parameter": {"direction": "kuzey", "distance": 5}}])
    assert hareket_ok is False

    _, inis_ok, _ = calistir(security_layer, drone, [{"action": "land", "parameter": None}])
    assert inis_ok is True
    assert drone.in_air is False


# === 4. DEĞİŞEN KOŞULLAR ===
def test_altitude_limit_tightens_as_battery_drains(drone, security_layer):
    """ Uçuş sırasında batarya düşünce irtifa limitinin daraldığını doğrular """
    drone.checklist_completed = True

    onay1, _ = security_layer.validate_and_execute(drone, "takeoff", 45)
    assert onay1 is True  # %95 batarya -> 50m limit

    drone.battery = 40  # batarya düştü -> 20m limit
    onay2, mesaj = security_layer.validate_and_execute(drone, "takeoff", 45)
    assert onay2 is False
    assert "sınırı aşmaktadır" in mesaj


def test_wind_can_ground_an_active_mission(drone, security_layer):
    """ Rüzgar yükselince hareketin durup inişe izin verildiğini doğrular """
    calistir(security_layer, drone, [
        {"action": "complete_checklist", "parameter": None},
        {"action": "takeoff", "parameter": 20},
    ])

    drone.wind_speed = 45.0  # fırtına

    _, hareket_ok, engel = calistir(security_layer, drone, [
        {"action": "move", "parameter": {"direction": "kuzey", "distance": 10}}])
    assert hareket_ok is False
    assert "RÜZGAR" in engel

    _, inis_ok, _ = calistir(security_layer, drone, [{"action": "land", "parameter": None}])
    assert inis_ok is True


# === 5. KÖTÜ LLM ÇIKTISINA KARŞI DAYANIKLILIK ===
def test_chain_with_hallucinated_action_is_rejected_safely(drone, security_layer):
    """ LLM uydurma bir eylem üretirse zincirin güvenle kesildiğini doğrular """
    zincir = [
        {"action": "complete_checklist", "parameter": None},
        {"action": "takeoff", "parameter": 20},
        {"action": "barrel_roll", "parameter": None},  # uydurma
        {"action": "land", "parameter": None},
    ]
    sonuclar, tamamlandi, engel = calistir(security_layer, drone, zincir)

    assert tamamlandi is False
    assert "Tanınmayan eylem" in engel
    assert len(sonuclar) == 2


def test_chain_with_malformed_parameters_does_not_crash(drone, security_layer):
    """ Bozuk parametreli zincirin çökmeden reddedildiğini doğrular """
    zincir = [
        {"action": "complete_checklist", "parameter": None},
        {"action": "takeoff", "parameter": "çok yükseğe"},
    ]
    _, tamamlandi, engel = calistir(security_layer, drone, zincir)

    assert tamamlandi is False
    assert "Geçersiz irtifa" in engel
    assert drone.in_air is False


def test_empty_chain_is_handled(drone, security_layer):
    """ Boş komut zincirinin sorunsuz işlendiğini doğrular """
    sonuclar, tamamlandi, _ = calistir(security_layer, drone, [])
    assert tamamlandi is True
    assert sonuclar == []


# === 6. SİMÜLATÖR BAĞLIYKEN ===
def test_mission_with_physics_simulator_attached(sim_drone, security_layer):
    """ Fizik simülatörü bağlıyken görev zincirinin çalıştığını doğrular """
    if sim_drone.sim is None:
        pytest.skip("Simülatör mevcut değil")

    zincir = [
        {"action": "complete_checklist", "parameter": None},
        {"action": "takeoff", "parameter": 20},
        {"action": "move", "parameter": {"direction": "doğu", "distance": 15}},
    ]
    _, tamamlandi, engel = calistir(security_layer, sim_drone, zincir)

    assert tamamlandi is True, f"Simülatörle görev başarısız: {engel}"
    assert sim_drone.sim.target_y == 20.0   # fizik motoruna irtifa hedefi iletildi
    assert sim_drone.sim.target_x == 15.0   # yatay hedef iletildi
    assert sim_drone.x == 15.0              # mantıksal görev koordinatı korundu
