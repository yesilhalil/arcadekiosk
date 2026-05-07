import qrcode
import serial
import cv2
import time
import os
import google.generativeai as genai
import fal_client
from PIL import Image
import io
import requests
import base64
from dotenv import load_dotenv
load_dotenv()

# Seri port ayarları (Arduino)
SERIAL_PORT = "COM4"
BAUD_RATE = 9600

# Kamera ayarları
OUTPUT_FILENAME = "temp_capture.jpg"

# API Anahtarları
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
FAL_KEY = os.getenv("FAL_KEY")
FIREBASE_BUCKET = os.getenv("FIREBASE_BUCKET")

if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY ayarlanmamış.")
if not FAL_KEY:
    raise ValueError("FAL_KEY ayarlanmamış.")

os.environ["FAL_KEY"] = FAL_KEY
genai.configure(api_key=GEMINI_API_KEY)

# --- GELİŞMİŞ STİL VE PARAMETRE TANIMLAMALARI ---
# Artık her buton kendi özel ayar paketine (dictionary) sahip.
STYLES = {
    "1": {
        "description": (
            "Cyberpunk style, neon lights, dystopian futuristic city, high-tech aesthetic. "
            "ENVIRONMENT: A dark, rainy neon-lit alleyway or futuristic cyberpunk street. "
            "LIGHTING: Dramatic neon pink, blue, and cyan rim lighting."
        ),
        "lora_path": "https://v3b.fal.media/files/b/0a992bb3/U1K45GdlqqdKJ1Rbv0xDu_ghibli_lora.safetensors", # Cyberpunk LoRA linki
        "lora_scale": 0.8,
        "strength": 0.75,
        "guidance_scale": 3.5
    },
    "2": {
        "description": (
            "Classic Renaissance oil painting style, royal clothing, dramatic lighting, masterpiece art. "
            "ENVIRONMENT: A grand medieval castle hall or a classic portrait studio background. "
            "LIGHTING: Chiaroscuro lighting, dark background with a soft, dramatic warm light on the subject."
        ),
        "lora_path": "https://v3b.fal.media/files/b/0a992d06/yqKSDuH2y7zpBvJjHQAFp_ghibli_lora.safetensors", # Yağlı Boya LoRA linki ile değiştir
        "lora_scale": 0.9,
        "strength": 0.65,
        "guidance_scale": 3.5
    },
    "3": {
        "description": (
            "Studio Ghibli nature aesthetic, 2D minimalist art, flat paint style illustration. "
            "ENVIRONMENT: A breathtaking lush wilderness, rolling green hills, vast blue sky, mossy trees. "
            "LIGHTING: Soft, warm golden hour sunlight filtering through the leaves (komorebi effect)."
        ),
        "lora_path": "https://v3b.fal.media/files/b/0a992e5e/Qq0aPre6xknYETusvflCV_ghibli_lora.safetensors",
        "lora_scale": 0.75,
        "strength": 0.72,
        "guidance_scale": 9,
    }
}

def process_image_with_ai(image_path, stil_ayarlari, buton_no):
    try:
        # 1. Fotoğrafı Hazırla (GEMİNİ İÇİN OPTİMİZE EDİLMİŞ)
        img = Image.open(image_path)
        
        # Orijinal fotoğrafı bozmadan, sadece bellekteki (RAM) kopyasını küçültüyoruz
        # thumbnail() metodu fotoğrafın en/boy oranını bozmadan maksimum 512x512 yapar
        img.thumbnail((512, 512)) 
        
        img_byte_arr = io.BytesIO()
        
        # quality=60 parametresi ile dosya boyutunu %80 oranında küçültüyoruz (Sadece Gemini için)
        img.save(img_byte_arr, format="JPEG", quality=60) 
        img_byte_arr = img_byte_arr.getvalue()
        
        # Terminalde boyut farkını görmek için (opsiyonel)
        print(f"DEBUG (AI): Resim optimize edildi. Yeni boyut: {len(img_byte_arr) / 1024:.1f} KB")

        # 2. Gemini ile Analiz (Dinamik Stil Kullanımı)
        gemini_model = genai.GenerativeModel("gemini-2.5-flash")
        print("DEBUG (AI): Gemini modeli başlatıldı.")
        
        # Prompt'a seçilen butona ait stili (description) yerleştiriyoruz
        # Gemini artık bir "Yönetmen" ve "Karakter Tasarımcısı"
        # Gemini: Polis Eskiz Ressamı + Aksiyon Yönetmeni
        prompt = (
            f"You are a master character designer for [STYLE: {stil_ayarlari['description']}]. "
            "Because the image-to-image denoising strength is very high, your text description is the ONLY way the AI will know what the person looks like. "
            "STRICT RULES FOR YOUR OUTPUT PROMPT: "
            "1. START WITH TRIGGER WORDS: Begin exactly with the trigger words for the style. "
            "2. EXTREME MICRO-DETAIL FACIAL PROFILE (CRITICAL): Describe the person's face in forensic detail. Include gender, approximate age, exact hair color and style (e.g., messy brown hair parted to the side), eye shape and color, eyebrow thickness, nose shape, jawline, skin tone, and any facial hair. "
            "3. SPECIFIC ACCESSORIES: If they have glasses, describe the EXACT frame shape, thickness, and material (e.g., 'round thin metal wire-rimmed glasses'). "
            "4. DYNAMIC POSE: Force a completely new, epic action pose typical for [STYLE] (e.g., heroic stance, running, casting magic). Destroy the original pose. "
            "5. EPIC WORLD: Describe a vast, detailed new background environment matching the style. Destroy the original room/background. "
            "6. OUTPUT ONLY THE FINAL PROMPT TEXT IN ENGLISH. NO INTRODUCTIONS, NO MARKDOWN."
        )
        
        print("Gemini ile fotoğraf analiz ediliyor...")
        response = gemini_model.generate_content([
            prompt,
            {"mime_type": "image/jpeg", "data": img_byte_arr}
        ])
        
        gemini_text_prompt = response.text.strip()
        if ":" in gemini_text_prompt:
            gemini_text_prompt = gemini_text_prompt.split(":", 1)[-1].strip()
        print(f"Üretilen Prompt: {gemini_text_prompt}")

        # 3. Fal.ai Yükleme ve Üretim (PREMIUM KALİTE MODU)
        print("DEBUG (AI): Orjinal görsel Fal.ai'ye yükleniyor...")
        image_url = fal_client.upload_file(image_path)
        print(f"DEBUG (AI): Orjinal görsel Fal.ai'ye yüklendi. URL: {image_url}")

        print(f"Fal.ai (Flux Dev LoRA - Premium) ile görsel üretiliyor... (Buton: {buton_no})")
        
        # SÖZLÜKTEN GELEN DİNAMİK DEĞERLERİ API'YE GÖNDERİYORUZ
        handler = fal_client.run(
            "fal-ai/flux-lora", 
            arguments={
                "prompt": gemini_text_prompt,
                "image_url": image_url,
                "model_name": "flux-dev",           
                "num_inference_steps": 28,          
                "strength": stil_ayarlari["strength"],         # DÜZELTİLDİ: Sabit 0.80 yerine dinamik sözlük değişkeni
                "image_size": "portrait_16_9",
                "loras": [
                    {
                        "path": stil_ayarlari["lora_path"], 
                        "scale": stil_ayarlari["lora_scale"]
                    }
                ],
                "guidance_scale": stil_ayarlari["guidance_scale"], # DÜZELTİLDİ: Sabit 9.0 yerine dinamik sözlük değişkeni
                "sync_mode": True                   
            }
        )
        
        fal_image_url = handler["images"][0]["url"]
        print(f"Görsel üretildi: {fal_image_url}")

        # ... üst kısımlar aynı ...
        
        fal_image_url = handler["images"][0]["url"]
        
        # 4. Final Görseli Çözümle veya İndir
        print("DEBUG (AI): Üretilen görsel işleniyor...")
        
        if fal_image_url.startswith("data:image"):
            # Eğer veri Base64 (metin) olarak geldiyse doğrudan piksellere çevir
            print("Görsel doğrudan metin (Base64) olarak geldi, dönüştürülüyor...")
            # "data:image/jpeg;base64," kısmını atıp sadece kodu alıyoruz
            base64_kodu = fal_image_url.split(",")[1] 
            img_data = base64.b64decode(base64_kodu)
        else:
            # Eğer standart bir https:// linki geldiyse internetten indir
            print(f"Görsel link olarak geldi, indiriliyor... URL kısaltması: {fal_image_url[:30]}...")
            img_data = requests.get(fal_image_url).content
        
        final_dosya_adi = f"paradoks_final_stil_{buton_no}.jpg"
        
        # Resmi bellekte (PIL formatında) aç
        ana_resim = Image.open(io.BytesIO(img_data))
        
        # --- QR KOD OLUŞTURMA BÖLÜMÜ ---
        # QR Kodun içine ne koyacağız?
        # Eğer Base64 geldiyse QR koda devasa metni koyamayız, o yüzden sitenin adresini koyalım
        # Şimdilik kendi sitenin adresini (veya geçici bir metin) yaz
        qr_hedef_link = "https://senin-kiosk-siten.com/yakinda" 
        if not fal_image_url.startswith("data:image"):
            qr_hedef_link = fal_image_url # Eğer link geldiyse linki koy
            
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=2,
        )
        qr.add_data(qr_hedef_link)
        qr.make(fit=True)
        
        qr_resim = qr.make_image(fill_color="black", back_color="white")
        hedef_qr_boyut = int(ana_resim.width * 0.15)
        qr_resim = qr_resim.resize((hedef_qr_boyut, hedef_qr_boyut))
        
        pos_x = ana_resim.width - hedef_qr_boyut - 30
        pos_y = ana_resim.height - hedef_qr_boyut - 30
        
        ana_resim.paste(qr_resim, (pos_x, pos_y))
        
        # QR kodlu final resmi bilgisayara kaydet
        ana_resim.save(final_dosya_adi)
        print(f"✅ İşlem başarıyla tamamlandı! '{final_dosya_adi}' hazır.")

    except Exception as e:
        print(f"AI İşlem Hatası: {e}")

def main():
    print("Seri port dinleniyor (Sonsuz Döngü Modu Aktif)...")
    try:
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.1)
        time.sleep(2) 
        print(f"COM Port {SERIAL_PORT} {BAUD_RATE} baud hızında açıldı.")
    except serial.SerialException as e:
        print(f"Hata: Seri port açılamadı - {e}")
        return

    while True:
        try:
            if ser.in_waiting > 0:
                gelen_kod = ser.readline().decode("utf-8", errors="ignore").strip()
                
                if gelen_kod in STYLES:
                    print("\n" + "="*50)
                    print(f"🎯 BUTON {gelen_kod} TETİKLENDİ! İşlem Başlatılıyor...")
                    print("="*50)
                    
                    # Seçilen butona ait TÜM AYARLARI değişkene atıyoruz
                    secilen_ayarlar = STYLES[gelen_kod]
                    
                    cap = cv2.VideoCapture("http://192.168.1.103:8080/video")
                    
                    if not cap.isOpened():
                        print("Hata: Kamera açılamadı. Tekrar deneniyor...")
                        ser.reset_input_buffer()
                        continue

                    try:
                        time.sleep(0.5) 
                        ret, frame = cap.read()
                        
                        if ret:
                            h, w, _ = frame.shape
                            hedef_w = int(h * 9 / 16) # 3/4 yerine 9/16 yapıyoruz
                            baslangic_x = (w - hedef_w) // 2
                            frame_portrait = frame[:, baslangic_x:baslangic_x + hedef_w]
                            
                            cv2.imwrite(OUTPUT_FILENAME, frame_portrait)
                            print(f"📸 Fotoğraf dikey (portrait) olarak kaydedildi.")
                            
                            # Yeni yapıda, stil stringi yerine direkt sözlük paketini (secilen_ayarlar) gönderiyoruz
                            process_image_with_ai(OUTPUT_FILENAME, secilen_ayarlar, gelen_kod)
                        else:
                            print("Hata: Kameradan görüntü okunamadı.")
                    finally:
                        cap.release()
                        
                        time.sleep(1) 
                        ser.reset_input_buffer() 
                        print("\n✅ Döngü tamamlandı. Yeni kişi bekleniyor...")
                        print("-" * 50)
            
            time.sleep(0.05)

        except KeyboardInterrupt:
            print("\n🛑 Program durduruldu.")
            break
        except Exception as e:
            print(f"⚠️ Bir hata oluştu ama döngü devam ediyor: {e}")
            time.sleep(2)
            continue

    if ser.is_open:
        ser.close()

if __name__ == "__main__":
    main()