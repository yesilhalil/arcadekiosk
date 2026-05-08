import os
import io
import time
import uuid
import base64
import serial
import cv2
import requests
import qrcode
import numpy as np
import threading  # 🔥 ARTIK GERÇEK THREAD KULLANIYORUZ
from PIL import Image
from flask import Flask, render_template
from flask_socketio import SocketIO
from dotenv import load_dotenv

import google.generativeai as genai
import fal_client
import firebase_admin
from firebase_admin import credentials, storage

# --- YAPILANDIRMA VE ANAHTARLAR ---
load_dotenv()

SERIAL_PORT = os.getenv("SERIAL_PORT", "COM4")
BAUD_RATE = 9600
CAMERA_URL = "http://192.168.1.112:8080/video"
VERCEL_SITE_URL = "https://arcadekiosk.vercel.app"

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
FAL_KEY = os.getenv("FAL_KEY")
FIREBASE_BUCKET = os.getenv("FIREBASE_BUCKET")

os.environ["FAL_KEY"] = FAL_KEY
genai.configure(api_key=GEMINI_API_KEY)

if not firebase_admin._apps:
    cred = credentials.Certificate("serviceAccountKey.json")
    firebase_admin.initialize_app(cred, {'storageBucket': FIREBASE_BUCKET})

app = Flask(__name__)
# 🔥 EN KRİTİK NOKTA: async_mode='threading' diyerek Eventlet'i devre dışı bırakıyoruz.
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

os.makedirs("templates", exist_ok=True)
os.makedirs("static", exist_ok=True)

system_state = "IDLE" 

STYLES = {
    "1": {
        "description": "Cyberpunk style, neon lights, dystopian futuristic city, high-tech aesthetic.",
        "lora_path": "https://v3b.fal.media/files/b/0a992bb3/U1K45GdlqqdKJ1Rbv0xDu_ghibli_lora.safetensors",
        "lora_scale": 0.8, "strength": 0.75, "guidance_scale": 3.5
    },
    "2": {
        "description": "Classic Renaissance oil painting style, royal clothing, dramatic lighting.",
        "lora_path": "https://v3b.fal.media/files/b/0a992d06/yqKSDuH2y7zpBvJjHQAFp_ghibli_lora.safetensors",
        "lora_scale": 0.9, "strength": 0.65, "guidance_scale": 3.5
    },
    "3": {
        "description": "Studio Ghibli nature aesthetic, 2D minimalist art.",
        "lora_path": "https://v3b.fal.media/files/b/0a992e5e/Qq0aPre6xknYETusvflCV_ghibli_lora.safetensors",
        "lora_scale": 0.75, "strength": 0.72, "guidance_scale": 9.0
    }
}

# --- YARDIMCI FONKSİYONLAR ---
def upload_to_firebase(image_path):
    print("☁️ Görsel Firebase'e yükleniyor...")
    bucket = storage.bucket()
    blob = bucket.blob(f"kiosk_images/{uuid.uuid4().hex}.jpg")
    blob.upload_from_filename(image_path)
    blob.make_public()
    return blob.public_url

def process_image_with_ai(image_path, stil_ayarlari, buton_no):
    try:
        img = Image.open(image_path)
        img.thumbnail((512, 512))
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format="JPEG", quality=60)
        img_data = img_byte_arr.getvalue()

        gemini_model = genai.GenerativeModel("gemini-2.5-flash")
        prompt = f"You are a master character designer for [STYLE: {stil_ayarlari['description']}]. Describe the person's face in forensic detail. Force a completely new, epic action pose and environment matching the style. OUTPUT ONLY THE FINAL PROMPT TEXT IN ENGLISH."
        response = gemini_model.generate_content([prompt, {"mime_type": "image/jpeg", "data": img_data}])
        gemini_prompt = response.text.strip().split(":", 1)[-1].strip()
        print(f"🧠 Gemini Prompt Üretti: {gemini_prompt[:50]}...")

        print("🎨 Fal.ai görseli üretiyor...")
        uploaded_original = fal_client.upload_file(image_path)
        handler = fal_client.run(
            "fal-ai/flux-lora", 
            arguments={
                "prompt": gemini_prompt,
                "image_url": uploaded_original,
                "model_name": "flux-dev",
                "num_inference_steps": 28,
                "strength": stil_ayarlari["strength"],
                "image_size": "portrait_16_9",
                "loras": [{"path": stil_ayarlari["lora_path"], "scale": stil_ayarlari["lora_scale"]}],
                "guidance_scale": stil_ayarlari["guidance_scale"],
                "sync_mode": True
            }
        )
        fal_image_url = handler["images"][0]["url"]

        if fal_image_url.startswith("data:image"):
            base64_data = fal_image_url.split(",")[1]
            final_img_bytes = base64.b64decode(base64_data)
        else:
            final_img_bytes = requests.get(fal_image_url).content

        clean_image_path = "static/clean_output.jpg"
        with open(clean_image_path, "wb") as f:
            f.write(final_img_bytes)

        cloud_url = upload_to_firebase(clean_image_path)
        full_web_link = f"{VERCEL_SITE_URL}/?url={cloud_url}"

        ana_resim = Image.open(clean_image_path)
        qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_H, box_size=10, border=4)
        qr.add_data(full_web_link)
        qr.make(fit=True)
        
        qr_resim = qr.make_image(fill_color="black", back_color="white")
        hedef_qr_boyut = int(ana_resim.width * 0.25)
        qr_resim = qr_resim.resize((hedef_qr_boyut, hedef_qr_boyut), Image.NEAREST)
        
        pos_x = ana_resim.width - hedef_qr_boyut - 40
        pos_y = ana_resim.height - hedef_qr_boyut - 40
        ana_resim.paste(qr_resim, (pos_x, pos_y))
        
        final_dosya_adi = f"static/paradoks_final.jpg"
        ana_resim.save(final_dosya_adi)
        
        return final_dosya_adi 

    except Exception as e:
        print(f"❌ AI İşlem Hatası: {e}")
        return None

# --- ARKA PLAN GÖREVİ (Kamera ve AI) ---
def process_kiosk_flow(gelen_kod):
    global system_state
    try:
        print("📸 Kameradan görüntü alınıyor...")
        snapshot_url = CAMERA_URL.replace("/video", "/shot.jpg")
        img_resp = requests.get(snapshot_url, timeout=5)
        
        if img_resp.status_code == 200:
            print("✅ Fotoğraf çekildi, yapay zekaya gönderiliyor...")
            img_array = np.array(bytearray(img_resp.content), dtype=np.uint8)
            frame = cv2.imdecode(img_array, -1)
            
            h, w, _ = frame.shape
            hedef_w = int(h * 9 / 16)
            baslangic_x = (w - hedef_w) // 2
            frame_portrait = frame[:, baslangic_x:baslangic_x + hedef_w]
            
            temp_path = "static/temp_capture.jpg"
            cv2.imwrite(temp_path, frame_portrait)
            
            final_resim_yolu = process_image_with_ai(temp_path, STYLES[gelen_kod], gelen_kod)
            
            if final_resim_yolu:
                system_state = "SHOWING"
                cache_buster = uuid.uuid4().hex[:6] 
                socketio.emit('state_update', {
                    'state': 'SHOWING',
                    'image_url': f"/{final_resim_yolu}?v={cache_buster}"
                })
                print("✅ İşlem bitti, ekranda gösteriliyor.")
            else:
                print("⚠️ AI işlemi başarısız oldu, sistem sıfırlanıyor.")
                system_state = "IDLE"
                socketio.emit('state_update', {'state': 'IDLE'})
        else:
            print("⚠️ Kameradan geçerli bir yanıt alınamadı!")
            system_state = "IDLE"
            socketio.emit('state_update', {'state': 'IDLE'})
            
    except Exception as cam_error:
        print(f"⚠️ Kiosk Akış Hatası: {cam_error}")
        system_state = "IDLE"
        socketio.emit('state_update', {'state': 'IDLE'})

# --- ANA DİNLEME DÖNGÜSÜ ---
def handle_arduino():
    global system_state
    try:
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.1)
        print("🔌 Arduino Dinleniyor...")
    except serial.SerialException as e:
        print(f"❌ Hata: Seri port açılamadı - {e}")
        return

    while True:
        try:
            if ser.in_waiting > 0:
                gelen_kod = ser.readline().decode("utf-8", errors="ignore").strip()
                
                if system_state == "SHOWING":
                    print("🔄 Yeni kişi için ana ekrana dönülüyor...")
                    system_state = "IDLE"
                    socketio.emit('state_update', {'state': 'IDLE'})
                    ser.reset_input_buffer()
                    time.sleep(1) # 🔥 Gerçek sleep
                    continue

                if system_state == "IDLE" and gelen_kod in STYLES:
                    print(f"🎯 BUTON {gelen_kod} TETİKLENDİ!")
                    system_state = "PROCESSING"
                    
                    # 1. FRONTEND'E FLAŞI TETİKLEMESİ İÇİN ANINDA SİNYAL GÖNDER
                    socketio.emit('state_update', {
                        'state': 'PROCESSING', 
                        'style_name': STYLES[gelen_kod]['description'].split(",", 1)[0]
                    })
                    
                    # 2. SISTEMİ GERÇEKTEN 0.1 SANİYE UYUT Kİ TARAYICI FLAŞI PATLATSIN
                    time.sleep(0.1) 
                    
                    # 3. KAMERA VE AI İŞLEMİNİ TAMAMEN BAĞIMSIZ BİR ÇEKİRDEĞE (THREAD) AT
                    threading.Thread(target=process_kiosk_flow, args=(gelen_kod,), daemon=True).start()
                    
            time.sleep(0.05)
        except Exception as e:
            print(f"⚠️ Döngü Hatası: {e}")
            time.sleep(1)

@app.route('/')
def index():
    return render_template('index.html')

if __name__ == '__main__':
    # Arduino dinleme işlemini gerçek bir Thread olarak başlatıyoruz
    threading.Thread(target=handle_arduino, daemon=True).start()
    
    print("\n" + "="*50)
    print("🚀 PARADOKS KIOSK SUNUCUSU AKTİF! (Gerçek Threading Mimarisi)")
    print("👉 Tarayıcından şu adrese git: http://127.0.0.1:5000")
    print("="*50 + "\n")
    
    # Eventlet uyarısı almamak ve stabil çalışmak için
    socketio.run(app, host="0.0.0.0", port=5000, debug=False, use_reloader=False)