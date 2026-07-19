# tests/test_assistant.py
""" LLM asistanının ayrıştırma ve gözlemci mantığı testleri.

    Gemini istemcisi tamamen sahtelenir — testler ağ bağlantısı veya API
    anahtarı gerektirmez, yalnızca bizim ayrıştırma/savunma kodumuzu ölçer.
"""
import json
from types import SimpleNamespace

import pytest

import assistant as assistant_module
from assistant import PilotAssistant


class FakeChat:
    """ client.chats.create(...) tarafından dönen sahte sohbet oturumu """

    def __init__(self, responses):
        self._responses = list(responses)
        self.sent_messages = []

    def send_message(self, message):
        self.sent_messages.append(message)
        cevap = self._responses.pop(0) if self._responses else "[]"
        if isinstance(cevap, BaseException):
            raise cevap
        return SimpleNamespace(text=cevap)


class FakeModels:
    """ client.models.generate_content(...) için sahte model uç noktası """

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def generate_content(self, model, contents, config):
        self.calls.append(contents)
        cevap = self._responses.pop(0) if self._responses else "{}"
        if isinstance(cevap, BaseException):
            raise cevap
        return SimpleNamespace(text=cevap)


class FakeClient:
    def __init__(self, chat_responses=(), model_responses=()):
        self.chat = FakeChat(chat_responses)
        self.models = FakeModels(model_responses)
        self.chats = SimpleNamespace(create=lambda **kwargs: self.chat)


@pytest.fixture
def llm_config():
    return {"model_name": "gemini-2.5-flash", "temperature": 0.1}


@pytest.fixture
def make_assistant(monkeypatch, llm_config):
    """ Sahte istemciyle donatılmış bir PilotAssistant üretir """
    def _make(chat_responses=(), model_responses=()):
        fake = FakeClient(chat_responses, model_responses)
        monkeypatch.setenv("GEMINI_API_KEY", "test-anahtari")
        monkeypatch.setattr(assistant_module.genai, "Client", lambda api_key: fake)
        a = PilotAssistant(llm_config)
        return a, fake
    return _make


TELEMETRI = {"altitude": 0.0, "battery": 100, "in_air": False, "x": 0.0, "y": 0.0}


# === 1. BAŞLATMA ===
def test_missing_api_key_raises(monkeypatch, llm_config):
    """ API anahtarı yokken açık bir hata verildiğini doğrular """
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        PilotAssistant(llm_config)


def test_config_is_applied(make_assistant):
    """ Model adı ve sıcaklığın config'ten alındığını doğrular """
    a, _ = make_assistant()
    assert a.model_name == "gemini-2.5-flash"
    assert a.temp == 0.1


# === 2. KOMUT AYRIŞTIRMA ===
def test_parses_valid_command_chain(make_assistant):
    """ Geçerli JSON zincirinin bozulmadan ayrıştırıldığını doğrular """
    zincir = [
        {"action": "takeoff", "parameter": 10},
        {"action": "move", "parameter": {"direction": "doğu", "distance": 20}},
        {"action": "land", "parameter": None},
    ]
    a, _ = make_assistant(chat_responses=[json.dumps(zincir)])

    assert a.parse_command("10 metreye çık, doğuya git, in", TELEMETRI) == zincir


def test_single_object_is_wrapped_in_list(make_assistant):
    """ LLM liste yerine tek nesne dönerse listeye sarmalandığını doğrular """
    a, _ = make_assistant(chat_responses=['{"action": "land", "parameter": null}'])

    sonuc = a.parse_command("iniş yap", TELEMETRI)
    assert isinstance(sonuc, list)
    assert sonuc == [{"action": "land", "parameter": None}]


@pytest.mark.parametrize("ham_cevap", [
    '```json\n[{"action": "land", "parameter": null}]\n```',
    '```\n[{"action": "land", "parameter": null}]\n```',
])
def test_markdown_code_fences_are_stripped(make_assistant, ham_cevap):
    """ Modelin eklediği markdown bloklarının temizlendiğini doğrular """
    a, _ = make_assistant(chat_responses=[ham_cevap])
    assert a.parse_command("iniş yap", TELEMETRI) == [{"action": "land", "parameter": None}]


def test_whitespace_is_tolerated(make_assistant):
    """ Baştaki/sondaki boşlukların ayrıştırmayı bozmadığını doğrular """
    a, _ = make_assistant(chat_responses=['\n\n  [{"action": "land", "parameter": null}]  \n'])
    assert a.parse_command("iniş", TELEMETRI) == [{"action": "land", "parameter": None}]


def test_malformed_json_returns_invalid_action(make_assistant):
    """ Bozuk JSON'un çökme yerine 'invalid' eylemine düştüğünü doğrular """
    a, _ = make_assistant(chat_responses=["bu json degil {{{"])
    assert a.parse_command("saçmalık", TELEMETRI) == [{"action": "invalid", "parameter": None}]


def test_api_exception_returns_invalid_action(make_assistant):
    """ API hatasının uçuşu kesmeyip 'invalid' döndüğünü doğrular """
    a, _ = make_assistant(chat_responses=[RuntimeError("ağ kesintisi")])
    assert a.parse_command("10 metreye çık", TELEMETRI) == [{"action": "invalid", "parameter": None}]


def test_empty_list_response_is_returned_as_is(make_assistant):
    """ Boş zincirin boş liste olarak döndüğünü doğrular """
    a, _ = make_assistant(chat_responses=["[]"])
    assert a.parse_command("merhaba", TELEMETRI) == []


# === 3. BAĞLAM AKTARIMI ===
def test_telemetry_is_sent_to_model(make_assistant):
    """ Modele güncel telemetrinin bağlam olarak verildiğini doğrular """
    a, fake = make_assistant(chat_responses=["[]"])
    telemetri = dict(TELEMETRI, battery=42, altitude=15.0)

    a.parse_command("nerede kaldık", telemetri)

    gonderilen = fake.chat.sent_messages[0]
    assert "TELEMETRİ" in gonderilen
    assert '"battery": 42' in gonderilen
    assert "PİLOT: nerede kaldık" in gonderilen


def test_chat_session_preserves_history(make_assistant):
    """ Aynı sohbet oturumunun korunduğunu (hafıza) doğrular """
    a, fake = make_assistant(chat_responses=["[]", "[]", "[]"])

    for komut in ["10 metreye çık", "biraz daha", "şimdi in"]:
        a.parse_command(komut, TELEMETRI)

    assert len(fake.chat.sent_messages) == 3


# === 4. GÖZLEMCİ (LLM 2) ===
def test_observer_approves_sufficient_battery(make_assistant):
    """ Gözlemcinin onay kararını ilettiğini doğrular """
    a, _ = make_assistant(model_responses=['{"decision": "APPROVED", "reason": "Batarya yeterli"}'])

    karar = a.observe_and_verify(TELEMETRI, [{"action": "takeoff", "parameter": 10}])
    assert karar["decision"] == "APPROVED"


def test_observer_vetoes_insufficient_battery(make_assistant):
    """ Gözlemcinin veto kararını gerekçesiyle ilettiğini doğrular """
    a, _ = make_assistant(model_responses=['{"decision": "VETOED", "reason": "Batarya yetersiz"}'])

    karar = a.observe_and_verify(dict(TELEMETRI, battery=8), [{"action": "takeoff", "parameter": 40}])
    assert karar["decision"] == "VETOED"
    assert "yetersiz" in karar["reason"]


def test_observer_fails_closed_on_api_error(make_assistant):
    """ Gözlemci ulaşılamazsa güvenli tarafa (VETO) düşüldüğünü doğrular """
    a, _ = make_assistant(model_responses=[RuntimeError("zaman aşımı")])

    karar = a.observe_and_verify(TELEMETRI, [{"action": "takeoff", "parameter": 10}])
    assert karar["decision"] == "VETOED"
    assert "bağlantı hatası" in karar["reason"]


def test_observer_fails_closed_on_malformed_json(make_assistant):
    """ Gözlemcinin bozuk yanıtında da VETO'ya düşüldüğünü doğrular """
    a, _ = make_assistant(model_responses=["json degil"])
    assert a.observe_and_verify(TELEMETRI, [])["decision"] == "VETOED"


def test_observer_veto_includes_failure_reason(make_assistant):
    """ Bağlantı hatasında gerekçenin loglanabilmesi için veto mesajına taşındığını doğrular """
    a, _ = make_assistant(model_responses=[RuntimeError("kota aşıldı")])

    karar = a.observe_and_verify(TELEMETRI, [])
    assert "kota aşıldı" in karar["reason"]


@pytest.mark.parametrize("kesme", [KeyboardInterrupt, SystemExit])
def test_observer_does_not_swallow_interrupts(make_assistant, kesme):
    """ Ctrl+C / çıkış sinyallerinin yutulmadığını doğrular.

    Regresyon: çıplak 'except' KeyboardInterrupt'ı da yakalayıp VETO'ya
    çeviriyordu — pilot sistemi Ctrl+C ile durduramıyordu.
    """
    a, _ = make_assistant(model_responses=[kesme()])
    with pytest.raises(kesme):
        a.observe_and_verify(TELEMETRI, [])


def test_observer_receives_full_command_chain(make_assistant):
    """ Gözlemciye zincirin tamamının denetim için verildiğini doğrular """
    a, fake = make_assistant(model_responses=['{"decision": "APPROVED", "reason": "ok"}'])
    zincir = [{"action": "takeoff", "parameter": 30}, {"action": "move",
              "parameter": {"direction": "kuzey", "distance": 40}}]

    a.observe_and_verify(dict(TELEMETRI, battery=55), zincir)

    gonderilen = fake.models.calls[0]
    assert "KOMUT_ZİNCİRİ" in gonderilen
    assert "takeoff" in gonderilen and "move" in gonderilen
    assert '"battery": 55' in gonderilen
