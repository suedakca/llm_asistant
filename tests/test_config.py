# tests/test_config.py
""" config.yaml ile kodun beklentilerinin uyumunu doğrulayan testler.

    Amaç: config'te bir anahtar yeniden adlandırılır veya silinirse, bunun
    uçuş sırasında KeyError olarak değil, burada test hatası olarak görülmesi.
"""
import os

import pytest
import yaml

from drone import Drone
from security import SecurityLayer

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config.yaml")


@pytest.fixture(scope="module")
def config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_config_file_is_valid_yaml(config):
    """ config.yaml'ın ayrıştırılabildiğini doğrular """
    assert isinstance(config, dict)


def test_required_top_level_sections_exist(config):
    """ Ana bölümlerin mevcut olduğunu doğrular """
    assert {"drone_settings", "llm_settings", "safety_settings"} <= set(config)


def test_security_layer_accepts_real_config(config):
    """ Güvenlik katmanının gerçek config ile sorunsuz kurulduğunu doğrular """
    s = SecurityLayer(config["drone_settings"])
    assert s.base_max_altitude > 0
    assert s.geofence_boundary > 0


def test_drone_accepts_real_config(config):
    """ Drone'un gerçek config ile sorunsuz kurulduğunu doğrular """
    d = Drone(config["drone_settings"])
    assert d.drain_rate > 0


def test_llm_settings_have_required_keys(config):
    """ Asistanın beklediği LLM anahtarlarının var olduğunu doğrular """
    llm = config["llm_settings"]
    assert "model_name" in llm and llm["model_name"]
    assert 0.0 <= float(llm["temperature"]) <= 2.0
    assert isinstance(llm["high_risk_actions"], list) and llm["high_risk_actions"]


def test_high_risk_actions_are_known_actions(config):
    """ Yüksek riskli eylemlerin güvenlik katmanınca tanınan eylemler olduğunu doğrular """
    from security import ALLOWED_ACTIONS
    assert set(config["llm_settings"]["high_risk_actions"]) <= ALLOWED_ACTIONS


def test_emergency_keywords_are_defined(config):
    """ Acil durdurma kelimelerinin tanımlı ve büyük harfli olduğunu doğrular.

    main.py karşılaştırmayı user_command.upper() ile yaptığı için küçük harfli
    bir anahtar kelime asla eşleşmez.
    """
    kelimeler = config["safety_settings"]["emergency_keywords"]
    assert kelimeler
    for k in kelimeler:
        assert k == k.upper(), f"'{k}' büyük harfli olmalı, aksi halde hiç eşleşmez"


# === TUTARLILIK KONTROLLERİ ===
def test_low_battery_altitude_is_stricter_than_base(config):
    """ Düşük batarya irtifa limitinin normal limitten DAHA kısıtlayıcı olduğunu doğrular """
    d = config["drone_settings"]
    assert float(d["low_battery_max_altitude"]) < float(d["base_max_altitude"])


def test_critical_battery_is_sane_percentage(config):
    """ Kritik batarya eşiğinin makul bir yüzde olduğunu doğrular """
    kritik = int(config["drone_settings"]["critical_battery"])
    assert 0 < kritik < 50  # dinamik irtifa kuralı %50'yi eşik alır


def test_simulated_wind_is_below_safety_limit(config):
    """ Varsayılan simüle rüzgarın limiti aşmadığını doğrular.

    Aşarsa sistem varsayılan hâlde hiçbir kalkışa izin vermez.
    """
    d = config["drone_settings"]
    assert float(d["simulated_wind_speed"]) < float(d["max_wind_speed"])


def test_telemetry_recording_settings_are_sane(config):
    """ Telemetri kayıt ayarlarının makul olduğunu doğrular """
    kayit = config.get("telemetry_recording", {})
    assert isinstance(kayit.get("enabled", True), bool)
    hz = float(kayit.get("sample_hz", 5.0))
    assert 0 <= hz <= 60, "Örnekleme hızı render döngüsünü (60 FPS) aşmamalı"
    assert kayit.get("filename", "t.json") != config.get("log_file", "uclus_loglari.json")


def test_fault_thresholds_are_wired_to_injector(config):
    """ Config'teki arıza eşiklerinin FaultInjector'a gerçekten ulaştığını doğrular.

    Bu ayarların sahte (kullanılmayan) olmadığının kanıtı.
    """
    from faults import FaultInjector

    ariza_cfg = config.get("fault_injection", {})
    inj = FaultInjector(ariza_cfg)

    if "min_safe_motor_health" in ariza_cfg:
        assert inj.min_safe_motor_health == float(ariza_cfg["min_safe_motor_health"])
    if "max_safe_altitude_drift" in ariza_cfg:
        assert inj.max_safe_drift_m == float(ariza_cfg["max_safe_altitude_drift"])


def test_fault_thresholds_are_in_valid_range(config):
    """ Arıza eşiklerinin anlamlı aralıkta olduğunu doğrular """
    ariza = config.get("fault_injection", {})
    assert 0.0 < float(ariza.get("min_safe_motor_health", 0.6)) <= 1.0
    assert float(ariza.get("max_safe_altitude_drift", 3.0)) > 0


def test_default_config_allows_takeoff(config):
    """ Varsayılan config ile temiz bir drone'un kalkış yapabildiğini doğrular.

    Bu test, config'teki bir değişikliğin sistemi baştan kullanılamaz hâle
    getirmesini engelleyen bir emniyet ağıdır.
    """
    d = Drone(config["drone_settings"])
    d.sim = None
    s = SecurityLayer(config["drone_settings"])

    onay_c, _ = s.validate_and_execute(d, "complete_checklist", None)
    assert onay_c is True

    onay_t, mesaj = s.validate_and_execute(d, "takeoff", 10)
    assert onay_t is True, f"Varsayılan config kalkışı engelliyor: {mesaj}"
