from flask import Flask, render_template_string, request, redirect, url_for
import sqlite3
import re
import json
import requests
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from urllib.parse import urlparse, unquote

app = Flask(__name__)

# --- E-POSTA AYARLARI ---
GONDEREN_EMAIL = "efehankulu14@gmail.com"
GMAIL_UYGULAMA_SIFRESI = "vqjlfxrlvhbfbspu"
ALICI_EMAIL = "efehankulu14@gmail.com"

def eposta_gonder(urun_adi, fiyat, stok, satis_adedi, ciro, url):
    konu = f"🚨 Trendyol Güncellemesi: {urun_adi[:25]}... - {fiyat} TL"
    icerik = f"""
    <html>
      <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <h2 style="color: #f27a1a; border-bottom: 2px solid #f27a1a; padding-bottom: 5px;">Trendyol Mağaza Takip Raporu</h2>
        <p><strong>Ürün Adı:</strong> {urun_adi}</p>
        <p><strong>Güncel Fiyat:</strong> <span style="font-size: 16px; color: #27ae60; font-weight: bold;">{fiyat} TL</span></p>
        <p><strong>Kalan Stok:</strong> {stok if stok is not None else 'Tespit Edilemedi'}</p>
        <hr style="border: 0; border-top: 1px solid #eee;">
        <p><strong>Tespit Edilen Satış:</strong> <span style="color: #d35400;">{satis_adedi} adet</span></p>
        <p><strong>Hesaplanan Ciro:</strong> <span style="font-size: 18px; color: #2980b9; font-weight: bold;">{ciro:,.2f} TL</span></p>
        <p><strong>Tarih:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        <br>
        <a href="{url}" style="background-color: #f27a1a; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px; font-weight: bold;">Ürünü İncele</a>
      </body>
    </html>
    """
    msg = MIMEMultipart("alternative")
    msg['Subject'] = konu
    msg['From'] = GONDEREN_EMAIL
    msg['To'] = ALICI_EMAIL
    msg.attach(MIMEText(icerik, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GONDEREN_EMAIL, GMAIL_UYGULAMA_SIFRESI)
            server.sendmail(GONDEREN_EMAIL, ALICI_EMAIL, msg.as_string())
        print(f"E-posta başarıyla gönderildi: {urun_adi[:20]}")
    except Exception as e:
        print(f"E-posta gönderme hatası: {e}")

# --- VERİTABANI OLUŞTURMA ---
def get_db():
    conn = sqlite3.connect('trendyol_takip.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
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

init_db()

# --- URL PARSER & GELİŞMİŞ SCRAPER ---
def url_den_isim_cikart(raw_url):
    try:
        parsed = urlparse(raw_url)
        path = parsed.path.strip('/')
        parts = path.split('/')
        if parts:
            slug = parts[-1] if '-p-' in parts[-1] else parts[0]
            if '-p-' in slug:
                slug = slug.split('-p-')[0]
            clean_name = unquote(slug).replace('-', ' ').title()
            if len(clean_name) > 3:
                return clean_name
    except Exception:
        pass
    return "Trendyol Takip Ürünü"

def trendyol_veri_cek(raw_url):
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Mobile/15E148 Safari/604.1",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "tr-TR,tr;q=0.9",
        "Referer": "https://www.google.com/"
    }

    clean_url = raw_url.split('?')[0] if '?' in raw_url else raw_url
    urun_adi = url_den_isim_cikart(clean_url)
    fiyat = 0.0
    stok = 0

    try:
        session = requests.Session()
        res = session.get(clean_url, headers=headers, timeout=10)
        
        if res.status_code == 200:
            html = res.text
            
            # 1. Yöntem: State JSON Parsing
            match = re.search(r'window\.__PRODUCT_DETAIL_APP_INITIAL_STATE__\s*=\s*({.*?});', html)
            if match:
                try:
                    data = json.loads(match.group(1))
                    product = data.get("product", {})
                    
                    if product.get("name"):
                        urun_adi = product.get("name")
                    
                    price_obj = product.get("price", {})
                    fiyat = price_obj.get("discountedPrice", {}).get("value") or \
                            price_obj.get("sellingPrice", {}).get("value") or \
                            price_obj.get("originalPrice", {}).get("value") or 0.0
                    
                    variants = product.get("variants", [])
                    if variants:
                        stok = sum([v.get("stock", 0) for v in variants if isinstance(v.get("stock"), (int, float))])
                except Exception as json_err:
                    print("JSON Parse Hatası:", json_err)

            # 2. Yöntem: Regex Fallback
            if fiyat == 0.0:
                price_match = re.search(r'"sellingPrice":\s*\{\s*"value":\s*([\d\.]+)', html) or re.search(r'"price":\s*([\d\.]+)', html)
                if price_match:
                    fiyat = float(price_match.group(1))

            # Title içinden başlık çekme
            if urun_adi == "Trendyol Takip Ürünü":
                title_match = re.search(r'<title>(.*?)</title>', html)
                if title_match:
                    extracted_title = title_match.group(1).split('|')[0].replace("- Trendyol", "").strip()
                    if extracted_title:
                        urun_adi = extracted_title

    except Exception as e:
        print(f"Scrape Hatası ({clean_url}): {e}")

    return {
        "urun_adi": str(urun_adi)[:80],
        "fiyat": float(fiyat) if fiyat else 0.0,
        "stok": int(stok) if stok else 0
    }

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
        
    if fiyat > 0 and fiyat < 100:
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

# --- HTML ŞABLONU ---
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
            <a href="/tarat" class="btn btn-light btn-sm fw-bold text-dark"><i class="fa-solid fa-arrows-rotate me-1"></i> Tümünü Taramayı Tetikle</a>
        </div>
    </nav>

    <div class="container mb-5">
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

        <h4 class="fw-bold mb-3 text-dark"><i class="fa-solid fa-chart-line me-2"></i>Takip Edilen Ürünler ve Pazar Analizi</h4>
        
        {% if urunler %}
            {% for u in urunler %}
            <div class="card p-3 mb-3">
                <div class="row align-items-center">
                    <div class="col-md-4">
                        <h6 class="fw-bold text-truncate mb-1" title="{{ u.urun_adi }}">{{ u.urun_adi }}</h6>
                        <a href="{{ u.url }}" target="_blank" class="text-decoration-none small text-muted"><i class="fa-solid fa-arrow-up-right-from-square me-1"></i>Trendyol'da İncele</a>
                        <div class="mt-2">
                            <span class="me-3"><strong>Fiyat:</strong> <span class="text-success fw-bold">{{ u.fiyat }} TL</span></span>
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
    try:
        url = request.form.get('url', '').strip()
        if url:
            veri = trendyol_veri_cek(url)
            conn = get_db()
            cursor = conn.cursor()
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            cursor.execute('''
                INSERT OR REPLACE INTO urunler (url, urun_adi, fiyat, son_stok, son_guncelleme)
                VALUES (?, ?, ?, ?, ?)
            ''', (url, veri['urun_adi'], veri['fiyat'], veri['stok'], now))
            conn.commit()
            conn.close()
    except Exception as e:
        print("Ekleme Hatası:", e)
    return redirect(url_for('index'))

@app.route('/tarat')
def tarat():
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM urunler")
        urunler = cursor.fetchall()

        for r in urunler:
            u = dict(r)
            yeni = trendyol_veri_cek(u.get('url', ''))
            
            if yeni:
                toplam_satis = u.get('toplam_satis') or 0
                toplam_ciro = u.get('toplam_ciro') or 0.0
                eski_stok = u.get('son_stok') or 0

                guncel_fiyat = yeni['fiyat'] if yeni['fiyat'] > 0 else (u.get('fiyat') or 0.0)
                guncel_stok = yeni['stok'] if yeni['stok'] > 0 else eski_stok

                if guncel_stok < eski_stok and eski_stok > 0:
                    satis_adedi = eski_stok - guncel_stok
                    ek_ciro = satis_adedi * guncel_fiyat
                    
                    yeni_toplam_satis = toplam_satis + satis_adedi
                    yeni_toplam_ciro = toplam_ciro + ek_ciro
                    
                    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    cursor.execute('''
                        UPDATE urunler 
                        SET urun_adi=?, fiyat=?, son_stok=?, toplam_satis=?, toplam_ciro=?, son_guncelleme=?
                        WHERE id=?
                    ''', (yeni['urun_adi'], guncel_fiyat, guncel_stok, yeni_toplam_satis, yeni_toplam_ciro, now, u['id']))
                    
                    conn.commit()
                    eposta_gonder(yeni['urun_adi'], guncel_fiyat, guncel_stok, satis_adedi, ek_ciro, u['url'])
                else:
                    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    cursor.execute("UPDATE urunler SET urun_adi=?, fiyat=?, son_stok=?, son_guncelleme=? WHERE id=?", 
                                   (yeni['urun_adi'], guncel_fiyat, guncel_stok, now, u['id']))
                    conn.commit()

        conn.close()
    except Exception as e:
        print("Taratma Hatası:", e)
        
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
