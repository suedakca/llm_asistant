# radar.py
import json
import os
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.animation import FuncAnimation

from telemetry import load_session

LOG_FILE = "uclus_loglari.json"
TELEMETRY_FILE = "telemetri_kaydi.json"

fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(16, 5))
fig.canvas.manager.set_window_title("İHA Otonom Görev Takip Radarı")


def _telemetri_kaydindan_oku():
    """ Gerçek uçuş izini kaydedilmiş telemetriden okur. """
    ornekler = load_session(TELEMETRY_FILE)
    if not ornekler:
        return None

    x_coords = [o.get("x", 0.0) for o in ornekler]
    y_coords = [o.get("y", 0.0) for o in ornekler]
    altitude_history = [(i, o.get("altitude", 0.0)) for i, o in enumerate(ornekler)]

    son = ornekler[-1]
    son_irtifa = son.get("altitude", 0.0)
    if son.get("failsafe"):
        durum = "KİLİTLİ (FAILSAFE)"
    elif son.get("in_air") and son_irtifa <= 0.5:
        durum = "YERDE — TIRMANAMIYOR (güç yetersiz)"
    elif son.get("in_air"):
        durum = f"HAVADA ({son_irtifa}m)"
    else:
        durum = f"YERDE ({son.get('mode', 'DISARMED')})"

    return {
        "kaynak": "telemetri",
        "home_x": 0.0,
        "home_y": 0.0,
        "x_coords": x_coords,
        "y_coords": y_coords,
        "altitude_history": altitude_history,
        "last_status": durum,
        "current_x": son.get("x", 0.0),
        "current_y": son.get("y", 0.0),
        "current_alt": son.get("altitude", 0.0),
        "session_id": son.get("session_id"),
        "battery": son.get("battery"),
        "active_faults": son.get("active_faults", []),
        "gps_healthy": son.get("gps_healthy", True),
    }


def _komut_loglarindan_yeniden_olustur():
    """ Telemetri kaydı yoksa rotayı komut loglarından tahmin eder. """
    home_x = 0.0
    home_y = 0.0
    x_coords = [0.0]
    y_coords = [0.0]
    altitude_history = []
    last_status = "DISARMED"
    current_x, current_y, current_alt = 0.0, 0.0, 0.0
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
        return None

    active_session_id = all_lines[-1].get("session_id")
    step = 0

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

    return {
        "kaynak": "komut_logu",
        "home_x": home_x,
        "home_y": home_y,
        "x_coords": x_coords,
        "y_coords": y_coords,
        "altitude_history": altitude_history,
        "last_status": last_status,
        "current_x": current_x,
        "current_y": current_y,
        "current_alt": current_alt,
        "session_id": active_session_id,
        "battery": None,
        "active_faults": [],
        "gps_healthy": True,
    }


def animate(_):
    veri = _telemetri_kaydindan_oku() or _komut_loglarindan_yeniden_olustur()

    if veri is None:
        for ax in (ax1, ax2, ax3):
            ax.clear()
        ax2.text(0.5, 0.5, "Henüz log yok", ha="center", va="center", transform=ax2.transAxes)
        return

    home_x = veri["home_x"]
    home_y = veri["home_y"]
    x_coords = veri["x_coords"]
    y_coords = veri["y_coords"]
    altitude_history = veri["altitude_history"]
    last_status = veri["last_status"]
    current_alt = veri["current_alt"]
    active_session_id = veri["session_id"]
    telemetri_kaynakli = veri["kaynak"] == "telemetri"

    ax1.clear()
    boundary = 50
    geofence = mpatches.Rectangle((-boundary, -boundary), boundary * 2, boundary * 2,
                                   linewidth=2, edgecolor="red", facecolor="none",
                                   linestyle="--", label=f"Geofence (±{boundary}m)")
    ax1.add_patch(geofence)
    if telemetri_kaynakli:
        ax1.plot(x_coords, y_coords, color="lime", linewidth=1.6, label="Gerçek uçuş izi")
    else:
        ax1.plot(x_coords, y_coords, color="green", linestyle="--", marker="o", markersize=4,
                 label="Rota (komuttan tahmin)")
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

    ax2.clear()
    if altitude_history:
        steps = [h[0] for h in altitude_history]
        alts  = [h[1] for h in altitude_history]
        steps = [0] + [s + 1 for s in steps]
        alts  = [0.0] + alts
        if telemetri_kaynakli:
            ax2.plot(steps, alts, color="royalblue", linewidth=1.8, label="İrtifa (gerçek)")
        else:
            ax2.plot(steps, alts, color="royalblue", marker="o", markersize=5, linewidth=2,
                     label="İrtifa (komuttan tahmin)")
        ax2.fill_between(steps, alts, alpha=0.15, color="royalblue")
        ax2.axhline(y=current_alt, color="orange", linestyle=":", linewidth=1.5, label=f"Anlık: {current_alt}m")
        ax2.set_ylim(0, 55)
        ax2.axhline(y=50, color="red", linestyle="--", linewidth=1, alpha=0.7, label="Maks limit (50m)")
    else:
        ax2.text(0.5, 0.5, "Henüz uçuş yok", ha="center", va="center", transform=ax2.transAxes, color="gray")
        ax2.set_ylim(0, 55)
    ax2.set_title("İrtifa Geçmişi (m)")
    ax2.set_xlabel("Telemetri Örneği (zaman)" if telemetri_kaynakli else "Komut Adımı")
    ax2.set_ylabel("İrtifa (m)")
    ax2.grid(True, linestyle=":", alpha=0.5)
    ax2.legend(loc="upper left", fontsize=8)

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

    aktif_arizalar = veri.get("active_faults") or []
    if aktif_arizalar:
        from faults import FAULT_LABELS
        etiketler = ", ".join(FAULT_LABELS.get(a, a) for a in aktif_arizalar)
        ax3.text(0.05, 0.28, f"! ARIZA: {etiketler}", fontsize=9, color="darkorange",
                 weight="bold", transform=ax3.transAxes, wrap=True)
    if not veri.get("gps_healthy", True):
        ax3.text(0.05, 0.22, "! GPS SINYALI YOK — konum donmus",
                 fontsize=9, color="red", weight="bold", transform=ax3.transAxes)

    kaynak_etiketi = "gercek telemetri" if telemetri_kaynakli else "komut logundan tahmin"
    ax3.text(0.05, 0.10, f"Veri kaynagi: {kaynak_etiketi}", fontsize=8, color="gray", transform=ax3.transAxes)
    ax3.text(0.05, 0.04, f"Oturum: {sid_display}", fontsize=9, color="gray", transform=ax3.transAxes)

ani = FuncAnimation(fig, animate, interval=1000, cache_frame_data=False)
plt.tight_layout()
plt.show()
