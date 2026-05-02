import requests
import time
import json
import os

# --- AYARLAR ---
API_URL = "http://127.0.0.1:5000/chat"
RAPOR_DOSYASI = "test_raporu.txt"
TEST_DOSYASI = "./test/test_data_all.json"

# --- TEST VERİSETİ (Sorular ve Doğrulama Kelimeleri) ---
TEST_DATA_PATH = os.path.join(os.path.dirname(__file__), TEST_DOSYASI)

with open(TEST_DATA_PATH, "r", encoding="utf-8") as f:
    TEST_DATA = json.load(f)

def metin_normalize_et(metin):
    """
    Hem aranan kelimeleri hem de cevabı normalize eder.
    Turkish character support (İ/I handling) and punctuation cleaning.
    """
    if not isinstance(metin, str):
        return ""
        
    # Turkish character handling for lowercase conversion
    # Python's .lower() can be problematic with 'İ' on some platforms/versions
    metin = metin.replace('İ', 'i').replace('I', 'ı')
    metin = metin.lower()
    
    # Eşleşmeyi bozan tüm noktalama işaretlerini siliyoruz
    noktalama = ".,:;!?\"'()[]{}/*-+"
    for char in noktalama:
        metin = metin.replace(char, ' ')
        
    # Çoklu boşlukları temizle ve kırp
    while "  " in metin:
        metin = metin.replace("  ", " ")
        
    return metin.strip()

def run_performance_test():
    print(f"🚀 Gelişmiş Performans ve Metrik Testi Başlıyor... ({len(TEST_DATA)} Soru)")
    print("Lütfen arka planda 'btu_assistant_gemma3.py' dosyasının çalıştığından emin olun.\n")
    print("-" * 60)

    toplam_sure = 0
    basarili_cevap_sayisi = 0
    kaynak_gosterme_sayisi = 0
    dogru_bilgi_sayisi = 0
    halusinasyon_sayisi = 0
    
    rapor_metni = "=================================================\n"
    rapor_metni += " BTÜ ON-PREMISE RAG ASİSTANI - GÜNCEL PERFORMANS RAPORU \n"
    rapor_metni += "=================================================\n\n"

    for i, data in enumerate(TEST_DATA, 1):
        soru = data["soru"]
        beklenen_kelimeler = data["beklenen_kelimeler"]
        
        print(f"[{i}/{len(TEST_DATA)}] Soru: {soru}")
        
        baslangic_zamani = time.time()
        
        try:
            response = requests.post(API_URL, json={"message": soru}, timeout=300)
            gecen_sure = time.time() - baslangic_zamani
            toplam_sure += gecen_sure
            
            if response.status_code == 200:
                resp_json = response.json()
                if resp_json.get("status") == "success":
                    cevap = resp_json.get("reply", "")
                    basarili_cevap_sayisi += 1
                    
                    # 1. Kaynak Gösterme Testi (Cevapta kaynak linki/belirtisi var mı?)
                    kaynak_var_mi = "kaynak :" in cevap.lower() or "http" in cevap.lower() or "kaynak:" in cevap.lower()
                    if kaynak_var_mi:
                        kaynak_gosterme_sayisi += 1
                        
                    # 2. Doğruluk / Halüsinasyon Testi (Gelişmiş Eşleştirme)
                    cevap_temiz = metin_normalize_et(cevap)
                    
                    dogru_mu = True
                    for kelime in beklenen_kelimeler:
                        # "kelime1|kelime2" gibi varyasyonları destekle (OR mantığı)
                        if "|" in kelime:
                            varyasyonlar = kelime.split("|")
                            herhangi_biri_var_mi = False
                            for v in varyasyonlar:
                                v_temiz = metin_normalize_et(v)
                                if v_temiz in cevap_temiz:
                                    herhangi_biri_var_mi = True
                                    break
                            if not herhangi_biri_var_mi:
                                dogru_mu = False
                                break
                        else:
                            kelime_temiz = metin_normalize_et(kelime)
                            # Eğer beklenen kelime temizlenmiş cevap içinde yoksa testi başarısız say
                            if kelime_temiz not in cevap_temiz:
                                dogru_mu = False
                                break
                    
                    if dogru_mu:
                        dogru_bilgi_sayisi += 1
                    else:
                        halusinasyon_sayisi += 1
                        
                    durum_ikonu = "✅" if dogru_mu else "❌"
                    kaynak_ikonu = "📄" if kaynak_var_mi else "⚠️"
                    
                    print(f"  {durum_ikonu} Süre: {gecen_sure:.2f} sn | Kaynak: {kaynak_ikonu} | Doğruluk: {durum_ikonu}")
                    
                    # Rapora detay ekle
                    rapor_metni += f"Soru {i}: {soru}\n"
                    rapor_metni += f"Yanıt Süresi: {gecen_sure:.2f} saniye\n"
                    rapor_metni += f"Cevap: {cevap}\n"
                    rapor_metni += f"Durum: {'BAŞARILI' if dogru_mu else 'OLASI HALÜSİNASYON / EKSİK BİLGİ'}\n"
                    rapor_metni += "-" * 50 + "\n"
                    
                else:
                    print(f"  ❌ API Hatası: {resp_json.get('message')}")
            else:
                print(f"  ❌ Sunucu Hatası: {response.status_code}")
                
        except Exception as e:
            print(f"  ❌ Bağlantı Hatası: {e}")

    # --- METRİK HESAPLAMALARI ---
    ortalama_sure = toplam_sure / basarili_cevap_sayisi if basarili_cevap_sayisi > 0 else 0
    kaynak_orani = (kaynak_gosterme_sayisi / basarili_cevap_sayisi) * 100 if basarili_cevap_sayisi > 0 else 0
    dogruluk_orani = (dogru_bilgi_sayisi / basarili_cevap_sayisi) * 100 if basarili_cevap_sayisi > 0 else 0
    halusinasyon_orani = (halusinasyon_sayisi / basarili_cevap_sayisi) * 100 if basarili_cevap_sayisi > 0 else 0

    # --- RAPOR ÖZETİ ---
    ozet = "\n" + "="*50 + "\n"
    ozet += " 📊 GENEL PERFORMANS METRİKLERİ (GÜNCELLENMİŞ)\n"
    ozet += "="*50 + "\n"
    ozet += f"Toplam Test Edilen Soru : {len(TEST_DATA)}\n"
    ozet += f"Başarılı API Yanıtı     : {basarili_cevap_sayisi}\n"
    ozet += f"Ortalama Yanıt Süresi   : {ortalama_sure:.2f} saniye\n"
    ozet += f"Kaynak Gösterme Oranı   : %{kaynak_orani:.1f} (Hedef: > %90)\n"
    ozet += f"Doğruluk Oranı          : %{dogruluk_orani:.1f} (Hedef: > %85)\n"
    ozet += f"Olası Halüsinasyon Oranı: %{halusinasyon_orani:.1f} (Hedef: < %15)\n"
    ozet += "="*50 + "\n"

    print(ozet)
    rapor_metni += ozet

    # Raporu dosyaya kaydet
    with open(RAPOR_DOSYASI, "w", encoding="utf-8") as f:
        f.write(rapor_metni)
    
    print(f"💾 Detaylı analiz raporu '{RAPOR_DOSYASI}' dosyasına kaydedildi.")

if __name__ == "__main__":
    run_performance_test()