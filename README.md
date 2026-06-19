# LLM Tabanlı İHA Pilot Asistanı

Doğal dil komutlarıyla kontrol edilen, Gemini destekli bir drone simülasyon sistemi.

## Kurulum

### 1. Gerekli Kütüphaneleri Yükle

```bash
pip3 install google-genai python-dotenv
```

### 2. `.env` Dosyası Oluştur

Proje kök dizininde `.env` adlı bir dosya oluştur ve Gemini API anahtarını ekle:

```
GEMINI_API_KEY=buraya_api_anahtarını_yaz
```

> API anahtarı [Google AI Studio](https://aistudio.google.com/app/apikey) adresinden ücretsiz alınabilir.

### 3. Çalıştır

```bash
python3 main.py
```

## Kullanım

Program çalıştığında Türkçe komut gir:

| Örnek Komut | Eylem |
|---|---|
| `50 metreye kalk` | Kalkış (hedef: 50m) |
| `in` | İniş |
| `eve dön` | Başlangıç noktasına dön |
| `durum ne?` | Telemetri bilgisi |
| `çıkış` | Programı kapat |

Uçuş logları `uclus_loglari.json` dosyasına kaydedilir.
