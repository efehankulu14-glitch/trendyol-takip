from flask import Flask, render_template, request, redirect, url_for
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
GMAIL_UYGULAMA_SIFRESI = "vqjlfxrlvhbfbqpu"
ALICI_EMAIL = "efehankulu14@gmail.com"

def eposta_gonder(urun_adi, fiyat, stok, satis_adedi, ciro, url):
    konu = f"📊 Trendyol Güncellemesi: {urun_adi[:25]}... - {fiyat}"
    icerik = f"""
    <html>
      <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <h2 style="color: #f27a1a; border-bottom: 2px solid #f27a1a; padding-bottom: 5px;">Trendyol Mağaza Takip Raporu</h2>
        <p><strong>Ürün Adı:</strong> {urun_adi}</p>
        <p><strong>Güncel Fiyat:</strong> <span style="font-size: 16px; color: #27ae60; font-weight: bold;">{fiyat}</span></p>
        <p><strong>Kalan Stok:</strong> {stok if stok is not None else 'Tespit Edilemedi'}</p>
        <hr style="border: 0; border-top: 1px solid #eee;">
        <p><strong>Tespit Edilen Satış:</strong> <span style="color: #d35400; font-weight: bold;">{satis_adedi} adet</span></p>
        <p><strong>Hesaplanan Ciro:</strong> <span style="font-size: 18px; color: #2980b9; font-weight: bold;">{ciro:,.2f} TL</span></p>
        <p><strong>Tarih:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        <br>
        <a href="{url}" style="background-color: #f27a1a; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px; font-weight: bold;">Ürünü İncele</a>
      </body>
    </html>
    """
    msg = MIMEMultipart()
    msg['From'] = GONDEREN_EMAIL
    msg['To'] = ALICI_EMAIL
    msg['Subject'] = konu
    msg.attach(MIMEText(icerik, 'html'))

    try:
        server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
        server.login(GONDEREN_EMAIL, GMAIL_UYGULAMA_SIFRESI)
        server.sendmail(GONDEREN_EMAIL, ALICI_EMAIL, msg.as_string())
        server.quit()
        print(f"📧 E-posta gönderildi: {urun_adi[:30]}...")
    except Exception as e:
        print(f"E-posta hatası: {e}")

def veritabani_kur():
    conn = sqlite3.connect("trendyol_takip.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS urunler (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT UNIQUE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS detayli_takip (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT,
            urun_adi TEXT,
            fiyat TEXT,
            stok INTEGER,
            satis_adedi INTEGER,
            ciro REAL,
            tarih TEXT
        )
    """)
    conn.commit()
    conn.close()

def fiyati_sayiya_cevir(fiyat_str):
    try:
        temiz = re.sub(r'[^\d,]', '', str(fiyat_str)).replace(',', '.')
        return float(temiz)
    except:
        return 0.0

def trendyol_api_tarama(url):
    urun_adi = "Başlık Bulunamadı"
    fiyat = "Fiyat Bulunamadı"
    stok = None

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "tr-TR,tr;q=0.9",
    }

    try:
        session = requests.Session()
        res = session.get(url, headers=headers, timeout=15)
        html_content = res.text

        # 1. Başlık Yakalama
        title_match = re.search(r'<title>(.*?)</title>', html_content)
        if title_match:
            raw_title = title_match.group(1)
            urun_adi = raw_title.split('Fiyatı')[0].split('|')[0].strip()

        # 2. Fiyat Yakalama
        price_match = re.search(r'"discountedPrice":\s*{\s*"value":\s*([\d\.]+)', html_content)
        if price_match:
            fiyat = f"{price_match.group(1)} TL"
        else:
            price_match_alt = re.search(r'"sellingPrice":\s*{\s*"value":\s*([\d\.]+)', html_content)
            if price_match_alt:
                fiyat = f"{price_match_alt.group(1)} TL"

        # 3. Stok Yakalama
        json_matches = re.findall(r'window\.__PRODUCT_DETAIL_APP_INITIAL_STATE__\s*=\s*({.*?});', html_content)
        if json_matches:
            try:
                data = json.loads(json_matches[0])
                product = data.get('product', {})
                
                # Eğer başlık daha detaylı alınabiliyorsa güncelle
                brand = product.get('brand', {}).get('name', '')
                name = product.get('name', '')
                if brand and name:
                    urun_adi = f"{brand} {name}"

                variants = product.get('variants', [])
                if variants:
                    stok = sum(v.get('quantity', 0) for v in variants if 'quantity' in v)
                else:
                    stok = product.get('totalQuantity', None)
            except:
                pass

        if stok is None:
            # Genel stok sayısı araması
            stok_list = re.findall(r'"quantity":\s*(\d+)', html_content)
            if stok_list:
                stok = sum(int(s) for s in stok_list[:10])

    except Exception as e:
        print(f"Tarama Hatası ({url}): {e}")

    return urun_adi, fiyat, stok

def tum_urunleri_guncelle():
    conn = sqlite3.connect("trendyol_takip.db")
    cursor = conn.cursor()
    cursor.execute("SELECT url FROM urunler")
    urls = [row[0] for row in cursor.fetchall()]
    conn.close()

    for url in urls:
        urun_adi, fiyat, stok = trendyol_api_tarama(url)
        
        conn = sqlite3.connect("trendyol_takip.db")
        cursor = conn.cursor()
        cursor.execute("SELECT stok, fiyat FROM detayli_takip WHERE url = ? ORDER BY id DESC LIMIT 1", (url,))
        row = cursor.fetchone()
        
        onceki_stok, onceki_fiyat = row if row else (None, None)

        satis_adedi = 0
        ciro = 0.0
        fiyat_num = fiyati_sayiya_cevir(fiyat)

        if onceki_stok is not None and stok is not None and stok < onceki_stok:
            satis_adedi = onceki_stok - stok
            ciro = satis_adedi * fiyat_num

        su_an = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("""
            INSERT INTO detayli_takip (url, urun_adi, fiyat, stok, satis_adedi, ciro, tarih)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (url, urun_adi, fiyat, stok, satis_adedi, ciro, su_an))
        conn.commit()
        conn.close()

        if onceki_fiyat is None or fiyat != onceki_fiyat or satis_adedi > 0:
            eposta_gonder(urun_adi, fiyat, stok, satis_adedi, ciro, url)

@app.route('/')
def index():
    conn = sqlite3.connect("trendyol_takip.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT u.id, u.url, 
               d.urun_adi, d.fiyat, d.stok, d.tarih as son_tarih,
               (SELECT SUM(satis_adedi) FROM detayli_takip WHERE url = u.url) as toplam_satis,
               (SELECT SUM(ciro) FROM detayli_takip WHERE url = u.url) as toplam_ciro
        FROM urunler u
        LEFT JOIN detayli_takip d ON d.id = (
            SELECT id FROM detayli_takip WHERE url = u.url ORDER BY id DESC LIMIT 1
        )
    """)
    urunler = cursor.fetchall()
    conn.close()
    return render_template('index.html', urunler=urunler)

@app.route('/urun-ekle', methods=['POST'])
def urun_ekle():
    url = request.form.get('url').strip()
    if url:
        conn = sqlite3.connect("trendyol_takip.db")
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT INTO urunler (url) VALUES (?)", (url,))
            conn.commit()
        except:
            pass
        conn.close()
        tum_urunleri_guncelle()
    return redirect(url_for('index'))

@app.route('/sil/<int:id>')
def urun_sil(id):
    conn = sqlite3.connect("trendyol_takip.db")
    cursor = conn.cursor()
    cursor.execute("SELECT url FROM urunler WHERE id = ?", (id,))
    row = cursor.fetchone()
    if row:
        url = row[0]
        cursor.execute("DELETE FROM urunler WHERE id = ?", (id,))
        cursor.execute("DELETE FROM detayli_takip WHERE url = ?", (url,))
        conn.commit()
    conn.close()
    return redirect(url_for('index'))

@app.route('/guncelle')
def guncelle():
    tum_urunleri_guncelle()
    return redirect(url_for('index'))

if __name__ == '__main__':
    veritabani_kur()
    print("🚀 Web Paneli Başlatılıyor: http://127.0.0.1:5000")
    app.run(debug=True, port=5000)