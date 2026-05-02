import os
import sys
import re
from datetime import datetime

from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser
from langchain_classic.retrievers import EnsembleRetriever
from langchain_community.retrievers import BM25Retriever

# Reranker modülleri
from langchain_classic.retrievers.document_compressors import CrossEncoderReranker
from langchain_community.cross_encoders import HuggingFaceCrossEncoder
from langchain_classic.retrievers import ContextualCompressionRetriever

# Lokal LLM Entegrasyonu (Gelişmiş paket kullanımı)
try:
    from langchain_ollama import ChatOllama
except ImportError:
    from langchain_community.chat_models import ChatOllama

from flask import Flask, request, jsonify
from flask_cors import CORS

# --- AYARLAR VE SABİTLER ---
CHROMA_PATH = "./chroma_db"
EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
RERANKER_MODEL = "BAAI/bge-reranker-v2-m3" # Çok dilli, son teknoloji reranker modeli
MODEL_NAME = "gemma3:12b"  # Ollama üzerindeki yerel modelin

# Global değişkenler
rag_chain = None
app = Flask(__name__)
# CORS ayarı: f:\Github Repo\BTU-AI-ASSISTANT\server\btu_assistant_gemma3.py
CORS(app)

def clean_text(text):
    """Metin içindeki gürültüleri temizler, LLM'in daha rahat okumasını sağlar."""
    if not text:
        return ""
    text = re.sub(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', '', text)
    text = re.sub(r'[\*_]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def setup_rag():
    """Reranker destekli RAG mimarisini başlatır."""
    global rag_chain
    print(f"\n🚀 Sistem Başlatılıyor (Hızlı Reranker Modu)... Model: {MODEL_NAME}")

    # 1. LOKAL DİL MODELİNİ YÜKLE
    try:
        # Net cevaplar için temperature 0.1 tutuldu
        llm = ChatOllama(model=MODEL_NAME, temperature=0.1) 
        llm.invoke("Test")
        print("✅ Yerel Dil Modeli (Ollama) bağlandı.")
    except Exception as e:
        print(f"❌ HATA: Ollama veya '{MODEL_NAME}' modeli çalışmıyor! Terminalde 'ollama run gemma3:12b' yazdığınızdan emin olun.")
        sys.exit(1)

    # 2. VEKTÖR VERİTABANINI YÜKLE
    if not os.path.exists(CHROMA_PATH):
        print(f"❌ HATA: {CHROMA_PATH} bulunamadı! Önce markdown_create_db.py çalıştırın.")
        sys.exit(1)

    print("🧠 Embedding modeli yükleniyor...")
    embedding_function = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
    vector_db = Chroma(persist_directory=CHROMA_PATH, embedding_function=embedding_function)
    print("✅ Vektör veritabanı başarıyla yüklendi.")

    # 3. GELİŞMİŞ ARAMA MOTORU (K=12: Hız ve doğruluk dengesi için optimize edildi)
    docs = vector_db.get()
    all_documents = []
    if docs and 'documents' in docs and len(docs['documents']) > 0:
        for i in range(len(docs['documents'])):
            all_documents.append(Document(
                page_content=clean_text(docs['documents'][i]),
                metadata=docs['metadatas'][i] if 'metadatas' in docs else {}
            ))
            
    bm25_retriever = BM25Retriever.from_documents(all_documents)
    bm25_retriever.k = 12 # Süreyi kısaltmak için 20'den 12'ye düşürüldü
    vector_retriever = vector_db.as_retriever(search_kwargs={"k": 12})
    
    ensemble_retriever = EnsembleRetriever(
        retrievers=[bm25_retriever, vector_retriever],
        weights=[0.5, 0.5]
    )

    # 4. RERANKER (BAĞLAM FİLTRELEME) SİSTEMİNİ KUR
    print(f"🎯 Reranker modeli yükleniyor... ({RERANKER_MODEL})")
    cross_encoder_model = HuggingFaceCrossEncoder(model_name=RERANKER_MODEL)
    # 12 belgeden en iyi 5 tanesini seçecek
    compressor = CrossEncoderReranker(model=cross_encoder_model, top_n=7) 
    
    compression_retriever = ContextualCompressionRetriever(
        base_compressor=compressor, 
        base_retriever=ensemble_retriever
    )
    print("✅ Reranker motoru aktif edildi.")

    # --- SORU DÜZELTME (QUERY REWRITING) ADIMI HIZ İÇİN KALDIRILDI ---

    # 5. ASIL CEVAPLAMA PROMPTU
    template = """Sen Bursa Teknik Üniversitesi (BTÜ) öğrencilerine ve personeline yardım etmek için tasarlanmış profesyonel bir yapay zeka asistanısın.
    
    Aşağıdaki "Bağlam" bölümünde üniversitenin veri tabanından çekilmiş bilgiler bulunmaktadır.

    GÖREV KURALLARI:
    1. BAĞLAMA SADIK KAL: Sadece sana verilen "Bağlam" (Context) bölümündeki bilgileri kullanarak cevap ver. Kendi ön bilgini (pre-trained knowledge) veya dış kaynakları kesinlikle kullanma.
    2. HALÜSİNASYON YAPMA: Bağlamda sorunun net ve doğrudan bir cevabı yoksa, kesinlikle tahmin etme veya mantık yürütme. Doğrudan "Üzgünüm, sağlanan belgelerde bu konu hakkında net bir bilgi bulamadım." şeklinde cevap ver.
    3. NETLİK, İSTATİSTİKLER VE SAYMA (COUNTING): Sayısal verilerde öncelikle bağlamda açıkça belirtilen istatistikleri kullan. ANCAK, kullanıcı "kaç adet", "toplam kaç" gibi bir miktar soruyorsa ve metinde doğrudan net bir rakam geçmiyorsa; sana sağlanan bağlamdaki listede yer alan maddeleri/satırları TEK TEK SAYARAK sonucu sen hesapla ve cevabı ver.
    4. KAYNAK GÖSTERİMİ: Cevabının en sonuna mutlaka bağlamdan aldığın "Kaynak : <URL>" bilgisini ekle. Eğer bağlamda birden fazla kaynak varsa hepsini listele.
    5. TEMİZ YAZIM: Gerekirse maddelendirme (bullet points) kullanarak Markdown formatında okunabilir, temiz bir yanıt oluştur. İşaretli sayıları (**_91_** gibi) temizleyerek (Örn: 91) ver.

    Bağlam:
    {context}

    Kullanıcı Sorusu: {question}

    Cevap:"""
    qa_prompt = ChatPromptTemplate.from_template(template)

    # 6. DİNAMİK RAG ZİNCİRİNİ (PIPELINE) KUR
    def format_docs(docs):
        formatted = []
        for doc in docs:
            kaynak = doc.metadata.get("source", "Bilinmeyen URL")
            formatted.append(f"İçerik: {doc.page_content}\nKaynak URL: {kaynak}")
        return "\n\n".join(formatted)

    def get_today_date(_):
        aylar = ["", "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
        gunler = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
        now = datetime.now()
        return f"{now.day} {aylar[now.month]} {now.year} {gunler[now.weekday()]}"

    # Doğrudan kullanıcının sorusu retriever'a gidiyor, LLM sadece 1 kez çalışıyor.
    rag_chain = (
        RunnablePassthrough.assign(context=lambda x: format_docs(compression_retriever.invoke(x["question"])))
        | RunnablePassthrough.assign(bugun=get_today_date)
        | qa_prompt
        | llm
        | StrOutputParser()
    )
    
    print("✅ Reranker destekli RAG Zinciri başarıyla oluşturuldu (Hızlı Mod).")
    return True

# --- API UÇ NOKTASI (ENDPOINT) ---
@app.route('/chat', methods=['POST'])
def chat():
    if not rag_chain:
         return jsonify({"status": "error", "message": "Sistem henüz hazır değil, lütfen bekleyiniz."}), 503

    data = request.json
    original_message = data.get('message', '')

    if not original_message:
        return jsonify({"status": "error", "message": "Boş mesaj gönderilemez."}), 400

    print(f"\n📩 Gelen Soru: {original_message}")

    try:
        cevap = rag_chain.invoke({"question": original_message}) 
        print(f"🤖 Üretilen Cevap:\n{cevap}\n{'-'*50}")
        return jsonify({"status": "success", "reply": cevap})
    
    except Exception as e:
        error_msg = str(e)
        print(f"⚠️ Hata: {error_msg}")
        return jsonify({
            "status": "error", 
            "message": "Cevap üretilirken bir hata oluştu. Lütfen tekrar deneyin."
        }), 500

if __name__ == '__main__':
    print("\n" + "="*50)
    print("🎓 BTÜ Reranker Destekli Asistan Başlatılıyor... (Gemma3)")
    print("="*50)
    if setup_rag():
        app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)