import json
import os
import re
import time
import requests
import io
import random
from urllib.parse import urlparse, urljoin, urldefrag
from dotenv import load_dotenv
from firecrawl import Firecrawl
from pypdf import PdfReader
import pdfplumber
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser


# .env dosyasındaki API anahtarlarını yükle
load_dotenv()

# =============================================================================
# AYARLAR VE SABİTLER
# =============================================================================
FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_KEY")
TARGET_URL = 'https://www.btu.edu.tr/' # Başlangıç noktası
OUTPUT_FILE = "okul_verisi.json"       # Sonuçların kaydedileceği dosya
VISITED_URLS_FILE = "gezilen_sayfalar.json" # Tekrar taramayı önlemek için log dosyası

MODEL = "gemini-1.5-flash" # Metin temizleme için kullanılacak AI modeli

HEDEF_YIL = 2026
LIMIT = 3000           # Toplam çekilecek maksimum içerik sayısı
MAX_HABER_SAYISI = 10  # (Opsiyonel kullanım için tanımlanmış limit)

# =============================================================================
# FİLTRELEME LİSTELERİ
# =============================================================================

# Otomatik taramada bulunamasa bile mutlaka işlenmesi istenen önemli PDF'ler
MANUEL_PDF_LISTESI = [
    "https://depo.btu.edu.tr/img/sayfa//1750918936_f917045e0381e65ac166.pdf",
    "https://depo.btu.edu.tr/img/sayfa//1750919090_9271f0af171b8349ee8c.pdf",
    "https://depo.btu.edu.tr/img/sayfa//1750935863_96a88481aec053f922dd.pdf"
]

# Taranmayacak dosya uzantıları, gereksiz klasörler ve anahtar kelimeler
YASAKLI_KELIMELER = [
    "img/duyurular", "duyurular//", 
    "/assets/", "/icons/", "/img/", "/css/", "/js/", "/fonts/",
    ".rar", ".zip", ".7z", ".tar", ".gz", ".xml", ".json", 
    ".xls", ".xlsx", ".xlsm", ".csv", ".doc", ".docx", ".ppt", ".pptx",
    ".jpg", ".png", ".jpeg", ".mp4", ".avi", ".gif", ".webp", ".svg", ".ico",
    "login", "signin", "signup", "register", "auth", "password", "reset", # Giriş sayfaları
    "giris", "uye-ol", "sepet", "cart", "hesabim", "sifre", "checkout",
    "filter", "sort", "search", "ara", "page=", "page_hbr=", # Arama ve filtreleme parametreleri
    "arsiv", "archive", "tag", "etiket", "addtoany", "share",
    "bilanco", "mali-tablo", "butce", "faaliyet-raporu", "ihale", "dogrudan-temin", # İstenmeyen idari belgeler
    "plan", "kroki", "dwg"
]

# =============================================================================
# YARDIMCI FONKSİYONLAR
# =============================================================================

def normalize_url(url):
    """
    URL'leri standart hale getirir.
    - Fragmentleri (#kısım) temizler.
    - http'yi https yapar.
    - Sondaki slash işaretini kaldırır.
    """
    if not url: return ""
    url = url.strip()
    url, _ = urldefrag(url) # #accordion-1 gibi kısımları atar
    if url.startswith("http://"):
        url = url.replace("http://", "https://")
    return url.rstrip("/")

def advanced_clean_text(text):
    """
    Ham metni temizler:
    - Markdown resim etiketlerini kaldırır.
    - Menü elemanlarını (Hızlı Erişim vb.) temizler.
    - Adres, telefon, footer gibi gürültü verilerini regex ile siler.
    """
    if not text: return ""
    # Markdown resim linklerini temizle
    text = re.sub(r'!\[.*?\]\(.*?\)', '', text) 
    text = re.sub(r'\[.*?\]\(.*?\)', '', text) 
    text = re.sub(r'(\d+\s+-\s+)+\d+', '', text) # 1 - 2 - 3 ... gibi sayfa numaralarını temizle
    text = re.sub(r'HIZLI ERİŞİM.*?(?=\n)', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\d{2}/\d{2}/\d{4}.*?tarihinde güncellenmiştir\.?', '', text)

    # Sayfa altlarında veya yanlarında çıkan standart gürültü metinleri
    noise_patterns = [
        r"Mimar Sinan Mahallesi Mimar Sinan Bulvarı",
        r"Bilgi İşlem Daire Başkanlığı",
        r"0\(224\) 300 32 21",
        r"Tüm Hakları Saklıdır",
        r"Kep Adresi:",
        r"bidb@btu.edu.tr"
    ]
    
    lines = text.split('\n')
    clean_lines = []
    for line in lines:
        is_noise = False
        for pattern in noise_patterns:
            if re.search(pattern, line, re.IGNORECASE):
                is_noise = True
                break
        if not is_noise:
            clean_lines.append(line)
            
    text = "\n".join(clean_lines)
    text = re.sub(r'\s+', ' ', text).strip() # Çoklu boşlukları teke indir
    return text

def safe_get(obj, attr_name, default=None):
    """Nesne veya sözlükten güvenli veri çekme (Hata almamak için)."""
    if isinstance(obj, dict): return obj.get(attr_name, default)
    else: return getattr(obj, attr_name, default)

def is_architectural_plan(text):
    """
    Metnin mimari bir plan veya kroki olup olmadığını tahmin eder.
    - Çok fazla 'm2' veya 'm²' geçiyorsa muhtemelen bina planıdır, elenir.
    """
    if not text: return False
    text_lower = text.lower()
    m2_count = text_lower.count("m2") + text_lower.count("m²")
    if m2_count > 3: return True
    return False

def is_directive_or_regulation(text):
    """Metnin yönetmelik veya yönerge olup olmadığını kontrol eder."""
    if not text: return False
    text_upper = text.upper()
    keywords = ["YÖNERGE", "YÖNETMELİK", "USUL VE ESASLAR", "MEVZUAT"]
    return any(k in text_upper[:2000] for k in keywords)

def extract_links_from_content(content, base_url):
    """
    Markdown içeriğindeki linkleri ayıklar.
    - Sadece btu.edu.tr domain'indeki linkleri alır.
    - İngilizce (/en/) sayfaları ve yasaklı uzantıları filtreler.
    """
    if not content: return []
    found_links = re.findall(r'\[.*?\]\((.*?)\)', content)
    valid_links = []
    base_domain = "btu.edu.tr"
    
    for link in found_links:
        link = link.strip()
        # Görsel dosyalarını link listesine ekleme
        if any(ext in link.lower() for ext in ['.png', '.jpg', '.jpeg', '.svg', '.ico', '.gif']):
            continue

        full_url = urljoin(base_url, link)
        full_url = normalize_url(full_url)
        
        is_english = "/en/" in full_url or full_url.endswith("/en")
        if any(bad in full_url.lower() for bad in YASAKLI_KELIMELER): continue
        
        # Sadece btu.edu.tr altındaki linkleri al
        if base_domain in full_url and full_url.startswith("http") and not is_english:
            valid_links.append(full_url)
            
    return list(set(valid_links))

def save_visited_urls(urls, filename):
    """İşlenen URL listesini JSON olarak kaydeder (Resume/Devam etme mantığı için)."""
    page_urls = list(urls)
    page_urls.sort()
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(page_urls, f, ensure_ascii=False, indent=4)
        print(f"📂 Ziyaret edilen {len(page_urls)} sayfa adresi '{filename}' dosyasına kaydedildi.")
    except Exception as e:
        print(f"⚠️ URL kayıt hatası: {e}")

def extract_text_from_pdf(pdf_url):
    """
    Verilen URL'den PDF indirir ve metne çevirir.
    - Önce pdfplumber dener, başarısız olursa pypdf dener.
    - Mimari plan ise (is_architectural_plan) içeriği boş döner.
    """
    if any(bad in pdf_url.lower() for bad in YASAKLI_KELIMELER): return None

    print(f"📄 PDF Kontrol Ediliyor: {pdf_url}")
    try:
        response = requests.get(pdf_url, timeout=15)
        if response.status_code != 200: return None
        # İçerik gerçekten PDF mi kontrol et
        if not response.content.startswith(b'%PDF'):
            print("   ⚠️ PDF değil (HTML döndü), atlanıyor.")
            return None

        with io.BytesIO(response.content) as f:
            text = ""
            try:
                # 1. Yöntem: pdfplumber
                with pdfplumber.open(f) as pdf:
                    for page in pdf.pages:
                        extracted = page.extract_text()
                        if extracted: text += extracted + "\n"
            except:
                # 2. Yöntem (Yedek): pypdf
                f.seek(0)
                reader = PdfReader(f)
                for page in reader.pages:
                    extracted = page.extract_text()
                    if extracted: text += extracted + "\n"
            
            clean_content = advanced_clean_text(text)
            if is_architectural_plan(clean_content): return None 
            return clean_content
    except: return None

def find_pdf_links_in_markdown(markdown_text):
    """Markdown metni içindeki .pdf uzantılı linkleri bulur."""
    if not markdown_text: return []
    pdf_links = re.findall(r'\((https?://.*?.pdf)\)', markdown_text)
    return list(set(pdf_links))

def should_keep_content(url, content):
    """
    İçeriğin saklanmaya değer olup olmadığına karar verir.
    - Strateji: 'Evergreen' (yönetmelik, bölüm bilgisi) ise her zaman sakla.
    - Haber/Duyuru ise tarih kontrolü yap (Eski haberleri atla).
    """
    url_lower = url.lower()
    
    # Evergreen içerik (Yönetmelik, Bölüm vb.) -> TARİH KONTROLÜ YAPMA
    evergreen_keywords = ["yonetmelik", "mevzuat", "yonerge", "bolum", "ders", "akademik", "iletisim", "hakkimizda", "yonetim", "fakulte"]
    if any(kw in url_lower for kw in evergreen_keywords):
        return True
    
    # Duyuru ve Haberler -> TARİH KONTROLÜ YAP
    is_news = "duyuru" in url_lower or "haber" in url_lower or "etkinlik" in url_lower
    
    if is_news:
        # BTU haber sayfalarında genellikle tarih bu markerlar arasındadır
        start_marker = "ANAHTAR KELİMELER"
        end_marker = "HABER FOTOĞRAFLARI"
        start_match = re.search(re.escape(start_marker), content, re.IGNORECASE)
        end_match = re.search(re.escape(end_marker), content, re.IGNORECASE)
        
        if not start_match or not end_match: return True
            
        start_index = start_match.end()
        end_index = end_match.start()
        if start_index >= end_index: return True
        
        target_section = content[start_index:end_index]
        aylar = r"(Ocak|Şubat|Mart|Nisan|Mayıs|Haziran|Temmuz|Ağustos|Eylül|Ekim|Kasım|Aralık)"
        # Regex ile 2025 veya 2026 yılına ait tarih ara
        pattern = re.compile(rf"(\d{{1,2}})\s+{aylar}\s+(2025|2026)", re.IGNORECASE)
        
        if pattern.search(target_section):
            return True
        else:
            print(f"   🗓️ Eski tarihli haber, atlanıyor: {url}")
            return False

    return True

def clean_complex_content_with_llm(raw_content, url):
    """
    Karmaşık veya bozuk formatlı metinleri (PDF tabloları, takvimler)
    Google Gemini AI kullanarak temizler ve yapılandırır.
    """
    if len(raw_content) < 300: return raw_content
    # Token limitine takılmamak için çok uzun metinleri kısalt
    if len(raw_content) > 25000: raw_content = raw_content[:25000] + "... [Kısaltıldı]"

    llm = ChatGoogleGenerativeAI(model=MODEL, temperature=0, google_api_key=os.getenv("GOOGLE_API_KEY"))
    template = "Metni temizle. İstatistikleri güncelle. Akademik Takvim tarihlerini koru. VERİ: {text}"
    prompt = ChatPromptTemplate.from_template(template)
    chain = prompt | llm | StrOutputParser()
    
    # API hatası olursa 3 kez tekrar dene
    for attempt in range(3):
        try:
            return chain.invoke({"text": raw_content})
        except:
            time.sleep(30)
            return raw_content 
    return raw_content

def discover_subdomains(firecrawl_app, base_url):
    """
    Ana sayfayı tarayıp, önemli alt birimlerin (Fakülteler, Daireler, oidb vb.) 
    URL'lerini otomatik bulur. Bu sayede manuel liste hazırlamak gerekmez.
    """
    print(f"🔍 Ana Sayfa Taranıyor ve Rota Oluşturuluyor: {base_url}")
    try:
        scrape_result = firecrawl_app.scrape(base_url, formats=['markdown'])
        content = safe_get(scrape_result, 'markdown', '')
        all_links = extract_links_from_content(content, base_url)
        
        subdomains = []
        normal_links = []
        
        for link in all_links:
            # Subdomain kontrolü (örn: oidb.btu.edu.tr)
            parsed = urlparse(link)
            if parsed.netloc.endswith("btu.edu.tr") and parsed.netloc != "www.btu.edu.tr" and parsed.netloc != "btu.edu.tr":
                subdomains.append(link)
            else:
                normal_links.append(link)
        
        # Subdomainleri listenin başına al (Öncelikli taranması için)
        prioritized_list = [base_url] + sorted(list(set(subdomains))) + sorted(list(set(normal_links)))
        
        print(f"   ✅ {len(subdomains)} adet alt birim (Subdomain) tespit edildi.")
        return prioritized_list
        
    except Exception as e:
        print(f"❌ Keşif Hatası: {e}. Sadece ana sayfadan başlanıyor.")
        return [base_url]

# =============================================================================
# ANA PROGRAM (MAIN LOOP)
# =============================================================================

def main():
    # Firecrawl başlatma
    firecrawl = Firecrawl(api_key=FIRECRAWL_API_KEY)
    
    tum_veriler = []
    bulunan_pdfler = set(MANUEL_PDF_LISTESI) # Başlangıçta manuel listeyi ekle
    visited_urls = set()
    
    # 1. Adım: Ana sayfa üzerinden alt domainleri (fakülteleri vb.) keşfet
    target_urls = discover_subdomains(firecrawl, TARGET_URL)
    
    print(f"🌐 Tarama Kuyruğu Hazır: {len(target_urls)} adet başlangıç noktası.")
    print(f"🚀 İşlem Başlıyor... (Limit: {LIMIT})")

    index = 0
    # 2. Adım: URL Listesi üzerinde dön (BFS benzeri tarama)
    while index < len(target_urls):
        if len(tum_veriler) >= LIMIT:
            print(f"⚠️ Maksimum içerik limitine ({LIMIT}) ulaşıldı.")
            break
        
        url = target_urls[index]
        index += 1

        if url in visited_urls: continue
        visited_urls.add(url)

        print(f"Scraping ({index}/{len(target_urls)}): {url}")
        
        try:
            # Dil ve yasaklı kelime kontrolü
            if "/en/" in url or url.endswith("/en"): continue
            if any(bad in url.lower() for bad in YASAKLI_KELIMELER): continue

            # Sayfayı 'markdown' formatında çek
            scrape_result = firecrawl.scrape(url, formats=['markdown'])
            raw_content = safe_get(scrape_result, 'markdown', '')
            if not raw_content: continue
            
            # Sayfa içindeki yeni linkleri topla
            page_links = extract_links_from_content(raw_content, url)
            
            # Yeni linkleri kuyruğa ekle (Kuyruk çok şişmesin diye limit kontrolü var)
            if len(target_urls) < LIMIT * 3:
                temp_new_links = []
                for new_link in page_links:
                    if new_link not in visited_urls and new_link not in target_urls:
                        temp_new_links.append(new_link)
                random.shuffle(temp_new_links)
                target_urls.extend(temp_new_links)

            # Temizlik ve Filtreleme
            final_content = advanced_clean_text(raw_content)
            content_len = len(final_content)
            link_count = len(page_links)

            # Çok kısa ve linksiz sayfalar genellikle bozuktur, atla
            if content_len < 200 and link_count < 5:
                print(f"   🗑️ İÇERİK YETERSİZ: {url}")
                continue
            
            # Tarih kontrolü (Eski haber mi?)
            if not should_keep_content(url, raw_content):
                continue
            
            metadata = safe_get(scrape_result, 'metadata', {})
            title = safe_get(metadata, 'title', 'Başlıksız')
            
            # Sayfadaki PDF linklerini biriktir (Daha sonra işlenecek)
            pdf_links = find_pdf_links_in_markdown(raw_content)
            for pdf in pdf_links: bulunan_pdfler.add(pdf)

            # Mimari plan kontrolü (Tekrar)
            if is_architectural_plan(raw_content): continue

            # Kategori (Metadata) Zenginleştirmesi
            category = "Genel"
            url_lower = url.lower()
            if "duyuru" in url_lower or "haber" in url_lower: category = "Duyuru/Haber"
            elif "yonetmelik" in url_lower or "mevzuat" in url_lower: category = "Yönetmelik"
            elif "bolum" in url_lower or "fakulte" in url_lower: category = "Akademik Birim"
            elif ".pdf" in url_lower: category = "Belge"

            # Veriyi listeye ekle
            tum_veriler.append({
                "source": url,
                "title": title,
                "type": "web_page",
                "category": category,
                "content": final_content
            })
            
            time.sleep(1) # Nezaket beklemesi

        except Exception as e:
            print(f"   ❌ Hata: {url} {e}")

    # =============================================================================
    # 3. Adım: PDF İŞLEME AŞAMASI
    # =============================================================================
    print("-" * 50)
    print(f"🔍 {len(bulunan_pdfler)} PDF adayı işleniyor...")
    
    eski_yillar = [str(y) for y in range(2010, 2024)]
    guncel_yillar = ["2025", "2026"]

    for i, pdf_url in enumerate(bulunan_pdfler):
        is_manual = pdf_url in MANUEL_PDF_LISTESI
        if not is_manual and any(bad in pdf_url.lower() for bad in YASAKLI_KELIMELER): 
            continue

        if i > 0 and i % 2 == 0: time.sleep(5) 
        if "plan" in pdf_url.lower() or "kroki" in pdf_url.lower(): continue 

        # Manuel

        if pdf_url in MANUEL_PDF_LISTESI:
                print(f"   ✅ MANUEL TAKVİM İŞLENİYOR: {pdf_url}")
                pdf_text = extract_text_from_pdf(pdf_url)
                if pdf_text and len(pdf_text) > 50:
                    print("   ✨ AI ile düzenleniyor...")
                    pdf_text = clean_complex_content_with_llm(pdf_text, pdf_url)
                    tum_veriler.append({
                        "source": pdf_url,
                        "title": f"PDF Belgesi: {pdf_url.split('/')[-1]}",
                        "type": "pdf_document",
                        "category": "Belge",
                        "content": pdf_text
                    })
                continue

        pdf_text = extract_text_from_pdf(pdf_url)
            
        if pdf_text and len(pdf_text) > 50:
            pdf_text_upper = pdf_text.upper()
            keyword_found = "AKADEMİK TAKVİM" in pdf_text_upper or "AKADEMIK TAKVIM" in pdf_text_upper
            has_old_years = any(y in pdf_text for y in eski_yillar)
            has_new_years = any(y in pdf_text for y in guncel_yillar)

            if keyword_found:
                if is_directive_or_regulation(pdf_text): pass 
                elif has_old_years and not has_new_years:
                    print(f"   🚫 ESKİ TAKVİM: {pdf_url}")
                    continue
                
            if keyword_found or "TABLO" in pdf_text_upper or "ÜCRET" in pdf_text_upper:
                print("   ✨ AI ile düzenleniyor...")
                pdf_text = clean_complex_content_with_llm(pdf_text, pdf_url)

            tum_veriler.append({
                "source": pdf_url,
                "title": f"PDF Belgesi: {pdf_url.split('/')[-1]}",
                "type": "pdf_document",
                "category": "Belge",
                "content": pdf_text
            })

    print("-" * 50)
    print("💾 Veriler Kaydediliyor...")
        
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(tum_veriler, f, ensure_ascii=False, indent=4)
        
    save_visited_urls(visited_urls, VISITED_URLS_FILE)
        
    print(f"🎉 İŞLEM TAMAMLANDI!")

if __name__ == "__main__":
    main()