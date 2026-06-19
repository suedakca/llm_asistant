# radar.py
import json
import os
import time
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation

LOG_FILE = "uclus_loglari.json"

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 5))
fig.canvas.manager.set_window_title("İHA Otonom Görev Takip Radarı")

def animate(i):
    x_coords = [0.0]  
    y_coords = [0.0]
    last_alt = 0.0
    last_batt = 100
    last_status = "DISARMED"
    
    # 1. Log dosyasını satır satır oku ve konum geçmişini topla
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        log = json.loads(line.strip())
                        msg = log.get("sonuc_mesaji", "")

                        if "ilerlendi" in msg or "dönüldü" in msg or "kalkış" in msg or "iniş" in msg:
                            pass
        except:
            pass


    current_x, current_y = 0.0, 0.0
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                lines = f.readlines()
                for line in lines:
                    if not line.strip(): continue
                    data = json.loads(line.strip())
                    res = data.get("sonuc_mesaji", "")
                    
                    # Başarılı eylem sonuçlarından koordinat/irtifa çıkarımı
                    if "KUZEY" in res: current_y += 10 # Örnek adımlama
                    elif "GÜNEY" in res: current_y -= 10
                    elif "DOĞU" in res: current_x += 10
                    elif "BATI" in res: current_x -= 10
                    elif "Başlangıç konumuna" in res:
                        current_x, current_y = 0.0, 0.0
                    
                    x_coords.append(current_x)
                    y_coords.append(current_y)
                    
                    # Son durumu yakala
                    if "metreye" in res: last_status = "HAVADA (GUIDED)"
                    elif "İniş gerçekleştirildi" in res: last_status = "YERDE (LAND)"; last_alt = 0.0
                    elif "FAILSAFE" in res: last_status = "KİLİTLİ (FAILSAFE)"
        except:
            pass

    # Sol Grafik: 2B Yatay Hareket Haritası (X / Y)
    ax1.clear()
    ax1.plot(x_coords, y_coords, color="green", linestyle="--", marker="o", markersize=4, label="Uçuş Rotası")
    ax1.scatter([0], [0], color="red", s=100, marker="H", label="Kalkış Noktası (Home)") # Home
    if x_coords:
        ax1.scatter([x_coords[-1]], [y_coords[-1]], color="blue", s=120, marker="^", label="Anlık İHA Konumu") # Drone
    
    ax1.set_xlim(-60, 60)
    ax1.set_ylim(-60, 60)
    ax1.grid(True, linestyle=":", alpha=0.6)
    ax1.set_title("🌐 2B Coğrafi Konum Takip Ekranı (Geofence)")
    ax1.set_xlabel("X Koordinatı (Metre)")
    ax1.set_ylabel("Y Koordinatı (Metre)")
    ax1.legend(loc="upper left")

    # Sağ Grafik: Telemetri Gösterge Paneli
    ax2.clear()
    ax2.set_axis_off() # Çizgileri gizle, sadece yazı yazacağız
    
    # En son koordinatları al
    cx = x_coords[-1] if x_coords else 0.0
    cy = y_coords[-1] if y_coords else 0.0
    
    # Ekrana şık telemetri metinleri basıyoruz
    ax2.text(0.1, 0.8, "🤖 İHA TELEMETRİ PANELİ", fontsize=14, weight='bold', color="darkblue")
    ax2.text(0.1, 0.6, f"🔸 Uçuş Modu    : {last_status}", fontsize=12)
    ax2.text(0.1, 0.5, f"📍 Anlık Konum  : (X: {cx}m, Y: {cy}m)", fontsize=12)
    ax2.text(0.1, 0.4, f"🛡️ Geofence Sınır: ±50 Metre", fontsize=12, color="red" if (abs(cx)>40 or abs(cy)>40) else "black")
    ax2.text(0.1, 0.2, "⚙️ Durum: Sistem İzleniyor...", fontsize=10, style='italic', color="gray")

# Animasyonu saniyede 1 kez yenilenecek şekilde başlat (1000 ms)
ani = FuncAnimation(fig, animate, interval=1000, cache_frame_data=False)
plt.tight_layout()
plt.show()