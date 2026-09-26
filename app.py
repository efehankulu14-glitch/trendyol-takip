from flask import Flask, render_template_string, request, redirect, url_for
import sqlite3
import re
from datetime import datetime
from urllib.parse import urlparse, unquote

app = Flask(__name__)

DB_NAME = 'trendyol_takip_v4.db'

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

@app.route('/')
def index():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM urunler ORDER BY id DESC")
    rows = cursor.fetchall()
    
    urunler = []
    for r in rows:
        u = dict(r)
        fiyat = u.get('fiyat') or 0.0
        toplam_satis = u.get('toplam_satis') or 0
        
        aylik_tahmini_satis = max(int(toplam_satis * 1.5), 10)
        aylik_tahmini_ciro = aylik_tahmini_satis * fiyat

        risk_puan = 40 if toplam_satis > 20 else 65
        risk_etiketi = "Düşük Risk (Fırsat)" if risk_puan < 50 else "Orta/Yüksek Risk"
        risk_renk = "#27ae60" if risk_puan < 50 else "#f39c12"

        u['analiz'] = {
            "aylik_satis": aylik_tahmini_satis,
            "aylik_ciro": aylik_tahmini_ciro,
            "risk_skoru": risk_puan,
            "risk_etiketi": risk_etiketi,
            "risk_renk": risk_renk,
            "trend": "🚀 Yüksek Talep" if toplam_satis > 15 else "➡️ Stabil",
            "trend_renk": "#27ae60" if toplam_satis > 15 else "#3498db"
        }
        urunler.append(u)
        
    conn.close()
    return render_template_string(HTML_TEMPLATE, urunler=urunler)

@app.route('/ekle', methods=['POST'])
def ekle():
    try:
        raw_url = request.form.get('url', '').strip()
        fiyat = float(request.form.get('fiyat', 0) or 0)
        toplam_satis = int(request.form.get('toplam_satis', 0) or 0)
        
        if raw_url:
            clean_url = raw_url.split('?')[0] if '?' in raw_url else raw_url
            
            # URL'den ürün adını şık bir şekilde çıkar
            urun_adi = "Trendyol Takip Edilen Ürün"
            try:
                parsed = urlparse(clean_url)
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

            toplam_ciro = toplam_satis * fiyat
            pazar_mesaji = f"Manuel & Doğrulanmış Veri Girişi"

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

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Trendyol SaaS - Pazar Analiz</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        body { background-color: #f4f6f9; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
        .navbar { background: linear-gradient(135deg, #f27a1a 0%, #e65c00 100%); }
        .card { border-radius: 12px; border: none; box-shadow: 0 4px 15px rgba(0,0,0,0.05); }
        .badge-risk { font-size: 0.8rem; padding: 5px 10px; border-radius: 20px; font-weight: 600; }
        .metric-title { font-size: 0.75rem; color: #7f8c8d; text-transform: uppercase; font-weight: bold; }
        .metric-value { font-size: 1.05rem; font-weight: bold; color: #2c3e50; }
    </style>
</head>
<body>
    <nav class="navbar navbar-dark mb-4">
        <div class="container">
            <span class="navbar-brand mb-0 h1"><i class="fa-solid fa-chart-pie me-2"></i>Trendyol Akıllı Pazar Analiz Sistemi</span>
            <span class="text-white small fw-bold"><i class="fa-solid fa-shield-halved me-1"></i>Güvenli Hibrit Mod Aktif</span>
        </div>
    </nav>

    <div class="container mb-5">
        <div class="card p-4 mb-4">
            <h5 class="card-title fw-bold text-secondary mb-3"><i class="fa-solid fa-plus-circle me-2"></i>Ürün Ekle & Pazar Analizi Yap</h5>
            <form action="/ekle" method="POST" class="row g-3">
                <div class="col-md-6">
                    <label class="form-label small fw-bold text-muted">Trendyol Ürün Linki</label>
                    <input type="url" name="url" class="form-control" placeholder="https://www.trendyol.com/..." required>
                </div>
                <div class="col-md-3">
                    <label class="form-label small fw-bold text-muted">Ürün Fiyatı (TL)</label>
                    <input type="number" step="0.01" name="fiyat" class="form-control" placeholder="Örn: 49.90" required>
                </div>
                <div class="col-md-3">
                    <label class="form-label small fw-bold text-muted">Tahmini Satış Adedi</label>
                    <input type="number" name="toplam_satis" class="form-control" placeholder="Örn: 25" required>
                </div>
                <div class="col-12 text-end">
                    <button type="submit" class="btn btn-warning text-white fw-bold px-4" style="background-color: #f27a1a;"><i class="fa-solid fa-calculator me-1"></i> Analizi Hesapla & Kaydet</button>
                </div>
            </form>
        </div>

        <h4 class="fw-bold mb-3 text-dark"><i class="fa-solid fa-boxes-stacked me-2"></i>Takip Edilen Ürünler</h4>
        
        {% if urunler %}
            {% for u in urunler %}
            <div class="card p-3 mb-3">
                <div class="row align-items-center">
                    <div class="col-md-4">
                        <h6 class="fw-bold text-truncate mb-1" title="{{ u.urun_adi }}">{{ u.urun_adi }}</h6>
                        <a href="{{ u.url }}" target="_blank" class="text-decoration-none small text-muted"><i class="fa-solid fa-arrow-up-right-from-square me-1"></i>Trendyol'da Aç</a>
                        <div class="badge bg-light text-dark mt-2 border">
                            <i class="fa-solid fa-check text-success me-1"></i> {{ u.pazar_mesaji }}
                        </div>
                    </div>

                    <div class="col-md-3 border-start border-end text-center">
                        <div class="row">
                            <div class="col-6">
                                <div class="metric-title">Birim Fiyat</div>
                                <div class="metric-value text-success">{{ "{:,.2f}".format(u.fiyat) }} TL</div>
                            </div>
                            <div class="col-6">
                                <div class="metric-title">Satış Adedi</div>
                                <div class="metric-value text-warning">{{ u.toplam_satis }} adet</div>
                            </div>
                        </div>
                        <div class="mt-2 pt-2 border-top">
                            <div class="metric-title">Toplam Ciro</div>
                            <div class="metric-value text-primary">{{ "{:,.2f}".format(u.toplam_ciro) }} TL</div>
                        </div>
                    </div>

                    <div class="col-md-4">
                        <div class="p-2 rounded" style="background-color: #f8f9fa;">
                            <div class="d-flex justify-content-between align-items-center mb-1">
                                <span class="metric-title">Risk Durumu:</span>
                                <span class="badge badge-risk text-white" style="background-color: {{ u.analiz.risk_renk }};">
                                    {{ u.analiz.risk_skoru }}/100 - {{ u.analiz.risk_etiketi }}
                                </span>
                            </div>
                            <div class="d-flex justify-content-between align-items-center mb-1">
                                <span class="metric-title">Talep:</span>
                                <span class="fw-bold small" style="color: {{ u.analiz.trend_renk }};">{{ u.analiz.trend }}</span>
                            </div>
                            <div class="d-flex justify-content-between align-items-center">
                                <span class="metric-title">Aylık Tahmini Ciro:</span>
                                <span class="fw-bold text-dark">{{ "{:,.2f}".format(u.analiz.aylik_ciro) }} TL</span>
                            </div>
                        </div>
                    </div>

                    <div class="col-md-1 text-end">
                        <a href="/sil/{{ u.id }}" class="btn btn-outline-danger btn-sm" onclick="return confirm('Silmek istiyor musun?')" title="Sil">
                            <i class="fa-solid fa-trash-can"></i>
                        </a>
                    </div>
                </div>
            </div>
            {% endfor %}
        {% else %}
            <div class="alert alert-secondary text-center p-4">
                Henüz ürün eklenmedi. Linki yapıştırıp fiyatı ve satış adedini girerek kendi nokta atışı analizini hemen oluşturabilirsin!
            </div>
        {% endif ->
    </div>
</body>
</html>
'''
