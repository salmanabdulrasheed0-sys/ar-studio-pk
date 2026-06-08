# ================================================================
# AR Studio PK — Backend (Flask)
# Platform: Render.com (Free Tier)
# ================================================================

from flask import Flask, request, jsonify, send_file, render_template, abort
from flask_cors import CORS
import requests
import io
import os
import re
import logging
import zipfile
import qrcode
from typing import Optional

from utils.responses import error_response
from utils.urls import build_ar_url, build_model_urls
from utils.database import get_supabase, get_model, create_model, update_model_status
from utils.kiri_client import upload_video, get_status, get_model_zip_url

# ── Logging ───────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ── CORS — restrict to configured origins ─────────────────────────
ALLOWED_ORIGINS = os.environ.get('ALLOWED_ORIGINS', '')
if ALLOWED_ORIGINS:
    CORS(app, origins=[o.strip() for o in ALLOWED_ORIGINS.split(',')])
else:
    CORS(app)
    logger.warning(
        "ALLOWED_ORIGINS not set — CORS is open to all origins. "
        "Set ALLOWED_ORIGINS env var for production."
    )

# ── Upload constraints ────────────────────────────────────────────
MAX_UPLOAD_BYTES = int(os.environ.get('MAX_UPLOAD_MB', '50')) * 1024 * 1024
ALLOWED_VIDEO_TYPES = {'video/mp4', 'video/quicktime', 'video/x-msvideo', 'video/webm'}
UPLOAD_API_KEY = os.environ.get('UPLOAD_API_KEY', '')

# ── Helpers ───────────────────────────────────────────────────────
_SID_RE = re.compile(r'^[a-zA-Z0-9_-]{1,128}$')

def _valid_sid(sid: str) -> bool:
    return bool(_SID_RE.match(sid))


# ── Security headers ──────────────────────────────────────────────
@app.after_request
def _set_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
    if request.is_secure:
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    return response


# ════════════════════════════════════════════════════════════════
# ROUTE 1 — Health Check
# ════════════════════════════════════════════════════════════════
@app.route('/', methods=['GET'])
def home():
    return jsonify({"status": "ok"})


# ════════════════════════════════════════════════════════════════
# ROUTE 2 — Video Upload
# POST /api/upload
# Form: video (file), quality (0/1/2)
# ════════════════════════════════════════════════════════════════
@app.route('/api/upload', methods=['POST'])
def upload_video_route():
    # ── Optional API-key authentication ───────────────────────────
    if UPLOAD_API_KEY:
        auth = request.headers.get('Authorization', '')
        if auth != f"Bearer {UPLOAD_API_KEY}":
            return error_response("Unauthorized", 401)

    if 'video' not in request.files:
        return error_response("Video file required", 400)

    video   = request.files['video']
    quality = request.form.get('quality', '1')  # 0=High 1=Medium 2=Low

    # ── Validate quality parameter ────────────────────────────────
    if quality not in ('0', '1', '2'):
        return error_response("quality must be 0, 1, or 2", 400)

    # ── Validate file type ────────────────────────────────────────
    if video.content_type not in ALLOWED_VIDEO_TYPES:
        return error_response("Unsupported video format. Use MP4, MOV, AVI, or WebM.", 400)

    # ── Validate file size ────────────────────────────────────────
    video.seek(0, io.SEEK_END)
    size = video.tell()
    video.seek(0)
    if size > MAX_UPLOAD_BYTES:
        max_mb = MAX_UPLOAD_BYTES // (1024 * 1024)
        return error_response(f"File too large. Maximum {max_mb} MB allowed.", 413)

    # ── Kiri Engine pe upload karo ──────────────────────────────
    try:
        kiri_resp = upload_video(video, quality)
    except requests.exceptions.Timeout:
        return error_response("Timeout! Video bahut bari hai ya internet slow hai.", 408)
    except Exception:
        logger.exception("Kiri upload failed")
        return error_response("Upload failed. Please try again later.", 500)

    if not kiri_resp.ok:
        logger.error("Kiri Engine error: %s", kiri_resp.text)
        return error_response("Processing service error", 500)

    kiri_data = kiri_resp.json()
    if not kiri_data.get('ok'):
        code = kiri_data.get('code', '')
        if code == 4011:
            return error_response("Kiri Engine credits khatam hain!", 403)
        if code == 4001:
            return error_response("Video format galat hai. MP4 use karo, max 1080p, max 3 min.", 400)
        logger.warning("Kiri rejected: %s", kiri_data)
        return error_response("Processing service rejected request", 400)

    sid = kiri_data['data']['serialize']

    # ── Supabase mein save karo ──────────────────────────────────
    err = create_model(sid)
    if err is not None:
        return err

    return jsonify(success=True, serialize_id=sid, **build_model_urls(sid))


# ════════════════════════════════════════════════════════════════
# ROUTE 3 — Status Check
# GET /api/status/<serialize_id>
# ════════════════════════════════════════════════════════════════
@app.route('/api/status/<sid>', methods=['GET'])
def check_status(sid):
    if not _valid_sid(sid):
        return error_response("Invalid ID format", 400)

    record, err = get_model(sid)
    if err is not None:
        return err

    # Already ready hai?
    if record['status'] == 'ready' and record.get('glb_url'):
        return jsonify(status='ready', **build_model_urls(sid))

    # Already failed?
    if record['status'] == 'failed':
        return jsonify(status='failed',
                       message='Processing fail hui. Better video try karo — white background pe.')

    # Kiri se live status lo
    try:
        kiri_resp = get_status(sid)
        kiri_status = kiri_resp.json()['data']['status']
    except Exception:
        return jsonify(status='processing')  # Agar kiri unreachable ho, processing assume karo

    LABELS = {-1: 'uploading', 3: 'queuing', 0: 'processing', 2: 'ready', 1: 'failed', 4: 'expired'}

    if kiri_status == 2:  # SUCCESS — GLB download karo!
        glb_url = _download_and_store_glb(sid)
        if glb_url:
            update_model_status(sid, 'ready', glb_url=glb_url)
            return jsonify(status='ready', **build_model_urls(sid))
        else:
            return error_response('GLB store karne mein error aya.', 500)

    if kiri_status in [1, 4]:  # FAILED or EXPIRED
        update_model_status(sid, 'failed')
        return jsonify(status='failed', message='Processing fail hui. Better video try karo.')

    return jsonify(status=LABELS.get(kiri_status, 'processing'))


def _download_and_store_glb(sid: str) -> Optional[str]:
    """Kiri se ZIP download karo, GLB extract karo, Supabase mein store karo"""
    try:
        # Download URL lo
        r       = get_model_zip_url(sid)
        zip_url = r.json()['data']['modelUrl']

        # ZIP download karo
        zip_data = requests.get(zip_url, timeout=120).content

        # GLB extract karo (safe extraction — reject path traversal)
        with zipfile.ZipFile(io.BytesIO(zip_data)) as z:
            glb_files = [
                f for f in z.namelist()
                if f.endswith('.glb') and '..' not in f and not f.startswith('/')
            ]
            if not glb_files:
                logger.warning("No GLB in ZIP for %s", sid)
                return None
            glb_data = z.read(glb_files[0])

        # Supabase Storage mein upload karo
        file_path = f"{sid}.glb"
        get_supabase().storage.from_('ar-models').upload(
            file_path,
            glb_data,
            file_options={"content-type": "model/gltf-binary"}
        )

        # Public URL lo
        return get_supabase().storage.from_('ar-models').get_public_url(file_path)

    except Exception:
        logger.exception("_download_and_store_glb error for sid=%s", sid)
        return None


# ════════════════════════════════════════════════════════════════
# ROUTE 4 — AR Viewer (WebAR Page)
# GET /api/ar/<serialize_id>
# ════════════════════════════════════════════════════════════════
@app.route('/api/ar/<sid>', methods=['GET'])
def ar_viewer(sid):
    if not _valid_sid(sid):
        return "Invalid ID", 400

    record, err = get_model(sid, columns='glb_url, status')
    if err is not None:
        return err

    # Processing ho raha hai — waiting page
    if record['status'] != 'ready' or not record.get('glb_url'):
        return render_template('processing.html'), 202

    # Jinja2 auto-escapes {{ glb_url }} — safe from XSS
    return render_template('ar_viewer.html', glb_url=record['glb_url'])


# ════════════════════════════════════════════════════════════════
# ROUTE 5 — QR Code
# GET /api/qr/<serialize_id>
# ════════════════════════════════════════════════════════════════
@app.route('/api/qr/<sid>', methods=['GET'])
def get_qr_code(sid):
    if not _valid_sid(sid):
        return error_response("Invalid ID format", 400)

    ar_url = build_ar_url(sid)

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
