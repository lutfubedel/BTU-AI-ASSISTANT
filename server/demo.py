from playwright.sync_api import sync_playwright

def run():
    # Playwright'ı başlat
    with sync_playwright() as p:
        # Chromium tarayıcısını başlat (headless=False yaparsan tarayıcının açıldığını gözünle görürsün)
        browser = p.chromium.launch(headless=True)
        
        # Yeni bir sekme aç
        page = browser.new_page()
        
        # Hedef web sitesine git
        print("🌐 Siteye gidiliyor...")
        page.goto("https://btu.edu.tr/tr")
        
        # Sayfa başlığını çek
        title = page.title()
        print(f"📌 Sayfa Başlığı: {title}")
        
        # Sayfanın ekran görüntüsünü al
        page.screenshot(path="ekran_goruntusu.png")
        print("📸 Ekran görüntüsü kaydedildi!")
        
        # Tarayıcıyı kapat
        browser.close()

if __name__ == "__main__":
    run()