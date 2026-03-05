import os
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

# Sabitler
CHROMA_PATH = "./chroma_db"
EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

print("📦 Veritabanı yükleniyor...")
embedding_function = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
vector_db = Chroma(persist_directory=CHROMA_PATH, embedding_function=embedding_function)

# Hatalı cevap aldığımız sorulardan birini test edelim
soru = "Toplam öğrenci sayısı kaçtır?"

print(f"\n❓ Soru: {soru}\n")
print("🔍 Veritabanından en alakalı 3 parça getiriliyor...\n")

# Sadece vektör araması yapıyoruz
docs = vector_db.similarity_search(soru, k=3)

for i, doc in enumerate(docs, 1):
    kaynak = doc.metadata.get('source', 'Bilinmiyor')
    icerik = doc.page_content.replace('\n', ' ')
    
    print(f"--- {i}. BULUNAN PARÇA ---")
    print(f"📄 Kaynak: {kaynak}")
    print(f"📝 İçerik: {icerik[:400]}...\n")