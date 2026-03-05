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

# Lokal LLM Entegrasyonu
from langchain_community.chat_models import ChatOllama

from flask import Flask, request, jsonify
from flask_cors import CORS

# --- AYARLAR VE SABİTLER ---
CHROMA_PATH = "./chroma_db"
EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
MODEL_NAME = "gemma3:12b"  # Ollama üzerindeki yerel modelin

# Global değişkenler
rag_chain = None
app = Flask(__name__)
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
    """RAG mimarisini, arama motorunu ve LLM zincirlerini başlatır."""
    global rag_chain
    print(f"\n🚀 Sistem Başlatılıyor... Model: {MODEL_NAME}")

    # 1. LOKAL DİL MODELİNİ YÜKLE
    try:
        # Net cevaplar için temperature 0.1 tutuldu
        llm = ChatOllama(model=MODEL_NAME, temperature=0.1) 
        llm.invoke("Test")
        print("✅ Yerel Dil Modeli (Ollama) bağlandı.")
    except Exception as e:
        print(f"❌ HATA: Ollama veya '{MODEL_NAME}' modeli çalışmıyor! Terminalde 'ollama run gemma3:4b' yazdığınızdan emin olun.")
        sys.exit(1)

    # 2. VEKTÖR VERİTABANINI YÜKLE
    if not os.path.exists(CHROMA_PATH):
        print(f"❌ HATA: {CHROMA_PATH} bulunamadı! Önce markdown_create_db.py çalıştırın.")
        sys.exit(1)

    print("🧠 Embedding modeli yükleniyor...")
    embedding_function = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
    vector_db = Chroma(persist_directory=CHROMA_PATH, embedding_function=embedding_function)
    print("✅ Vektör veritabanı başarıyla yüklendi.")

    # 3. GELİŞMİŞ ARAMA MOTORU (Ensemble Retriever: Vektör + Kelime Bazlı)
    docs = vector_db.get()
    all_documents = []
    if docs and 'documents' in docs and len(docs['documents']) > 0:
        for i in range(len(docs['documents'])):
            all_documents.append(Document(
                page_content=clean_text(docs['documents'][i]),
                metadata=docs['metadatas'][i] if 'metadatas' in docs else {}
            ))
            
    bm25_retriever = BM25Retriever.from_documents(all_documents)
    bm25_retriever.k = 6
    vector_retriever = vector_db.as_retriever(search_kwargs={"k": 6})
    
    ensemble_retriever = EnsembleRetriever(
        retrievers=[bm25_retriever, vector_retriever],
        weights=[0.5, 0.5]
    )

# 4. SORU DÜZELTME MOTORU (Query Rewriting)
    rewrite_prompt = ChatPromptTemplate.from_template(
        "Sen bir veri tabanı arama optimizasyon uzmanısın. Kullanıcının uzun sorusunu, sistemde en iyi eşleşmeyi bulacak kısa anahtar kelimelere çevir.\n"
        "KURALLAR:\n"
        "1. Gereksiz fiilleri ve ekleri (okuldaki, yürütülen, kaçtır, nedir) tamamen SİL.\n"
        "2. Kullanıcı 'toplam öğrenci', 'öğrenci topluluğu', 'proje sayısı', 'personel' gibi genel istatistikleri soruyorsa, arama sorgusunun başına mutlaka 'Sayılarla BTÜ' ekle.\n"
        "3. Eğer 'öğrenci topluluğu' soruluyorsa arama sorgun sadece 'Sayılarla BTÜ Öğrenci Topluluğu' olsun (içinde 'sayısı' kelimesi bile geçmesin ki kafası karışmasın).\n"
        "4. Zaman soruluyorsa '2026' ekle.\n"
        "SADECE anahtar kelimeleri yaz, başka hiçbir şey yazma.\n\n"
        "Orijinal Soru: {question}\n"
        "Arama Sorgusu:"
    )
    query_rewriter = rewrite_prompt | llm | StrOutputParser()

    # 5. ASIL CEVAPLAMA PROMPTU (Nihai Prompt)
    template = """Sen Bursa Teknik Üniversitesi (BTÜ) öğrencilerine ve personeline yardım etmek için tasarlanmış profesyonel bir yapay zeka asistanısın.
    
    Aşağıdaki "Bağlam" bölümünde üniversitenin veri tabanından çekilmiş bilgiler bulunmaktadır.

    GÖREV KURALLARI:
    1. KENDİ HAFIZANI KAPAT (ÇOK KRİTİK): Bağlamda (context) yer almayan HİÇBİR BİLGİYİ, kendi ön bilgini (pre-trained knowledge) veya internetteki genel geçer doğruları KESİNLİKLE KULLANMA. Turnitin limitleri, öğrenci sayıları gibi konularda bağlamda net bir sayı yoksa asla tahmin etme, sadece "Üzgünüm, net bir bilgi bulamadım" de.
    2. ZAMAN VE İSTATİSTİK ALGISI: Sınav ve takvim sorularında en güncel tarihleri kullan. 
    3. GENEL İSTATİSTİKLER: Soruda yıl belirtilse (Örn: 2026) bile, bağlamda (özellikle Sayılarla BTÜ kısmında) bulunan rakamları doğrudan ver. Yıl eşleşmiyor diye 'Bağlamda 2026 yılına ait bilgi yok' YAZMA. Direkt sayıları söyle.
    4. DİKKATLİ OKUMA: Bağlamdaki sayıları başlıklarıyla doğru eşleştir.
    5. KAYNAK GÖSTERİMİ: Cevabının en sonuna mutlaka "Kaynak : <URL>" ekle.
    6. TEMİZ YAZIM: "**_91_**" gibi işaretli sayıları Markdown'dan temizleyerek (Örn: 91) ver, sayıları sakın silme.
    Bağlam:
    {context}

    Kullanıcı Sorusu: {corrected_question}

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

    rag_chain = (
        RunnablePassthrough.assign(corrected_question=query_rewriter)
        | RunnablePassthrough.assign(context=lambda x: format_docs(ensemble_retriever.invoke(x["corrected_question"])))
        | RunnablePassthrough.assign(bugun=get_today_date)
        | qa_prompt
        | llm
        | StrOutputParser()
    )
    
    print("✅ RAG Zinciri (Otomatik Soru Düzeltme Özellikli) başarıyla oluşturuldu.")
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

    print(f"\n📩 Gelen Orijinal Soru: {original_message}")

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
    print("🎓 BTÜ Yapay Zeka Asistanı Başlatılıyor... (Gemma3)")
    print("="*50)
    if setup_rag():
        app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)