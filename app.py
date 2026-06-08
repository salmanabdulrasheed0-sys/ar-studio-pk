# ================================================================
# AR Studio PK — Backend (Flask)
# Platform: Render.com (Free Tier)
# ================================================================

from flask import Flask, request, jsonify, send_file, render_template
from flask_cors import CORS
import requests
import io
import logging
import os
import zipfile
import qrcode
from typing import Optional

from utils.responses import error_response
from utils.urls import build_ar_url, build_model_urls
from utils.database import get_supabase, get_model, create_model, update_model_status
from utils.kiri_client import upload_video, get_status, get_model_zip_url

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)  # Frontend ko allow karo API call karne ke liye


# ════════════════════════════════════════════════════════════════
# ROUTE 1 — Health Check
# ════════════════════════════════════════════════════════════════
@app.errorhandler(Exception)
def handle_unexpected_error(exc):
    logger.exception("Unhandled exception on %s %s", request.method, request.path)
    return jsonify(error="Internal server error"), 500


@app.route('/', methods=['GET'])
def home():
    return jsonify({"status": "✅ AR Studio PK Backend running!"})


# ════════════════════════════════════════════════════════════════
# ROUTE 2 — Video Upload
# POST /api/upload
# Form: video (file), quality (0/1/2)
# ════════════════════════════════════════════════════════════════
@app.route('/api/upload', methods=['POST'])
def upload_video_route():
    if 'video' not in request.files:
        return error_response("Video file required", 400)

    video   = request.files['video']
    quality = request.form.get('quality', '1')  # 0=High 1=Medium 2=Low

    # ── Kiri Engine pe upload karo ──────────────────────────────
    try:
        kiri_resp = upload_video(video, quality)
    except requests.exceptions.Timeout:
        return error_response("Timeout! Video bahut bari hai ya internet slow hai.", 408)
    except Exception as e:
        return error_response(f"Upload error: {e}", 500)

    if not kiri_resp.ok:
        logger.error("Kiri upload returned HTTP %s: %s", kiri_resp.status_code, kiri_resp.text[:500])
        return error_response("Kiri Engine error", 500, detail=kiri_resp.text)

    try:
        kiri_data = kiri_resp.json()
    except ValueError:
        logger.error("Kiri upload returned non-JSON response: %s", kiri_resp.text[:500])
        return error_response("Invalid response from Kiri Engine", 502)

    if not kiri_data.get('ok'):
        code = kiri_data.get('code', '')
        if code == 4011:
            return error_response("Kiri Engine credits khatam hain!", 403)
        if code == 4001:
            return error_response("Video format galat hai. MP4 use karo, max 1080p, max 3 min.", 400)
        return error_response("Kiri rejected request", 400, detail=kiri_data)

    try:
        sid = kiri_data['data']['serialize']
    except (KeyError, TypeError) as e:
        logger.error("Unexpected Kiri response structure: %s — response: %s", e, kiri_data)
        return error_response("Unexpected response from Kiri Engine", 502)

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
        kiri_resp.raise_for_status()
        kiri_data = kiri_resp.json()
        kiri_status = kiri_data['data']['status']
    except requests.exceptions.RequestException as e:
        logger.warning("Kiri status check network error for %s: %s", sid, e)
        return jsonify(status='processing', note='Status service temporarily unreachable')
    except (ValueError, KeyError, TypeError) as e:
        logger.error("Kiri status check returned unexpected payload for %s: %s", sid, e)
        return jsonify(status='processing', note='Received unexpected status response')

    LABELS = {-1: 'uploading', 3: 'queuing', 0: 'processing', 2: 'ready', 1: 'failed', 4: 'expired'}

    if kiri_status == 2:  # SUCCESS — GLB download karo!
        glb_url = _download_and_store_glb(sid)
        if glb_url:
            try:
                update_model_status(sid, 'ready', glb_url=glb_url)
            except Exception as e:
                logger.error("DB update to 'ready' failed for %s (GLB already uploaded): %s", sid, e)
                return error_response("Model processed but failed to update database", 500)
            return jsonify(status='ready', **build_model_urls(sid))
        else:
            return error_response('GLB store karne mein error aya.', 500)

    if kiri_status in [1, 4]:  # FAILED or EXPIRED
        try:
            update_model_status(sid, 'failed')
        except Exception as e:
            logger.error("DB update to 'failed' failed for %s: %s", sid, e)
        return jsonify(status='failed', message='Processing fail hui. Better video try karo.')

    return jsonify(status=LABELS.get(kiri_status, 'processing'))


def _download_and_store_glb(sid: str) -> Optional[str]:
    """Kiri se ZIP download karo, GLB extract karo, Supabase mein store karo"""
    # Download URL lo
    try:
        r = get_model_zip_url(sid)
        r.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error("Failed to fetch model ZIP URL for %s: %s", sid, e)
        return None

    try:
        zip_url = r.json()['data']['modelUrl']
    except (ValueError, KeyError, TypeError) as e:
        logger.error("Unexpected getModelZip response for %s: %s — body: %s", sid, e, r.text[:500])
        return None

    # ZIP download karo
    try:
        zip_resp = requests.get(zip_url, timeout=120)
        zip_resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error("Failed to download ZIP for %s from %s: %s", sid, zip_url, e)
        return None

    # GLB extract karo
    try:
        with zipfile.ZipFile(io.BytesIO(zip_resp.content)) as z:
            glb_files = [f for f in z.namelist() if f.endswith('.glb')]
            if not glb_files:
                logger.error("No .glb file found in ZIP for %s (contents: %s)", sid, z.namelist())
                return None
            glb_data = z.read(glb_files[0])
    except zipfile.BadZipFile as e:
        logger.error("Corrupt ZIP for %s: %s", sid, e)
        return None

    # Supabase Storage mein upload karo
    file_path = f"{sid}.glb"
    try:
        get_supabase().storage.from_('ar-models').upload(
            file_path,
            glb_data,
            file_options={"content-type": "model/gltf-binary"}
        )
    except Exception as e:
        logger.error("Supabase storage upload failed for %s: %s", sid, e)
        return None

    # Public URL lo
    return get_supabase().storage.from_('ar-models').get_public_url(file_path)


# ════════════════════════════════════════════════════════════════
# ROUTE 4 — AR Viewer (WebAR Page)
# GET /api/ar/<serialize_id>
# ════════════════════════════════════════════════════════════════
@app.route('/api/ar/<sid>', methods=['GET'])
def ar_viewer(sid):
    record, err = get_model(sid, columns='glb_url, status')
    if err is not None:
        return err

    # Processing ho raha hai — waiting page
    if record['status'] != 'ready' or not record.get('glb_url'):
        return render_template('processing.html'), 202

    return render_template('ar_viewer.html', glb_url=record['glb_url'])


# ════════════════════════════════════════════════════════════════
# ROUTE 5 — QR Code
# GET /api/qr/<serialize_id>
# ════════════════════════════════════════════════════════════════
@app.route('/api/qr/<sid>', methods=['GET'])
def get_qr_code(sid):
    ar_url = build_ar_url(sid)

    try:
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
    except Exception:
        logger.exception("QR code generation failed for %s", sid)
        return jsonify(error="Failed to generate QR code"), 500

    return send_file(buf, mimetype='image/png', download_name=f'ar-qr-{sid[:8]}.png')


# ════════════════════════════════════════════════════════════════
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
