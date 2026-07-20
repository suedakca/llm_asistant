# telemetry.py
""" Telemetri zaman serisi kaydı. """
import json
import os
from datetime import datetime


class TelemetryRecorder:
    """ Telemetriyi sabit örnekleme hızında JSONLines olarak kaydeder. """

    def __init__(self, session_id, filename="telemetri_kaydi.json",
                 sample_hz=5.0, buffer_size=20, max_file_mb=25.0):
        self.session_id = str(session_id)
        self.filename = filename
        self.sample_interval = 1.0 / float(sample_hz) if sample_hz > 0 else 0.0
        self.buffer_size = int(buffer_size)
        self.max_file_bytes = float(max_file_mb) * 1024 * 1024

        self._buffer = []
        self._time_since_sample = 0.0
        self.sample_count = 0

    def tick(self, dt, telemetry):
        """ Örnekleme aralığı dolduğunda telemetriyi kaydeder. """
        self._time_since_sample += dt
        if self._time_since_sample < self.sample_interval:
            return False

        self._time_since_sample -= self.sample_interval
        if self._time_since_sample > self.sample_interval:
            self._time_since_sample = 0.0

        self.record(telemetry)
        return True

    def record(self, telemetry):
        """ Tek bir telemetri örneğini tampona ekler. """
        ornek = {
            "session_id": self.session_id,
            "zaman_damgasi": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
            "x": telemetry.get("x", 0.0),
            "y": telemetry.get("y", 0.0),
            "altitude": telemetry.get("altitude", 0.0),
            "battery": telemetry.get("battery", 0),
            "in_air": telemetry.get("in_air", False),
            "mode": telemetry.get("mode", "UNKNOWN"),
            "failsafe": telemetry.get("failsafe", False),
            "wind_speed": telemetry.get("wind_speed", 0.0),
            "gps_healthy": telemetry.get("gps_healthy", True),
            "motor_health": telemetry.get("motor_health", 1.0),
            "active_faults": telemetry.get("active_faults", []),
        }
        self._buffer.append(ornek)
        self.sample_count += 1

        if len(self._buffer) >= self.buffer_size:
            self.flush()

    def flush(self):
        """ Tamponu diske yazar. """
        if not self._buffer:
            return

        try:
            self._rotate_if_oversized()
            with open(self.filename, "a", encoding="utf-8") as f:
                for ornek in self._buffer:
                    f.write(json.dumps(ornek, ensure_ascii=False) + "\n")
            self._buffer.clear()
        except Exception as e:
            print(f"[TELEMETRİ KAYIT HATASI] Yazma başarısız: {e}")
            self._buffer.clear()

    def _rotate_if_oversized(self):
        """ Dosya boyutu sınırı aşarsa eski dosyayı arşivler. """
        try:
            if os.path.exists(self.filename) and os.path.getsize(self.filename) > self.max_file_bytes:
                arsiv = self.filename + ".1"
                if os.path.exists(arsiv):
                    os.remove(arsiv)
                os.rename(self.filename, arsiv)
        except OSError:
            pass

    def close(self):
        self.flush()


def load_session(filename="telemetri_kaydi.json", session_id=None):
    """ Kaydedilmiş telemetri verisini okur. """
    if not os.path.exists(filename):
        return []

    ornekler = []
    try:
        with open(filename, "r", encoding="utf-8") as f:
            for satir in f:
                satir = satir.strip()
                if not satir:
                    continue
                try:
                    ornekler.append(json.loads(satir))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []

    if not ornekler:
        return []

    hedef = str(session_id) if session_id is not None else ornekler[-1].get("session_id")
    return [o for o in ornekler if o.get("session_id") == hedef]
