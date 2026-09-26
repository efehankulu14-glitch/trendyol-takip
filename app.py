from flask import Flask, render_template_string, request, redirect, url_for
import sqlite3
import re
import json
import requests
from datetime import datetime
from urllib.parse import urlparse, unquote

app = Flask(__name__)

# --- VERİTABANI BAĞLANTISI ---
def get_db():
    conn = sqlite3.connect('trendyol_takip.db')
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
                son_guncelleme TEXT
            )
        ''')
        conn.commit()
        conn.close()
    except Exception as e:
        print("DB Init Hatası:", e)

init_db()

# --- URL'DEN HIZLI İSİM / ID ÇIKARICI ---
def url_den_isim_cikart(raw_url):
    try:
        parsed = urlparse(raw_url)
        path = parsed.path.strip('/')
        parts = path.split('/')
        for part in parts:
            if '-p-' in part:
                slug = part.split('-p-')[0]
                clean_name = unquote(slug).replace('-', ' ').title()
                if clean_name:
                    return clean_name[:60]
            elif part:
                clean_name = unquote(part).replace('-', ' ').title()
                if len(clean_name) > 3:
                    return clean_name[:60]
    except Exception:
        pass
    return "Trendyol Ürünü"

# --- PAZAR ANALİZİ ENGINE ---
def pazar_analizi_hesapla(toplam_satis, fiyat, stok):
    fiyat = fiyat or 0.0
    toplam_satis = toplam_satis or 0
    
    aylik_tahmini_satis = max(toplam_satis * 4, 0) if toplam_satis > 0 else 0
    aylik_tahmini_ciro = aylik_tahmini_satis * fiyat

    risk_puan = 50
    if toplam_satis > 15:
        risk_puan -= 20
    elif toplam_satis == 0:
        risk_puan += 15
        
    if 0 < fiyat < 100:
        risk_puan += 10
    elif fiyat > 500:
        risk_puan -= 10

    risk_puan = max(1, min(99, risk_puan))
    
    if risk_puan < 40:
        risk_etiketi = "Düşük Risk (Fırsat)"
        risk_renk = "#27ae60"
    elif risk_puan < 70:
        risk_etiketi = "Orta Risk"
        risk_renk = "#f39c12"
    else:
        risk_etiketi = "Yüksek Risk"
        risk_renk = "#e74c3c"

    if toplam_satis > 5:
        trend = "🚀 Yükselişte (Yüksek Talep)"
        trend_renk = "#27ae60"
    elif toplam_satis > 0:
        trend = "➡️ Durağan (Normal Seyir)"
        trend_renk = "#f39c12"
    else:
        trend = "📉 Düşüşte / Hareketsiz"
        trend_renk = "#95a5a6"

    return {
        "aylik_satis": aylik_tahmini_satis,
        "aylik_ciro": aylik_tahmini_ciro,
        "risk_skoru": risk_puan,
        "risk_etiketi": risk_etiketi,
        "risk_renk": risk_renk,
        "trend": trend,
        "trend_renk": trend_renk
    }

# --- ARAYÜZ (HTML) ---
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
    </style>
</head>
<body>
    <nav class="navbar navbar-dark mb-4">
        <div class="container">
            <span class="navbar-brand mb-0 h1"><i class="fa-solid fa-chart-pie me-2"></i>Trendyol Pazar Analizi & Stok Takip SaaS</span>
            <a href="/tarat" class="btn btn-light btn-sm fw-bold text-dark"><i class="fa-solid fa-arrows-rotate me-1"></i> Taramayı Tetikle</a>
        </div>
    </nav>

    <div class="container mb-5">
        <!-- HIZLI EKLEME FORMU -->
        <div class="card p-4 mb-4">
            <h5 class="card-title fw-bold text-secondary mb-3"><i class="fa-solid fa-plus-circle me-2"></i>Takibe & Analize Yeni Ürün Ekle</h5>
            <form action="/ekle" method="POST" class="row g-3">
                <div class="col-md-10">
                    <input type="url" name="url" class="form-control form-control-lg" placeholder="https://www.trendyol.com/..." required>
                </div>
                <div class="col-md-2">
                    <button type="submit" class="btn btn-warning btn-lg text-white w-100 fw-bold" style="background-color: #f27a1a;">Takibe Al</button>
                </div>
            </form>
        </div>

        <!-- ÜRÜN LİSTESİ -->
        <h4 class="fw-bold mb-3 text-dark"><i class="fa-solid fa-chart-line me-2"></i>Takip Edilen Ürünler ve Pazar Analizi</h4>
        
        {% if urunler %}
            {% for u in urunler %}
            <div class="card p-3 mb-3">
                <div class="row align-items-center">
                    <div class="col-md-4">
                        <h6 class="fw-bold text-truncate mb-1" title="{{ u.urun_adi }}">{{ u.urun_adi }}</h6>
                        <a href="{{ u.url }}" target="_blank" class="text-decoration-none small text-muted"><i class="fa-solid fa-arrow-up-right-from-square me-1"></i>Trendyol'da İncele</a>
                        <div class="mt-2">
                            <span class="me-3"><strong>Fiyat:</strong> <span class="text-success fw-bold">{{ "{:,.2f}".format(u.fiyat) }} TL</span></span>
                            <span><strong>Kalan Stok:</strong> {{ u.son_stok }}</span>
                        </div>
                    </div>

                    <div class="col-md-3 border-start border-end">
                        <div class="row text-center">
                            <div class="col-6">
                                <div class="metric-title">Tespit Satış</div>
                                <div class="metric-value text-warning">{{ u.satis }} adet</div>
                            </div>
                            <div class="col-6">
                                <div class="metric-title">Gerçek Ciro</div>
                                <div class="metric-value text-primary">{{ "{:,.2f}".format(u.ciro) }} TL</div>
                            </div>
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
                                <span class="metric-title">Trend Yönü:</span>
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
                Henüz takip edilen ürün yok. Yukarıdaki alandan ilk Trendyol ürün linkini ekleyebilirsiniz!
            </div>
        {% endif %}
    </div>
</body>
</html>
'''

# --- ROUTE'LAR ---
@app.route('/')
def index():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM urunler ORDER BY id DESC")
    rows = cursor.fetchall()
    
    urunler = []
    for r in rows:
        u = dict(r)
        satis = u.get('toplam_satis') or 0
        ciro = u.get('toplam_ciro') or 0.0
        fiyat = u.get('fiyat') or 0.0
        stok = u.get('son_stok') or 0
        
        u['satis'] = satis
        u['ciro'] = ciro
        u['fiyat'] = fiyat
        u['son_stok'] = stok
        u['analiz'] = pazar_analizi_hesapla(satis, fiyat, stok)
        urunler.append(u)
        
    conn.close()
    return render_template_string(HTML_TEMPLATE, urunler=urunler)

@app.route('/ekle', methods=['POST'])
def ekle():
    raw_url = request.form.get('url', '').strip()
    if raw_url:
        clean_url = raw_url.split('?')[0] if '?' in raw_url else raw_url
        urun_adi = url_den_isim_cikart(clean_url)
        
        conn = get_db()
        cursor = conn.cursor()
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # ANINDA KAYIT (HİÇBİR İSTEK BEKLEMEDEN)
        try:
            cursor.execute('''
                INSERT INTO urunler (url, urun_adi, fiyat, son_stok, son_guncelleme)
                VALUES (?, ?, 0.0, 0, ?)
            ''', (clean_url, urun_adi, now))
            conn.commit()
        except sqlite3.IntegrityError:
            pass
        
        conn.close()

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
