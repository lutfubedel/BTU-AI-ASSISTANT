import json
import os
import sys
import re
import shutil
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from dotenv import load_dotenv

load_dotenv()

# --- AYARLAR VE SABİTLER ---
JSON_FILE = "okul_verisi.json"
CHROMA_PATH = "./chroma_db"
EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
CHUNK_SIZE = 800
CHUNK_OVERLAP = 120

def clean_text(text):
    if not text:
        return ""
    # 1. Gereksiz linkleri (URL'leri) temizle
    text = re.sub(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', '', text)
    text = re.sub(r'www\.[a-zA-Z0-9-]+\.[a-zA-Z]{2,}', '', text)
    # 2. Uzun tire çizgilerini ve gereksiz ayraçları temizle
    text = re.sub(r'[-\s]{4,}', ' ', text)
    # 3. Markdown kalın/italik işaretlerini temizle (**_12629_** -> 12629)
    text = re.sub(r'[\*_]', '', text)
    # 4. Boş tablo satırlarını ve gereksiz tablo karakterlerini temizle
    text = re.sub(r'\|[\s\|]+\|', '', text)
    # 5. Yan yana gelmiş fazla boşlukları tek boşluğa düşür
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def load_documents_from_json(file_path):
    """
    JSON dosyasını okur, metni temizler ve LangChain'in anlayacağı 'Document' formatına çevirir.
    """
    if not os.path.exists(file_path):
        print(f"❌ Hata: {file_path} bulunamadı!")
        return []

    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    documents = []
    for item in data:
        raw_content = item.get('content', '')
        content = clean_text(raw_content) # METNİ TEMİZLE
        
        # Çok kısa veya boş içerikleri filtrele
        if not content or len(content) < 10: 
            continue
            
        doc = Document(
            page_content=content,
            metadata={
                "source": item.get('source', 'Bilinmiyor'),
                "title": item.get('title', 'Başlıksız'),
                "category": item.get('category', 'Genel')
            }
        )
        documents.append(doc)
    return documents

def create_vector_db():
    """
    Vektör veritabanını (Chroma) oluşturur ve diske kaydeder.
    """
    print(f"⚙️ Embedding motoru hazırlanıyor ({EMBEDDING_MODEL})...")
    try:
        embedding_function = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
    except Exception as e:
        print(f"❌ Embedding hatası: {e}")
        sys.exit(1)

    print("⚡ Veriler işleniyor ve temizleniyor...")
    docs = load_documents_from_json(JSON_FILE)
    if not docs:
        print("❌ JSON dosyası boş veya okunamadı.")
        return None

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE, 
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ".", " ", ""]
    )
    splits = text_splitter.split_documents(docs)
    print(f"🧩 Metinler {len(splits)} parçaya bölündü ve işleniyor...")

# YENİ EKLENEN KISIM: Her chunk'ın başına belgenin başlığını ve türünü gizlice ekle
    for split in splits:
        title = split.metadata.get('title', 'Başlıksız Belge')
        # Bu sayede vektör araması bu parçanın "Akademik Takvim" olduğunu bilecek
        split.page_content = f"[KAYNAK BELGE: {title}]\n{split.page_content}"
        
    if os.path.exists(CHROMA_PATH):
        print("⚠️  Eski veritabanı siliniyor...")
        shutil.rmtree(CHROMA_PATH) 

    vectorstore = Chroma.from_documents(
        documents=splits, 
        embedding=embedding_function, 
        persist_directory=CHROMA_PATH 
    )
    print("💾 Veritabanı başarıyla temiz verilerle oluşturuldu ve diske kaydedildi.")

if __name__ == "__main__":
    create_vector_db()