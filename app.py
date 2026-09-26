from flask import Flask, render_template_string, request, redirect, url_for
import sqlite3
import re
import json
import requests
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

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

# --- VERİTABANI OLUŞTURMA & OTOMATİK MİGRASYON ---
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
    
    # Eksik sütun kontrolü ve otomatik ekleme
    cursor.execute("PRAGMA table_info(urunler)")
    columns = [col[1] for col in cursor.fetchall()]
    
    if 'fiyat' not in columns:
        cursor.execute("ALTER TABLE urunler ADD COLUMN fiyat REAL DEFAULT 0.0")
    if 'son_stok' not in columns:
        cursor.execute("ALTER TABLE urunler ADD COLUMN son_stok INTEGER DEFAULT 0")
    if 'toplam_satis' not in columns:
        cursor.execute("ALTER TABLE urunler ADD COLUMN toplam_satis INTEGER DEFAULT 0")
    if 'toplam_ciro' not in columns:
        cursor.execute("ALTER TABLE urunler ADD COLUMN toplam_ciro REAL DEFAULT 0.0")

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS stok_gecmisi (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            urun_id INTEGER,
            tarih TEXT,
            fiyat REAL,
            stok INTEGER,
            FOREIGN KEY (urun_id) REFERENCES urunler (id)
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# --- VERİ ÇEKME FONKSİYONU ---
def trendyol_veri_cek(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code != 200:
            return None
        
        html = res.text
        match = re.search(r'window\.__PRODUCT_DETAIL_APP_INITIAL_STATE__\s*=\s*({.*?});', html)
        if not match:
            return None
        
        data = json.loads(match.group(1))
        product = data.get("product", {})
        
        urun_adi = product.get("name", "Bilinmeyen Ürün")
        fiyat = product.get("price", {}).get("sellingPrice", {}).get("value", 0.0)
        
        stok = None
        variants = product.get("variants", [])
        if variants:
            stok = sum([v.get("stock", 0) for v in variants])
        elif "stok" in product:
            stok = product.get("stok")

        return {
            "urun_adi": urun_adi,
            "fiyat": fiyat,
            "stok": stok
        }
    except Exception as e:
        print(f"Scrape Hatası ({url}): {e}")
        return None

# --- PAZAR ANALİZİ ENGINE ---
def pazar_analizi_hesapla(toplam_satis, fiyat, stok):
    fiyat = fiyat or 0.0
    toplam_satis = toplam_satis or 0
    
    # 1. Aylık Tahmini Satış & Ciro
    aylik_tahmini_satis = max(toplam_satis * 4, 0) if toplam_satis > 0 else 0
    aylik_tahmini_ciro = aylik_tahmini_satis * fiyat

    # 2. Pazara Giriş Risk Skoru (1 - 100 Arası)
    risk_puan = 50
    
    if toplam_satis > 15:
        risk_puan -= 20
    elif toplam_satis == 0:
        risk_puan += 15
        
    if fiyat < 100:
        risk_puan += 10
    elif fiyat > 500:
        risk_puan -= 10

    if stok is not None and stok == 0:
        risk_puan += 20

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

    # 3. Trend Yönü
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
        <!-- ÜRÜN EKLEME KART -->
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

        <!-- ÜRÜN LİSTESİ VE PAZAR ANALİZLERİ -->
        <h4 class="fw-bold mb-3 text-dark"><i class="fa-solid fa-chart-line me-2"></i>Takip Edilen Ürünler ve Pazar Analizi</h4>
        
        {% if urunler %}
            {% for u in urunler %}
            <div class="card p-3 mb-3">
                <div class="row align-items-center">
                    <!-- ÜRÜN TEMEL BİLGİSİ -->
                    <div class="col-md-4">
                        <h6 class="fw-bold text-truncate mb-1" title="{{ u.urun_adi }}">{{ u.urun_adi }}</h6>
                        <a href="{{ u.url }}" target="_blank" class="text-decoration-none small text-muted"><i class="fa-solid fa-arrow-up-right-from-square me-1"></i>Trendyol'da İncele</a>
                        <div class="mt-2">
                            <span class="me-3"><strong>Fiyat:</strong> <span class="text-success fw-bold">{{ u.fiyat }} TL</span></span>
                            <span><strong>Kalan Stok:</strong> {{ u.son_stok if u.son_stok is not none else 'Bilinmiyor' }}</span>
                        </div>
                    </div>

                    <!-- REEL GERÇEKLEŞEN TAKİP -->
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

                    <!-- PAZAR ANALİZİ VE PROJEKSİYON -->
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

                    <!-- İŞLEM -->
                    <div class="col-md-1 text-end">
                        <a href="/sil/{{ u.id }}" class="btn btn-outline-danger btn-sm" onclick="return confirm('Bu ürünü takipten çıkarmak istediğinize emin misiniz?')" title="Sil">
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
        
        # GÜVENLİ VERİ ÇEKME (.get kullanımı)
        satis = u.get('toplam_satis', 0) or 0
        ciro = u.get('toplam_ciro', 0.0) or 0.0
        fiyat = u.get('fiyat', 0.0) or 0.0
        stok = u.get('son_stok', 0)
        
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
    url = request.form.get('url', '').strip()
    if url:
        veri = trendyol_veri_cek(url)
        if veri:
            conn = get_db()
            cursor = conn.cursor()
            try:
                now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                cursor.execute('''
                    INSERT INTO urunler (url, urun_adi, fiyat, son_stok, son_guncelleme)
                    VALUES (?, ?, ?, ?, ?)
                ''', (url, veri['urun_adi'], veri['fiyat'], veri['stok'], now))
                conn.commit()
            except sqlite3.IntegrityError:
                pass
            conn.close()
    return redirect(url_for('index'))

@app.route('/tarat')
def tarat():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM urunler")
    urunler = cursor.fetchall()

    for r in urunler:
        u = dict(r)
        yeni = trendyol_veri_cek(u.get('url', ''))
        
        toplam_satis = u.get('toplam_satis', 0) or 0
        toplam_ciro = u.get('toplam_ciro', 0.0) or 0.0

        if yeni and yeni['stok'] is not None and u.get('son_stok') is not None:
            if yeni['stok'] < u['son_stok']:
                satis_adedi = u['son_stok'] - yeni['stok']
                ek_ciro = satis_adedi * yeni['fiyat']
                
                yeni_toplam_satis = toplam_satis + satis_adedi
                yeni_toplam_ciro = toplam_ciro + ek_ciro
                
                now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                cursor.execute('''
                    UPDATE urunler 
                    SET fiyat=?, son_stok=?, toplam_satis=?, toplam_ciro=?, son_guncelleme=?
                    WHERE id=?
                ''', (yeni['fiyat'], yeni['stok'], yeni_toplam_satis, yeni_toplam_ciro, now, u['id']))
                
                conn.commit()
                eposta_gonder(yeni['urun_adi'], yeni['fiyat'], yeni['stok'], satis_adedi, ek_ciro, u['url'])
            else:
                now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                cursor.execute("UPDATE urunler SET fiyat=?, son_stok=?, son_guncelleme=? WHERE id=?", 
                               (yeni['fiyat'], yeni['stok'], now, u['id']))
                conn.commit()

    conn.close()
    return redirect(url_for('index'))

@app.route('/sil/<int:id>')
def sil(id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM urunler WHERE id=?", (id,))
    conn.commit()
    conn.close()
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)
