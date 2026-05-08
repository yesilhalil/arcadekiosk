import os
import io
import time
import uuid
import serial
import cv2
import requests
import qrcode
import threading
from PIL import Image
from flask import Flask, render_template
from flask_socketio import SocketIO
from dotenv import load_dotenv

import fal_client
import firebase_admin
from firebase_admin import credentials, storage

# --- 1. AYARLAR VE API ---
load_dotenv()

SERIAL_PORT = os.getenv("SERIAL_PORT", "COM4")
BAUD_RATE = 9600
CAMERA_URL = "http://192.168.1.112:8080/video"
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

STYLES = {
    "1": {
        "name": "Cyberpunk",
        "base_prompt": "Cyberpunk style portrait, cinematic lighting, glowing neon lights, futuristic dystopian city background, high-tech streetwear, dramatic rim lighting, masterpiece, 8k resolution, highly detailed",
        "guidance_scale": 4.0
    },
    "2": {
        "name": "Renaissance",
        "description": "Classic Renaissance oil painting portrait, elegant royal clothing, dramatic chiaroscuro lighting, museum quality, masterpiece, brush strokes",
        "guidance_scale": 4.0
    },
    "3": {
        "name": "Studio Ghibli",
        "description": "Studio Ghibli animation style portrait, Hayao Miyazaki style, lush nature background, soft flat anime shading, 2D minimalist masterpiece",
        "guidance_scale": 4.0
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
        # 1. OPTİMİZASYON (Görseli küçültmek ağ hızını artırır)
        img = Image.open(image_path)
        img.thumbnail((768, 768))
        opt_path = "static/opt_upload.jpg"
        img.save(opt_path, format="JPEG", quality=85)
        
        # 🔥 Gemini aşaması tamamen kaldırıldı. Direkt stilin promptu kullanılıyor.
        final_prompt = stil_ayarlari.get('base_prompt', stil_ayarlari.get('description'))

        # 2. YÜKLEME
        print("☁️ Görsel Fal.ai CDN'ine yükleniyor...")
        fal_image_url = fal_client.upload_file(opt_path)

        # 3. ÜRETİM (PULID - HIZLANDIRILMIŞ)
        print("🚀 FLUX PuLID başlatılıyor (Hız Modu: 10 Steps)...")
        fal_headers = {
            "Authorization": f"Key {FAL_KEY}",
            "Content-Type": "application/json"
        }
        
        fal_payload = {
            "prompt": final_prompt,
            "reference_image_url": fal_image_url, 
            "num_inference_steps": 10, # 🔥 Hız için 20'den 10'a düşürüldü
            "guidance_scale": stil_ayarlari["guidance_scale"],
            "image_size": "portrait_16_9"
        }

        # Senkron API çağrısı
        response = requests.post(
            "https://fal.run/fal-ai/flux-pulid",
            headers=fal_headers,
            json=fal_payload,
            timeout=90 
        )
        
        if response.status_code != 200:
            raise Exception(f"API Hatası: {response.text}")

        print("\n✅ Üretim tamamlandı!")
        image_url = response.json()["images"][0]["url"]

        # 4. QR VE KAYIT
        image_data = requests.get(image_url, timeout=15).content
        final_path = os.path.join("static", "paradoks_final.jpg")
        with open(final_path, "wb") as f:
            f.write(image_data)

        print("☁️ Sonuç QR için Firebase'e kaydediliyor...")
        cloud_url = upload_to_firebase(final_path)
        full_web_link = f"{VERCEL_SITE_URL}/?url={cloud_url}"

        ana_resim = Image.open(final_path)
        qr = qrcode.QRCode(version=1, box_size=10, border=4)
        qr.add_data(full_web_link)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="black", back_color="white").resize((250, 250))
        
        ana_resim.paste(qr_img, (ana_resim.width - 290, ana_resim.height - 290))
        ana_resim.save(final_path)
        
        return final_path
    except Exception as e:
        print(f"❌ AI Hatası: {e}")
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

            resim_yolu = process_image_with_ai(temp_capture, STYLES[buton_no])
            
            if resim_yolu:
                system_state = "SHOWING"
                socketio.emit('state_update', {
                    'state': 'SHOWING',
                    'image_url': f"/static/paradoks_final.jpg?v={time.time()}"
                })
                print("✅ İşlem bitti!")
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
    try:
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.1)
        print("🔌 Arduino Dinleniyor...")
    except:
        print("❌ Arduino portuna bağlanılamadı!")
        return

    while True:
        if ser.in_waiting > 0:
            kod = ser.readline().decode("utf-8", errors="ignore").strip()
            
            if system_state == "SHOWING":
                system_state = "IDLE"
                socketio.emit('state_update', {'state': 'IDLE'})
                ser.reset_input_buffer()
                continue
            
            if system_state == "IDLE" and kod in STYLES:
                print(f"🎯 Buton {kod} basıldı. Flaş tetikleniyor...")
                system_state = "PROCESSING"
                ser.reset_input_buffer()
                socketio.emit('trigger_capture', {'buton_no': kod, 'style_name': STYLES[kod]['name']})
        
        time.sleep(0.01)

@app.route('/')
def index():
    return render_template('index.html')

if __name__ == '__main__':
    threading.Thread(target=handle_arduino, daemon=True).start()
    print("\n🚀 PARADOKS KIOSK AKTİF! (Hız ve PuLID Odaklı)")
    socketio.run(app, host="0.0.0.0", port=5000, debug=False)