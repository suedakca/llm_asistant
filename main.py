# main.py
from drone import Drone
from security import SecurityLayer

def main():
    print("=== İNSANSI GÜVENLİK KATMANI TESTLERİ BAŞLADI ===\n")
    
    # Drone ve Güvenlik nesnelerini oluşturuyoruz
    drone_asistani = Drone()
    guvenlik_duvari = SecurityLayer(max_altitude=50.0, min_battery=20)

    # Telemetriyi ekrana basan yardımcı fonksiyon
    def anlik_durum():
        t = drone_asistani.get_telemetry()
        print(f"   [DRONE DURUMU] İrtifa: {t['altitude']}m | Batarya: %{t['battery']} | Havada: {t['in_air']}")

    # -------------------------------------------------------------
    # TEST 1: Doğru ve Güvenli Kalkış Komutu
    # -------------------------------------------------------------
    print("TEST 1: '15 metreye kalkış yap' komutu gönderiliyor...")
    onay, mesaj = guvenlik_duvari.validate_and_execute(drone_asistani, "takeoff", 15)
    print(f"-> Güvenlik Onayı: {onay} | Sonuç: {mesaj}")
    anlik_durum()
    print("-" * 60)

    # -------------------------------------------------------------
    # TEST 2: Güvensiz Komut (Maksimum İrtifa Sınırını Aşma)
    # -------------------------------------------------------------
    print("TEST 2: '80 metreye kalkış yap' komutu gönderiliyor (Sınır: 50m)...")
    onay, mesaj = guvenlik_duvari.validate_and_execute(drone_asistani, "takeoff", 80)
    print(f"-> Güvenlik Onayı: {onay} | Sonuç: {mesaj}")
    anlik_durum()
    print("-" * 60)

    # -------------------------------------------------------------
    # TEST 3: Geçersiz Parametre (Negatif İrtifa)
    # -------------------------------------------------------------
    print("TEST 3: '-10 metreye git' komutu gönderiliyor...")
    onay, mesaj = guvenlik_duvari.validate_and_execute(drone_asistani, "takeoff", -10)
    print(f"-> Güvenlik Onayı: {onay} | Sonuç: {mesaj}")
    anlik_durum()
    print("-" * 60)

    # -------------------------------------------------------------
    # TEST 4: Tanımsız/Hatalı Fonksiyon İsteyi
    # -------------------------------------------------------------
    print("TEST 4: 'motorlari_sonsuza_kadar_yak' komutu gönderiliyor...")
    onay, mesaj = guvenlik_duvari.validate_and_execute(drone_asistani, "motorlari_sonsuza_kadar_yak")
    print(f"-> Güvenlik Onayı: {onay} | Sonuç: {mesaj}")
    anlik_durum()
    print("-" * 60)

    # -------------------------------------------------------------
    # TEST 5: Başarılı İniş Komutu
    # -------------------------------------------------------------
    print("TEST 5: 'iniş yap' komutu gönderiliyor...")
    onay, mesaj = guvenlik_duvari.validate_and_execute(drone_asistani, "land")
    print(f"-> Güvenlik Onayı: {onay} | Sonuç: {mesaj}")
    anlik_durum()
    print("\n=== TÜM GÜVENLİK TESTLERİ TAMAMLANDI ===")

if __name__ == "__main__":
    main()