# tests/test_security.py
import pytest
from drone import Drone
from security import SecurityLayer

@pytest.fixture
def mock_config():
    """ Testler için standart sınır parametrelerini dönen fikstür """
    return {
        "base_max_altitude": 50.0,
        "low_battery_max_altitude": 20.0,
        "critical_battery": 20,
        "geofence_boundary": 50.0
    }

@pytest.fixture
def security_layer(mock_config):
    """ Her testten önce temiz bir güvenlik katmanı oluşturur """
    return SecurityLayer(mock_config)

@pytest.fixture
def drone(mock_config):
    """ Testler için temiz bir drone nesnesi oluşturur """
    # drone_settings olarak mock_config'in aynısını paslıyoruz (katsayı dahil edilebilir)
    cfg = mock_config.copy()
    cfg["battery_drain_per_second"] = 0.5
    return Drone(cfg)


# === 1. TEST: GEOGENCE (SANAL SINIR) SINIR TESTLERİ ===
def test_geofence_within_bounds(drone, security_layer):
    """ Sınırlar içindeki geçerli yatay hareketlerin onaylandığını doğrular """
    drone.in_air = True
    drone.altitude = 10.0
    
    # Merkezden Doğuya 40 metre (Sınır 50)
    onay, mesaj = security_layer.validate_and_execute(drone, "move", {"direction": "doğu", "distance": 40})
    assert onay is True
    assert drone.x == 40.0

def test_geofence_violation(drone, security_layer):
    """ Sınırı (50m) aşan hareketlerin güvenlik tarafından engellendiğini doğrular """
    drone.in_air = True
    drone.altitude = 10.0
    drone.x = 40.0
    
    # 40m konumundayken 15m daha Doğuya gitmek X=55 yapar ve Geofence'i deler
    onay, mesaj = security_layer.validate_and_execute(drone, "move", {"direction": "doğu", "distance": 15})
    assert onay is False
    assert "GEOFENCE İHLALİ" in mesaj
    assert drone.x == 40.0  # Konumun değişmediğini doğrula (Defensive)


# === 2. TEST: KRİTİK BATARYA KORUMA TESTLERİ ===
def test_takeoff_blocked_at_critical_battery(drone, security_layer):
    """ Kritik batarya eşiğinin altındayken (%20) kalkışın kesinlikle engellendiğini doğrular """
    drone.battery = 15  # Kritik eşik %20
    
    onay, mesaj = security_layer.validate_and_execute(drone, "takeoff", 10)
    assert onay is False
    assert "Batarya kritik seviyede" in mesaj
    assert drone.in_air is False

def test_land_allowed_at_critical_battery(drone, security_layer):
    """ Kritik bataryada uçuş yasaklanırken acil inişe izin verildiğini doğrular """
    drone.in_air = True
    drone.altitude = 15.0
    drone.battery = 10
    
    onay, mesaj = security_layer.validate_and_execute(drone, "land", None)
    assert onay is True
    assert drone.in_air is False


# === 3. TEST: DİNAMİK İRTİFA SINIRLANDIRMA TESTLERİ ===
def test_altitude_limit_at_high_battery(drone, security_layer):
    """ Batarya %50'nin üzerindeyken 50 metreye kadar tırmanışa izin verildiğini doğrular """
    drone.battery = 80
    onay, _ = security_layer.validate_and_execute(drone, "takeoff", 45)
    assert onay is True

def test_altitude_limit_at_low_battery(drone, security_layer):
    """ Batarya %50'nin altına düşünce irtifa sınırının dinamik olarak 20m'ye düşürüldüğünü doğrular """
    drone.battery = 45  # %50'nin altı
    
    # 25 metreye kalkış isteği 20m sınırına takılmalı
    onay, mesaj = security_layer.validate_and_execute(drone, "takeoff", 25)
    assert onay is False
    assert "güvenli uçuş üst sınırını" in mesaj


# === 4. TEST: DURUM TABANLI DEFANSİF KONTROLLER ===
def test_move_action_blocked_on_ground(drone, security_layer):
    """ Araç yerdeyken yatay hareket komutlarının reddedildiğini doğrular """
    drone.in_air = False
    
    onay, mesaj = security_layer.validate_and_execute(drone, "move", {"direction": "kuzey", "distance": 10})
    assert onay is False
    assert "Yerdeyken yatay hareket yapılamaz" in mesaj


# === 5. TEST: ACİL DURDURMA (FAILSAFE) KİLİTLENME TESTİ ===
def test_failsafe_lock_blocks_everything(drone, security_layer):
    """ Sistem bir kez Failsafe moduna girdiğinde hiçbir komutun işlenemediğini doğrular """
    drone.emergency_stop()  # Sistemi kilitledik
    
    onay, mesaj = security_layer.validate_and_execute(drone, "takeoff", 10)
    assert onay is False
    assert "Failsafe modunda kilitli" in mesaj