# faults.py
""" Kontrollü arıza enjeksiyonu.

    Güvenlik katmanının bozulmuş sensör ve donanım koşullarında da
    doğru davrandığını test etmek için kullanılır.
"""

GPS_LOSS = "gps_loss"
SENSOR_DRIFT = "sensor_drift"
MOTOR_DEGRADATION = "motor_degradation"
BATTERY_FAULT = "battery_fault"

FAULT_TYPES = (GPS_LOSS, SENSOR_DRIFT, MOTOR_DEGRADATION, BATTERY_FAULT)

FAULT_LABELS = {
    GPS_LOSS: "GPS SİNYAL KAYBI",
    SENSOR_DRIFT: "İRTİFA SENSÖRÜ SAPMASI",
    MOTOR_DEGRADATION: "MOTOR GÜÇ KAYBI",
    BATTERY_FAULT: "BATARYA ARIZASI",
}

MIN_SAFE_MOTOR_HEALTH = 0.6
MAX_SAFE_DRIFT_M = 3.0


class FaultInjector:
    """ Aktif arızaları tutar ve telemetri/fizik üzerindeki etkilerini uygular. """

    def __init__(self, config=None):
        self.active = {}
        self._last_known_x = 0.0
        self._last_known_y = 0.0

        ayarlar = config or {}
        self.min_safe_motor_health = float(
            ayarlar.get("min_safe_motor_health", MIN_SAFE_MOTOR_HEALTH))
        self.max_safe_drift_m = float(
            ayarlar.get("max_safe_altitude_drift", MAX_SAFE_DRIFT_M))

    def inject(self, fault_type, **params):
        """ Arızayı etkinleştirir. Bilinmeyen tip ValueError fırlatır. """
        if fault_type not in FAULT_TYPES:
            raise ValueError(
                f"Bilinmeyen arıza tipi: '{fault_type}'. Geçerli tipler: {', '.join(FAULT_TYPES)}")

        varsayilanlar = {
            GPS_LOSS: {},
            SENSOR_DRIFT: {"drift_m": 5.0},
            MOTOR_DEGRADATION: {"health": 0.5},
            BATTERY_FAULT: {"drain_multiplier": 5.0},
        }[fault_type]

        ayarlar = dict(varsayilanlar)
        ayarlar.update(params)

        if fault_type == MOTOR_DEGRADATION:
            ayarlar["health"] = max(0.0, min(1.0, float(ayarlar["health"])))
        if fault_type == BATTERY_FAULT:
            ayarlar["drain_multiplier"] = max(1.0, float(ayarlar["drain_multiplier"]))

        self.active[fault_type] = ayarlar
        return f"[ARIZA ENJEKTE EDİLDİ] {FAULT_LABELS[fault_type]} — {ayarlar}"

    def clear(self, fault_type=None):
        """ Tek bir arızayı veya (tip verilmezse) tümünü temizler. """
        if fault_type is None:
            self.active.clear()
            return "[ARIZALAR TEMİZLENDİ] Tüm sistemler normale döndü."
        self.active.pop(fault_type, None)
        return f"[ARIZA TEMİZLENDİ] {FAULT_LABELS.get(fault_type, fault_type)}"

    def is_active(self, fault_type):
        return fault_type in self.active

    @property
    def any_active(self):
        return bool(self.active)

    @property
    def motor_health(self):
        if MOTOR_DEGRADATION not in self.active:
            return 1.0
        return self.active[MOTOR_DEGRADATION]["health"]

    @property
    def battery_drain_multiplier(self):
        if BATTERY_FAULT not in self.active:
            return 1.0
        return self.active[BATTERY_FAULT]["drain_multiplier"]

    @property
    def altitude_drift(self):
        if SENSOR_DRIFT not in self.active:
            return 0.0
        return float(self.active[SENSOR_DRIFT]["drift_m"])

    def apply_to_telemetry(self, telemetry):
        """ Ham telemetriye aktif arıza bozulmalarını uygular. """
        bozulmus = dict(telemetry)

        bozulmus["gps_healthy"] = not self.is_active(GPS_LOSS)
        bozulmus["motor_health"] = self.motor_health
        bozulmus["altitude_drift"] = self.altitude_drift
        bozulmus["active_faults"] = sorted(self.active.keys())

        if self.is_active(GPS_LOSS):
            bozulmus["x"] = self._last_known_x
            bozulmus["y"] = self._last_known_y
        else:
            self._last_known_x = telemetry.get("x", 0.0)
            self._last_known_y = telemetry.get("y", 0.0)

        if self.is_active(SENSOR_DRIFT):
            bozulmus["altitude"] = round(
                float(telemetry.get("altitude", 0.0)) + self.altitude_drift, 2)

        return bozulmus

    def blocking_reason(self, action, telemetry):
        """ Bu eylem mevcut arıza durumunda yasaklanmalı mı?

        İniş ve telemetri okuma her zaman serbesttir.
        """
        if action in ("land", "get_telemetry"):
            return None

        if self.is_active(GPS_LOSS) and action in ("move", "return_to_home", "set_home"):
            return ("GPS SİNYAL KAYBI: Konum bilgisi güvenilir değil, "
                    "navigasyon gerektiren komutlar uygulanamaz. Derhal iniş yapın (land).")

        if self.is_active(MOTOR_DEGRADATION):
            saglik = self.motor_health
            if saglik < self.min_safe_motor_health and action in ("takeoff", "move"):
                return (f"MOTOR GÜÇ KAYBI: Motor sağlığı %{saglik * 100:.0f} — "
                        f"güvenli eşiğin (%{self.min_safe_motor_health * 100:.0f}) altında. "
                        "Kalkış ve manevra yasak, iniş yapın (land).")

        if self.is_active(SENSOR_DRIFT):
            sapma = abs(self.altitude_drift)
            if sapma > self.max_safe_drift_m and action == "takeoff":
                return (f"İRTİFA SENSÖRÜ SAPMASI: Sensör {sapma:.1f}m sapma gösteriyor "
                        f"(güvenli sınır {self.max_safe_drift_m}m). İrtifa komutları güvenilir değil.")

        return None
