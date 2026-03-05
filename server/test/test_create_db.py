import os
import sys
import random
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

# --- SABİTLER (Projendeki create_db.py ile uyumlu) ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHROMA_PATH = os.path.join(BASE_DIR, "chroma_db")
EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

def run_database_tests():
    print("🚀 Veritabanı testleri başlatılıyor...\n")

    # 1. Veritabanı Klasörü Kontrolü
    if not os.path.exists(CHROMA_PATH):
        print(f"❌ HATA: Chroma DB klasörü ({CHROMA_PATH}) bulunamadı!")
        print("Lütfen önce create_db.py scriptini çalıştırarak veritabanını oluşturun.")
        sys.exit(1)

    # 2. Veritabanına Bağlanma
    print("📦 Veritabanı yükleniyor (Bu işlem birkaç saniye sürebilir)...")
    try:
        embedding_function = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
        vector_db = Chroma(persist_directory=CHROMA_PATH, embedding_function=embedding_function)
    except Exception as e:
        print(f"❌ HATA: Veritabanına bağlanılamadı. Detay: {e}")
        sys.exit(1)

    # 3. Verileri Çekme
    db_data = vector_db.get()
    documents = db_data.get('documents', [])
    metadatas = db_data.get('metadatas', [])

    if not documents:
        print("❌ HATA: Veritabanında hiç veri (chunk) bulunamadı!")
        sys.exit(1)

    # 4. Rastgele 20 Örnek Seçme
    sample_size = min(20, len(documents))
    random_indices = random.sample(range(len(documents)), sample_size)
    
    print(f"🔍 Toplam {len(documents)} parça arasından rastgele {sample_size} tanesi seçildi.\n")
    print("-" * 60)

    basarili_test_sayisi = 0

    # 5. Seçilen Parçaları Test Etme
    for i, idx in enumerate(random_indices, 1):
        chunk_text = documents[idx]
        metadata = metadatas[idx]
        
        hatalar = []

        # --- KALİTE KONTROLLERİ ---
        if len(chunk_text) <= 40:
            hatalar.append("Çok kısa (<= 40 karakter)")
        if len(chunk_text.split()) < 5:
            hatalar.append("Kelime sayısı yetersiz (< 5)")
        if "[KAYNAK BELGE:" not in chunk_text:
            hatalar.append("Kaynak belge başlığı eksik")
        if "source" not in metadata:
            hatalar.append("Metadata içinde 'source' bilgisi yok")

        # Görsel önizleme hazırlığı
        source_url = metadata.get('source', 'Bilinmeyen Kaynak')
        clean_preview = chunk_text.replace('\n', ' ')[:100]

        # Sonuçları Yazdırma
        if not hatalar:
            print(f"[{i}/{sample_size}] ✅ BAŞARILI | Kaynak: {source_url}")
            print(f"         Önizleme: {clean_preview}...\n")
            basarili_test_sayisi += 1
        else:
            print(f"[{i}/{sample_size}] ❌ BAŞARISIZ | Kaynak: {source_url}")
            print(f"         Hatalar: {', '.join(hatalar)}")
            print(f"         İçerik: {clean_preview}...\n")

    # 6. Test Özeti
    print("-" * 60)
    print(f"🎯 TEST SONUCU: {sample_size} testten {basarili_test_sayisi} tanesi kalite standartlarına uygun.")
    
    if basarili_test_sayisi == sample_size:
        print("✨ Harika! Veritabanındaki metin parçalanma (chunking) işlemi son derece başarılı.")
    else:
        print("⚠️ Bazı parçalarda sorun tespit edildi. `create_db.py` içindeki CHUNK_SIZE ayarlarını gözden geçirebilirsin.")

if __name__ == "__main__":
    run_database_tests()