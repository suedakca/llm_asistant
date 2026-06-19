# radar.py
import json
import os
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation

# Log dosyasının yolu
LOG_FILE = "uclus_loglari.json"

# Görsel şema kurulumu
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 5))
fig.canvas.manager.set_window_title("İHA Otonom Görev Takip Radarı")

def animate(i):
    home_x = 0.0
    home_y = 0.0
    x_coords = [0.0]  # Başlangıç (Home) noktası
    y_coords = [0.0]
    last_status = "DISARMED"
    current_x, current_y = 0.0, 0.0
    active_session_id = None
    all_lines = []

    # 1. PERFORMANS OPTİMİZASYONU: Dosyayı tek bir seferde oku
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        all_lines.append(json.loads(line.strip()))
        except Exception as e:
            print(f"Log okuma hatası: {e}")

    if not all_lines:
        return

    # 2. SESSION FILTER: Dosyanın en sonundaki aktif oturum kimliğini tespit et
    active_session_id = all_lines[-1].get("session_id")

    # 3. DİNAMİK MESAFE VE KONUM HESAPLAMA: Sadece aktif oturumu işle
    for log in all_lines:
        if log.get("session_id") != active_session_id:
            continue  # Eski uçuş oturumlarını haritaya karıştırma, atla!

        res = log.get("sonuc_mesaji", "")
        guvenlik_onayi = log.get("guvenlik_onayi", False)
        llm_yorumu = log.get("llm_yorumu", {})
        action = llm_yorumu.get("action")
        parameter = llm_yorumu.get("parameter", {})

        # Sadece güvenlik katmanından onay almış gerçek uçuş hareketlerini çiz
        if guvenlik_onayi and action == "move" and isinstance(parameter, dict):
            direction = parameter.get("direction", "").lower()
            try:
                # [DÜZELTME] Sabit 10m yerine pilotun gerçek girdi mesafesini alıyoruz
                distance = float(parameter.get("distance", 0))
                
                if direction in ["kuzey", "north", "ileri"]: current_y += distance
                elif direction in ["güney", "south", "geri"]: current_y -= distance
                elif direction in ["doğu", "east", "sağ"]: current_x += distance
                elif direction in ["batı", "west", "sol"]: current_x -= distance
            except (ValueError, TypeError):
                pass  # Mesafe sayıya çevrilemezse güvenli geçiş

        elif guvenlik_onayi and action == "set_home" and isinstance(parameter, dict):
            try:
                home_x = float(parameter.get("x", 0.0))
                home_y = float(parameter.get("y", 0.0))
                # İlk konum güncellemesi (İHA yerdeyken ev konumu değiştiği için anlık konum da yeni ev konumuyla güncellenir)
                current_x, current_y = home_x, home_y
                # Rota başlangıcını da güncelle
                if len(x_coords) == 1:
                    x_coords = [home_x]
                    y_coords = [home_y]
            except (ValueError, TypeError):
                pass

        elif guvenlik_onayi and action == "return_to_home":
            current_x, current_y = home_x, home_y  # Drone evine döndü

        # Rota geçmişini güncelle
        x_coords.append(current_x)
        y_coords.append(current_y)

        # Durum Göstergesi Güncellemesi
        if "FAILSAFE" in res or "kilitlendi" in res.lower():
            last_status = "KİLİTLİ (FAILSAFE)"
        elif action == "takeoff" and guvenlik_onayi:
            try:
                last_status = f"HAVADA ({float(parameter)}m)"
            except:
                last_status = "HAVADA (GUIDED)"
        elif action == "land" and guvenlik_onayi:
            last_status = "YERDE (LAND)"

    # Sol Grafik: 2B Yatay Hareket Haritası (X / Y)
    ax1.clear()
    ax1.plot(x_coords, y_coords, color="green", linestyle="--", marker="o", markersize=4, label="Uçuş Rotası")
    ax1.scatter([home_x], [home_y], color="red", s=100, marker="H", label="Kalkış Noktası (Home)") 
    if x_coords:
        ax1.scatter([x_coords[-1]], [y_coords[-1]], color="blue", s=120, marker="^", label="Anlık İHA Konumu") 
    
    ax1.set_xlim(-60, 60)
    ax1.set_ylim(-60, 60)
    ax1.grid(True, linestyle=":", alpha=0.6)
    ax1.set_title("🌐 2B Coğrafi Konum Takip Ekranı (Geofence)")
    ax1.set_xlabel("X Koordinatı (Metre)")
    ax1.set_ylabel("Y Koordinatı (Metre)")
    ax1.legend(loc="upper left")

    # Sağ Grafik: Telemetri Gösterge Paneli
    ax2.clear()
    ax2.set_axis_off() 
    
    cx = x_coords[-1] if x_coords else 0.0
    cy = y_coords[-1] if y_coords else 0.0
    
    ax2.text(0.1, 0.8, "🤖 İHA TELEMETRİ PANELİ", fontsize=14, weight='bold', color="darkblue")
    ax2.text(0.1, 0.6, f"🔸 Uçuş Durumu  : {last_status}", fontsize=12)
    ax2.text(0.1, 0.5, f"📍 Anlık Konum  : (X: {cx}m, Y: {cy}m)", fontsize=12)
    ax2.text(0.1, 0.4, f"🛡️ Geofence Sınır: ±50 Metre", fontsize=12, color="red" if (abs(cx)>40 or abs(cy)>40) else "black")
    sid_display = (active_session_id[:8] + "...") if active_session_id else "N/A"
    ax2.text(0.1, 0.2, f"🆔 Aktif Oturum : {sid_display}", fontsize=10, color="gray")

# Animasyonu başlat
ani = FuncAnimation(fig, animate, interval=1000, cache_frame_data=False)
plt.tight_layout()
plt.show()