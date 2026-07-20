# LLM Tabanlı İHA Pilot Asistanı

Doğal dil komutlarıyla kontrol edilen, çift LLM mimarili ve fizik simülasyonlu otonom İHA yönetim sistemi. Gemini 2.0 Flash kullanarak Türkçe komutları ayrıştırır, güvenlik katmanından geçirir, Pygame grafik simülatöründe ve MAVLink/radar üzerinde çalıştırır.

---

## Mimari

```
Pilot Komutu (Ses / Metin)
    │
    ▼
[LLM 1 - Asistan]   → Komutları JSON görev zincirine dönüştürür
    │
    ▼
[LLM 2 - Gözlemci]  → Yüksek riskli görevlerde batarya denetimi yapar
    │
    ▼
[Güvenlik Katmanı]  → Geofence, irtifa, batarya, rüzgar kurallarını uygular
    │
    ▼
[Drone Simülatörü]  → Pygame 2D fizik motoru / MAVLink ile görevi icra eder
```

> **Dinamik Yeniden Planlama:** Güvenlik engeline takılan eylemlerde LLM otomatik olarak alternatif güvenli rota planlar.

---

## Kurulum

### 1. Bağımlılıkları Yükleyin

```bash
pip3 install -r requirements.txt
```

*(Sesli komut desteği için macOS üzerinde: `brew install portaudio && pip3 install pyaudio`)*

### 2. API Anahtarını Tanımlayın

Proje kök dizininde `.env` dosyası oluşturun:

```env
GEMINI_API_KEY=your_gemini_api_key_here
```

---

## Kullanım

### Başlatma

```bash
python3 main.py
```

### Giriş Seçenekleri
- **K** — Klavyeden metin komutu girin.
- **S** — Sesli komut verin (Google Speech Recognition).
- **Ç** — Çıkış yapın ve uçuş özet raporunu görüntüleyin.

### Canlı Radar Görselleştirme (Opsiyonel)
İkinci bir terminal ekranında uçuş izini canlı takip edebilirsiniz:

```bash
python3 radar.py
```

---

## Örnek Komutlar ve Uçuş Adımları

İlk kalkış öncesinde güvenlik gereği kontrol listesinin onaylanması zorunludur:

1. **Kontrol Listesi Onayı (Zorunlu):** `kontroller tamam` veya `hazırız`
2. **Kalkış Yapma:** `10 metreye kalk` veya `10 metre yüksel`
3. **Manevra / Hareket:** `10 metre ileri git, sonra 5 metre sağa git`
4. **Eve Dönüş / İniş:** `eve dön` veya `in`
5. **Acil Durum:** `ABORT` veya `ACİL DURDURMA` (LLM bypass edilerek anında motor kesilir)

---

## Güvenlik Kuralları

| Parametre | Limit |
|---|---|
| Normal İrtifa Limiti | 50m |
| Düşük Batarya İrtifa Limiti (<%50) | 20m |
| Kritik Batarya Eşiği | %20 (Yalnızca iniş / RTH izni) |
| Geofence Sınırı | ±50m (X ve Y ekseni) |
| Maksimum Rüzgar Hızı | 30 km/s |

---

## Arıza Enjeksiyonu (F-Tuşları)

Simülatör ekranı açıkken donanım arızalarını test etmek için klavye kısayolları kullanılabilir:

- **F5:** GPS kaybı (Konum donar)
- **F6:** İrtifa sensörü sapması
- **F7:** Motor güç kaybı
- **F9:** Hızlandırılmış batarya tüketimi
- **F8:** Tüm arızaları temizler

---

## Testler

Tüm test paketini çalıştırmak için:

```bash
python3 -m pytest
```

*(271 birim testi kapsar, harici API anahtarı veya ağ bağlantısı gerektirmez.)*
