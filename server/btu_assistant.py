import os
import sys
import json
import re
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

def clean_text(text):
    if not text:
        return ""
    # Linkleri, markdown işaretlerini ve gereksiz boşlukları temizler
    text = re.sub(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', '', text)
    text = re.sub(r'www\.[a-zA-Z0-9-]+\.[a-zA-Z]{2,}', '', text)
    text = re.sub(r'[-\s]{4,}', ' ', text)
    text = re.sub(r'[\*_]', '', text)
    text = re.sub(r'\|[\s\|]+\|', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

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
        raw_content = item.get('content', '')
        content = clean_text(raw_content) # METNİ TEMİZLE
        
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
        # 1. Vektör ve BM25 Arayıcıları Başlat (Genişletilmiş Kapsam k=8)
        embedding_function = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
        vectorstore = Chroma(persist_directory=CHROMA_PATH, embedding_function=embedding_function)
        chroma_retriever = vectorstore.as_retriever(search_kwargs={"k": 8})
        
        docs = load_documents_for_bm25(JSON_FILE)
        if docs:
            bm25_retriever = BM25Retriever.from_documents(docs)
            bm25_retriever.k = 8
            
            retriever = EnsembleRetriever(
                retrievers=[bm25_retriever, chroma_retriever],
                weights=[0.4, 0.6] 
            )
            print("✅ Hybrid Search başarıyla aktif edildi.")
        else:
            print("⚠️ Json dosyası okunamadı, sadece Vektör araması ile devam edilecek.")
            retriever = chroma_retriever

        llm = get_gemini_model()

    except Exception as e:
        print(f"❌ RAG Başlatma Hatası: {e}")
        return False

    # 1. SORU DÜZELTİCİ (Query Rewriter) PROMPT'U
    rewrite_template = """Sen bir arama motoru optimizasyon asistanısın. Kullanıcının girdiği metni, Bursa Teknik Üniversitesi (BTÜ) veritabanında arama yapmak için en uygun, yazım hatasız ve zenginleştirilmiş bir soru cümlesine dönüştür. 
    
    KURALLAR:
    1. Yazım hatalarını düzelt ve çok kısa soruları tamamla.
    2. Eğer soru "zaman, tarih, ne zaman başlıyor, ne zaman bitiyor, sınavlar ne zaman, tatil" gibi ifadeler içeriyorsa, arama teriminin sonuna KESİNLİKLE "Akademik Takvim Tarihleri" kelimesini ekle.
    3. Eğer kullanıcı "yüksek lisans, doktora, enstitü" gibi kelimeler kullanmadıysa, aramanın geneli için "Lisans" kelimesini ekle.
    4. SADECE ve SADECE düzeltilmiş soruyu döndür.
    
    Örnekler:
    - Kullanıcı: "dersler ne zaman" -> Düzeltilmiş: "Lisans dersleri ne zaman başlıyor Akademik Takvim Tarihleri"
    - Kullanıcı: "vizeler" -> Düzeltilmiş: "Lisans ara sınavları vizeler ne zaman Akademik Takvim Tarihleri"
    
    Kullanıcı Metni: {question}
    Düzeltilmiş Soru:"""

    rewrite_prompt = ChatPromptTemplate.from_template(rewrite_template)
    query_rewriter = rewrite_prompt | llm | StrOutputParser()

    # 2. ANA CEVAPLAYICI PROMPT
    template = """Sen Bursa Teknik Üniversitesi (BTÜ) için yardımcı bir yapay zeka asistanısın.
        
        GÖREV KURALLARI:
        1. Bugünün tarihi: {bugun}. Tarihsel soruları buna göre cevapla.
        2. Sadece sana verilen "Bağlam" bilgisini kullan. 
        3. ÖNEMLİ: Tarih, ders başlangıcı, sınav veya tatil zamanları soruluyorsa, "Bağlam" içinde "AKADEMİK TAKVİM" geçen belgelere her zaman ÖNCELİK VER. Geçmiş dönemlere ait duyuruları veya Yüksek Lisans (Enstitü) duyurularını, kullanıcı özellikle sormadığı sürece ana cevap olarak KULLANMA. Doğrudan "BAHAR YARIYILI DERSLERİN BAŞLANGICI" veya "GÜZ YARIYILI DERSLERİN BAŞLANGICI" gibi net verileri ara.
        4. Eğer bağlamda HİÇBİR bilgi yoksa, uydurma.
        5. Cevabının sonuna mutlaka kaynağı (URL) ekle.

        Bağlam:
        {context}

        Kullanıcı Sorusu: {question}
    """
    prompt = ChatPromptTemplate.from_template(template)

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

    # 3. ZİNCİR İŞLEYİŞİ FONKSİYONU (HATA BURADA DÜZELTİLDİ)
    def process_and_retrieve(raw_question):
        # Eğer bir şekilde dict gelirse diye güvenlik önlemi:
        if isinstance(raw_question, dict):
            raw_question = raw_question.get("question", str(raw_question))
            
        # A) Önce soruyu LLM'e gönderip düzelttiriyoruz
        refined_question = query_rewriter.invoke({"question": raw_question})
        print(f"\n🪄 [DEBUG] Orijinal Soru: '{raw_question}'")
        print(f"🪄 [DEBUG] Düzeltilen Soru: '{refined_question}'")
        
        # B) Düzeltilmiş tertemiz soru ile veritabanında arama yapıyoruz
        docs = retriever.invoke(refined_question)
        
        # C) Tüm verileri ana modele (Prompt'a) paslıyoruz
        return {
            "context": format_docs(docs),
            "question": refined_question, # Ana modele de düzgün soruyu veriyoruz
            "bugun": datetime.now().strftime("%d %B %Y")
        }

    # 4. GÜNCELLENMİŞ RAG ZİNCİRİ
    rag_chain = (
        RunnablePassthrough() 
        | process_and_retrieve
        | prompt
        | llm
        | StrOutputParser()
    )
    print("✅ RAG Zinciri (Soru Düzeltme Özellikli) başarıyla oluşturuldu.")
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
        cevap = rag_chain.invoke(message) # Doğrudan string gönderiyoruz
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