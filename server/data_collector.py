import json
import os
import time
import random
from dotenv import load_dotenv
from firecrawl import Firecrawl

# Yardımcı fonksiyonları ve sabitleri utils modülünden içe aktarıyoruz
from utils import (
    YASAKLI_KELIMELER, 
    safe_get, 
    extract_links_from_content, 
    advanced_clean_text, 
    should_keep_content, 
    find_pdf_links_in_markdown, 
    is_architectural_plan, 
    discover_subdomains, 
    extract_text_from_pdf, 
    clean_complex_content_with_llm, 
    is_directive_or_regulation, 
    save_visited_urls
)

# .env dosyasındaki API anahtarlarını yükle
load_dotenv()

# =============================================================================
# AYARLAR VE SABİTLER
# =============================================================================
FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_KEY")
TARGET_URL = 'https://www.btu.edu.tr/' # Başlangıç noktası
OUTPUT_FILE = "okul_verisi.json"       # Sonuçların kaydedileceği dosya
VISITED_URLS_FILE = "visited_urls.json" # Tekrar taramayı önlemek için log dosyası

HEDEF_YIL = 2026
LIMIT = 900           # Toplam çekilecek maksimum içerik sayısı
MAX_HABER_SAYISI = 10  # (Opsiyonel kullanım için tanımlanmış limit)

# Otomatik taramada bulunamasa bile mutlaka işlenmesi istenen önemli PDF'ler
MANUEL_PDF_LISTESI = [
    "https://depo.btu.edu.tr/img/sayfa//1750918936_f917045e0381e65ac166.pdf",
    "https://depo.btu.edu.tr/img/sayfa//1750919090_9271f0af171b8349ee8c.pdf",
    "https://depo.btu.edu.tr/img/sayfa//1750935863_96a88481aec053f922dd.pdf"
]

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
            
            # Eğer başlıkta veya içeriğin kendisinde hata mesajı varsa bu sayfayı çöpe at!
            if "404" in title or "Hata" in title or "sayfa bulunamadı" in final_content.lower():
                print(f"   🗑️ 404 KIRI/HATALI SAYFA ATLANDI: {url}")
                continue # Listeye eklemeden bir sonraki linke geç

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
                pdf_text = extract_text_from_pdf(pdf_url, is_manual=True)
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