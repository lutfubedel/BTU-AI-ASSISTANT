import json
import os
import re
import time
import requests
import io
from urllib.parse import urlparse, urljoin, urldefrag, unquote
from pypdf import PdfReader
import pdfplumber
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
# =============================================================================
# PAYLAŞILAN SABİTLER
# =============================================================================

MODEL = "gemini-1.5-flash" # Metin temizleme için kullanılacak AI modeli

# Taranmayacak dosya uzantıları, gereksiz klasörler ve anahtar kelimeler
YASAKLI_KELIMELER = [
    "img/duyurular", "duyurular//", "sayfa/detay/sinav_sonuc/"
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
    """URL'leri standart hale getirir."""
    if not url: return ""
    url = url.strip()
    url, _ = urldefrag(url)
    url = unquote(url)
    if url.startswith("http://"):
        url = url.replace("http://", "https://")
    return url.rstrip("/")

def advanced_clean_text(text):
    """Ham metni temizler."""
    if not text: return ""
    text = re.sub(r'!\[.*?\]\(.*?\)', '', text) 
    text = re.sub(r'\[.*?\]\(.*?\)', '', text) 
    text = re.sub(r'(\d+\s+-\s+)+\d+', '', text) 
    text = re.sub(r'HIZLI ERİŞİM.*?(?=\n)', '', text, flags=re.IGNORECASE)
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
    """Nesne veya sözlükten güvenli veri çekme."""
    if isinstance(obj, dict): return obj.get(attr_name, default)
    else: return getattr(obj, attr_name, default)

def is_architectural_plan(text):
    """Metnin mimari bir plan veya kroki olup olmadığını tahmin eder."""
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
    """Markdown içeriğindeki linkleri ayıklar."""
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
    """İşlenen URL listesini JSON olarak kaydeder."""
    page_urls = list(urls)
    page_urls.sort()
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(page_urls, f, ensure_ascii=False, indent=4)
        print(f"📂 Ziyaret edilen {len(page_urls)} sayfa adresi '{filename}' dosyasına kaydedildi.")
    except Exception as e:
        print(f"⚠️ URL kayıt hatası: {e}")

def extract_text_from_pdf(pdf_url, is_manual=False):
    """Verilen URL'den PDF indirir ve metne çevirir."""
    if not is_manual and any(bad in pdf_url.lower() for bad in YASAKLI_KELIMELER): 
        return None

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
    """Markdown metni içindeki .pdf uzantılı linkleri bulur."""
    if not markdown_text: return []
    pdf_links = re.findall(r'\((https?://.*?.pdf)\)', markdown_text)
    return list(set(pdf_links))

def should_keep_content(url, content):
    """İçeriğin saklanmaya değer olup olmadığına karar verir."""
    url_lower = url.lower()
    
    evergreen_keywords = ["yonetmelik", "mevzuat", "yonerge", "bolum", "ders", "akademik", "iletisim", "hakkimizda", "yonetim", "fakulte"]
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
    """Karmaşık veya bozuk formatlı metinleri Google Gemini AI kullanarak temizler."""
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
    """Ana sayfayı tarayıp, önemli alt birimlerin URL'lerini otomatik bulur."""
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