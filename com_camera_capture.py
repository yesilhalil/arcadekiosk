import serial
import cv2
import time

# Seri port ayarları
SERIAL_PORT = 'COM3'
BAUD_RATE = 9600

def main():
    print(f"[{time.strftime('%H:%M:%S')}] Seri portu dinlemeye başlanıyor: {SERIAL_PORT} @ {BAUD_RATE} baud")
    ser = None
    try:
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
        print(f"[{time.strftime('%H:%M:%S')}] Seri port açıldı.")

        while True:
            print(f"[{time.strftime('%H:%M:%S')}] 'T' sinyali bekleniyor...")
            if ser.in_waiting > 0:
                received_char = ser.read().decode('ascii')
                if received_char == 'T':
                    print(f"[{time.strftime('%H:%M:%S')}] 'T' sinyali alındı. Fotoğraf çekiliyor...")
                    
                    # Web kamerasını başlat
                    cap = cv2.VideoCapture(0) # 0 varsayılan web kamerası için
                    if not cap.isOpened():
                        print(f"[{time.strftime('%H:%M:%S')}] Hata: Kamera açılamadı.")
                        continue

                    ret, frame = cap.read()
                    if ret:
                        IMAGE_FILENAME = 'temp_capture.jpg'
                        cv2.imwrite(IMAGE_FILENAME, frame)
                        print(f"[{time.strftime('%H:%M:%S')}] Fotoğraf '{IMAGE_FILENAME}' olarak kaydedildi.")
                    else:
                        print(f"[{time.strftime('%H:%M:%S')}] Hata: Kameradan görüntü alınamadı.")

                    # Kamerayı serbest bırak
                    cap.release()
                    print(f"[{time.strftime('%H:%M:%S')}] Kamera serbest bırakıldı.")

            time.sleep(0.1) # CPU kullanımını azaltmak için kısa bir bekleme

    except serial.SerialException as e:
        print(f"[{time.strftime('%H:%M:%S')}] Seri port hatası: {e}")
    except Exception as e:
        print(f"[{time.strftime('%H:%M:%S')}] Bir hata oluştu: {e}")
    finally:
        if ser and ser.is_open:
            ser.close()
            print(f"[{time.strftime('%H:%M:%S')}] Seri port kapatıldı.")

if __name__ == '__main__':
    main()
