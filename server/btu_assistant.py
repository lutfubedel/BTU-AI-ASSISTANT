import os
import sys
import json
from datetime import datetime

from langchain_huggingface import HuggingFaceEmbeddings
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser
from langchain_classic.retrievers import EnsembleRetriever
from langchain_community.retrievers import BM25Retriever
from langchain_text_splitters import RecursiveCharacterTextSplitter

from dotenv import load_dotenv
from flask import Flask, request, jsonify
from flask_cors import CORS

load_dotenv()

# --- AYARLAR VE SABİTLER ---
JSON_FILE = "okul_verisi.json"
CHROMA_PATH = "./chroma_db"
EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

# 🚨 DİKKAT: En kararlı ve kotası geniş model kullanılıyor
MODEL = "gemini-2.5-flash" 

# Global RAG Chain değişkeni
rag_chain = None

app = Flask(__name__)
CORS(app) 

def load_documents_for_bm25(file_path):
    if not os.path.exists(file_path):
        return []
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    web_page_count = sum(1 for item in data if item.get("type") == "web_page")
    pdf_count = sum(1 for item in data if item.get("type") == "pdf_document")
    print(f"📊 'okul_verisi.json' içerisinden {web_page_count} web sitesi ve {pdf_count} PDF başarıyla yüklendi.")
    
    documents = []
    for item in data:
        content = item.get('content', '').strip()
        if content and len(content) >= 10:
            doc = Document(
                page_content=content, 
                metadata={
                    "source": item.get('source', 'Bilinmiyor'), 
                    "title": item.get('title', 'Başlıksız'),
                    "category": item.get('category', 'Genel')
                }
            )
            documents.append(doc)
            
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=800, 
        chunk_overlap=120,
        separators=["\n\n", "\n", ".", " ", ""]
    )
    splits = text_splitter.split_documents(documents)
    return splits

def get_gemini_model():
    if not GOOGLE_API_KEY:
        print("❌ HATA: .env dosyasında GOOGLE_API_KEY bulunamadı!")
        sys.exit(1)

    return ChatGoogleGenerativeAI(
        model=MODEL, 
        temperature=0, 
        google_api_key=GOOGLE_API_KEY
    )

def init_rag_chain():
    global rag_chain
    print("⚙️ Sistem başlatılıyor...")
    
    if not os.path.exists(CHROMA_PATH):
        print(f"❌ HATA: {CHROMA_PATH} klasörü bulunamadı! Lütfen önce create_db.py'yi çalıştırın.")
        return False
        
    try:
        # 1. Vektör (Anlam) Arayıcı - Kapsam Genişletildi (k=5)
        embedding_function = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
        vectorstore = Chroma(persist_directory=CHROMA_PATH, embedding_function=embedding_function)
        chroma_retriever = vectorstore.as_retriever(search_kwargs={"k": 5})
        
        # 2. Kelime (BM25) Arayıcı - Kapsam Genişletildi (k=5)
        docs = load_documents_for_bm25(JSON_FILE)
        if docs:
            bm25_retriever = BM25Retriever.from_documents(docs)
            bm25_retriever.k = 5
            
            # 3. İkisini Birleştir (Hybrid Search)
            retriever = EnsembleRetriever(
                retrievers=[bm25_retriever, chroma_retriever],
                weights=[0.4, 0.6] 
            )
            print("✅ Hybrid Search başarıyla aktif edildi. (Genişletilmiş Ağ: 10 Belge)")
        else:
            print("⚠️ Json dosyası okunamadı, sadece Vektör araması ile devam edilecek.")
            retriever = chroma_retriever

        llm = get_gemini_model()

    except Exception as e:
        print(f"❌ RAG Başlatma Hatası: {e}")
        return False

    template = """Sen Bursa Teknik Üniversitesi (BTÜ) için yardımcı bir yapay zeka asistanısın.
        
        GÖREV KURALLARI:
        1. Bugünün tarihi: {bugun}. Tarihsel soruları (geçti mi, gelecek mi) buna göre cevapla.
        2. Sadece sana verilen "Bağlam" bilgisini kullan. Eğer bağlamda net bir cevap yoksa ama dolaylı yoldan çıkarım yapılabiliyorsa, "Elimdeki bilgilere dayanarak şöyle olabilir..." şeklinde belirt.
        3. Eğer bağlamda HİÇBİR bilgi yoksa, "Üzgünüm, veri tabanımda bu konuda net bir bilgi bulamadım ancak BTÜ web sayfasını ziyaret edebilirsiniz." şeklinde nazikçe cevap ver.
        4. Cevabını verdikten sonra, kullandığın bilginin kaynağını (URL) mutlaka parantez içinde veya madde sonunda belirt.
        
        Örnek Cevap Formatı:
        "...başvurular 15 Eylül'de bitiyor. (Kaynak: https://btu.edu.tr/duyuru-15 )"

        Bağlam (Veritabanından gelen bilgi):
        {context}

        Kullanıcı Sorusu: {question}
    """
    prompt = ChatPromptTemplate.from_template(template)

    # 🚨 EKRANDA NELER BULDUĞUNU GÖRMEK İÇİN DEBUG FONKSİYONU
    def format_docs(docs):
        print(f"\n🔍 [DEBUG] Veritabanından LLM'e {len(docs)} adet belge gönderiliyor...")
        formatted = ""
        for i, doc in enumerate(docs):
            source = doc.metadata.get('source', 'Bilinmiyor')
            title = doc.metadata.get('title', 'Bilinmiyor')
            content = doc.page_content
            print(f"   📄 Belge {i+1} Kaynağı: {source}")
            formatted += f"\n--- KAYNAK {i+1}: {title} (URL: {source}) ---\n{content}\n"
        return formatted

    rag_chain = (
        {
            "context": retriever | format_docs, 
            "question": RunnablePassthrough(), 
            "bugun": lambda x: datetime.now().strftime("%d %B %Y")
        }
        | prompt
        | llm
        | StrOutputParser()
    )
    print("✅ RAG Zinciri başarıyla oluşturuldu.")
    return True

@app.route('/chat', methods=['POST'])
def chat():
    if not rag_chain:
         return jsonify({"status": "error", "message": "Sistem henüz hazır değil, lütfen bekleyiniz."}), 503

    data = request.json
    message = data.get('message', '')

    if not message:
        return jsonify({"status": "error", "message": "Boş mesaj gönderilemez."}), 400

    print(f"\n📩 Yeni Kullanıcı Mesajı: {message}")

    try:
        cevap = rag_chain.invoke(message)
        print(f"\n🤖 ÜRETİLEN CEVAP:\n{cevap}\n{'-'*50}")
        return jsonify({"status": "success", "reply": cevap})
    except Exception as e:
        error_msg = str(e)
        print(f"⚠️ Hata: {error_msg}")
        if "429" in error_msg:
             return jsonify({
                 "status": "error", 
                 "message": "Şu an çok fazla soru soruldu, sistem dinleniyor. Lütfen 30 saniye sonra tekrar deneyin."
             }), 429
        return jsonify({
            "status": "error", 
            "message": "Sistemsel bir hata oluştu, lütfen daha sonra tekrar deneyin."
        }), 500

if __name__ == '__main__':
    if init_rag_chain():
        print("🚀 Flask sunucusu 5000 portunda başlatılıyor...")
        app.run(host='0.0.0.0', port=5000, debug=False)
    else:
        print("❌ Sistem başlatılamadı.")