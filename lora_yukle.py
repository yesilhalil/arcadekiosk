import fal_client
import os

# API anahtarını buraya ekle
os.environ["FAL_KEY"] = "f1f9f3c3-5d7f-4f23-9f80-10f01fdd11cf:016592c54c57eceee7b9d0455e5d130e"

dosya_adi = "ghibli_lora.safetensors" # İndirdiğin LoRA dosyasının tam adı

print(f"{dosya_adi} Fal.ai sunucularına yükleniyor. Lütfen bekleyin (İnternet hızınıza göre 1-2 dakika sürebilir)...")

try:
    # Dosyayı doğrudan Fal.ai'nin hızlı belleğine yüklüyoruz
    hizli_url = fal_client.upload_file(dosya_adi)
    print("\n✅ YÜKLEME BAŞARILI!")
    print("=" * 50)
    print(f"Bu linki kopyala ve STYLES sözlüğündeki lora_path kısmına yapıştır:\n{hizli_url}")
    print("=" * 50)
except Exception as e:
    print(f"Hata oluştu: {e}")