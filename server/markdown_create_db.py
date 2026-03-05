import os
import re
import sys
import shutil
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from dotenv import load_dotenv

load_dotenv()

# --- AYARLAR VE SABİTLER ---
MARKDOWN_DIR = "./markdown_data"
CHROMA_PATH = "./chroma_db"
EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
CHUNK_SIZE = 800
CHUNK_OVERLAP = 150  # Cümlelerin bölünme ihtimaline karşı örtüşmeyi biraz artırdık

def get_department_from_url(url):
    """
    URL'yi analiz ederek belgenin hangi üniversite birimine ait olduğunu tespit eder.
    Bu, yapay zekanın bağlamı (context) kaybetmemesi için kritik bir adımdır.
    """
    if not url:
        return "Bilinmeyen Birim"
        
    url_lower = url.lower()
    
    # BTÜ Birim Eşleştirmeleri
    if "/bidb/" in url_lower: return "Bilgi İşlem Daire Başkanlığı"
    elif "/sks/" in url_lower: return "Sağlık, Kültür ve Spor Daire Başkanlığı"
    elif "/kutuphane/" in url_lower: return "Kütüphane ve Dokümantasyon Daire Başkanlığı"
    elif "/oidb/" in url_lower: return "Öğrenci İşleri Daire Başkanlığı"
    elif "/erasmus" in url_lower: return "Erasmus Koordinatörlüğü"
    elif "/uzem/" in url_lower: return "Uzaktan Eğitim Merkezi"
    elif "/ydyo/" in url_lower: return "Yabancı Diller Yüksekokulu"
    elif "merlab" in url_lower: return "Merkezi Araştırma Laboratuvarı"
    elif "kalite" in url_lower: return "Kalite Koordinatörlüğü"
    elif "enstitu" in url_lower: return "Lisansüstü Eğitim Enstitüsü"
    elif "ogrenci" in url_lower: return "Öğrenci Portalı ve Rehberi"
    elif "obs" in url_lower: return "Öğrenci Bilgi Sistemi (OBS) / Bologna"
    elif "/pdb/" in url_lower: return "Personel Daire Başkanlığı"
    elif "/imid/" in url_lower: return "İdari ve Mali İşler Daire Başkanlığı"
    
    return "Genel Üniversite Birimi"

def parse_markdown_file(filepath):
    """Markdown dosyasını ayrıştırıp metadata ve içeriği döndürür."""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    metadata = {
        "title": "Başlıksız Belge",
        "source": "Bilinmeyen Kaynak",
        "type": "Bilinmeyen Tür",
        "category": "Genel"
    }

    match = re.match(r"^---\n(.*?)\n---\n(.*)", content, flags=re.DOTALL)
    if match:
        frontmatter = match.group(1)
        text_content = match.group(2).strip()
        text_content = re.sub(r'[\*_]', '', text_content)
        
        for line in frontmatter.split('\n'):
            line = line.strip()
            if line.startswith('title:'):
                metadata['title'] = line[len('title:'):].strip()
            elif line.startswith('source:'):
                metadata['source'] = line[len('source:'):].strip()
            elif line.startswith('type:'):
                metadata['type'] = line[len('type:'):].strip()
            elif line.startswith('category:'):
                metadata['category'] = line[len('category:'):].strip()
                
        return text_content, metadata
    else:
        return content.strip(), metadata

def load_documents_from_markdown(md_dir):
    """Klasördeki tüm md dosyalarını Langchain Document formatına çevirir."""
    if not os.path.exists(md_dir):
        print(f"❌ HATA: {md_dir} klasörü bulunamadı!")
        return []

    docs = []
    
    for filename in os.listdir(md_dir):
        if not filename.endswith('.md'):
            continue
            
        filepath = os.path.join(md_dir, filename)
        content, metadata = parse_markdown_file(filepath)
        
        if content:
            docs.append(Document(page_content=content, metadata=metadata))
            
    return docs

def clear_database():
    """Eski Chroma veritabanı klasörünü siler."""
    if os.path.exists(CHROMA_PATH):
        print("🧹 Eski veritabanı temizleniyor...")
        shutil.rmtree(CHROMA_PATH)

def create_chroma_db():
    print("🚀 Veritabanı (Chroma DB) oluşturma işlemi başlıyor...")
    
    # 1. Eski DB'yi temizle
    clear_database()

    # 2. Embedding Modelini Yükle
    print(f"🧠 Embedding motoru yükleniyor ({EMBEDDING_MODEL})...")
    try:
        embedding_function = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
    except Exception as e:
        print(f"❌ Embedding hatası: {e}")
        sys.exit(1)

    # 3. Markdown'dan Verileri Oku
    print(f"📥 '{MARKDOWN_DIR}' klasöründen markdown dosyaları okunuyor...")
    docs = load_documents_from_markdown(MARKDOWN_DIR)
    if not docs:
        print("❌ Veri bulunamadı. İşlem iptal edildi.")
        return

    print(f"✅ Toplam {len(docs)} adet markdown belge hafızaya alındı.")

    # 4. Metinleri Parçalara (Chunks) Ayır
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE, 
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "# ", "\n", ".", " ", ""]
    )
    splits = text_splitter.split_documents(docs)
    print(f"🧩 Belgeler vektörel arama için {len(splits)} parçaya bölündü.")

    # 5. GELİŞMİŞ BAĞLAM AŞILAMA (Context Injection) - KRİTİK ADIM
    print("💉 Vektörlere bağlam (context) aşılanıyor...")
    for split in splits:
        title = split.metadata.get('title', 'Başlıksız Belge')
        source_url = split.metadata.get('source', '')
        
        # URL'den departmanı analiz et
        departman = get_department_from_url(source_url)
        
        # Her parçanın başına görünmez bir etiket yerleştiriyoruz
        # Böylece model, okuduğu parçanın hangi birime ve rapora ait olduğunu bilecek
        context_header = f"[KAYNAK BELGE: {title} | İLGİLİ BİRİM: {departman}]\n"
        split.page_content = context_header + split.page_content

    # 6. Vektör Veritabanını Kaydet
    print("💾 Vektörler hesaplanıyor ve veritabanı diske kaydediliyor (Bu biraz zaman alabilir)...")
    try:
        vector_db = Chroma.from_documents(
            documents=splits,
            embedding=embedding_function,
            persist_directory=CHROMA_PATH
        )
        print(f"✨ BAŞARILI! Chroma DB başarıyla oluşturuldu ve '{CHROMA_PATH}' dizinine kaydedildi.")
    except Exception as e:
        print(f"❌ Veritabanı kaydedilirken kritik bir hata oluştu: {e}")

if __name__ == "__main__":
    create_chroma_db()
