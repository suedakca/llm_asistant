# tests/conftest.py
""" Tüm test modülleri tarafından paylaşılan fikstürler. """
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
        "geofence_boundary": 50.0,
        "max_wind_speed": 30.0,
        "battery_drain_per_second": 0.5,
        "simulated_wind_speed": 3.0,
    }


@pytest.fixture
def security_layer(mock_config):
    """ Her testten önce temiz bir güvenlik katmanı oluşturur """
    return SecurityLayer(mock_config)


@pytest.fixture
def drone(mock_config):
    """ Deterministik birim testler için simülatörsüz drone.

    Fizik motoru bağlıyken irtifa/konum sürekli değiştiği için testlerde
    devre dışı bırakılır; simülatörle entegrasyon `sim_drone` ile test edilir.
    """
    d = Drone(mock_config)
    d.sim = None
    return d


@pytest.fixture
def sim_drone(mock_config):
    """ Fizik simülatörü bağlı drone — gerçek çalışma koşulunu temsil eder.

    `global_simulator` süreç genelinde tek nesne olduğu için her testten
    önce durumu sıfırlanır, aksi halde testler birbirini etkiler.
    """
    d = Drone(mock_config)
    if d.sim is not None:
        sim = d.sim
        sim.x = sim.y = sim.vx = sim.vy = 0.0
        sim.theta = sim.omega = 0.0
        sim.target_x = sim.target_y = 0.0
        sim.in_air = False
        sim.failsafe = False
        sim.checklist_completed = False
        sim.battery = 100.0
        sim.mode = "DISARMED"
        sim.trail_history = []
        sim.gui_logs = []
    return d
