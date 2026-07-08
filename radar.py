# radar.py
import json
import os
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.animation import FuncAnimation

LOG_FILE = "uclus_loglari.json"

fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(16, 5))
fig.canvas.manager.set_window_title("İHA Otonom Görev Takip Radarı")

def animate(_):
    home_x = 0.0
    home_y = 0.0
    x_coords = [0.0]
    y_coords = [0.0]
    altitude_history = []   # (zaman_indeksi, irtifa) çiftleri
    last_status = "DISARMED"
    current_x, current_y, current_alt = 0.0, 0.0, 0.0
    active_session_id = None
    all_lines = []

    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        all_lines.append(json.loads(line.strip()))
        except Exception as e:
            print(f"Log okuma hatası: {e}")

    if not all_lines:
        for ax in (ax1, ax2, ax3):
            ax.clear()
        ax2.text(0.5, 0.5, "Henüz log yok", ha="center", va="center", transform=ax2.transAxes)
        return

    active_session_id = all_lines[-1].get("session_id")
    step = 0  # irtifa geçmişi için zaman ekseni

    for log in all_lines:
        if log.get("session_id") != active_session_id:
            continue

        guvenlik_onayi = log.get("guvenlik_onayi", False)
        llm_yorumu = log.get("llm_yorumu", {})
        action = llm_yorumu.get("action")
        parameter = llm_yorumu.get("parameter", {})
        res = log.get("sonuc_mesaji", "")

        if guvenlik_onayi and action == "takeoff":
            try:
                current_alt = float(parameter)
                altitude_history.append((step, current_alt))
                step += 1
                last_status = f"HAVADA ({current_alt}m)"
            except (TypeError, ValueError):
                last_status = "HAVADA (GUIDED)"

        elif guvenlik_onayi and action == "move" and isinstance(parameter, dict):
            direction = parameter.get("direction", "").lower()
            try:
                distance = float(parameter.get("distance", 0))
                if direction in ["kuzey", "north", "ileri"]:
                    current_y += distance
                elif direction in ["güney", "south", "geri"]:
                    current_y -= distance
                elif direction in ["doğu", "east", "sağ"]:
                    current_x += distance
                elif direction in ["batı", "west", "sol"]:
                    current_x -= distance
            except (ValueError, TypeError):
                pass
            x_coords.append(current_x)
            y_coords.append(current_y)
            altitude_history.append((step, current_alt))
            step += 1

        elif guvenlik_onayi and action == "set_home" and isinstance(parameter, dict):
            try:
                home_x = float(parameter.get("x", 0.0))
                home_y = float(parameter.get("y", 0.0))
            except (ValueError, TypeError):
                pass

        elif guvenlik_onayi and action == "return_to_home":
            current_x, current_y = home_x, home_y
            current_alt = 0.0
            x_coords.append(current_x)
            y_coords.append(current_y)
            altitude_history.append((step, 0.0))
            step += 1
            last_status = "YERDE (RTH)"

        elif guvenlik_onayi and action == "land":
            current_alt = 0.0
            altitude_history.append((step, 0.0))
            step += 1
            last_status = "YERDE (LAND)"

        if "FAILSAFE" in res or "kilitlendi" in res.lower():
            last_status = "KİLİTLİ (FAILSAFE)"

    # --- Sol panel: 2B Yatay Harita ---
    ax1.clear()
    boundary = 50
    geofence = mpatches.Rectangle((-boundary, -boundary), boundary * 2, boundary * 2,
                                   linewidth=2, edgecolor="red", facecolor="none",
                                   linestyle="--", label=f"Geofence (±{boundary}m)")
    ax1.add_patch(geofence)
    ax1.plot(x_coords, y_coords, color="green", linestyle="--", marker="o", markersize=4, label="Rota")
    ax1.scatter([home_x], [home_y], color="red", s=100, marker="H", zorder=5, label="Home")
    if x_coords:
        ax1.scatter([x_coords[-1]], [y_coords[-1]], color="blue", s=120, marker="^", zorder=6, label="İHA")
    ax1.set_xlim(-65, 65)
    ax1.set_ylim(-65, 65)
    ax1.set_aspect("equal")
    ax1.grid(True, linestyle=":", alpha=0.6)
    ax1.set_title("2B Konum Haritası (Kuş Bakışı)")
    ax1.set_xlabel("X — Doğu/Batı (m)")
    ax1.set_ylabel("Y — Kuzey/Güney (m)")
    ax1.legend(loc="upper left", fontsize=8)

    # --- Orta panel: İrtifa grafiği ---
    ax2.clear()
    if altitude_history:
        steps = [h[0] for h in altitude_history]
        alts  = [h[1] for h in altitude_history]
        # Başlangıç noktasını (0m) ekle
        steps = [0] + [s + 1 for s in steps]
        alts  = [0.0] + alts
        ax2.plot(steps, alts, color="royalblue", marker="o", markersize=5, linewidth=2, label="İrtifa")
        ax2.fill_between(steps, alts, alpha=0.15, color="royalblue")
        # Anlık irtifayı göster
        ax2.axhline(y=current_alt, color="orange", linestyle=":", linewidth=1.5, label=f"Anlık: {current_alt}m")
        ax2.set_ylim(0, 55)
        ax2.axhline(y=50, color="red", linestyle="--", linewidth=1, alpha=0.7, label="Maks limit (50m)")
    else:
        ax2.text(0.5, 0.5, "Henüz uçuş yok", ha="center", va="center", transform=ax2.transAxes, color="gray")
        ax2.set_ylim(0, 55)
    ax2.set_title("İrtifa Geçmişi (m)")
    ax2.set_xlabel("Komut Adımı")
    ax2.set_ylabel("İrtifa (m)")
    ax2.grid(True, linestyle=":", alpha=0.5)
    ax2.legend(loc="upper left", fontsize=8)

    # --- Sağ panel: Telemetri metni ---
    ax3.clear()
    ax3.set_axis_off()
    cx = x_coords[-1] if x_coords else 0.0
    cy = y_coords[-1] if y_coords else 0.0
    geofence_alarm = abs(cx) > 40 or abs(cy) > 40
    sid_display = (active_session_id[:8] + "...") if active_session_id else "N/A"

    ax3.text(0.05, 0.92, "IHA TELEMETRI PANELI", fontsize=13, weight="bold", color="darkblue", transform=ax3.transAxes)
    ax3.text(0.05, 0.78, f"Ucus Durumu  : {last_status}",       fontsize=11, transform=ax3.transAxes)
    ax3.text(0.05, 0.66, f"Irtifa       : {current_alt} m",     fontsize=11, color="royalblue", transform=ax3.transAxes)
    ax3.text(0.05, 0.54, f"Konum        : X={cx}m  Y={cy}m",   fontsize=11, transform=ax3.transAxes)
    ax3.text(0.05, 0.42, f"Geofence     : +/-50m",              fontsize=11,
             color="red" if geofence_alarm else "black", transform=ax3.transAxes)
    if geofence_alarm:
        ax3.text(0.05, 0.35, "! SINIRA YAKIN !", fontsize=10, color="red", weight="bold", transform=ax3.transAxes)
    ax3.text(0.05, 0.18, f"Oturum: {sid_display}", fontsize=9, color="gray", transform=ax3.transAxes)

ani = FuncAnimation(fig, animate, interval=1000, cache_frame_data=False)
plt.tight_layout()
plt.show()
