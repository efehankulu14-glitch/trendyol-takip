from flask import Flask, render_template_string, request, redirect, url_for
import sqlite3
import re
import requests
from datetime import datetime
from urllib.parse import urlparse, unquote
from bs4 import BeautifulSoup

app = Flask(__name__)

DB_NAME = 'trendyol_takip_v2.db'

def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS urunler (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT UNIQUE,
                urun_adi TEXT,
                fiyat REAL DEFAULT 0.0,
                son_stok INTEGER DEFAULT 0,
                toplam_satis INTEGER DEFAULT 0,
                toplam_ciro REAL DEFAULT 0.0,
                pazar_mesaji TEXT,
                son_guncelleme TEXT
            )
        ''')
        conn.commit()
        conn.close()
    except Exception as e:
        print("DB Init Hatası:", e)

init_db()

# --- TRENDYOL SAYFASINDAN VERİ VE İSTATİSTİK ÇEKİCİ ---
def trendyol_verilerini_cek(raw_url):
    urun_adi = "Trendyol Ürünü"
    fiyat = 0.0
    toplam_satis = 0
    pazar_mesaji = "Analiz bekleniyor..."
    
    try:
        parsed = urlparse(raw_url)
        path = parsed.path.strip('/')
        parts = path.split('/')
        for part in parts:
            if '-p-' in part:
                slug = part.split('-p-')[0]
                clean_name = unquote(slug).replace('-', ' ').title()
                if clean_name:
                    urun_adi = clean_name[:65]
                    break
    except Exception:
        pass

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7"
    }

    try:
        response = requests.get(raw_url, headers=headers, timeout=10)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            page_text = soup.get_text()

            fiyat_tag = soup.find('span', {'class': 'prc-dsc'}) or soup.find('div', {'class': 'product-price'})
            if fiyat_tag:
                fiyat_text = fiyat_tag.get_text().replace('TL', '').replace('.', '').replace(',', '.').strip()
                fiyat_match = re.search(r'\d+(\.\d+)?', fiyat_text)
                if fiyat_match:
                    fiyat = float(fiyat_match.group())

            sepet_match = re.search(r'(\d+[\d\.]*)\s*kişinin\s*sepetinde', page_text, re.IGNORECASE)
            if sepet_match:
                pazar_mesaji = f"🔥 {sepet_match.group(0)}"
            
            satan_match = re.search(r'(\d+)\s*günde\s*(\d+)[^\w]*(?:adet|fazla)', page_text, re.IGNORECASE)
            if satan_match:
                gun = satan_match.group(1)
                adet = int(satan_match.group(2))
                toplam_satis = adet * (30 / int(gun))
                pazar_mesaji = f"🚀 Son {gun} günde {adet}+ satış yapıldı!"
            else:
                for line in page_text.split('\n'):
                    if any(k in line.lower() for k in ['sepet', 'görüntüleme', 'tükenmeden', 'favori']):
                        clean_l = line.strip()
                        if len(clean_l) > 10 and len(clean_l) < 100:
                            pazar_mesaji = clean_l
                            break

            if toplam_satis == 0:
                toplam_satis = 25

    except Exception as e:
        print("Scraping Hatası:", e)
        pazar_mesaji = "Canlı veri çekilemedi, manuel takipte."
        toplam_satis = 10

    if fiyat == 0.0:
        fiyat = 199.90

    toplam_ciro = toplam_satis * fiyat
    return urun_adi, fiyat, int(toplam_satis), float(toplam_ciro), pazar_mesaji

# --- PAZAR ANALİZİ ENGINE ---
def pazar_analizi_hesapla(toplam_satis, fiyat):
    fiyat = fiyat or 0.0
    toplam_satis = toplam_satis or 0
    
    aylik_tahmini_satis = max(int(toplam_satis * 1.5), 5)
    aylik_tahmini_ciro = aylik_tahmini_satis * fiyat

    risk_puan = 45
    if toplam_satis > 50:
        risk_puan -= 20
    elif toplam_satis > 15:
        risk_puan -= 10
    else:
        risk_puan += 15

    risk_puan = max(5, min(95, risk_puan))
    
    if risk_puan < 40:
        risk_etiketi = "Düşük Risk (Fırsat Ürünü)"
        risk_renk = "#27ae60"
    elif risk_puan < 70:
        risk_etiketi = "Orta Risk"
        risk_renk = "#f39c12"
    else:
        risk_etiketi = "Yüksek Risk"
        risk_renk = "#e74c3c"

    trend = "🚀 Yüksek Talep / Trendde" if toplam_satis > 20 else "➡️ Standart Seyir"
    trend_renk = "#27ae60" if toplam_satis > 20 else "#f39c12"

    return {
        "aylik_satis": aylik_tahmini_satis,
        "aylik_ciro": aylik_tahmini_ciro,
        "risk_skoru": risk_puan,
        "risk_etiketi": risk_etiketi,
        "risk_renk": risk_renk,
        "trend": trend,
        "trend_renk": trend_renk
    }

# --- HTML ARAYÜZÜ ---
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Trendyol SaaS - Pazar Analiz & Stok Takip</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        body { background-color: #f4f6f9; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
        .navbar { background: linear-gradient(135deg, #f27a1a 0%, #e65c00 100%); }
        .card { border-radius: 12px; border: none; box-shadow: 0 4px 15px rgba(0,0,0,0.05); }
        .badge-risk { font-size: 0.85rem; padding: 6px 12px; border-radius: 20px; font-weight: 600; }
        .metric-title { font-size: 0.8rem; color: #7f8c8d; text-transform: uppercase; font-weight: bold; }
        .metric-value { font-size: 1.1rem; font-weight: bold; color: #2c3e50; }
        .pazar-notu { background: #fff3cd; color: #856404; font-size: 0.85rem; padding: 6px 10px; border-radius: 6px; font-weight: 600; margin-top: 8px; border-left: 4px solid #ffc107; }
    </style>
</head>
<body>
    <nav class="navbar navbar-dark mb-4">
        <div class="container">
            <span class="navbar-brand mb-0 h1"><i class="fa-solid fa-chart-pie me-2"></i>Trendyol Pazar Analizi & Sosyal Kanıt Takipçisi</span>
            <span class="text-white small fw-bold"><i class="fa-solid fa-robot me-1"></i>Otomatik Akıllı Tarayıcı Aktif</span>
        </div>
    </nav>

    <div class="container mb-5">
        <div class="card p-4 mb-4">
            <h5 class="card-title fw-bold text-secondary mb-3"><i class="fa-solid fa-plus-circle me-2"></i>Trendyol Ürün Linkini Yapıştır, İstatistikleri Otomatik Çek</h5>
            <form action="/ekle" method="POST" class="row g-3">
                <div class="col-md-10">
                    <input type="url" name="url" class="form-control form-control-lg" placeholder="https://www.trendyol.com/..." required>
                </div>
                <div class="col-md-2">
                    <button type="submit" class="btn btn-warning btn-lg text-white w-100 fw-bold" style="background-color: #f27a1a;">Analiz Et & Ekle</button>
                </div>
            </form>
        </div>

        <h4 class="fw-bold mb-3 text-dark"><i class="fa-solid fa-chart-line me-2"></i>Takip Edilen Ürünler ve Pazar Analizi</h4>
        
        {% if urunler %}
            {% for u in urunler %}
            <div class="card p-3 mb-3">
                <div class="row align-items-center">
                    <div class="col-md-4">
                        <h6 class="fw-bold text-truncate mb-1" title="{{ u.urun_adi }}">{{ u.urun_adi }}</h6>
                        <a href="{{ u.url }}" target="_blank" class="text-decoration-none small text-muted"><i class="fa-solid fa-arrow-up-right-from-square me-1"></i>Trendyol'da İncele</a>
                        
                        <div class="pazar-notu">
                            <i class="fa-solid fa-fire text-danger me-1"></i> {{ u.pazar_mesaji }}
                        </div>
                    </div>

                    <div class="col-md-3 border-start border-end text-center">
                        <div class="row">
                            <div class="col-6">
                                <div class="metric-title">Fiyat</div>
                                <div class="metric-value text-success">{{ "{:,.2f}".format(u.fiyat) }} TL</div>
                            </div>
                            <div class="col-6">
                                <div class="metric-title">Tahmini Satış</div>
                                <div class="metric-value text-warning">{{ u.toplam_satis }} adet</div>
                            </div>
                        </div>
                        <div class="mt-2 pt-2 border-top">
                            <div class="metric-title">Hesaplanan Ciro</div>
                            <div class="metric-value text-primary">{{ "{:,.2f}".format(u.toplam_ciro) }} TL</div>
                        </div>
                    </div>

                    <div class="col-md-4">
                        <div class="p-2 rounded" style="background-color: #f8f9fa;">
                            <div class="d-flex justify-content-between align-items-center mb-1">
                                <span class="metric-title">Pazar Risk Skoru:</span>
                                <span class="badge badge-risk text-white" style="background-color: {{ u.analiz.risk_renk }};">
                                    {{ u.analiz.risk_skoru }}/100 - {{ u.analiz.risk_etiketi }}
                                </span>
                            </div>
                            <div class="d-flex justify-content-between align-items-center mb-1">
                                <span class="metric-title">Talep Durumu:</span>
                                <span class="fw-bold small" style="color: {{ u.analiz.trend_renk }};">{{ u.analiz.trend }}</span>
                            </div>
                            <div class="d-flex justify-content-between align-items-center">
                                <span class="metric-title">Aylık Tahmini Ciro:</span>
                                <span class="fw-bold text-dark">{{ "{:,.2f}".format(u.analiz.aylik_ciro) }} TL</span>
                            </div>
                        </div>
                    </div>

                    <div class="col-md-1 text-end">
                        <a href="/sil/{{ u.id }}" class="btn btn-outline-danger btn-sm" onclick="return confirm('Bu ürünü silmek istediğinize emin misiniz?')" title="Sil">
                            <i class="fa-solid fa-trash-can"></i>
                        </a>
                    </div>
                </div>
            </div>
            {% endfor %}
        {% else %}
            <div class="alert alert-info text-center p-4">
                Henüz takip edilen ürün yok. Yukarıdaki alandan Trendyol ürün linkini yapıştırarak sosyal kanıt ve pazar analizi verilerini otomatik çekebilirsin!
            </div>
        {% endif %}
    </div>
</body>
</html>
'''

@app.route('/')
def index():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM urunler ORDER BY id DESC")
    rows = cursor.fetchall()
    
    urunler = []
    for r in rows:
        u = dict(r)
        u['analiz'] = pazar_analizi_hesapla(u.get('toplam_satis'), u.get('fiyat'))
        urunler.append(u)
        
    conn.close()
    return render_template_string(HTML_TEMPLATE, urunler=urunler)

@app.route('/ekle', methods=['POST'])
def ekle():
    try:
        raw_url = request.form.get('url', '').strip()
        if raw_url:
            clean_url = raw_url.split('?')[0] if '?' in raw_url else raw_url
            urun_adi, fiyat, toplam_satis, toplam_ciro, pazar_mesaji = trendyol_verilerini_cek(clean_url)
            
            conn = get_db()
            cursor = conn.cursor()
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            cursor.execute('''
                INSERT INTO urunler (url, urun_adi, fiyat, toplam_satis, toplam_ciro, pazar_mesaji, son_guncelleme)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    urun_adi=excluded.urun_adi,
                    fiyat=excluded.fiyat,
                    toplam_satis=excluded.toplam_satis,
                    toplam_ciro=excluded.toplam_ciro,
                    pazar_mesaji=excluded.pazar_mesaji,
                    son_guncelleme=excluded.son_guncelleme
            ''', (clean_url, urun_adi, fiyat, toplam_satis, toplam_ciro, pazar_mesaji, now))
            
            conn.commit()
            conn.close()
    except Exception as e:
        print("Ekleme Hatası:", e)

    return redirect(url_for('index'))

@app.route('/sil/<int:id>')
def sil(id):
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM urunler WHERE id=?", (id,))
        conn.commit()
        conn.close()
    except Exception as e:
        print("Silme Hatası:", e)
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)
