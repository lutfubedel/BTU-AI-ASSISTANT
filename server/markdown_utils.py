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
    "img/duyurular", "duyurular//", "sayfa/detay/sinav_sonuc/",
    "/assets/", "/icons/", "/img/", "/css/", "/js/", "/fonts/",
    ".rar", ".zip", ".7z", ".tar", ".gz", ".xml", ".json", 
    ".xls", ".xlsx", ".xlsm", ".csv", ".doc", ".docx", ".ppt", ".pptx",
    ".jpg", ".png", ".jpeg", ".mp4", ".avi", ".gif", ".webp", ".svg", ".ico",
    "login", "signin", "signup", "register", "auth", "password", "reset",
    "giris", "uye-ol", "sepet", "cart", "hesabim", "sifre", "checkout",
    "filter", "sort", "search", "ara", "page=", "page_hbr=",
    "arsiv", "archive", "tag", "etiket", "addtoany", "share",
    "bilanco", "mali-tablo", "butce", "faaliyet-raporu", "ihale", "dogrudan-temin",
    "plan", "kroki", "dwg", "img/duyurular/"
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
    """Ham metni temizler ama satır yapılarını (Markdown formunu) korur."""
    if not text: return ""
    
    # Görsel ve Markdown Linklerini temizle
    text = re.sub(r'!\[.*?\]\(.*?\)', '', text) 
    text = re.sub(r'\[(.*?)\]\(.*?\)', r'\1', text)
    text = re.sub(r'(\d+\s+-\s+)+\d+', '', text) 
    text = re.sub(r'HIZLI ERİŞİM.*?(?=\n)', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\d{2}/\d{2}/\d{4}.*?tarihinde güncellenmiştir\.?', '', text)

    # 1. Breadcrumb temizliği ve Genel UI link temizliği
    text = re.sub(r'Anasayfa\s*[_]*?/_.*?(?=\n)', '', text, flags=re.IGNORECASE)

    # Menü ve takvim gürültüsü
    text = re.sub(r'\|?\s*Pt\s*\|\s*Sa\s*\|\s*Ça\s*\|\s*Pe\s*\|\s*Cu\s*\|\s*Ct\s*\|\s*Pz\s*\|?.*?(?=\n\n|\Z)', '', text, flags=re.DOTALL)
    
    # Çok sayıda bölüm listesini (Bölüm menülerini) filtreleme
    text = re.sub(r'(\s*-\s+[A-Za-zçÇğĞıİöÖşŞüÜ\s]+ABD\n?)+', '\n', text, flags=re.MULTILINE)

    noise_patterns = [
        r"Mimar Sinan Mahallesi Mimar Sinan Bulvarı",
        r"Bilgi İşlem Daire Başkanlığı",
        r"0\(224\) 300 32 21",
        r"Tüm Hakları Saklıdır",
        r"Kep Adresi:",
        r"bidb@btu.edu.tr",
        r"^(Otomasyon|BTÜ-İMER|Sanal Tur|E-Posta|e-Kampüs|Kütüphane|Anasayfa|Öğrenciyim|Personelim|Dış Paydaşım|Aday Öğrenciyim)$",
        r"^TÜMÜNÜ GÖSTER$", 
        r"^TÜM HABERLER$", 
        r"^<geriileri>$",
        r"sağlanan hizmetlerin iyileştirilmesi ve web sitesinde en iyi deneyimi",
        r"çerezleri kullanır\.",
        r"^kapat$",
        r"💬"
    ]
    
    lines = text.split('\n')
    clean_lines = []
    seen = set()
    for line in lines:
        line_stripped = line.strip()
        
        # Boş satırları koruyabiliriz fakat set üzerinde yinelenen araması yapmamıza gerek yok
        if not line_stripped:
            clean_lines.append(line)
            continue
            
        # Eğer bu satırı daha önce işlediysek, tekrar ekleme
        if line_stripped in seen:
            continue
            
        is_noise = any(re.search(pattern, line, re.IGNORECASE) for pattern in noise_patterns)
        if not is_noise:
            seen.add(line_stripped)
            clean_lines.append(line)
            
    text = "\n".join(clean_lines)
    
    # ÖNEMLİ DÜZELTME: Sadece yan yana boşlukları tek boşluğa indir. Satır atlamalarını KORU.
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text) 
    return text.strip()

def safe_get(obj, attr_name, default=None):
    if isinstance(obj, dict): return obj.get(attr_name, default)
    else: return getattr(obj, attr_name, default)

def is_architectural_plan(text):
    if not text: return False
    text_lower = text.lower()
    return (text_lower.count("m2") + text_lower.count("m²")) > 3

def is_directive_or_regulation(text):
    if not text: return False
    keywords = ["YÖNERGE", "YÖNETMELİK", "USUL VE ESASLAR", "MEVZUAT"]
    return any(k in text.upper()[:2000] for k in keywords)

def extract_links_from_content(content, base_url):
    if not content: return []
    found_links = re.findall(r'\[.*?\]\((.*?)\)', content)
    valid_links = []
    base_domain = "btu.edu.tr"
    
    for link in found_links:
        link = link.strip()
        if any(ext in link.lower() for ext in ['.png', '.jpg', '.jpeg', '.svg', '.ico', '.gif']):
            continue

        full_url = normalize_url(urljoin(base_url, link))
        is_english = "/en/" in full_url or full_url.endswith("/en")
        
        if any(bad in full_url.lower() for bad in YASAKLI_KELIMELER): continue
        
        if base_domain in full_url and full_url.startswith("http") and not is_english:
            valid_links.append(full_url)
            
    return list(set(valid_links))

def save_visited_urls(urls, filename):
    page_urls = sorted(list(urls))
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(page_urls, f, ensure_ascii=False, indent=4)
        print(f"📂 Ziyaret edilen {len(page_urls)} sayfa adresi '{filename}' dosyasına kaydedildi.")
    except Exception as e:
        print(f"⚠️ URL kayıt hatası: {e}")

def extract_text_from_pdf(pdf_url, is_manual=False):
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
            
            # PDF içeriğinde çok fazla m2 veya m² geçiyorsa kroki/plan kabul et ve atla
            if is_architectural_plan(clean_content): 
                print(f"   ⚠️ PDF kroki veya plan içeriyor (m2 sayısı yüksek), atlanıyor: {pdf_url}")
                return None 
                
            return clean_content
    except: return None

def find_pdf_links_in_markdown(markdown_text):
    if not markdown_text: return []
    return list(set(re.findall(r'\((https?://.*?.pdf)\)', markdown_text)))

def should_keep_content(url, content):
    url_lower = url.lower()
    
    evergreen_keywords = ["yonetmelik", "mevzuat", "yonerge", "bolum", "ders", "akademik", "iletisim", "hakkimizda", "yonetim", "fakulte"]
    if any(kw in url_lower for kw in evergreen_keywords):
        return True
    
    if "duyuru" in url_lower or "haber" in url_lower or "etkinlik" in url_lower:
        start_match = re.search(r"ANAHTAR KELİMELER", content, re.IGNORECASE)
        end_match = re.search(r"HABER FOTOĞRAFLARI", content, re.IGNORECASE)
        
        if not start_match or not end_match: return True
            
        start_index, end_index = start_match.end(), end_match.start()
        if start_index >= end_index: return True
        
        target_section = content[start_index:end_index]
        aylar = r"(Ocak|Şubat|Mart|Nisan|Mayıs|Haziran|Temmuz|Ağustos|Eylül|Ekim|Kasım|Aralık)"
        if re.compile(rf"(\d{{1,2}})\s+{aylar}\s+(2025|2026)", re.IGNORECASE).search(target_section):
            return True
        else:
            print(f"   🗓️ Eski tarihli haber, atlanıyor: {url}")
            return False
    return True

def clean_complex_content_with_llm(raw_content, url):
    """Karmaşık veya bozuk formatlı metinleri Google Gemini AI kullanarak temizler. Markdown tablosuna zorlar."""
    if len(raw_content) < 300: return raw_content
    if len(raw_content) > 25000: raw_content = raw_content[:25000] + "... [Kısaltıldı]"

    llm = ChatGoogleGenerativeAI(model=MODEL, temperature=0, google_api_key=os.getenv("GOOGLE_API_KEY"))
    
    # Prompt Geliştirildi: LLM kesinlikle Markdown tablosu/listesi oluşturmaya zorlanıyor ve gürültüler detaylandırıldı.
    template = """Aşağıdaki metni anlamsal bütünlüğünü koruyarak düzenle. 
    1. Sayfa numaraları, filigranlar, iletişim bilgileri, Çerez uyarıları (kapat, kullanım koşulları) gibi web gürültülerini tamamen sil.
    2. Metnin başında, sonunda veya yan panellerinde yer alan 'Breadcrumb (Anasayfa > ...)' menü linklerini; 'Tümünü Göster', 'Geri', 'İleri' gibi genel site navigasyon butonlarını metinden ayıkla.
    3. Eğer metin içerisinde bilgi içeren bir tablo veya liste yapısı seziyorsan bunu KESİNLİKLE düzgün bir "Markdown Tablosu" veya "Markdown Listesi" olarak formatla. Yalnızca içeriğe odaklan! Sütunların birbirine girmesini engelle.
    VERİ: {text}"""
    
    prompt = ChatPromptTemplate.from_template(template)
    chain = prompt | llm | StrOutputParser()
    
    for attempt in range(3):
        try:
            return chain.invoke({"text": raw_content})
        except:
            time.sleep(30)
    return raw_content