import json
import os
import time
import sys
import requests
import re
from urllib.parse import urljoin, urldefrag, unquote
from dotenv import load_dotenv
from firecrawl import Firecrawl

# utils.py modülündeki fonksiyonlar
from utils import (
    YASAKLI_KELIMELER, 
    safe_get, 
    extract_links_from_content, 
    advanced_clean_text, 
    should_keep_content, 
    find_pdf_links_in_markdown, 
    is_architectural_plan, 
    extract_text_from_pdf, 
    clean_complex_content_with_llm, 
    is_directive_or_regulation,
    save_visited_urls
)

load_dotenv()

# =============================================================================
# AYARLAR VE SABİTLER
# =============================================================================
FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_KEY")

if not FIRECRAWL_API_KEY:
    print("❌ HATA: .env dosyasında FIRECRAWL_KEY bulunamadı!")
    sys.exit(1)

OUTPUT_FILE = "okul_verisi.json"       
VISITED_URLS_FILE = "visited_urls.json" 
TARGET_URL = 'https://www.btu.edu.tr/' 

# Otomatik taramada bulunamasa bile mutlaka işlenmesi istenen önemli PDF'ler
MANUEL_PDF_LISTESI = [
    "https://depo.btu.edu.tr/img/sayfa//1750918936_f917045e0381e65ac166.pdf",
    "https://depo.btu.edu.tr/img/sayfa//1750919090_9271f0af171b8349ee8c.pdf",
    "https://depo.btu.edu.tr/img/sayfa//1750935863_96a88481aec053f922dd.pdf"
]

def normalize_url(url):
    if not url: return ""
    url = url.strip()
    url, _ = urldefrag(url) 
    url = unquote(url) 
    if url.startswith("http://"):
        url = url.replace("http://", "https://")
    return url.rstrip("/")

def hizli_html_link_bul(url):
    """Firecrawl kredisi harcamadan sayfa içindeki linkleri hızlıca bulur."""
    try:
        res = requests.get(url, timeout=5) 
        if res.status_code != 200: return []
        html = res.text
        
        hrefs = re.findall(r'href=[\'"]?(https?://[^\'" >]+)', html)
        rel_hrefs = re.findall(r'href=[\'"]?(/[^\'" >]+)', html)
        
        valid_links = []
        base_domain = "btu.edu.tr"
        
        for link in hrefs:
            if base_domain in link: valid_links.append(normalize_url(link))
                
        for rel in rel_hrefs:
            full_url = urljoin(url, rel)
            if base_domain in full_url: valid_links.append(normalize_url(full_url))
                
        return list(set(valid_links))
    except:
        return []

def load_existing_data():
    """Mevcut json dosyalarını okuyarak listeleri hafızaya alır."""
    tum_veriler = []
    visited_urls = set()

    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
            try: tum_veriler = json.load(f)
            except: pass

    if os.path.exists(VISITED_URLS_FILE):
        with open(VISITED_URLS_FILE, 'r', encoding='utf-8') as f:
            try:
                urls = json.load(f)
                visited_urls = set(urls)
            except: pass

    return tum_veriler, visited_urls

# =============================================================================
# ANA TARAMA DÖNGÜSÜ
# =============================================================================
def main():
    print("⚙️ Veritabanı ve Geçmiş Hafıza Yükleniyor...")
    tum_veriler, visited_urls = load_existing_data()
    baslangic_veri_sayisi = len(tum_veriler)
    
    print(f"📦 Mevcut Veri: {baslangic_veri_sayisi} | 🌐 Bilinen URL: {len(visited_urls)}")
    
    firecrawl = Firecrawl(api_key=FIRECRAWL_API_KEY)
    
    # Manuel PDF'leri kuyruğa al (Eğer taranmadılarsa)
    bulunan_yeni_pdfler = set()
    for m_pdf in MANUEL_PDF_LISTESI:
        if m_pdf not in visited_urls:
            bulunan_yeni_pdfler.add(m_pdf)
    
    # Hedef URL listesini oluştur
    target_urls = list(visited_urls)
    if TARGET_URL not in target_urls:
        target_urls.insert(0, TARGET_URL)
        
    kuyruk_index = 0
    yeni_kayit_sayisi = 0

    print("\n🚀 EKSİK TARAYICI BAŞLATILDI! Her adım raporlanacak...\n" + "="*50)

    while kuyruk_index < len(target_urls):
        url = target_urls[kuyruk_index]
        kuyruk_index += 1

        if "/en/" in url or url.endswith("/en"): continue
        if any(bad in url.lower() for bad in YASAKLI_KELIMELER): continue

        # DURUM 1: SAYFA ZATEN TARANMIŞ (Sadece Linkleri Kontrol Et)
        if url in visited_urls:
            print(f"⏩ [ATLANDI] İçerik zaten var: {url}")
            print(f"   🔍 İçindeki eksik linkler hızlıca taranıyor...")
            
            hizli_linkler = hizli_html_link_bul(url)
            yeni_bulunanlar = 0
            
            for link in hizli_linkler:
                if link not in visited_urls and link not in target_urls:
                    target_urls.append(link)
                    yeni_bulunanlar += 1
            
            if yeni_bulunanlar > 0:
                print(f"   🎯 [BAŞARI] {yeni_bulunanlar} YENİ LİNK kuyruğa eklendi!")
            continue

        # DURUM 2: YEPYENİ BİR SAYFA (Firecrawl ile Kazı)
        print(f"\n✨ [YENİ SAYFA BULUNDU] Firecrawl ile taranıyor: {url}")
        visited_urls.add(url) 

        try:
            scrape_result = firecrawl.scrape(url, formats=['markdown'])
            raw_content = safe_get(scrape_result, 'markdown', '')
            
            if not raw_content:
                print(f"   ❌ [BOŞ] Sayfadan metin alınamadı.")
                continue

            page_links = extract_links_from_content(raw_content, url)
            for new_link in page_links:
                if new_link not in visited_urls and new_link not in target_urls:
                    target_urls.append(new_link)

            final_content = advanced_clean_text(raw_content)
            
            is_vip_page = "/sayfa/" in url.lower() or "/detay/" in url.lower()
            min_length = 30 if is_vip_page else 200

            if len(final_content) < min_length:
                print(f"   🗑️ [ÇÖPE ATILDI] İçerik çok kısa.")
                continue
                
            if not should_keep_content(url, raw_content):
                print(f"   🗑️ [ÇÖPE ATILDI] Kalıcı (Evergreen) içerik kriterlerine uymuyor.")
                continue
            
            metadata = safe_get(scrape_result, 'metadata', {})
            title = safe_get(metadata, 'title', 'Başlıksız')
            
            if "404" in title or "Hata" in title or "sayfa bulunamadı" in final_content.lower():
                print(f"   🚫 [REDDEDİLDİ] Sayfa 404 Kırık Link hatası veriyor.")
                continue

            if is_architectural_plan(raw_content): 
                print(f"   📐 [ATLANDI] Mimari plan tespit edildi.")
                continue

            pdf_links = find_pdf_links_in_markdown(raw_content)
            for pdf in pdf_links: 
                if pdf not in visited_urls: bulunan_yeni_pdfler.add(pdf)

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
            yeni_kayit_sayisi += 1
            print(f"   💾 [KAYDEDİLDİ] İçerik hafızaya alındı. (Yeni Veri: {yeni_kayit_sayisi})")
            
            time.sleep(1)

        except Exception as e:
            error_msg = str(e).lower()
            if "429" in error_msg or "credit" in error_msg or "quota" in error_msg or "401" in error_msg:
                print("\n⛔ [KOTA DOLDU] Firecrawl kredisi bitti! Yeni PDF'lerin işlenmesine geçiliyor...")
                break 
            else:
                print(f"   ⚠️ [HATA] {e}")

    # =============================================================================
    # PDF İŞLEME AŞAMASI
    # =============================================================================
    if bulunan_yeni_pdfler:
        print("\n" + "-" * 50)
        print(f"🔍 {len(bulunan_yeni_pdfler)} YENİ PDF adayı işleniyor...")
        
        eski_yillar = [str(y) for y in range(2010, 2024)]
        guncel_yillar = ["2025", "2026"]

        for i, pdf_url in enumerate(bulunan_yeni_pdfler):
            visited_urls.add(pdf_url)
            
            is_manual = pdf_url in MANUEL_PDF_LISTESI
            if not is_manual and any(bad in pdf_url.lower() for bad in YASAKLI_KELIMELER): 
                continue

            if i > 0 and i % 2 == 0: time.sleep(5) 
            if "plan" in pdf_url.lower() or "kroki" in pdf_url.lower(): 
                print(f"   📐 [ATLANDI] Plan/Kroki PDF'i: {pdf_url}")
                continue 

            print(f"   📄 PDF İnceleniyor: {pdf_url}")
            # is_manual parametresi varsa utils'e gönder (önceki dosyadan taşındı)
            pdf_text = extract_text_from_pdf(pdf_url, is_manual=is_manual) if is_manual else extract_text_from_pdf(pdf_url)
            
            if pdf_text and len(pdf_text) > 50:
                pdf_text_upper = pdf_text.upper()
                keyword_found = "AKADEMİK TAKVİM" in pdf_text_upper or "AKADEMIK TAKVIM" in pdf_text_upper
                has_old_years = any(y in pdf_text for y in eski_yillar)
                has_new_years = any(y in pdf_text for y in guncel_yillar)

                if keyword_found:
                    if is_directive_or_regulation(pdf_text): pass 
                    elif has_old_years and not has_new_years:
                        print(f"   🚫 [ESKİ TAKVİM] Yılı geçmiş takvim atlandı.")
                        continue
                
                if keyword_found or "TABLO" in pdf_text_upper or "ÜCRET" in pdf_text_upper:
                    print("   ✨ AI ile karmaşık PDF içeriği düzenleniyor...")
                    pdf_text = clean_complex_content_with_llm(pdf_text, pdf_url)

                pdf_category = "Akademik Takvim" if is_manual else "Belge"
                tum_veriler.append({
                    "source": pdf_url,
                    "title": f"PDF Belgesi: {pdf_url.split('/')[-1]}",
                    "type": "pdf_document",
                    "category": pdf_category,
                    "content": pdf_text
                })
                yeni_kayit_sayisi += 1
                print(f"   💾 [KAYDEDİLDİ] PDF hafızaya alındı.")

    # =============================================================================
    # DOSYALARA YAZMA AŞAMASI VE SON TEMİZLİK (GÜRÜLTÜ/LİNK TEMİZLİĞİ)
    # =============================================================================
    print("\n" + "="*50)
    print("🧹 İçeriklerdeki gereksiz linkler ve gürültüler temizleniyor...")
    
    for item in tum_veriler:
        content = item.get("content", "")
        if content:
            # 1. URL'leri temizle (http/https ve www ile başlayanlar)
            content = re.sub(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', '', content)
            content = re.sub(r'www\.[a-zA-Z0-9-]+\.[a-zA-Z]{2,}', '', content)
            # 2. Fazladan boşlukları ve gürültüleri yok et
            content = re.sub(r'[-\s]{4,}', ' ', content)
            content = re.sub(r'\s+', ' ', content).strip()
            item["content"] = content

    print("💾 SONUÇLAR JSON DOSYALARINA YAZILIYOR...")
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(tum_veriler, f, ensure_ascii=False, indent=4)
    
    save_visited_urls(visited_urls, VISITED_URLS_FILE)
    
    web_page_count = sum(1 for item in tum_veriler if item.get("type") == "web_page")
    pdf_count = sum(1 for item in tum_veriler if item.get("type") == "pdf_document")
    
    print(f"\n🎉 İŞLEM TAMAMLANDI!")
    print(f"📊 Özet: Toplam {yeni_kayit_sayisi} yepyeni içerik bulundu ve eklendi.")
    print(f"📊 Veritabanındaki Toplam Web Sitesi: {web_page_count}")
    print(f"📊 Veritabanındaki Toplam PDF Sayısı: {pdf_count}")

if __name__ == "__main__":
    main()