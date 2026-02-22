import json
import os
import sys
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
import shutil
from dotenv import load_dotenv

load_dotenv()

# --- AYARLAR VE SABİTLER ---
JSON_FILE = "okul_verisi.json"
CHROMA_PATH = "./chroma_db"
EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
CHUNK_SIZE = 800
CHUNK_OVERLAP = 120

def load_documents_from_json(file_path):
    """
    JSON dosyasını okur ve LangChain'in anlayacağı 'Document' formatına çevirir.
    """
    if not os.path.exists(file_path):
        print(f"❌ Hata: {file_path} bulunamadı!")
        return []

    # JSON dosyasını utf-8 formatında oku
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    documents = []
    for item in data:
        # JSON içindeki 'content' alanını al, boşlukları temizle
        content = item.get('content', '').strip()
        
        # Çok kısa veya boş içerikleri filtrele (Gürültüyü azaltır)
        if not content or len(content) < 10: 
            continue
            
        # LangChain Document nesnesi oluştur
        doc = Document(
            page_content=content, # Asıl metin
            metadata={            # Metinle ilgili ek bilgiler (kaynak, başlık vb.)
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
        # Metni sayılara çevirecek motoru başlat
        embedding_function = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
    except Exception as e:
        print(f"❌ Embedding hatası: {e}")
        sys.exit(1)

    print("⚡ Veriler işleniyor...")
    docs = load_documents_from_json(JSON_FILE)
    if not docs:
        print("❌ JSON dosyası boş veya okunamadı.")
        return None

    # Chunk Stratejisi: Metinleri parçalara bölme
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE, 
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ".", " ", ""] # Bölme öncelik sırası (önce paragraflar, sonra satırlar...)
    )
    splits = text_splitter.split_documents(docs)
    print(f"🧩 Metinler {len(splits)} parçaya bölündü ve işleniyor...")

    # Verileri vektöre çevir ve ChromaDB'ye kaydet
    if os.path.exists(CHROMA_PATH):
        print("⚠️  Eski veritabanı siliniyor...")
        shutil.rmtree(CHROMA_PATH) # Temiz bir başlangıç için eskisini silebiliriz

    vectorstore = Chroma.from_documents(
        documents=splits, 
        embedding=embedding_function, 
        persist_directory=CHROMA_PATH # Diske kalıcı kayıt
    )
    print("💾 Veritabanı başarıyla oluşturuldu ve diske kaydedildi.")

if __name__ == "__main__":
    create_vector_db()
