# tests/test_logger.py
""" Uçuş kayıt (JSONLines) ve oturum özet raporu testleri.

    Tüm testler tmp_path kullanır — gerçek uclus_loglari.json'a dokunulmaz.
"""
import json

import pytest

from logger import ProjectLogger


@pytest.fixture
def log_path(tmp_path):
    return tmp_path / "test_loglari.json"


@pytest.fixture
def project_logger(log_path):
    return ProjectLogger(filename=str(log_path))


def _satirlari_oku(log_path):
    """ JSONLines dosyasını sözlük listesine çevirir """
    return [json.loads(s) for s in log_path.read_text(encoding="utf-8").splitlines() if s.strip()]


def _telemetri(**overrides):
    t = {"altitude": 0.0, "x": 0.0, "y": 0.0, "battery": 100}
    t.update(overrides)
    return t


# === 1. KAYIT YAZMA ===
def test_log_action_writes_jsonlines_entry(project_logger, log_path):
    """ Her kaydın tek satırlık geçerli JSON olarak yazıldığını doğrular """
    project_logger.log_action("oturum-1", "10 metreye çık", "takeoff", 10, True, "Başarılı")

    kayitlar = _satirlari_oku(log_path)
    assert len(kayitlar) == 1
    k = kayitlar[0]
    assert k["session_id"] == "oturum-1"
    assert k["kullanici_komutu"] == "10 metreye çık"
    assert k["llm_yorumu"] == {"action": "takeoff", "parameter": 10}
    assert k["guvenlik_onayi"] is True
    assert k["sonuc_mesaji"] == "Başarılı"
    assert "zaman_damgasi" in k


def test_log_action_appends_without_overwriting(project_logger, log_path):
    """ Ardışık kayıtların üzerine yazmadan eklendiğini doğrular """
    for i in range(5):
        project_logger.log_action("oturum-1", f"komut {i}", "move", None, True, "ok")
    assert len(_satirlari_oku(log_path)) == 5


def test_log_action_preserves_turkish_characters(project_logger, log_path):
    """ Türkçe karakterlerin escape edilmeden okunabilir yazıldığını doğrular """
    project_logger.log_action("oturum-1", "güneye git", "move", None, False, "Geçersiz yön")

    ham = log_path.read_text(encoding="utf-8")
    assert "güneye git" in ham
    assert "\\u" not in ham


def test_log_action_serializes_dict_parameters(project_logger, log_path):
    """ Sözlük parametrelerin (move/set_home) bozulmadan kaydedildiğini doğrular """
    param = {"direction": "kuzey", "distance": 20}
    project_logger.log_action("oturum-1", "kuzeye git", "move", param, True, "ok")
    assert _satirlari_oku(log_path)[0]["llm_yorumu"]["parameter"] == param


def test_log_action_records_rejected_commands(project_logger, log_path):
    """ Reddedilen komutların da denetim izi için kaydedildiğini doğrular """
    project_logger.log_action("oturum-1", "100 metreye çık", "takeoff", 100, False, "GÜVENLİK REDDİ")
    assert _satirlari_oku(log_path)[0]["guvenlik_onayi"] is False


def test_log_action_survives_unwritable_file(tmp_path, capsys):
    """ Yazma hatasının uçuşu kesmediğini (yalnızca uyarı bastığını) doğrular """
    okunamaz_yol = tmp_path / "olmayan_klasor" / "log.json"
    lg = ProjectLogger(filename=str(okunamaz_yol))

    lg.log_action("oturum-1", "komut", "takeoff", 10, True, "ok")  # istisna fırlatmamalı
    assert "LOG HATASI" in capsys.readouterr().out


# === 2. ESKİ FORMAT GEÇİŞİ ===
def test_legacy_json_array_format_is_reset(log_path, capsys):
    """ Eski JSON dizi formatındaki dosyanın sıfırlandığını doğrular """
    log_path.write_text('[{"eski": "kayit"}]', encoding="utf-8")

    ProjectLogger(filename=str(log_path))
    assert not log_path.exists()
    assert "Eski log formatı" in capsys.readouterr().out


def test_jsonlines_format_is_preserved(project_logger, log_path):
    """ Geçerli JSONLines dosyasının silinmediğini doğrular """
    project_logger.log_action("oturum-1", "komut", "takeoff", 10, True, "ok")

    ProjectLogger(filename=str(log_path))  # yeniden başlat
    assert log_path.exists()
    assert len(_satirlari_oku(log_path)) == 1


# === 3. OTURUM ÖZET RAPORU ===
def test_summary_counts_approved_and_rejected(project_logger, capsys):
    """ Özet raporun onaylanan/reddedilen sayımlarını doğru yaptığını doğrular """
    project_logger.log_action("oturum-1", "a", "takeoff", 10, True, "ok")
    project_logger.log_action("oturum-1", "b", "move", None, True, "ok")
    project_logger.log_action("oturum-1", "c", "takeoff", 999, False, "reddedildi")

    project_logger.print_session_summary("oturum-1", _telemetri())
    cikti = capsys.readouterr().out
    assert "Bu Oturumdaki Komutlar  : 3" in cikti
    assert "Onaylanan Eylemler     : 2" in cikti
    assert "Reddedilen Güvensiz    : 1" in cikti


def test_summary_isolates_sessions(project_logger, capsys):
    """ Raporun yalnızca ilgili oturumun kayıtlarını saydığını doğrular """
    project_logger.log_action("oturum-1", "a", "takeoff", 10, True, "ok")
    project_logger.log_action("oturum-2", "b", "takeoff", 20, True, "ok")
    project_logger.log_action("oturum-2", "c", "move", None, True, "ok")

    project_logger.print_session_summary("oturum-1", _telemetri())
    assert "Bu Oturumdaki Komutlar  : 1" in capsys.readouterr().out


def test_summary_reports_max_altitude_not_final(project_logger, capsys):
    """ Raporun son irtifayı değil ulaşılan EN YÜKSEK irtifayı bildirdiğini doğrular """
    project_logger.log_action("oturum-1", "a", "takeoff", 10, True, "ok")
    project_logger.log_action("oturum-1", "b", "takeoff", 45, True, "ok")
    project_logger.log_action("oturum-1", "c", "land", None, True, "ok")

    project_logger.print_session_summary("oturum-1", _telemetri(altitude=0.0))
    cikti = capsys.readouterr().out
    assert "En Yüksek İrtifa: 45.0m" in cikti
    assert "Kapanış Anındaki İrtifa : 0.0m" in cikti


def test_summary_ignores_rejected_altitudes(project_logger, capsys):
    """ Reddedilen kalkışların en yüksek irtifaya sayılmadığını doğrular """
    project_logger.log_action("oturum-1", "a", "takeoff", 10, True, "ok")
    project_logger.log_action("oturum-1", "b", "takeoff", 500, False, "GÜVENLİK REDDİ")

    project_logger.print_session_summary("oturum-1", _telemetri())
    assert "En Yüksek İrtifa: 10.0m" in capsys.readouterr().out


def test_summary_handles_empty_session(project_logger, capsys):
    """ Hiç komut verilmemiş oturumun rapor üretirken çökmediğini doğrular """
    project_logger.print_session_summary("bos-oturum", _telemetri())
    cikti = capsys.readouterr().out
    assert "Bu Oturumdaki Komutlar  : 0" in cikti
    assert "En Yüksek İrtifa: 0.0m" in cikti


def test_summary_handles_missing_log_file(log_path, capsys):
    """ Log dosyası hiç yokken raporun çökmediğini doğrular """
    lg = ProjectLogger(filename=str(log_path))
    lg.print_session_summary("oturum-1", _telemetri())
    assert "UÇUŞ ÖZET RAPORU" in capsys.readouterr().out


def test_summary_skips_corrupted_lines(project_logger, log_path, capsys):
    """ Bozuk JSON satırlarının raporu çökertmeyip atlandığını doğrular """
    project_logger.log_action("oturum-1", "a", "takeoff", 10, True, "ok")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write("{bu gecerli json degil\n")
    project_logger.log_action("oturum-1", "b", "land", None, True, "ok")

    project_logger.print_session_summary("oturum-1", _telemetri())
    assert "Bu Oturumdaki Komutlar  : 2" in capsys.readouterr().out


def test_summary_handles_non_numeric_altitude_parameter(project_logger, capsys):
    """ İrtifa parametresi sayısal olmayan kaydın raporu bozmadığını doğrular """
    project_logger.log_action("oturum-1", "a", "takeoff", "yüksek", True, "ok")
    project_logger.log_action("oturum-1", "b", "takeoff", 25, True, "ok")

    project_logger.print_session_summary("oturum-1", _telemetri())
    assert "En Yüksek İrtifa: 25.0m" in capsys.readouterr().out


def test_summary_prints_final_telemetry(project_logger, capsys):
    """ Kapanış telemetrisinin rapora yansıdığını doğrular """
    project_logger.log_action("oturum-1", "a", "move", None, True, "ok")

    project_logger.print_session_summary("oturum-1", _telemetri(x=12.0, y=-8.0, battery=64))
    cikti = capsys.readouterr().out
    assert "X: 12.0" in cikti and "Y: -8.0" in cikti
    assert "%64" in cikti
