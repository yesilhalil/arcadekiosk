import os
import time
import uuid
import serial
import cv2
import requests
import threading
from PIL import Image # Optimizasyon için gerekli, QR işlemleri silindi.
from flask import Flask, render_template
from flask_socketio import SocketIO
from dotenv import load_dotenv

import fal_client
import firebase_admin
from firebase_admin import credentials, storage

# --- 1. AYARLAR VE API ---
load_dotenv()

SERIAL_PORT = os.getenv("SERIAL_PORT", "COM5")
BAUD_RATE = 9600
CAMERA_URL = "http://192.168.1.127:8080/video"
SNAPSHOT_URL = CAMERA_URL.replace("/video", "/shot.jpg")
VERCEL_SITE_URL = "https://arcadekiosk.vercel.app"

FAL_KEY = os.getenv("FAL_KEY")
FIREBASE_BUCKET = os.getenv("FIREBASE_BUCKET")

os.environ["FAL_KEY"] = FAL_KEY

if not firebase_admin._apps:
    cred = credentials.Certificate("serviceAccountKey.json")
    firebase_admin.initialize_app(cred, {'storageBucket': FIREBASE_BUCKET})

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

os.makedirs("static", exist_ok=True)
os.makedirs("templates", exist_ok=True)

# --- 2. SİSTEM DURUMLARI VE KİLİTLER ---
system_state = "IDLE" 
is_processing_image = False 

# PuLID + Schnell için optimize edilmiş stiller
STYLES = {
    "1": {
        "name": "Cyberpunk",
        "prompt": "Cyberpunk man, neon night city background, clear face, tactical armor",
        "guidance_scale": 1.2
    },
    "2": {
        "name": "Renaissance",
        "prompt": "Oil painting portrait, noble person, velvet clothing, dark studio background",
        "guidance_scale": 1.2
    },
    "3": {
        "name": "Studio Ghibli",
        "prompt": "Ghibli anime style, clear face, meadow background, soft colors",
        "guidance_scale": 1.5
    }
}

# --- 3. YARDIMCI FONKSİYONLAR ---
def upload_to_firebase(image_path):
    bucket = storage.bucket()
    blob = bucket.blob(f"kiosk_images/{uuid.uuid4().hex}.jpg")
    blob.upload_from_filename(image_path)
    blob.make_public()
    return blob.public_url

def process_image_with_ai(image_path, stil_ayarlari):
    try:
        # 1. OPTİMİZASYON
        img = Image.open(image_path)
        img.thumbnail((768, 768))
        opt_path = "static/opt_upload.jpg"
        img.save(opt_path, format="JPEG", quality=85)
        
        # 2. REFERANS YÜKLEME
        print("☁️ Referans fotoğraf Fal.ai CDN'ine yükleniyor...")
        fal_image_url = fal_client.upload_file(opt_path)

        # 3. HİBRİT ÜRETİM (PULID + FLUX SCHNELL)
        print(f"🚀 {stil_ayarlari['name']} stili PuLID + Schnell ile işleniyor...")
        fal_headers = {
            "Authorization": f"Key {FAL_KEY}",
            "Content-Type": "application/json"
        }
        
        fal_payload = {
            "prompt": stil_ayarlari["prompt"],
            "reference_image_url": fal_image_url,
            "num_inference_steps": 12,
            "guidance_scale": 3.5,
            "id_weight": 1.0,
            "image_size": "portrait_16_9",
            "keep_alive": 120 
        }

        # PuLID Endpoint'i üzerinden Schnell motorunu çalıştırıyoruz
        response = requests.post(
            "https://fal.run/fal-ai/flux-pulid",
            headers=fal_headers,
            json=fal_payload,
            timeout=60
        )
        
        if response.status_code != 200:
            raise Exception(f"API Hatası: {response.text}")

        print("✅ Hibrit üretim tamamlandı!")
        image_url = response.json()["images"][0]["url"]

        # 4. FIREBASE KAYIT VE LİNK OLUŞTURMA (QR İşlemleri Silindi)
        print("☁️ Sonuç Firebase'e arşivleniyor...")
        image_data = requests.get(image_url, timeout=15).content
        final_path = os.path.join("static", "paradoks_final.jpg")
        with open(final_path, "wb") as f:
            f.write(image_data)

        cloud_url = upload_to_firebase(final_path)
        full_web_link = f"{VERCEL_SITE_URL}/?url={cloud_url}"

        print("🎉 İşlem başarıyla bitti!")
        
        # HTML'e iki farklı link gönderiyoruz
        return {
            "display_url": f"/static/paradoks_final.jpg?v={time.time()}", # Ekranda hızlı göstermek için yerel resim
            "qr_link": full_web_link # Müşterinin telefonunda açılacak Vercel sitesi
        }

    except Exception as e:
        print(f"❌ Hibrit Mod Hatası: {e}")
        return None

# --- 4. AKIŞ YÖNETİMİ ---
def run_kiosk_process(buton_no):
    global system_state, is_processing_image
    try:
        print("📸 Fotoğraf alınıyor...")
        resp = requests.get(SNAPSHOT_URL, timeout=5)
        if resp.status_code == 200:
            temp_capture = os.path.join("static", "temp_capture.jpg")
            with open(temp_capture, "wb") as f:
                f.write(resp.content)
            
            img = cv2.imread(temp_capture)
            h, w = img.shape[:2]
            target_w = int(h * 9 / 16)
            start_x = (w - target_w) // 2
            cropped = img[:, start_x:start_x + target_w]
            cv2.imwrite(temp_capture, cropped)

            # AI İşlemi
            sonuclar = process_image_with_ai(temp_capture, STYLES[buton_no])
            
            if sonuclar:
                system_state = "SHOWING"
                socketio.emit('state_update', {
                    'state': 'SHOWING',
                    'image_url': sonuclar["display_url"], 
                    'qr_data': sonuclar["qr_link"]  # Vercel linkini arayüze fırlatıyoruz
                })
            else:
                system_state = "IDLE"
                socketio.emit('state_update', {'state': 'IDLE'})
    except Exception as e:
        print(f"❌ Akış Hatası: {e}")
        system_state = "IDLE"
        socketio.emit('state_update', {'state': 'IDLE'})
    finally:
        is_processing_image = False 

@socketio.on('flash_done')
def handle_flash_done(data):
    global is_processing_image
    if not is_processing_image:
        is_processing_image = True
        threading.Thread(target=run_kiosk_process, args=(data['buton_no'],)).start()

def handle_arduino():
    global system_state
    last_action_time = 0  
    cooldown_period = 2.0  

    try:
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.1)
        print("🔌 Arduino Dinleniyor...")
    except:
        print("❌ Arduino portuna bağlanılamadı!")
        return

    while True:
        current_time = time.time() 
        
        if ser.in_waiting > 0:
            kod = ser.readline().decode("utf-8", errors="ignore").strip()
            
            if (current_time - last_action_time) < cooldown_period:
                ser.reset_input_buffer()
                continue

            if system_state == "SHOWING":
                print("🔄 Menüye dönülüyor...")
                system_state = "IDLE"
                socketio.emit('state_update', {'state': 'IDLE'})
                last_action_time = current_time 
                ser.reset_input_buffer()
                continue
            
            if system_state == "IDLE" and kod in STYLES:
                print(f"🎯 Buton {kod} basıldı. Flaş tetikleniyor...")
                system_state = "PROCESSING"
                socketio.emit('trigger_capture', {'buton_no': kod, 'style_name': STYLES[kod]['name']})
                last_action_time = current_time 
                ser.reset_input_buffer()
        
        time.sleep(0.01)

@app.route('/')
def index():
    return render_template('index.html')

if __name__ == '__main__':
    threading.Thread(target=handle_arduino, daemon=True).start()
    print("\n🚀 PARADOKS KIOSK AKTİF! (Hibrit PuLID + Schnell Modu)")
    socketio.run(app, host="0.0.0.0", port=5000, debug=False)