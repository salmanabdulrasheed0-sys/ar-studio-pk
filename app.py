# ================================================================
# AR Studio PK — Backend (Flask)
# Platform: Render.com (Free Tier)
# ================================================================

from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import requests
import os
import io
import zipfile
import qrcode
from typing import Optional
from supabase import create_client

app = Flask(__name__)
CORS(app)  # Frontend ko allow karo API call karne ke liye

# ── Environment Variables (Render.com pe set karna) ──────────────
KIRI_API_KEY = os.environ.get('KIRI_API_KEY', '')
SUPABASE_URL = os.environ.get('SUPABASE_URL', '')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY', '')   # Service Role Key
APP_BASE_URL = os.environ.get('APP_BASE_URL', '')    # https://yourapp.onrender.com
# ─────────────────────────────────────────────────────────────────

KIRI_BASE    = "https://api.kiriengine.app/api/v1/open"
KIRI_HEADERS = {"Authorization": f"Bearer {KIRI_API_KEY}"}

# Supabase client
supa = create_client(SUPABASE_URL, SUPABASE_KEY)


# ════════════════════════════════════════════════════════════════
# ROUTE 1 — Health Check
# ════════════════════════════════════════════════════════════════
@app.route('/', methods=['GET'])
def home():
    return jsonify({"status": "✅ AR Studio PK Backend running!"})


# ════════════════════════════════════════════════════════════════
# ROUTE 2 — Video Upload
# POST /api/upload
# Form: video (file), quality (0/1/2)
# ════════════════════════════════════════════════════════════════
@app.route('/api/upload', methods=['POST'])
def upload_video():
    if 'video' not in request.files:
        return jsonify(error="Video file required"), 400

    video   = request.files['video']
    quality = request.form.get('quality', '1')  # 0=High 1=Medium 2=Low

    # ── Kiri Engine pe upload karo ──────────────────────────────
    try:
        kiri_resp = requests.post(
            f"{KIRI_BASE}/photo/video",
            headers=KIRI_HEADERS,
            files={"videoFile": (video.filename, video.read(), 'video/mp4')},
            data={
                "modelQuality":     quality,
                "textureQuality":   "1",
                "fileFormat":       "glb",
                "isMask":           "1",
                "textureSmoothing": "0"
            },
            timeout=300  # 5 min timeout (badi files ke liye)
        )
    except requests.exceptions.Timeout:
        return jsonify(error="Timeout! Video bahut bari hai ya internet slow hai."), 408
    except Exception as e:
        return jsonify(error=f"Upload error: {str(e)}"), 500

    if not kiri_resp.ok:
        return jsonify(error="Kiri Engine error", detail=kiri_resp.text), 500

    kiri_data = kiri_resp.json()
    if not kiri_data.get('ok'):
        code = kiri_data.get('code', '')
        if code == 4011:
            return jsonify(error="Kiri Engine credits khatam hain!"), 403
        if code == 4001:
            return jsonify(error="Video format galat hai. MP4 use karo, max 1080p, max 3 min."), 400
        return jsonify(error="Kiri rejected request", detail=kiri_data), 400

    sid = kiri_data['data']['serialize']

    # ── Supabase mein save karo ──────────────────────────────────
    try:
        supa.table('models').insert({
            'serialize_id': sid,
            'status':       'processing',
            'glb_url':      None
        }).execute()
    except Exception as e:
        return jsonify(error=f"DB error: {str(e)}"), 500

    return jsonify(
        success      = True,
        serialize_id = sid,
        ar_url       = f"{APP_BASE_URL}/api/ar/{sid}",
        qr_url       = f"{APP_BASE_URL}/api/qr/{sid}"
    )


# ════════════════════════════════════════════════════════════════
# ROUTE 3 — Status Check
# GET /api/status/<serialize_id>
# ════════════════════════════════════════════════════════════════
@app.route('/api/status/<sid>', methods=['GET'])
def check_status(sid):
    # DB se check karo
    try:
        result = supa.table('models').select('*').eq('serialize_id', sid).execute()
    except Exception as e:
        return jsonify(error=f"DB error: {str(e)}"), 500

    if not result.data:
        return jsonify(error="Task not found"), 404

    record = result.data[0]

    # Already ready hai?
    if record['status'] == 'ready' and record.get('glb_url'):
        return jsonify(
            status  = 'ready',
            ar_url  = f"{APP_BASE_URL}/api/ar/{sid}",
            qr_url  = f"{APP_BASE_URL}/api/qr/{sid}"
        )

    # Already failed?
    if record['status'] == 'failed':
        return jsonify(status='failed',
                       message='Processing fail hui. Better video try karo — white background pe.')

    # Kiri se live status lo
    try:
        kiri_resp = requests.get(
            f"{KIRI_BASE}/model/getStatus",
            headers=KIRI_HEADERS,
            params={"serialize": sid},
            timeout=30
        )
        kiri_status = kiri_resp.json()['data']['status']
    except Exception:
        return jsonify(status='processing')  # Agar kiri unreachable ho, processing assume karo

    LABELS = {-1: 'uploading', 3: 'queuing', 0: 'processing', 2: 'ready', 1: 'failed', 4: 'expired'}

    if kiri_status == 2:  # SUCCESS — GLB download karo!
        glb_url = _download_and_store_glb(sid)
        if glb_url:
            supa.table('models').update({
                'status':  'ready',
                'glb_url': glb_url
            }).eq('serialize_id', sid).execute()
            return jsonify(
                status = 'ready',
                ar_url = f"{APP_BASE_URL}/api/ar/{sid}",
                qr_url = f"{APP_BASE_URL}/api/qr/{sid}"
            )
        else:
            return jsonify(status='failed', message='GLB store karne mein error aya.'), 500

    if kiri_status in [1, 4]:  # FAILED or EXPIRED
        supa.table('models').update({'status': 'failed'}).eq('serialize_id', sid).execute()
        return jsonify(status='failed', message='Processing fail hui. Better video try karo.')

    return jsonify(status=LABELS.get(kiri_status, 'processing'))


def _download_and_store_glb(sid: str) -> Optional[str]:
    """Kiri se ZIP download karo, GLB extract karo, Supabase mein store karo"""
    try:
        # Download URL lo
        r        = requests.get(f"{KIRI_BASE}/model/getModelZip",
                                headers=KIRI_HEADERS,
                                params={"serialize": sid}, timeout=30)
        zip_url  = r.json()['data']['modelUrl']

        # ZIP download karo
        zip_data = requests.get(zip_url, timeout=120).content

        # GLB extract karo
        with zipfile.ZipFile(io.BytesIO(zip_data)) as z:
            glb_files = [f for f in z.namelist() if f.endswith('.glb')]
            if not glb_files:
                print(f"No GLB in ZIP for {sid}")
                return None
            glb_data = z.read(glb_files[0])

        # Supabase Storage mein upload karo
        file_path = f"{sid}.glb"
        supa.storage.from_('ar-models').upload(
            file_path,
            glb_data,
            file_options={"content-type": "model/gltf-binary"}
        )

        # Public URL lo
        return supa.storage.from_('ar-models').get_public_url(file_path)

    except Exception as e:
        print(f"_download_and_store_glb error: {e}")
        return None


# ════════════════════════════════════════════════════════════════
# ROUTE 4 — AR Viewer (WebAR Page)
# GET /api/ar/<serialize_id>
# ════════════════════════════════════════════════════════════════
@app.route('/api/ar/<sid>', methods=['GET'])
def ar_viewer(sid):
    try:
        row = supa.table('models').select('glb_url, status').eq('serialize_id', sid).execute()
    except:
        return "Database error", 500

    if not row.data:
        return "Model not found", 404

    record = row.data[0]

    # Processing ho raha hai — waiting page
    if record['status'] != 'ready' or not record.get('glb_url'):
        return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#0a0a0f">
<title>Processing...</title>
<style>
  body{{margin:0;background:#0a0a0f;color:#fff;font-family:-apple-system,BlinkMacSystemFont,sans-serif;
       display:flex;align-items:center;justify-content:center;height:100vh;text-align:center;padding:24px}}
  .spinner{{width:60px;height:60px;border:3px solid rgba(255,255,255,0.08);
            border-top-color:#7c3aed;border-radius:50%;animation:spin 1s linear infinite;margin:0 auto 28px}}
  @keyframes spin{{to{{transform:rotate(360deg)}}}}
  h2{{font-size:24px;font-weight:700;margin-bottom:10px}}
  p{{color:#666;font-size:15px;line-height:1.7}}
  .dot{{display:inline-block;animation:blink 1.4s infinite both}}
  .dot:nth-child(2){{animation-delay:.2s}}
  .dot:nth-child(3){{animation-delay:.4s}}
  @keyframes blink{{0%,80%,100%{{opacity:0}}40%{{opacity:1}}}}
</style>
<script>setTimeout(()=>location.reload(), 10000)</script>
</head>
<body>
<div>
  <div class="spinner"></div>
  <h2>3D Model Ban Raha Hai<span class="dot">.</span><span class="dot">.</span><span class="dot">.</span></h2>
  <p>Processing chal rahi hai<br>Yeh page 10 seconds mein auto-refresh hoga</p>
  <p style="margin-top:20px;font-size:13px;color:#444">Is link ko save kar lo — ready hone pe yahan AR dikhega</p>
</div>
</body>
</html>""", 202

    glb_url = record['glb_url']

    # ── AR Viewer Page ──────────────────────────────────────────
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<meta name="theme-color" content="#0a0a0f">
<title>AR View — AR Studio PK</title>
<script type="module" src="https://ajax.googleapis.com/ajax/libs/model-viewer/3.3.0/model-viewer.min.js"></script>
<style>
  *{{margin:0;padding:0;box-sizing:border-box}}
  body{{background:#111;overflow:hidden;font-family:-apple-system,sans-serif}}
  model-viewer{{
    width:100vw;height:100vh;
    background:radial-gradient(ellipse at 50% 80%,#1e1b4b 0%,#0a0a0f 65%);
  }}
  .ar-btn{{
    background:linear-gradient(135deg,#7c3aed,#4338ca);
    color:#fff;border:none;padding:16px 36px;border-radius:50px;
    font-size:17px;font-weight:700;cursor:pointer;letter-spacing:0.3px;
    box-shadow:0 6px 28px rgba(124,58,237,0.5);
    display:flex;align-items:center;gap:10px;white-space:nowrap;
    transition:transform .15s,box-shadow .15s;
  }}
  .ar-btn:active{{transform:scale(0.97);box-shadow:0 3px 14px rgba(124,58,237,0.4)}}
  .brand{{
    position:fixed;top:16px;left:50%;transform:translateX(-50%);
    background:rgba(0,0,0,0.55);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);
    color:rgba(255,255,255,0.6);font-size:12px;font-weight:600;
    padding:7px 18px;border-radius:20px;white-space:nowrap;
    border:1px solid rgba(255,255,255,0.08);letter-spacing:0.8px;
  }}
</style>
</head>
<body>
<model-viewer
  src="{glb_url}"
  ar
  ar-modes="webxr scene-viewer quick-look"
  camera-controls
  auto-rotate
  auto-rotate-delay="1500"
  shadow-intensity="1.2"
  exposure="0.95"
  tone-mapping="commerce"
>
  <button class="ar-btn" slot="ar-button">
    📱 View in AR
  </button>
</model-viewer>
<div class="brand">⚡ AR Studio PK</div>
</body>
</html>"""


# ════════════════════════════════════════════════════════════════
# ROUTE 5 — QR Code
# GET /api/qr/<serialize_id>
# ════════════════════════════════════════════════════════════════
@app.route('/api/qr/<sid>', methods=['GET'])
def get_qr_code(sid):
    ar_url = f"{APP_BASE_URL}/api/ar/{sid}"

    qr = qrcode.QRCode(
        version             = 1,
        error_correction    = qrcode.constants.ERROR_CORRECT_M,
        box_size            = 12,
        border              = 4
    )
    qr.add_data(ar_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#7c3aed", back_color="white")

    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)

    return send_file(buf, mimetype='image/png', download_name=f'ar-qr-{sid[:8]}.png')


# ════════════════════════════════════════════════════════════════
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
