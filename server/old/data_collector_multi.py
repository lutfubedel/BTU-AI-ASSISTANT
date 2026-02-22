import json
import os
import re
import sys
import time
import requests
import io
import random
from urllib.parse import urlparse, urljoin, urldefrag
from dotenv import load_dotenv

# --- KÜTÜPHANELER ---
from pypdf import PdfReader
import pdfplumber
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

load_dotenv()

# =============================================================================
# AYARLAR VE SABİTLER
# =============================================================================
TARGET_URL = 'https://www.btu.edu.tr/' 
OUTPUT_FILE = "okul_verisi.json"       
VISITED_URLS_FILE = "gezilen_sayfalar.json" 

# Model ayarı (Asla 2.5 yapmayın, kota ve kararlılık için 1.5-flash idealdir)
MODEL = "gemini-1.5-flash" 
HEDEF_YIL = 2026
LIMIT = 3000           

# --- API ANAHTARI YÖNETİMİ (ROTASYON) ---
raw_keys = os.getenv("FIRECRAWL_KEYS", "")
if raw_keys:
    # Virgülle ayrılmış birden fazla anahtar varsa listeye çevir
    FIRECRAWL_API_KEYS = [k.strip() for k in raw_keys.split(",") if k.strip()]
else:
    # Sadece tek anahtar varsa onu kullan (Eski sisteme uyumluluk)
    FIRECRAWL_API_KEYS = [os.getenv("FIRECRAWL_KEY")]

if not FIRECRAWL_API_KEYS or not FIRECRAWL_API_KEYS[0]:
    print("❌ HATA: .env dosyasında FIRECRAWL_KEYS veya FIRECRAWL_KEY bulunamadı!")
    sys.exit(1)

CURRENT_KEY_INDEX = 0 

# =============================================================================
# FİLTRELEME LİSTELERİ
# =============================================================================
MANUEL_PDF_LISTESI = [
    "https://depo.btu.edu.tr/img/sayfa//1750918936_f917045e0381e65ac166.pdf",
    "https://depo.btu.edu.tr/img/sayfa//1750919090_9271f0af171b8349ee8c.pdf",
    "https://depo.btu.edu.tr/img/sayfa//1750935863_96a88481aec053f922dd.pdf"
]

YASAKLI_KELIMELER = [
    "img/duyurular", "duyurular//", 
    "/assets/", "/icons/", "/img/", "/css/", "/js/", "/fonts/",
    ".rar", ".zip", ".7z", ".tar", ".gz", ".xml", ".json", 
    ".xls", ".xlsx", ".xlsm", ".csv", ".doc", ".docx", ".ppt", ".pptx",
    ".jpg", ".png", ".jpeg", ".mp4", ".avi", ".gif", ".webp", ".svg", ".ico",
    "login", "signin", "signup", "register", "auth", "password", "reset",
    "giris", "uye-ol", "sepet", "cart", "hesabim", "sifre", "checkout",
    "filter", "sort", "search", "ara", "page=", "page_hbr=", 
    "arsiv", "archive", "tag", "etiket", "addtoany", "share",
    "bilanco", "mali-tablo", "butce", "faaliyet-raporu", "ihale", "dogrudan-temin",
    "plan", "kroki", "dwg"
]

# =============================================================================
# YARDIMCI FONKSİYONLAR
# =============================================================================

def get_firecrawl_client():
    """Mevcut index'teki API anahtarı ile Firecrawl'ı başlatır."""
    global CURRENT_KEY_INDEX
    api_key = FIRECRAWL_API_KEYS[CURRENT_KEY_INDEX]
    print(f"\n🔄 Firecrawl Aktif: Anahtar {CURRENT_KEY_INDEX + 1} / {len(FIRECRAWL_API_KEYS)}")
    try:
        from firecrawl import FirecrawlApp
        return FirecrawlApp(api_key=api_key)
    except ImportError:
        from firecrawl import Firecrawl
        return Firecrawl(api_key=api_key)

def normalize_url(url):
    if not url: return ""
    url = url.strip()
    url, _ = urldefrag(url) 
    if url.startswith("http://"):
        url = url.replace("http://", "https://")
    return url.rstrip("/")

def advanced_clean_text(text):
    if not text: return ""
    text = re.sub(r'!\[.*?\]\(.*?\)', '', text) 
    text = re.sub(r'\[.*?\]\(.*?\)', '', text) 
    
    # Gelişmiş gürültü temizliği
    text = re.sub(r'(\d+\s+-\s+)+\d+', '', text) 
    text = re.sub(r'(?:-\s*\d+\s*)+', '', text) 
    text = re.sub(r'HIZLI ERİŞİM.*?(?=\n\n|\Z)', '', text, flags=re.IGNORECASE | re.DOTALL) 
    text = re.sub(r'\|(?: --- \|)+', '', text) 
    text = re.sub(r'\d{2}/\d{2}/\d{4}.*?tarihinde güncellenmiştir\.?', '', text)

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
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def safe_get(obj, attr_name, default=None):
    if isinstance(obj, dict): return obj.get(attr_name, default)
    else: return getattr(obj, attr_name, default)

def is_architectural_plan(text):
    if not text: return False
    text_lower = text.lower()
    m2_count = text_lower.count("m2") + text_lower.count("m²")
    if m2_count > 3: return True
    return False

def is_directive_or_regulation(text):
    if not text: return False
    text_upper = text.upper()
    keywords = ["YÖNERGE", "YÖNETMELİK", "USUL VE ESASLAR", "MEVZUAT"]
    return any(k in text_upper[:2000] for k in keywords)

def extract_links_from_content(content, base_url):
    if not content: return []
    found_links = re.findall(r'\[.*?\]\((.*?)\)', content)
    valid_links = []
    base_domain = "btu.edu.tr"
    
    for link in found_links:
        link = link.strip()
        if any(ext in link.lower() for ext in ['.png', '.jpg', '.jpeg', '.svg', '.ico', '.gif']):
            continue

        full_url = urljoin(base_url, link)
        full_url = normalize_url(full_url)
        
        is_english = "/en/" in full_url or full_url.endswith("/en")
        if any(bad in full_url.lower() for bad in YASAKLI_KELIMELER): continue
        
        if base_domain in full_url and full_url.startswith("http") and not is_english:
            valid_links.append(full_url)
            
    return list(set(valid_links))

def save_visited_urls(urls, filename):
    page_urls = list(urls)
    page_urls.sort()
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(page_urls, f, ensure_ascii=False, indent=4)
        print(f"📂 Ziyaret edilen {len(page_urls)} sayfa adresi '{filename}' dosyasına kaydedildi.")
    except Exception as e:
        print(f"⚠️ URL kayıt hatası: {e}")

def extract_text_from_pdf(pdf_url):
    print(f"📄 PDF Kontrol Ediliyor: {pdf_url}")
    try:
        response = requests.get(pdf_url, timeout=15)
        if response.status_code != 200: return None
        if not response.content.startswith(b'%PDF'):
            print("   ⚠️ PDF değil (HTML döndü), atlanıyor.")
            return None

        with io.BytesIO(response.content) as f:
            text = ""
            try:
                with pdfplumber.open(f) as pdf:
                    for page in pdf.pages:
                        extracted = page.extract_text()
                        if extracted: text += extracted + "\n"
            except:
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
    if not markdown_text: return []
    pdf_links = re.findall(r'\((https?://.*?.pdf)\)', markdown_text)
    return list(set(pdf_links))

def should_keep_content(url, content):
    url_lower = url.lower()
    evergreen_keywords = ["yonetmelik", "mevzuat", "yonerge", "bolum", "ders", "akademik", "iletisim", "hakkimizda", "yonetim", "fakulte", "rehber"]
    if any(kw in url_lower for kw in evergreen_keywords):
        return True
    
    is_news = "duyuru" in url_lower or "haber" in url_lower or "etkinlik" in url_lower
    
    if is_news:
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
        pattern = re.compile(rf"(\d{{1,2}})\s+{aylar}\s+(2025|2026)", re.IGNORECASE)
        
        if pattern.search(target_section):
            return True
        else:
            print(f"   🗓️ Eski tarihli haber, atlanıyor: {url}")
            return False

    return True

def clean_complex_content_with_llm(raw_content, url):
    if len(raw_content) < 300: return raw_content
    if len(raw_content) > 25000: raw_content = raw_content[:25000] + "... [Kısaltıldı]"

    llm = ChatGoogleGenerativeAI(model=MODEL, temperature=0, google_api_key=os.getenv("GOOGLE_API_KEY"))
    template = "Metni temizle. İstatistikleri güncelle. Akademik Takvim tarihlerini koru. VERİ: {text}"
    prompt = ChatPromptTemplate.from_template(template)
    chain = prompt | llm | StrOutputParser()
    
    for attempt in range(3):
        try:
            return chain.invoke({"text": raw_content})
        except:
            time.sleep(30)
            return raw_content 
    return raw_content

def discover_subdomains(firecrawl_app, base_url):
    print(f"🔍 Ana Sayfa Taranıyor ve Rota Oluşturuluyor: {base_url}")
    try:
        scrape_result = firecrawl_app.scrape(base_url, formats=['markdown'])
        content = safe_get(scrape_result, 'markdown', '')
        all_links = extract_links_from_content(content, base_url)
        
        subdomains = []
        normal_links = []
        
        for link in all_links:
            parsed = urlparse(link)
            if parsed.netloc.endswith("btu.edu.tr") and parsed.netloc != "www.btu.edu.tr" and parsed.netloc != "btu.edu.tr":
                subdomains.append(link)
            else:
                normal_links.append(link)
        
        prioritized_list = [base_url] + sorted(list(set(subdomains))) + sorted(list(set(normal_links)))
        print(f"   ✅ {len(subdomains)} adet alt birim (Subdomain) tespit edildi.")
        return prioritized_list
    except Exception as e:
        print(f"❌ Keşif Hatası: {e}. Sadece ana sayfadan başlanıyor.")
        return [base_url]

# =============================================================================
# ANA PROGRAM
# =============================================================================

def main():
    global CURRENT_KEY_INDEX
    
    firecrawl = get_firecrawl_client()
    
    tum_veriler = []
    bulunan_pdfler = set(MANUEL_PDF_LISTESI)
    visited_urls = set()
    
    target_urls = discover_subdomains(firecrawl, TARGET_URL)
    
    print(f"🌐 Tarama Kuyruğu Hazır: {len(target_urls)} adet başlangıç noktası.")
    print(f"🚀 İşlem Başlıyor... (Limit: {LIMIT})")

    index = 0
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
            if "/en/" in url or url.endswith("/en"): continue
            if any(bad in url.lower() for bad in YASAKLI_KELIMELER): continue

            scrape_result = firecrawl.scrape(url, formats=['markdown'])
            raw_content = safe_get(scrape_result, 'markdown', '')
            if not raw_content: continue
            
            page_links = extract_links_from_content(raw_content, url)
            
            # Starvation'ı önlemek için yeni linkleri karıştırarak ekliyoruz
            if len(target_urls) < LIMIT * 3:
                temp_new_links = []
                for new_link in page_links:
                    if new_link not in visited_urls and new_link not in target_urls:
                        temp_new_links.append(new_link)
                random.shuffle(temp_new_links)
                target_urls.extend(temp_new_links)

            final_content = advanced_clean_text(raw_content)
            content_len = len(final_content)
            link_count = len(page_links)

            if content_len < 200 and link_count < 5:
                print(f"   🗑️ İÇERİK YETERSİZ: {url}")
                continue
            
            if not should_keep_content(url, raw_content):
                continue
            
            metadata = safe_get(scrape_result, 'metadata', {})
            title = safe_get(metadata, 'title', 'Başlıksız')
            
            pdf_links = find_pdf_links_in_markdown(raw_content)
            for pdf in pdf_links: bulunan_pdfler.add(pdf)

            if is_architectural_plan(raw_content): continue

            # Kategori Ataması
            category = "Genel"
            url_lower = url.lower()
            if "duyuru" in url_lower or "haber" in url_lower: category = "Duyuru/Haber"
            elif "yonetmelik" in url_lower or "mevzuat" in url_lower: category = "Yönetmelik"
            elif "bolum" in url_lower or "fakulte" in url_lower: category = "Akademik Birim"
            elif ".pdf" in url_lower: category = "Belge"

            tum_veriler.append({
                "source": url,
                "title": title,
                "type": "web_page",
                "category": category,
                "content": final_content
            })
            
            time.sleep(1) 

        except Exception as e:
            error_msg = str(e).lower()
            
            # KOTA / KREDİ HATASI YAKALAYICI (API ROTATION)
            if "429" in error_msg or "credit" in error_msg or "quota" in error_msg or "401" in error_msg or "unauthorized" in error_msg:
                print(f"   ⚠️ KREDİ BİTTİ VEYA KOTA DOLDU! (Mevcut Anahtar: {CURRENT_KEY_INDEX + 1})")
                CURRENT_KEY_INDEX += 1
                
                if CURRENT_KEY_INDEX >= len(FIRECRAWL_API_KEYS):
                    print("❌ TÜM FIRECRAWL ANAHTARLARININ KOTASI DOLDU! Tarama mecburen PDF aşamasına geçiyor.")
                    break 
                
                firecrawl = get_firecrawl_client()
                
                # Kaldığı url'den devam edebilmesi için sayacı ve geçmişi 1 adım geri al
                index -= 1
                visited_urls.remove(url)
                print(f"   🔄 Kalan siteler yeni anahtar ile taranmaya devam ediliyor...")
                continue 
            else:
                print(f"   ❌ Hata: {url} {e}")

    # =============================================================================
    # PDF İŞLEME AŞAMASI
    # =============================================================================
    print("-" * 50)
    print(f"🔍 {len(bulunan_pdfler)} PDF adayı işleniyor...")
    
    eski_yillar = [str(y) for y in range(2010, 2024)]
    guncel_yillar = ["2025", "2026"]

    for i, pdf_url in enumerate(bulunan_pdfler):
        # YENİLİK: Manuel eklenen PDF'ler (/img/ içerse bile) yasaklı filtresine takılmaz!
        is_manual = pdf_url in MANUEL_PDF_LISTESI
        if not is_manual and any(bad in pdf_url.lower() for bad in YASAKLI_KELIMELER): 
            continue

        if i > 0 and i % 2 == 0: time.sleep(5) 
        if "plan" in pdf_url.lower() or "kroki" in pdf_url.lower(): continue 

        if is_manual:
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

    # =============================================================================
    # VERİ KAYDETME AŞAMASI (Döngü Dışında - Düzeltildi)
    # =============================================================================
    print("-" * 50)
    print("💾 Veriler Kaydediliyor...")
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(tum_veriler, f, ensure_ascii=False, indent=4)
    
    save_visited_urls(visited_urls, VISITED_URLS_FILE)
    
    print(f"🎉 İŞLEM TAMAMLANDI!")

if __name__ == "__main__":
    main()