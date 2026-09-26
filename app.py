from flask import Flask, render_template_string, request, redirect, url_for
import sqlite3
import re
import json
import requests
from datetime import datetime
from urllib.parse import quote

app = Flask(__name__)
DB_NAME = 'trendyol_takip_v10.db'

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
                sepet_sayisi INTEGER DEFAULT 0,
                favori_sayisi INTEGER DEFAULT 0,
                yorum_sayisi INTEGER DEFAULT 0,
                pazar_mesaji TEXT,
                son_guncelleme TEXT
            )
        ''')
        conn.commit()
        conn.close()
    except Exception as e:
        print("DB Hatası:", e)

init_db()

def fetch_trendyol_product_data(product_url):
    clean_url = product_url.split('?')[0] if '?' in product_url else product_url
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept-Language": "tr-TR,tr;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    }
    
    html_content = ""
    success = False
    error_msg = ""

    # 1. Adım: Doğrudan istek atmayı dene
    try:
        resp = requests.get(clean_url, headers=headers, timeout=10)
        if resp.status_code == 200 and "window.__PRODUCT_DETAIL_APP_INITIAL_STATE__" in resp.text:
            html_content = resp.text
            success = True
        else:
            error_msg = f"Doğrudan HTTP {resp.status_code}"
    except Exception as e:
        error_msg = str(e)

    # 2. Adım: Doğrudan 403 veya hata yerse, proxy köprüsü üzerinden geç (Render engelini aşmak için)
    if not success:
        try:
            proxy_api = f"https://api.allorigins.win/raw?url={quote(clean_url)}"
            resp = requests.get(proxy_api, timeout=15)
            if resp.status_code == 200 and "window.__PRODUCT_DETAIL_APP_INITIAL_STATE__" in resp.text:
                html_content = resp.text
                success = True
                error_msg = "Proxy ile Canlı Çekildi"
            else:
                error_msg = f"Proxy HTTP {resp.status_code}"
        except Exception as e:
            error_msg = f"Proxy Hatası: {e}"

    if success and html_content:
        match = re.search(r'window\.__PRODUCT_DETAIL_APP_INITIAL_STATE__\s*=\s*({.*?});', html_content, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(1))
                product = data.get('product', {})
                
                title = product.get('name', 'Trendyol Ürünü')
                price_info = product.get('price', {})
                price = price_info.get('sellingPrice', {}).get('value') or price_info.get('discountedPrice', {}).get('value') or 0.0
                
                rating_count = int(product.get('ratingCount', 0))
                favorite_count = int(product.get('favoriteCount', 0))
                
                return {
                    "success": True,
                    "title": title,
                    "price": float(price),
                    "ratingCount": rating_count,
                    "favoriteCount": favorite_count,
                    "msg": "Canlı Gerçek Veri Çekildi ✅"
                }
            except Exception as parse_err:
                return {"success": False, "error": f"JSON Parse: {parse_err}"}
                
        return {"success": False, "error": "JSON state bulunamadı"}
    
    return {"success": False, "error": error_msg}

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
        yorum_sayisi = u.get('yorum_sayisi') or 0
        
        toplam_satis = max(int(yorum_sayisi * 3.5), 15)
        toplam_ciro = toplam_satis * fiyat

        u['analiz'] = {
            "aylik_satis": toplam_satis,
            "aylik_ciro": toplam_ciro,
            "risk_skoru": 35 if yorum_sayisi > 100 else 60,
            "risk_etiketi": "Yüksek Talep / Fırsat" if yorum_sayisi > 100 else "Normal",
            "risk_renk": "#27ae60" if yorum_sayisi > 100 else "#f39c12",
            "trend": "🔥 Çok Satan" if yorum_sayisi > 100 else "🚀 Artışta",
            "trend_renk": "#27ae60"
        }
        urunler.append(u)
        
    conn.close()
    return render_template_string(HTML_TEMPLATE, urunler=urunler)

@app.route('/ekle', methods=['POST'])
def ekle():
    try:
        raw_url = request.form.get('url', '').strip()
        if raw_url:
            clean_url = raw_url.split('?')[0] if '?' in raw_url else raw_url
            res = fetch_trendyol_product_data(clean_url)
            
            if res["success"]:
                urun_adi = res["title"]
                fiyat = res["price"]
                yorum_sayisi = res["ratingCount"]
                favori_sayisi = res["favoriteCount"]
                pazar_mesaji = res["msg"]
            else:
                urun_adi = "Trendyol Ürünü (Hata)"
                fiyat = 0.0
                yorum_sayisi = 0
                favori_sayisi = 0
                pazar_mesaji = f"Hata: {res.get('error', 'Bilinmeyen')}"

            sepet_sayisi = max(int(favori_sayisi * 0.1), 5)
            toplam_satis = max(int(yorum_sayisi * 3.5), 10)
            toplam_ciro = toplam_satis * fiyat

            conn = get_db()
            cursor = conn.cursor()
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            cursor.execute('''
                INSERT INTO urunler (url, urun_adi, fiyat, toplam_satis, toplam_ciro, sepet_sayisi, favori_sayisi, yorum_sayisi, pazar_mesaji, son_guncelleme)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    urun_adi=excluded.urun_adi,
                    fiyat=excluded.fiyat,
                    toplam_satis=excluded.toplam_satis,
                    toplam_ciro=excluded.toplam_ciro,
                    sepet_sayisi=excluded.sepet_sayisi,
                    favori_sayisi=excluded.favori_sayisi,
                    yorum_sayisi=excluded.yorum_sayisi,
                    pazar_mesaji=excluded.pazar_mesaji,
                    son_guncelleme=excluded.son_guncelleme
            ''', (clean_url, urun_adi, fiyat, toplam_satis, toplam_ciro, sepet_sayisi, favori_sayisi, yorum_sayisi, pazar_mesaji, now))
            
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
    <title>Trendyol SaaS - Pazar Analiz Sistemi</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        body { background-color: #f4f6f9; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
        .navbar { background: linear-gradient(135deg, #f27a1a 0%, #e65c00 100%); }
        .card { border-radius: 12px; border: none; box-shadow: 0 4px 15px rgba(0,0,0,0.05); }
        .badge-risk { font-size: 0.75rem; padding: 4px 8px; border-radius: 20px; font-weight: 600; }
        .metric-title { font-size: 0.7rem; color: #7f8c8d; text-transform: uppercase; font-weight: bold; }
        .metric-value { font-size: 0.95rem; font-weight: bold; color: #2c3e50; }
    </style>
</head>
<body>
    <nav class="navbar navbar-dark mb-4">
        <div class="container">
            <span class="navbar-brand mb-0 h1"><i class="fa-solid fa-chart-line me-2"></i>Trendyol Akıllı Pazar Analiz Sistemi</span>
            <span class="text-white small fw-bold"><i class="fa-solid fa-shield-halved me-1"></i>Proxy Bypass Aktif</span>
        </div>
    </nav>
    <div class="container mb-5">
        <div class="card p-4 mb-4">
            <h5 class="card-title fw-bold text-secondary mb-3"><i class="fa-solid fa-link me-2"></i>Trendyol Ürün Linkini Yapıştır ve Otomatik Analiz Et</h5>
            <form action="/ekle" method="POST" class="row g-3">
                <div class="col-md-10">
                    <input type="url" name="url" class="form-control form-control-lg" placeholder="https://www.trendyol.com/..." required>
                </div>
                <div class="col-md-2 d-grid">
                    <button type="submit" class="btn btn-warning text-white fw-bold py-2" style="background-color: #f27a1a;"><i class="fa-solid fa-bolt me-1"></i> Analiz Et</button>
                </div>
            </form>
        </div>
        <h4 class="fw-bold mb-3 text-dark"><i class="fa-solid fa-boxes-stacked me-2"></i>Analiz Edilen Ürünler</h4>
        {% if urunler %}
            {% for u in urunler %}
            <div class="card p-3 mb-3">
                <div class="row align-items-center">
                    <div class="col-md-3">
                        <h6 class="fw-bold text-truncate mb-1" title="{{ u.urun_adi }}">{{ u.urun_adi }}</h6>
                        <a href="{{ u.url }}" target="_blank" class="text-decoration-none small text-muted"><i class="fa-solid fa-arrow-up-right-from-square me-1"></i>Trendyol'da Aç</a>
                        <div class="badge bg-light text-dark mt-2 border small" style="font-size: 0.7rem;">
                            <i class="fa-solid fa-check text-success me-1"></i> {{ u.pazar_mesaji }}
                        </div>
                    </div>
                    <div class="col-md-3 text-center border-start border-end">
                        <div class="row mb-1">
                            <div class="col-6">
                                <div class="metric-title">Birim Fiyat</div>
                                <div class="metric-value text-success">{{ "{:,.2f}".format(u.fiyat) }} TL</div>
                            </div>
                            <div class="col-6">
                                <div class="metric-title">Tahmini Satış</div>
                                <div class="metric-value text-warning">{{ u.toplam_satis }} adet</div>
                            </div>
                        </div>
                        <div class="row pt-1 border-top">
                            <div class="col-6">
                                <div class="metric-title">Sepetteki</div>
                                <div class="metric-value text-info">{{ u.sepet_sayisi }} kişi</div>
                            </div>
                            <div class="col-6">
                                <div class="metric-title">Yorum / Favori</div>
                                <div class="metric-value text-secondary">{{ u.yorum_sayisi }} / {{ u.favori_sayisi }}</div>
                            </div>
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
                                <span class="metric-title">Talep Trendi:</span>
                                <span class="fw-bold small" style="color: {{ u.analiz.trend_renk }};">{{ u.analiz.trend }}</span>
                            </div>
                            <div class="d-flex justify-content-between align-items-center">
                                <span class="metric-title">Toplam Ciro (Tahmin):</span>
                                <span class="fw-bold text-primary">{{ "{:,.2f}".format(u.toplam_ciro) }} TL</span>
                            </div>
                        </div>
                    </div>
                    <div class="col-md-2 text-end">
                        <a href="/sil/{{ u.id }}" class="btn btn-outline-danger btn-sm" onclick="return confirm('Silmek istiyor musun?')" title="Sil">
                            <i class="fa-solid fa-trash-can"></i> Sil
                        </a>
                    </div>
                </div>
            </div>
            {% endfor %}
        {% else %}
            <div class="alert alert-secondary text-center p-4">
                Henüz ürün eklenmedi. Trendyol linkini yapıştır, canlı verileri çekelim!
            </div>
        {% endif %}
    </div>
</body>
</html>
'''

if __name__ == '__main__':
    app.run(debug=True)
