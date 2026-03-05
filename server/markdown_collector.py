import json
import os
import time
import sys
import requests
import re
import hashlib
from urllib.parse import urljoin, urldefrag, unquote
from dotenv import load_dotenv
from firecrawl import Firecrawl

# utils.py modülündeki fonksiyonlar
from markdown_utils import (
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

OUTPUT_DIR = "markdown_data"       
VISITED_URLS_FILE = "visited_urls.json" 
TARGET_URL = 'https://www.btu.edu.tr/' 

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

def get_visited_urls():
    visited_urls = set()
    if os.path.exists(VISITED_URLS_FILE):
        with open(VISITED_URLS_FILE, 'r', encoding='utf-8') as f:
            try:
                urls = json.load(f)
                visited_urls = set(urls)
            except: pass
    return visited_urls

def generate_safe_filename(url, title, extension=".md"):
    safe_title = re.sub(r'[^\w\s-]', '', title).strip()
    safe_title = re.sub(r'[-\s]+', '_', safe_title)
    url_hash = hashlib.md5(url.encode('utf-8')).hexdigest()[:8]
    
    filename = f"{safe_title}_{url_hash}{extension}" if safe_title else f"doc_{url_hash}{extension}"
    
    if len(filename) > 200:
        filename = safe_title[:150] + "_" + url_hash + extension
        
    return filename

def write_markdown_file(url, title, category, content, type_str):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filename = generate_safe_filename(url, title)
    filepath = os.path.join(OUTPUT_DIR, filename)

    # İlgili regex düzeltmesi ile satır atlamaları korunuyor.
    if content:
        content = re.sub(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', '', content)
        content = re.sub(r'www\.[a-zA-Z0-9-]+\.[a-zA-Z]{2,}', '', content)
        content = re.sub(r'[-\s]{4,}', ' ', content)
    
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(f"---\n")
            f.write(f"title: {title}\n")
            f.write(f"source: {url}\n")
            f.write(f"type: {type_str}\n")
            f.write(f"category: {category}\n")
            f.write(f"---\n\n")
            f.write(f"# {title}\n\n")
            f.write(content)
        return filepath
    except Exception as e:
        print(f"⚠️ Dosya yazma hatası ({filepath}): {e}")
        fallback_filepath = os.path.join(OUTPUT_DIR, f"fallback_{hashlib.md5(url.encode('utf-8')).hexdigest()[:8]}.md")
        with open(fallback_filepath, 'w', encoding='utf-8') as f:
            f.write(f"---\n")
            f.write(f"title: {title}\n")
            f.write(f"source: {url}\n")
            f.write(f"---\n\n")
            f.write(content)
        return fallback_filepath

# =============================================================================
# ANA TARAMA DÖNGÜSÜ
# =============================================================================
def main():
    print("⚙️ Geçmiş Hafıza Yükleniyor...")
    visited_urls = get_visited_urls()
    
    print(f"🌐 Bilinen URL: {len(visited_urls)}")
    
    firecrawl = Firecrawl(api_key=FIRECRAWL_API_KEY)
    
    bulunan_yeni_pdfler = set()
    for m_pdf in MANUEL_PDF_LISTESI:
        if m_pdf not in visited_urls:
            bulunan_yeni_pdfler.add(m_pdf)
    
    target_urls = list(visited_urls)
    if TARGET_URL not in target_urls:
        target_urls.insert(0, TARGET_URL)
        
    kuyruk_index = 0
    yeni_kayit_sayisi = 0
    web_page_count = 0
    pdf_count = 0

    print("\n🚀 EKSİK TARAYICI BAŞLATILDI! Her adım markdown olarak kaydedilecek...\n" + "="*50)

    while kuyruk_index < len(target_urls):
        url = target_urls[kuyruk_index]
        kuyruk_index += 1

        if "/en/" in url or url.endswith("/en"): continue
        if any(bad in url.lower() for bad in YASAKLI_KELIMELER): continue

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

            pdf_links = find_pdf_links_in_markdown(raw_content)
            for pdf in pdf_links: 
                if pdf not in visited_urls: bulunan_yeni_pdfler.add(pdf)

            category = "Genel"
            url_lower = url.lower()
            if "duyuru" in url_lower or "haber" in url_lower: category = "Duyuru/Haber"
            elif "yonetmelik" in url_lower or "mevzuat" in url_lower: category = "Yönetmelik"
            elif "bolum" in url_lower or "fakulte" in url_lower: category = "Akademik Birim"
            elif ".pdf" in url_lower: category = "Belge"

            filepath = write_markdown_file(url, title, category, final_content, "web_page")
            
            yeni_kayit_sayisi += 1
            web_page_count += 1
            print(f"   💾 [KAYDEDİLDİ] İçerik markdown olarak alındı -> {filepath} (Yeni Veri: {yeni_kayit_sayisi})")
            
            save_visited_urls(visited_urls, VISITED_URLS_FILE)

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
                print(f"    [ATLANDI] Plan/Kroki PDF'i: {pdf_url}")
                continue 

            print(f"   📄 PDF İnceleniyor: {pdf_url}")
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
                title = f"PDF Belgesi: {pdf_url.split('/')[-1]}"
                
                filepath = write_markdown_file(pdf_url, title, pdf_category, pdf_text, "pdf_document")
                
                yeni_kayit_sayisi += 1
                pdf_count += 1
                print(f"   💾 [KAYDEDİLDİ] PDF markdown olarak alındı -> {filepath}")
            
            save_visited_urls(visited_urls, VISITED_URLS_FILE)

    # =============================================================================
    # SON KAYIT VE BİLGİLENDİRME
    # =============================================================================
    print("\n" + "="*50)
    print("💾 GEÇMİŞ GÜNCELLENİYOR...")
    
    save_visited_urls(visited_urls, VISITED_URLS_FILE)
    
    print(f"\n🎉 İŞLEM TAMAMLANDI!")
    print(f"📊 Özet: Toplam {yeni_kayit_sayisi} yepyeni içerik bulundu ve klasöre kaydedildi.")
    print(f"📊 Markdown Olarak Kaydedilen Web Sitesi: {web_page_count}")
    print(f"📊 Markdown Olarak Kaydedilen PDF Sayısı: {pdf_count}")
    print(f"📂 Çıktı Klasörü: {OUTPUT_DIR}/")

    # =============================================================================
    # JSON DERLEME VE İÇERİK (CONTENT) TEMİZLİĞİ
    # =============================================================================
    print("\n" + "="*50)
    print("🧹 JSON Dosyası Oluşturuluyor ve Content Temizliği Yapılıyor...")
    
    knowledge_base = []
    
    if os.path.exists(OUTPUT_DIR):
        for filename in os.listdir(OUTPUT_DIR):
            if filename.endswith(".md"):
                filepath = os.path.join(OUTPUT_DIR, filename)
                with open(filepath, 'r', encoding='utf-8') as f:
                    file_content = f.read()
                    
                # Metadata (Frontmatter) ile içeriği ayırma
                parts = file_content.split('---', 2)
                metadata = ""
                raw_text = file_content
                
                if len(parts) >= 3:
                    metadata = parts[1].strip()
                    raw_text = parts[2]
                    
                # Yalnızca "content" kısmındaki gereksiz linkleri ve gürültüleri kaldır
                clean_content = re.sub(r'http[s]?://\S+', '', raw_text) 
                clean_content = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', clean_content) 
                clean_content = re.sub(r'[<>]', '', clean_content) 
                clean_content = clean_content.strip()
                
                # Metadatayı objeye dönüştürme
                title, source, category, type_str = "Bilinmeyen Başlık", "Bilinmeyen Kaynak", "Genel", "Bilinmeyen Tip"
                
                for line in metadata.split('\n'):
                    if line.startswith('title:'): title = line.replace('title:', '').strip()
                    elif line.startswith('source:'): source = line.replace('source:', '').strip()
                    elif line.startswith('category:'): category = line.replace('category:', '').strip()
                    elif line.startswith('type:'): type_str = line.replace('type:', '').strip()

                knowledge_base.append({
                    "title": title,
                    "source": source,
                    "category": category,
                    "type": type_str,
                    "content": clean_content # Temizlenmiş ve gürültüden arındırılmış metin
                })
                
    with open("knowledge_base.json", "w", encoding="utf-8") as json_file:
        json.dump(knowledge_base, json_file, ensure_ascii=False, indent=4)
        
    print("✅ 'knowledge_base.json' başarıyla oluşturuldu!")

if __name__ == "__main__":
    main()