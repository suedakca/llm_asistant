# LLM Tabanlı İHA Pilot Asistanı

Doğal dil komutlarıyla kontrol edilen, çift LLM mimarili bir drone simülasyon sistemi. Gemini 2.0 Flash kullanarak Türkçe komutları ayrıştırır, güvenlik katmanından geçirir ve ardışık görev zinciri olarak çalıştırır.

## Mimari

```
Pilot Komutu
    │
    ▼
[LLM 1 - Asistan]  →  Komutu JSON görev zincirine dönüştürür
    │
    ▼
[LLM 2 - Gözlemci] →  Yüksek riskli zincirlerde batarya denetimi yapar (opsiyonel)
    │
    ▼
[Güvenlik Katmanı] →  Geofence, irtifa, batarya, rüzgar kurallarını uygular
    │
    ▼
[Drone Simülatörü] →  Komutu çalıştırır, telemetriyi günceller
```

**Dinamik Yeniden Planlama:** Güvenlik katmanı bir komutu engellerse, LLM 1 otomatik olarak alternatif güvenli rota planlar (maksimum 2 deneme).

## Kurulum

### 1. Gerekli Kütüphaneleri Yükle

```bash
pip3 install google-genai python-dotenv pyyaml SpeechRecognition pyaudio matplotlib
```

### 2. `.env` Dosyası Oluştur

Proje kök dizininde `.env` adlı bir dosya oluştur ve Gemini API anahtarını ekle:

```
GEMINI_API_KEY=buraya_api_anahtarını_yaz
```

> API anahtarı [Google AI Studio](https://aistudio.google.com/app/apikey) adresinden ücretsiz alınabilir.
> Key formatı `AIza...` ile başlar ve 39 karakterdir. OAuth token veya service account key çalışmaz.

### 3. Çalıştır

```bash
python3 main.py
```

## Kullanım

Program her komut için giriş yöntemi sorar:

```
Giriş Yöntemi [K: Klavye / S: Sesli Komut / Ç: Çıkış]:
```

- **K** — Klavyeden Türkçe komut gir
- **S** — Mikrofondan sesli komut ver (Google STT, Türkçe)
- **Ç** — Programı kapat ve oturum özetini göster

### Örnek Komutlar

| Komut | Eylem |
|---|---|
| `kontroller tamam` | Kalkış öncesi kontrol listesini onayla |
| `10 metreye kalk` | Belirtilen irtifaya kalkış yap |
| `10 metre yukarı 5 metre sağa git` | Zincirleme görev: yüksel + yatay hareket |
| `eve dön` | Return-to-Home (başlangıç noktasına dön) |
| `in` | İniş yap |
| `durum ne?` | Güncel telemetriyi sorgula |
| `sistemi yeniden başlat` | Failsafe sonrası reboot |
| `ABORT` / `ACİL DURDURMA` | Acil durdurma (LLM bypass, anında) |

### Kalkış Sırası

1. Sistemi başlat: `python3 main.py`
2. Kontrolleri onayla: `kontroller tamam`
3. Kalkış yap: `10 metreye kalk`
4. Komutları gönder

## Güvenlik Kuralları

| Kural | Limit |
|---|---|
| Maksimum irtifa (normal) | 50m |
| Maksimum irtifa (batarya < %50) | 20m |
| Kritik batarya | %20 — sadece iniş/RTH |
| Geofence sınırı | ±50m (X ve Y ekseni) |
| Maksimum rüzgar hızı | 30 km/s |

Geofence veya irtifa ihlali durumunda sistem otomatik olarak alternatif güvenli rota planlar.

## Konfigürasyon

`config.yaml` dosyasından tüm parametreler ayarlanabilir:

```yaml
drone_settings:
  base_max_altitude: 50.0       # Normal irtifa limiti (m)
  low_battery_max_altitude: 20.0 # Düşük batarya irtifa limiti (m)
  critical_battery: 20           # Kritik batarya eşiği (%)
  geofence_boundary: 50.0        # Geofence yarıçapı (m)
  max_wind_speed: 30.0           # Maks rüzgar hızı (km/s)

llm_settings:
  model_name: "gemini-2.0-flash"
  temperature: 0.1
```

## Dosyalar

| Dosya | Açıklama |
|---|---|
| `main.py` | Giriş noktası, ana döngü, ses/klavye girişi |
| `assistant.py` | LLM 1 (komut ayrıştırıcı) ve LLM 2 (gözlemci) |
| `security.py` | Güvenlik katmanı kuralları |
| `drone.py` | Drone simülatörü ve telemetri |
| `radar.py` | Matplotlib tabanlı radar/harita görselleştirme |
| `logger.py` | Uçuş log yönetimi |
| `config.yaml` | Sistem parametreleri |
| `uclus_loglari.json` | Uçuş logları (otomatik oluşturulur) |

## Simülasyon Çalıştırma

### Tam Simülasyon (Asistan + Radar)

İki terminal aç ve her birinde şunu çalıştır:

**Terminal 1 — Ana sistem:**
```bash
python3 main.py
```

**Terminal 2 — Canlı radar görselleştirme:**
```bash
python3 radar.py
```

Radar penceresi `uclus_loglari.json` dosyasını her saniye okur ve drone konumunu canlı günceller.

### Radar Ekranı

| Panel | İçerik |
|---|---|
| Sol — 2B Harita | Uçuş rotası, kalkış noktası (Home), anlık İHA konumu, Geofence sınırı |
| Sağ — Telemetri | Uçuş durumu, anlık koordinatlar, aktif oturum ID |

Geofence sınırına (±50m) yaklaşıldığında sınır göstergesi kırmızıya döner.

### Örnek Simülasyon Senaryosu

```
Giriş Yöntemi: k
Pilot Mesajı: kontroller tamam
→ Kalkış öncesi kontrol listesi onaylandı.

Giriş Yöntemi: k
Pilot Mesajı: 20 metreye kalk
→ 20 metreye ilk kalkış yapıldı.

Giriş Yöntemi: k
Pilot Mesajı: 10 metre kuzeye git, sonra 15 metre doğuya git
→ 2 alt görev planlandı ve sırayla çalıştırıldı.

Giriş Yöntemi: k
Pilot Mesajı: eve dön
→ Başlangıç konumuna dönüldü ve güvenli iniş tamamlandı.
```

### MAVLink ile Gerçek Araç Bağlantısı (Opsiyonel)

`config.yaml` dosyasında MAVLink desteğini etkinleştir:

```yaml
drone_settings:
  mavlink_enabled: true
  mavlink_connection_string: "udpin:localhost:14540"
```

ArduPilot veya PX4 SITL simülatörü çalışırken bağlanır. Bağlantı başarısız olursa otomatik olarak yerel simülasyon moduna geçer.

## Testler

```bash
python3 -m pytest tests/ -v
```

15 güvenlik testi kapsamı: geofence, batarya limitleri, irtifa kuralları, failsafe kilidi, checklist zorunluluğu, rüzgar engellemesi.
