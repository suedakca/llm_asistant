# tests/test_telemetry.py
""" Telemetri zaman serisi kaydı testleri.

    Kayıt 60 FPS'lik render döngüsünden çağrıldığı için iki şey kritiktir:
    örnekleme hızı sınırı ve tampon davranışı. İkisi de burada ölçülür.
"""
import json

import pytest

from telemetry import TelemetryRecorder, load_session


@pytest.fixture
def kayit_yolu(tmp_path):
    return tmp_path / "telemetri.json"


@pytest.fixture
def recorder(kayit_yolu):
    # buffer_size=1 -> her örnek anında diske yazılır (test edilebilirlik)
    return TelemetryRecorder(session_id="oturum-1", filename=str(kayit_yolu),
                             sample_hz=10.0, buffer_size=1)


def _satirlari_oku(yol):
    return [json.loads(s) for s in yol.read_text(encoding="utf-8").splitlines() if s.strip()]


def _telemetri(**overrides):
    t = {"x": 1.0, "y": 2.0, "altitude": 15.0, "battery": 88, "in_air": True,
         "mode": "GUIDED", "failsafe": False, "wind_speed": 3.0,
         "gps_healthy": True, "motor_health": 1.0, "active_faults": []}
    t.update(overrides)
    return t


# === 1. KAYIT İÇERİĞİ ===
def test_record_writes_all_fields(recorder, kayit_yolu):
    """ Örneğin tüm alanlarıyla kaydedildiğini doğrular """
    recorder.record(_telemetri())

    kayitlar = _satirlari_oku(kayit_yolu)
    assert len(kayitlar) == 1
    k = kayitlar[0]
    assert k["session_id"] == "oturum-1"
    assert k["x"] == 1.0 and k["y"] == 2.0
    assert k["altitude"] == 15.0
    assert k["battery"] == 88
    assert k["in_air"] is True
    assert k["mode"] == "GUIDED"
    assert "zaman_damgasi" in k


def test_record_includes_fault_state(recorder, kayit_yolu):
    """ Arıza durumunun kaydedildiğini doğrular.

    Uçuş sonrası "bu anomali arızadan mı kaynaklandı?" sorusunun
    yanıtlanabilmesi buna bağlı.
    """
    recorder.record(_telemetri(gps_healthy=False, motor_health=0.4,
                               active_faults=["gps_loss", "motor_degradation"]))

    k = _satirlari_oku(kayit_yolu)[0]
    assert k["gps_healthy"] is False
    assert k["motor_health"] == 0.4
    assert k["active_faults"] == ["gps_loss", "motor_degradation"]


def test_missing_telemetry_fields_get_defaults(recorder, kayit_yolu):
    """ Eksik alanların çökme yerine varsayılana düştüğünü doğrular """
    recorder.record({"x": 5.0})

    k = _satirlari_oku(kayit_yolu)[0]
    assert k["x"] == 5.0
    assert k["altitude"] == 0.0
    assert k["gps_healthy"] is True
    assert k["mode"] == "UNKNOWN"


# === 2. ÖRNEKLEME HIZI SINIRI ===
def test_tick_respects_sample_rate(recorder):
    """ 60 FPS döngüden çağrılsa da yalnızca örnekleme hızında kayıt alındığını doğrular """
    # 10 Hz -> 0.1 sn aralık. 1 saniyelik simülasyon = 60 kare.
    for _ in range(60):
        recorder.tick(1 / 60.0, _telemetri())

    # ~10 örnek beklenir, 60 değil
    assert 9 <= recorder.sample_count <= 11


def test_tick_returns_true_only_when_sampled(recorder):
    """ tick()'in yalnızca kayıt aldığında True döndüğünü doğrular """
    assert recorder.tick(0.01, _telemetri()) is False  # aralık dolmadı
    assert recorder.tick(0.2, _telemetri()) is True    # aralık doldu


def test_slow_frames_still_sample(recorder):
    """ Kare süresi örnekleme aralığından uzunsa da kayıt alındığını doğrular """
    assert recorder.tick(0.5, _telemetri()) is True
    assert recorder.sample_count == 1


def test_zero_hz_records_every_tick(kayit_yolu):
    """ sample_hz=0 verildiğinde her tick'in kaydedildiğini doğrular """
    r = TelemetryRecorder("oturum-1", filename=str(kayit_yolu), sample_hz=0, buffer_size=1)
    for _ in range(5):
        r.tick(0.001, _telemetri())
    assert r.sample_count == 5


# === 3. TAMPON DAVRANIŞI ===
def test_buffer_delays_disk_writes(kayit_yolu):
    """ Tampon dolmadan diske yazılmadığını doğrular (döngü bloke olmasın) """
    r = TelemetryRecorder("oturum-1", filename=str(kayit_yolu), sample_hz=100, buffer_size=5)

    for _ in range(3):
        r.record(_telemetri())
    assert not kayit_yolu.exists()  # henüz yazılmadı

    for _ in range(2):
        r.record(_telemetri())
    assert len(_satirlari_oku(kayit_yolu)) == 5  # tampon dolunca yazıldı


def test_close_flushes_pending_samples(kayit_yolu):
    """ Oturum kapanışında tamponda bekleyenlerin kaybolmadığını doğrular """
    r = TelemetryRecorder("oturum-1", filename=str(kayit_yolu), sample_hz=100, buffer_size=50)
    for _ in range(3):
        r.record(_telemetri())

    r.close()
    assert len(_satirlari_oku(kayit_yolu)) == 3


def test_write_failure_does_not_crash_flight(tmp_path, capsys):
    """ Disk yazma hatasının uçuşu kesmediğini doğrular """
    olmayan = tmp_path / "olmayan_klasor" / "t.json"
    r = TelemetryRecorder("oturum-1", filename=str(olmayan), buffer_size=1)

    r.record(_telemetri())  # istisna fırlatmamalı
    assert "TELEMETRİ KAYIT HATASI" in capsys.readouterr().out


def test_buffer_does_not_grow_after_write_failure(tmp_path):
    """ Yazma hatası tekrarlansa da tamponun sınırsız büyümediğini doğrular """
    olmayan = tmp_path / "olmayan_klasor" / "t.json"
    r = TelemetryRecorder("oturum-1", filename=str(olmayan), buffer_size=2)

    for _ in range(20):
        r.record(_telemetri())
    assert len(r._buffer) < 5


# === 4. DOSYA ARŞİVLEME ===
def test_oversized_file_is_rotated(kayit_yolu):
    """ Dosya sınırı aşınca arşivlendiğini doğrular (disk dolmasın) """
    kayit_yolu.write_text("x" * 3000, encoding="utf-8")

    r = TelemetryRecorder("oturum-1", filename=str(kayit_yolu),
                          buffer_size=1, max_file_mb=0.001)  # ~1 KB sınır
    r.record(_telemetri())

    arsiv = kayit_yolu.parent / (kayit_yolu.name + ".1")
    assert arsiv.exists()
    assert len(_satirlari_oku(kayit_yolu)) == 1  # yeni dosya temiz başladı


# === 5. OKUMA (load_session) ===
def test_load_session_returns_latest_session(kayit_yolu):
    """ Oturum belirtilmezse en son oturumun döndüğünü doğrular """
    r1 = TelemetryRecorder("eski-oturum", filename=str(kayit_yolu), buffer_size=1)
    r1.record(_telemetri(x=1.0))
    r2 = TelemetryRecorder("yeni-oturum", filename=str(kayit_yolu), buffer_size=1)
    r2.record(_telemetri(x=2.0))
    r2.record(_telemetri(x=3.0))

    ornekler = load_session(str(kayit_yolu))
    assert len(ornekler) == 2
    assert [o["x"] for o in ornekler] == [2.0, 3.0]


def test_load_session_filters_by_id(kayit_yolu):
    """ Belirli bir oturumun seçilebildiğini doğrular """
    r1 = TelemetryRecorder("oturum-a", filename=str(kayit_yolu), buffer_size=1)
    r1.record(_telemetri())
    r2 = TelemetryRecorder("oturum-b", filename=str(kayit_yolu), buffer_size=1)
    r2.record(_telemetri())

    assert len(load_session(str(kayit_yolu), session_id="oturum-a")) == 1


def test_load_session_handles_missing_file(tmp_path):
    """ Dosya yokken boş liste döndüğünü doğrular """
    assert load_session(str(tmp_path / "yok.json")) == []


def test_load_session_skips_corrupted_lines(kayit_yolu):
    """ Bozuk satırların okumayı çökertmediğini doğrular """
    r = TelemetryRecorder("oturum-1", filename=str(kayit_yolu), buffer_size=1)
    r.record(_telemetri(x=1.0))
    with open(kayit_yolu, "a", encoding="utf-8") as f:
        f.write("{bozuk json\n")
    r.record(_telemetri(x=2.0))

    ornekler = load_session(str(kayit_yolu))
    assert [o["x"] for o in ornekler] == [1.0, 2.0]


def test_load_session_handles_empty_file(kayit_yolu):
    """ Boş dosyanın çökme üretmediğini doğrular """
    kayit_yolu.write_text("", encoding="utf-8")
    assert load_session(str(kayit_yolu)) == []


# === 6. GERÇEK UÇUŞLA ENTEGRASYON ===
def test_recorder_captures_real_flight_trajectory(kayit_yolu, sim_drone, security_layer):
    """ Kaydın gerçek uçuş izini (fizik dâhil) yakaladığını doğrular.

    Asıl kazanım bu: komut logundan tahmin değil, aracın gerçekten
    bulunduğu konum kaydedilir.
    """
    if sim_drone.sim is None:
        pytest.skip("Simülatör mevcut değil")

    sim = sim_drone.sim
    sim.wind_speed = 0.0
    r = TelemetryRecorder("ucus-1", filename=str(kayit_yolu), sample_hz=20.0, buffer_size=1)

    sim_drone.checklist_completed = True
    security_layer.validate_and_execute(sim_drone, "takeoff", 20)

    # Fizik motorunu ilerlet ve eş zamanlı kaydet
    for _ in range(600):  # 6 saniye
        sim.update_physics(0.01)
        r.tick(0.01, sim_drone.get_telemetry())
    r.close()

    ornekler = load_session(str(kayit_yolu))
    assert len(ornekler) > 10

    irtifalar = [o["altitude"] for o in ornekler]
    # Tırmanış kademeli olmalı: ilk örnek son örnekten belirgin düşük
    assert irtifalar[0] < irtifalar[-1]
    # Ara değerler var — yani komut logundaki gibi 0'dan 20'ye sıçrama değil
    assert any(0 < a < 20 for a in irtifalar), "Ara irtifa değerleri kaydedilmemiş"
