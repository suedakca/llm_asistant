# main.py

# 1. drone.py dosyasındaki Drone sınıfını bu dosyaya çağırıyoruz (import)
from drone import Drone

def main():
    print("=== İHA Pilot Asistanı Simülasyonu Başlatıldı ===")
    
    # 2. Drone nesnemizi üretiyoruz
    asistan_dronu = Drone()
    
    # 3. Telemetriyi kontrol fonksiyonu (Kod tekrarını önlemek için)
    def durumu_goster():
        telemetri = asistan_dronu.get_telemetry()
        print(f"[TELEMETRİ] İrtifa: {telemetri['altitude']}m | Mod: {telemetri['mode']} | Batarya: %{telemetri['battery']} | Havada mı?: {telemetri['in_air']}")

    # İlk durumu görelim
    durumu_goster()
    print("-" * 50)

    # 4. Drone'a komutlar gönderiyoruz
    print("Komut: 15 metreye kalkış yap.")
    sonuc = asistan_dronu.takeoff(15)
    print(f"Sistem Yanıtı: {sonuc}")
    durumu_goster()
    print("-" * 50)

    print("Komut: Eve geri dön.")
    sonuc = asistan_dronu.return_to_home()
    print(f"Sistem Yanıtı: {sonuc}")
    durumu_goster()
    print("-" * 50)

    print("Komut: İniş yap.")
    sonuc = asistan_dronu.land()
    print(f"Sistem Yanıtı: {sonuc}")
    durumu_goster()
    print("================================================")

if __name__ == "__main__":
    main()