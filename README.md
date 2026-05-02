# 🎓 BTU AI Asistan

> **Bursa Teknik Üniversitesi öğrenci ve personeli için geliştirilmiş, tamamen yerel çalışan (on-premise) RAG tabanlı yapay zeka asistanı.**

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat&logo=python&logoColor=white)](https://python.org)
[![Flask](https://img.shields.io/badge/Flask-3.1.2-000000?style=flat&logo=flask&logoColor=white)](https://flask.palletsprojects.com)
[![LangChain](https://img.shields.io/badge/LangChain-1.2.11-1C3C3C?style=flat)](https://langchain.com)
[![ChromaDB](https://img.shields.io/badge/ChromaDB-1.5.0-FF6B35?style=flat)](https://trychroma.com)
[![Ollama](https://img.shields.io/badge/Ollama-Gemma3:12b-white?style=flat)](https://ollama.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 📋 İçindekiler

- [Proje Hakkında](#-proje-hakkında)
- [Mimari](#-mimari)
- [Özellikler](#-özellikler)
- [Kullanılan Teknolojiler](#-kullanılan-teknolojiler)
- [Dizin Yapısı](#-dizin-yapısı)
- [Kurulum](#-kurulum)
- [Kullanım](#-kullanım)
- [Test Sonuçları ve Başarılar](#-test-sonuçları-ve-başarılar)
- [Tasarım Kararları](#-tasarım-kararları)
- [Katkıda Bulunma](#-katkıda-bulunma)

---

## 📖 Proje Hakkında

BTU AI Asistan, **Bursa Teknik Üniversitesi (BTÜ)** web sitesindeki bilgileri otomatik olarak toplayıp bir vektör veritabanına işleyen ve bu bilgilere dayanarak öğrenci/personel sorularını doğru, kaynak göstererek yanıtlayan akıllı bir chatbot sistemidir.

### Neden On-Premise?

- 🔒 **Veri Gizliliği:** Üniversite verisi dışarıya çıkmaz
- 🌐 **Çevrimdışı Kullanım:** İnternet bağlantısı gerekmeden çalışır
- 💰 **Sıfır API Maliyeti:** Cevaplama aşamasında hiçbir ücretli API kullanılmaz
- ⚡ **Düşük Gecikme:** Lokal LLM ile hızlı yanıt üretimi

---

## 🏗️ Mimari

```
┌─────────────────────────────────────────────────────────────────┐
│                     VERİ TOPLAMA AŞAMASI                        │
│                                                                 │
│  🌐 btu.edu.tr  ──Firecrawl API──►  data_collector.py           │
│                                         │                       │
│                                    utils.py                     │
│                                    (temizleme, PDF)             │
│                                         │                       │
│                                    markdown_data/               │
│                                    (340 .md belgesi)            │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    VEKTÖRLEŞTİRME AŞAMASI                       │
│                                                                 │
│  markdown_data/ ──► create_db.py ──► chroma_db/                 │
│                     (Embedding +      (Kalıcı vektör DB)        │
│                      Chunking +                                 │
│                      Bağlam Enjeksiyonu)                        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                       SORU-CEVAP AŞAMASI                        │
│                                                                 │
│  Kullanıcı Sorusu                                               │
│       │                                                         │
│       ├──► BM25 Retriever (k=12)  ──┐                           │
│       │                             ├──► Ensemble (50/50)       │
│       └──► Vector Retriever (k=12) ─┘        │                  │
│                                         CrossEncoder Reranker   │
│                                         (24 → Top 7 belge)      │
│                                              │                  │
│                                    Gemma3:12b (Ollama)          │
│                                         (Lokal LLM)             │
│                                              │                  │
│                                    Flask /chat API              │
│                                              │                  │
│                                    💬 Frontend (PHP/JS)         │
└─────────────────────────────────────────────────────────────────┘
```

---

## ✨ Özellikler

### 🔍 Akıllı Veri Toplama
- BTÜ web sitesini tam otomatik olarak tarayan web scraper
- 1000+ URL'yi hafızada tutan artımlı tarama (kaldığı yerden devam eder)
- İngilizce sayfalar, görsel dosyalar, arşivler ve bütçe sayfaları otomatik filtrelenir
- PDF belgelerini `pdfplumber` → `pypdf` fallback zinciriyle işler
- Tablo/takvim içeren karmaşık PDF'leri **Google Gemini AI** ile temizler
- Eski tarihli duyurular (2024 öncesi) otomatik atlanır

### 🧠 Gelişmiş RAG Pipeline
- **Hibrit Retrieval:** BM25 (anahtar kelime) + Vektör (anlam) araması birlikte çalışır
- **CrossEncoder Reranker:** 24 adaydan en kaliteli 7 belgeyi seçer
- **Bağlam Enjeksiyonu:** Her chunk'a kaynak belge ve ilgili birim etiketi eklenir
- Halüsinasyona karşı katı sistem promptu kuralları
- Her yanıta kaynak URL zorunlu olarak eklenir

### 💬 Modern Chat Arayüzü
- ChatGPT benzeri dark-mode arayüz
- Yazıyor... animasyonu
- Otomatik kaydırma
- Hızlı erişim öneri butonları (Akademik Takvim, Kütüphane, Yemekhane)
- URL'leri otomatik tıklanabilir link'e dönüştürme
- Mobil uyumlu responsive tasarım

### 🧪 Otomatik Test Sistemi
- 50 soruluk kapsamlı test veri seti (5 set × 10 soru)
- Türkçe bilinçli metin normalleştirme (`İ→i`, `I→ı`)
- OR mantığıyla çoklu doğru cevap desteği (`muaftır|muafdır|ödemez`)
- 4 metrik otomatik ölçülür: Doğruluk, Kaynak Gösterme, Halüsinasyon, Yanıt Süresi

---

## 🛠️ Kullanılan Teknolojiler

### Backend (Python)

| Katman | Teknoloji | Versiyon | Amaç |
|--------|-----------|---------|------|
| **LLM** | Ollama / Gemma3 | 12b | Lokal dil modeli |
| **Framework** | LangChain | 1.2.11 | RAG pipeline |
| **Vektör DB** | ChromaDB | 1.5.0 | Embedding depolama |
| **Embedding** | sentence-transformers | 5.2.2 | Çok dilli embedding |
| **Reranker** | BAAI/bge-reranker-v2-m3 | - | Bağlam kalitesi |
| **BM25** | rank-bm25 | 0.2.2 | Anahtar kelime arama |
| **Web API** | Flask + Flask-CORS | 3.1.2 | REST endpoint |
| **PDF** | pdfplumber + pypdf | 0.11.9 / 6.7.0 | PDF metin çıkarma |
| **Web Scraping** | Firecrawl | 4.14.1 | Sayfa tarama |
| **AI Temizleme** | Google Gemini 1.5 Flash | - | PDF tablo düzenleme |

### Modeller

| Model | Kullanım Alanı | Boyut |
|-------|----------------|-------|
| `gemma3:12b` (Ollama) | Soru yanıtlama | ~8GB |
| `paraphrase-multilingual-MiniLM-L12-v2` | Metin embedding | ~470MB |
| `BAAI/bge-reranker-v2-m3` | Belge yeniden sıralama | ~570MB |
| `gemini-1.5-flash` | PDF veri temizleme | Cloud API |

### Frontend (Client)

| Teknoloji | Amaç |
|-----------|------|
| PHP | Sayfa sunumu |
| JavaScript (Vanilla) | Chat mantığı, Fetch API |
| Tailwind CSS | Stillendirme |
| Font Awesome | İkonlar |

---

## 📁 Dizin Yapısı

```
BTU-AI-ASSISTANT/
│
├── 📁 server/                          # Python backend
│   │
│   ├── 🐍 btu_assistant_gemma3.py      # Ana RAG asistanı & Flask API
│   ├── 🐍 create_db.py                 # ChromaDB vektör veritabanı oluşturucu
│   ├── 🐍 data_collector.py            # Web scraper & veri toplayıcı
│   ├── 🐍 utils.py                     # Ortak yardımcı fonksiyonlar
│   ├── 🐍 test_model.py                # Otomatik performans test scripti
│   ├── 🐍 demo.py                      # Hızlı demo scripti
│   │
│   ├── 📋 requirements.txt             # Python bağımlılıkları (~150 paket)
│   ├── 🔐 .env                         # API anahtarları (git'e eklenmez)
│   ├── 🚫 .gitignore                   # Git dışlama kuralları
│   │
│   ├── 📂 markdown_data/               # 340 adet .md belgesi (BTÜ içerikleri)
│   │   └── *.md                        # {başlık}_{hash8}.md formatında
│   │
│   ├── 📂 chroma_db/                   # Kalıcı ChromaDB vektör dosyaları
│   │   └── ...                         # (create_db.py tarafından oluşturulur)
│   │
│   ├── 📂 test/                        # Test veri setleri
│   │   ├── test_data_1.json            # Kütüphane & burs (10 soru)
│   │   ├── test_data_2.json            # Ders kaydı & e-posta (10 soru)
│   │   ├── test_data_3.json            # Yemekhane & sağlık (10 soru)
│   │   ├── test_data_4.json            # Erasmus & teknoloji (10 soru)
│   │   ├── test_data_5.json            # İstatistikler & spor (10 soru)
│   │   └── test_data_all.json          # Tüm 50 soru birleşik
│   │
│   ├── 📂 reports/                     # Set bazında test raporları
│   │   ├── test_raporu_1.txt ~ 5.txt
│   │   └── test_raporu_all.txt
│   │
│   ├── 📄 test_raporu.txt              # Son test çalıştırması sonuçları
│   ├── 📄 visited_urls.json            # 1000+ taranmış URL hafızası
│   └── 📄 btu_ai_proje_raporu.md       # Detaylı teknik proje raporu
│
├── 📁 client/                          # Web arayüzü (PHP + JS)
│   ├── 🌐 index.php                    # Ana chat arayüzü
│   ├── 🎨 style.css                    # Özel stiller & animasyonlar
│   ├── ⚙️  script.js                   # Chat mantığı & API iletişimi
│   └── 📁 images/
│       └── btu_icon.png                # BTÜ logosu
│
├── 📄 rapor.docx                       # Proje raporu (Word belgesi)
├── 📄 LICENSE                          # MIT Lisansı
└── 📄 README.md                        # Bu dosya
```

---

## ⚙️ Kurulum

### Ön Gereksinimler

- Python 3.10+
- [Ollama](https://ollama.com) kurulu ve çalışıyor olmalı
- PHP (client için) veya herhangi bir HTTP sunucusu
- Firecrawl API anahtarı (veri toplama için)
- Google API anahtarı (PDF temizleme için, opsiyonel)

### 1. Depoyu Klonla

```bash
git clone https://github.com/lutfubedel/BTU-AI-ASSISTANT.git
cd BTU-AI-ASSISTANT/server
```

### 2. Sanal Ortam Oluştur ve Bağımlılıkları Kur

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS/Linux
source venv/bin/activate

pip install -r requirements.txt
```

### 3. Ortam Değişkenlerini Ayarla

`server/.env` dosyasını oluştur:

```env
FIRECRAWL_KEY=your_firecrawl_api_key_here
GOOGLE_API_KEY=your_google_api_key_here
```

### 4. Ollama ile LLM'i İndir

```bash
ollama pull gemma3:12b
```

---

## 🚀 Kullanım

Sistemi ilk kez kullanmak için adımları sırayla takip edin:

### Adım 1 — Veri Topla

```bash
cd server
python data_collector.py
```

> BTÜ web sitesini tarar ve `markdown_data/` klasörüne ~340 Markdown dosyası kaydeder.
> Daha önce taranan URL'leri atlar; kaldığı yerden devam eder.

### Adım 2 — Vektör Veritabanını Oluştur

```bash
python create_db.py
```

> Markdown dosyalarını okur, embedding hesaplar ve `chroma_db/` klasörüne kaydeder.
> İlk çalıştırma 10-20 dakika sürebilir.

### Adım 3 — Ollama LLM'i Başlat

```bash
ollama run gemma3:12b
```

### Adım 4 — Flask API'yi Başlat

```bash
python btu_assistant_gemma3.py
```

> API `http://localhost:5000` adresinde çalışmaya başlar.

### Adım 5 — Frontend'i Aç

`client/index.php` dosyasını PHP sunucusunda çalıştır veya doğrudan tarayıcıda aç:

```
http://localhost/BTU-AI-ASSISTANT/client/
```

### Manuel API Testi

```bash
curl -X POST http://localhost:5000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Kütüphanede kaç bilgisayar var?"}'
```

**Yanıt:**
```json
{
  "status": "success",
  "reply": "Üniversite kütüphanesinde 30 adet masaüstü bilgisayar bulunmaktadır...\n\nKaynak: https://kutuphane.btu.edu.tr/..."
}
```

### Performans Testini Çalıştır

```bash
python test_model.py
```

---

## 📊 Test Sonuçları ve Başarılar

50 soruluk kapsamlı test setinde elde edilen sonuçlar:

| Metrik | Sonuç | Hedef |
|--------|-------|-------|
| ✅ **Doğruluk Oranı** | **%88.0** | > %85 |
| 🔗 **Kaynak Gösterme** | **%100.0** | > %90 |
| 🚫 **Halüsinasyon Oranı** | **%12.0** | < %15 |
| ⏱️ **Ort. Yanıt Süresi** | **17.58 sn** | — |

### Test Kapsamı

Test soruları 5 kategoriye ayrılmıştır:

| Set | Konu Alanı |
|-----|-----------|
| Set 1 | Kütüphane (bilgisayar, gecikme cezası, ödünç) & Bursiyer hakları |
| Set 2 | Ders kaydı, e-posta formatı, AGNO limitleri, kayıt dondurma |
| Set 3 | Yemekhane saatleri, revir, PDR danışmanlık, sağlık birimi |
| Set 4 | Erasmus başvurusu, Eduroam, Turnitin, MERLAB |
| Set 5 | Akademik istatistikler, öğrenci toplulukları, spor turnuvaları |

### Örnek Başarılı Yanıtlar

> **Soru:** "Kütüphanede ödünç alınan kitabın günü geçerse günlük ne kadar ceza uygulanır?"
>
> **Yanıt:** "Her geçen gün için 0,50 kuruş gecikme cezası alınır. Borcun 10 TL'yi geçmesi halinde kitap ödünç-iade hizmetinden faydalanamaz."
>
> **Kaynak:** `https://kutuphane.btu.edu.tr/tr/sayfa/detay/4131/sss`

---

## 💡 Tasarım Kararları

| Karar | Gerekçe |
|-------|---------|
| **Hibrit Retrieval (BM25 + Vektör)** | Tam kelime eşleşmesi + anlam araması birlikte kullanılarak recall artırıldı |
| **CrossEncoder Reranker** | 24 adaydan en iyi 7'yi seçerek LLM bağlamı kalitesi iyileştirildi |
| **Lokal LLM (Ollama)** | Veri gizliliği ve çevrimdışı kullanım için cloud API yerine lokal model tercih edildi |
| **Google Gemini (Sadece veri toplama)** | Karmaşık PDF tablolarını temizlemek için yalnızca `data_collector.py` aşamasında kullanılıyor |
| **Chunk Bağlam Etiketi** | `[KAYNAK BELGE: X \| İLGİLİ BİRİM: Y]` etiketi retrieval kalitesini ve kaynak doğruluğunu artırıyor |
| **OR mantığı test eşleştirmede** | `"muaftır\|muafdır\|ödemez"` varyasyonları sayesinde anlam doğruyken teknik hata sayılmıyor |
| **Artımlı tarama** | `visited_urls.json` ile daha önce taranan sayfalar atlanır; kota kesilirse kaldığı yerden devam eder |

---

## 🔧 Sistem Gereksinimleri

| Bileşen | Minimum | Önerilen |
|---------|---------|---------|
| RAM | 16 GB | 32 GB |
| GPU | — | NVIDIA 8GB+ VRAM |
| Disk | 15 GB | 30 GB |
| CPU | 8 çekirdek | 16 çekirdek |
| Python | 3.10 | 3.11+ |

> **Not:** GPU olmadan da çalışır ancak yanıt süresi 30-60 saniyeye çıkabilir. NVIDIA GPU ile ortalama süre ~17 saniyedir.

---

## 🤝 Katkıda Bulunma

1. Bu repoyu fork edin
2. Feature branch oluşturun: `git checkout -b feature/yeni-ozellik`
3. Değişikliklerinizi commit edin: `git commit -m 'feat: yeni özellik eklendi'`
4. Branch'inizi push edin: `git push origin feature/yeni-ozellik`
5. Pull Request açın

---

## 📄 Lisans

Bu proje [MIT Lisansı](LICENSE) altında lisanslanmıştır.

---

<div align="center">
  <strong>🎓 Bursa Teknik Üniversitesi — BTU AI Asistan</strong><br>
  Öğrenciler ve personel için, yapay zeka ile güçlendirilmiş bilgi erişimi.
</div>
