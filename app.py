"""
Flask backend cho Hệ thống Website Chấm công & Quản lý Nhân viên bằng Nhận diện Khuôn mặt FaceID.
Tích hợp ArcFace IR-SE50 + MTCNN + Liveness Detection 4 tầng và SQLite Database.

Gồm 2 luồng phân quyền riêng biệt:
  1. Luồng Nhân viên (/):
     - Đăng nhập tài khoản nhân viên (Mã NV + Mật khẩu)
     - Quét mặt Chấm công Vào ca (Check-in) & Quét mặt Ra ca (Check-out) kèm ghi nhận Vị trí GPS, Thời gian, Ca làm việc
     - Quét mặt xác thực khi nộp Đơn xin nghỉ phép (bắt buộc nộp trước ngày nghỉ ít nhất 3 ngày)
     - Xem số ngày công chi tiết và bảng lương tạm tính theo tháng
  2. Luồng Người quản lý (/admin):
     - Đăng nhập quản trị viên -> Giao diện quản lý riêng
     - Thêm / Sửa / Xóa nhân viên (quét khuôn mặt liên tục 3-5 góc tạo đa vector embedding)
     - Xem báo cáo đăng nhập hệ thống (Login Audit Logs)
     - Duyệt / Từ chối đơn nghỉ phép, Quản lý Ca làm việc, Bảng chấm công, Bảng lương & Thống kê
"""
import csv
import io
import os
import sys
import time
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path

# Cấu hình mã hóa UTF-8 cho stdout/stderr
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import importlib.util as _ilu
import numpy as np
import torch
from flask import (
    Flask,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    send_from_directory,
    session,
    url_for,
)
from PIL import Image

import database

# ── Nạp model ArcFace từ external/InsightFace_Pytorch ────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent
REPO_PATH = PROJECT_ROOT / "external" / "InsightFace_Pytorch"

_spec = _ilu.spec_from_file_location("insightface_model", REPO_PATH / "model.py")
_mod = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
Backbone = _mod.Backbone

from facenet_pytorch import MTCNN

# ── Cấu hình hệ thống ─────────────────────────────────────────────────────────
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
FINETUNED_MODEL_PATH = PROJECT_ROOT / "models" / "best_model.pth"
PRETRAINED_MODEL_PATH = (
    PROJECT_ROOT / "external" / "InsightFace_Pytorch" / "work_space" / "model" / "model_ir_se50.pth"
)
ACTIVE_MODEL_PATH = (
    FINETUNED_MODEL_PATH if FINETUNED_MODEL_PATH.exists() else PRETRAINED_MODEL_PATH
)

SIMILARITY_THRESHOLD = 0.60  # Yêu cầu: mức tương đồng > 60%
ATTENDANCE_COOLDOWN_SEC = 180  # Cooldown 3 phút (180s) tránh quét lặp cùng thao tác

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = "faceid_secure_system_key_2026_rf92"
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB

# Khởi tạo cơ sở dữ liệu
database.init_db()

# ── Khởi tạo module chống giả mạo khuôn mặt (Face Anti-Spoofing / Liveness) ──
from src.utils.liveness import liveness_detector
ENABLE_LIVENESS_CHECK = True

# ── Nạp model một lần khi khởi động ─────────────────────────────────────────
print(f"Đang nạp ArcFace model từ: {ACTIVE_MODEL_PATH}")
backbone = Backbone(50, 0.6, "ir_se").to(DEVICE)
state_dict = torch.load(str(ACTIVE_MODEL_PATH), map_location=DEVICE)
backbone.load_state_dict(state_dict)
backbone.eval()
print(f"✓ Model nạp thành công (thiết bị: {DEVICE})")

mtcnn = MTCNN(image_size=112, margin=10, device=DEVICE, keep_all=False)
print("✓ MTCNN sẵn sàng")

# Cache embeddings của nhân viên trong RAM để so sánh siêu nhanh
# face_cache = {emp_id: {"emp": dict, "embeddings": [np.ndarray, ...]}}
face_cache = {}
last_attendance_time = {}  # {(emp_id, mode): float_timestamp}


def reload_face_cache():
    """Nạp toàn bộ embedding từ bảng face_embeddings (hỗ trợ 3-5 góc mặt B2)."""
    global face_cache
    new_cache = {}

    all_embs = database.get_all_face_embeddings()
    if all_embs:
        for row in all_embs:
            eid = row["emp_id"]
            npy_path = database.EMBEDDING_DIR / row["embedding_file"]
            if not npy_path.exists():
                continue
            try:
                vec = np.load(str(npy_path))
            except Exception as e:
                print(f"Lỗi nạp embedding {row['embedding_file']}: {e}")
                continue
            if eid not in new_cache:
                new_cache[eid] = {
                    "emp": {
                        "id": eid,
                        "emp_code": row["emp_code"],
                        "name": row["name"],
                        "department": row["department"],
                        "position": row["position"],
                        "avatar_file": row["avatar_file"],
                    },
                    "embeddings": [],
                }
            new_cache[eid]["embeddings"].append(vec)
    else:
        for emp in database.get_all_employees():
            emb_file = emp.get("embedding_file")
            if emb_file:
                npy_path = database.EMBEDDING_DIR / emb_file
                if npy_path.exists():
                    try:
                        new_cache[emp["id"]] = {
                            "emp": emp,
                            "embeddings": [np.load(str(npy_path))],
                        }
                    except Exception as e:
                        print(f"Lỗi nạp embedding {emb_file}: {e}")

    face_cache = new_cache
    print(f"✓ Cache khuôn mặt: {len(face_cache)} nhân viên")


reload_face_cache()


# ── Hàm tiện ích xử lý ảnh ───────────────────────────────────────────────────
def extract_embedding_from_crop(face_crop_pil: Image.Image):
    """Trích xuất 512-d ArcFace embedding trực tiếp từ ảnh đã crop."""
    import torchvision.transforms as T
    transform = T.Compose([
        T.Resize((112, 112)),
        T.ToTensor(),
        T.Normalize([0.5, 0.5, 0.5], [0.5, 0.5, 0.5]),
    ])
    face_tensor = transform(face_crop_pil).unsqueeze(0).to(DEVICE)
    with torch.no_grad():
        emb = backbone(face_tensor)
    return emb.squeeze(0).cpu().numpy()


def extract_embedding(pil_img: Image.Image):
    """Trích xuất 512-d ArcFace embedding từ ảnh PIL đầy đủ."""
    import torchvision.transforms as T

    face_tensor = mtcnn(pil_img)
    if face_tensor is None:
        transform = T.Compose([
            T.Resize((112, 112)),
            T.ToTensor(),
            T.Normalize([0.5, 0.5, 0.5], [0.5, 0.5, 0.5]),
        ])
        face_tensor = transform(pil_img)

    with torch.no_grad():
        emb = backbone(face_tensor.unsqueeze(0).to(DEVICE))
    return emb.squeeze(0).cpu().numpy()


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    a_norm = a / (np.linalg.norm(a) + 1e-8)
    b_norm = b / (np.linalg.norm(b) + 1e-8)
    return float(np.dot(a_norm, b_norm))


def get_client_ip():
    if request.headers.get("X-Forwarded-For"):
        return request.headers.get("X-Forwarded-For").split(",")[0].strip()
    return request.remote_addr or "127.0.0.1"


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_id"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "Vui lòng đăng nhập với quyền quản lý."}), 401
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)
    return decorated


def employee_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("emp_id"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "Vui lòng đăng nhập tài khoản nhân viên."}), 401
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)
    return decorated


# ── ROUTES: TRANG GIAO DIỆN ──────────────────────────────────────────────────

@app.route("/login")
@app.route("/admin/login")
def login_page():
    """Trang đăng nhập chung cho Nhân viên và Người quản lý."""
    return render_template("admin_login.html")


@app.route("/")
@app.route("/employee")
@employee_required
def kiosk_page():
    """Giao diện Cổng Nhân Viên (sau khi đăng nhập):
    - Quét mặt Chấm công Vào ca (Check-in) / Ra ca (Check-out) kèm Vị trí & Ca làm
    - Quét mặt xác thực nộp Đơn xin nghỉ phép (trước >= 3 ngày)
    - Xem Số ngày công & Bảng lương cá nhân
    """
    emp_id = session.get("emp_id")
    emp = database.get_employee_by_id(emp_id)
    if not emp:
        session.clear()
        return redirect(url_for("login_page"))
    shift_info = database.get_employee_shift(emp_id)
    today_log = database.get_today_attendance(emp_id)
    return render_template(
        "kiosk.html",
        employee=emp,
        shift_info=shift_info,
        today_log=today_log,
        model_name=ACTIVE_MODEL_PATH.name,
        device=DEVICE,
        threshold_pct=int(SIMILARITY_THRESHOLD * 100),
    )


@app.route("/admin")
@app.route("/admin/dashboard")
@admin_required
def admin_dashboard_page():
    """Giao diện Luồng Người Quản Lý riêng:
    Quản lý nhân viên, Lịch chấm công, Ca làm việc, Duyệt nghỉ phép, Báo cáo đăng nhập, Lương & Thống kê.
    """
    return render_template(
        "admin_dashboard.html",
        admin_name=session.get("admin_name", "Quản Trị Viên"),
        model_name=ACTIVE_MODEL_PATH.name,
        device=DEVICE,
    )


# ── ROUTES: TÀI NGUYÊN TĨNH / AVATAR ──────────────────────────────────────────

@app.route("/api/avatar/<filename>")
def get_avatar(filename):
    return send_from_directory(str(database.AVATAR_DIR), filename)


# ── ROUTES: ĐĂNG NHẬP NHÂN VIÊN & QUẢN LÝ (CÓ GHI NHẬT KÝ ĐĂNG NHẬP) ─────────

@app.route("/api/employee/login", methods=["POST"])
def api_employee_login():
    data = request.get_json(silent=True) or request.form
    emp_code = data.get("emp_code", "").strip().upper() or data.get("username", "").strip().upper()
    password = data.get("password", "").strip()
    ip_addr = get_client_ip()
    ua = request.headers.get("User-Agent", "")

    if not emp_code or not password:
        return jsonify({"error": "Vui lòng nhập đầy đủ Mã nhân viên và Mật khẩu."}), 400

    emp = database.verify_employee(emp_code, password)
    if not emp:
        database.log_login_event(
            user_type="employee",
            user_id=None,
            username=emp_code,
            full_name="Không xác định",
            department="",
            ip_address=ip_addr,
            user_agent=ua,
            status="Thất bại (Sai mã NV hoặc mật khẩu)",
        )
        return jsonify({"error": "Sai Mã nhân viên hoặc Mật khẩu."}), 401

    session["emp_id"] = emp["id"]
    session["emp_code"] = emp["emp_code"]
    session["emp_name"] = emp["name"]
    session["emp_dept"] = emp.get("department", "")

    database.log_login_event(
        user_type="employee",
        user_id=emp["id"],
        username=emp["emp_code"],
        full_name=emp["name"],
        department=emp.get("department", ""),
        ip_address=ip_addr,
        user_agent=ua,
        status="Thành công",
    )

    return jsonify({
        "success": True,
        "message": f"Xin chào nhân viên {emp['name']} ({emp['emp_code']})!",
        "redirect": "/",
    })


@app.route("/api/employee/logout", methods=["POST", "GET"])
def api_employee_logout():
    session.pop("emp_id", None)
    session.pop("emp_code", None)
    session.pop("emp_name", None)
    session.pop("emp_dept", None)
    return redirect(url_for("login_page"))


@app.route("/api/employee/me", methods=["GET"])
@employee_required
def api_employee_me():
    emp_id = session.get("emp_id")
    emp = database.get_employee_by_id(emp_id)
    if not emp:
        return jsonify({"logged_in": False}), 401
    shift_info = database.get_employee_shift(emp_id)
    today_log = database.get_today_attendance(emp_id)
    return jsonify({
        "logged_in": True,
        "employee": emp,
        "shift_info": shift_info,
        "today_log": today_log,
    })


@app.route("/api/employee/payroll", methods=["GET"])
@employee_required
def api_employee_payroll():
    """Nhân viên xem số ngày công và bảng lương cá nhân theo tháng."""
    emp_id = session.get("emp_id")
    month_str = request.args.get("month", datetime.now().strftime("%Y-%m")).strip()
    payroll = database.calculate_payroll(month_str=month_str, emp_id=emp_id)
    return jsonify({"payroll": payroll})


@app.route("/api/admin/login", methods=["POST"])
def api_admin_login():
    data = request.get_json(silent=True) or request.form
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    ip_addr = get_client_ip()
    ua = request.headers.get("User-Agent", "")

    if not username or not password:
        return jsonify({"error": "Vui lòng nhập đầy đủ tên đăng nhập và mật khẩu."}), 400

    admin = database.verify_admin(username, password)
    if not admin:
        database.log_login_event(
            user_type="admin",
            user_id=None,
            username=username,
            full_name="Quản trị viên",
            department="Ban Quản Trị",
            ip_address=ip_addr,
            user_agent=ua,
            status="Thất bại (Sai mật khẩu)",
        )
        return jsonify({"error": "Sai tên đăng nhập hoặc mật khẩu quản trị."}), 401

    session["admin_id"] = admin["id"]
    session["admin_name"] = admin["full_name"]
    session["admin_user"] = admin["username"]

    database.log_login_event(
        user_type="admin",
        user_id=admin["id"],
        username=admin["username"],
        full_name=admin["full_name"],
        department="Ban Quản Trị",
        ip_address=ip_addr,
        user_agent=ua,
        status="Thành công",
    )

    return jsonify({
        "success": True,
        "message": f"Chào mừng {admin['full_name']}!",
        "redirect": "/admin",
    })


@app.route("/api/admin/logout", methods=["POST", "GET"])
def api_admin_logout():
    session.pop("admin_id", None)
    session.pop("admin_name", None)
    session.pop("admin_user", None)
    return redirect(url_for("login_page"))


@app.route("/api/admin/me", methods=["GET"])
def api_admin_me():
    if not session.get("admin_id"):
        return jsonify({"logged_in": False})
    return jsonify({
        "logged_in": True,
        "admin_id": session.get("admin_id"),
        "admin_name": session.get("admin_name"),
    })


# ── ROUTES: NHẬN DIỆN KHUÔN MẶT CHẤM CÔNG CHECK-IN & CHECK-OUT ────────────────

@app.route("/api/attendance/recognize", methods=["POST"])
def api_attendance_recognize():
    """
    Nhận dạng khuôn mặt từ live camera để Chấm công Vào ca (Check-in) hoặc Ra ca (Check-out).
    - Kiểm tra Lớp 1: Liveness Detection (Chống giả mạo ảnh in / màn hình).
    - Kiểm tra Lớp 2: ArcFace IR-SE50 Cosine Similarity (> 60%) khớp với tài khoản nhân viên đang đăng nhập.
    - Ghi nhận đầy đủ: Vị trí GPS (location), Thời gian, Ca làm việc, Trạng thái (Đúng giờ / Đi trễ / Về sớm).
    """
    global ENABLE_LIVENESS_CHECK

    if "file" not in request.files or request.files["file"].filename == "":
        return jsonify({"error": "Không nhận được frame ảnh từ camera."}), 400

    mode = request.form.get("mode", "checkin").strip().lower()  # 'checkin' hoặc 'checkout'
    location = request.form.get("location", "").strip() or "Văn phòng công ty"
    logged_emp_id = session.get("emp_id")

    file = request.files["file"]
    try:
        img = Image.open(io.BytesIO(file.read())).convert("RGB")
    except Exception:
        return jsonify({"error": "Lỗi định dạng ảnh gửi lên."}), 400

    # ── Bước 1: Phát hiện khuôn mặt và điểm mốc bằng MTCNN ─────────────────────
    boxes, probs, landmarks = mtcnn.detect(img, landmarks=True)
    if boxes is None or len(boxes) == 0:
        return jsonify({"matched": False, "box": None, "message": "Không tìm thấy khuôn mặt rõ ràng."}), 200

    best_box = boxes[0]
    best_lm = landmarks[0] if landmarks is not None and len(landmarks) > 0 else None
    box_coords = [int(v) for v in best_box]

    # ── Bước 2: Kiểm tra Khuôn mặt sống (Face Anti-Spoofing / Liveness) ────────
    liveness_pct = 100.0
    if ENABLE_LIVENESS_CHECK:
        liveness_res = liveness_detector.check_liveness(img, best_box, best_lm)
        liveness_pct = liveness_res["liveness_pct"]

        if not liveness_res["is_live"]:
            return jsonify({
                "matched": False,
                "is_spoof": True,
                "box": box_coords,
                "liveness_pct": liveness_pct,
                "message": liveness_res["message"],
                "details": liveness_res.get("details", {}),
            }), 200

    # ── Bước 3: Trích xuất ArcFace embedding siêu tốc từ face crop ─────────────
    w_img, h_img = img.size
    x1 = max(0, box_coords[0])
    y1 = max(0, box_coords[1])
    x2 = min(w_img, box_coords[2])
    y2 = min(h_img, box_coords[3])

    if (x2 - x1) < 20 or (y2 - y1) < 20:
        face_crop = img
    else:
        pad_x = int((x2 - x1) * 0.05)
        pad_y = int((y2 - y1) * 0.05)
        cx1 = max(0, x1 - pad_x)
        cy1 = max(0, y1 - pad_y)
        cx2 = min(w_img, x2 + pad_x)
        cy2 = min(h_img, y2 + pad_y)
        face_crop = img.crop((cx1, cy1, cx2, cy2))

    query_emb = extract_embedding_from_crop(face_crop)
    if query_emb is None:
        return jsonify({"matched": False, "box": box_coords, "message": "Không thể trích xuất đặc trưng khuôn mặt."}), 200

    if not face_cache:
        return jsonify({
            "matched": False,
            "box": box_coords,
            "message": "Hệ thống chưa có dữ liệu khuôn mặt nhân viên.",
        }), 200

    # Nếu nhân viên đã đăng nhập: bắt buộc xác thực đúng khuôn mặt của chính nhân viên đó
    if logged_emp_id and logged_emp_id in face_cache:
        target_data = face_cache[logged_emp_id]
        self_sim = max(cosine_similarity(query_emb, vec) for vec in target_data["embeddings"])

        # Kiểm tra xem có khớp với người khác cao hơn không
        best_other_sim = -1.0
        for eid, data in face_cache.items():
            if eid == logged_emp_id:
                continue
            for vec in data["embeddings"]:
                s = cosine_similarity(query_emb, vec)
                if s > best_other_sim:
                    best_other_sim = s

        if self_sim < SIMILARITY_THRESHOLD:
            if best_other_sim >= SIMILARITY_THRESHOLD:
                msg = f"Khuôn mặt không khớp với tài khoản {target_data['emp']['name']} ({target_data['emp']['emp_code']})! Nghiêm cấm chấm công hộ."
                return jsonify({
                    "matched": False,
                    "wrong_account": True,
                    "box": box_coords,
                    "similarity": round(max(0.0, self_sim), 4),
                    "similarity_pct": round(max(0.0, self_sim) * 100, 1),
                    "liveness_pct": liveness_pct,
                    "is_live": True,
                    "message": msg,
                })
            else:
                msg = f"Chưa nhận diện rõ khuôn mặt của {target_data['emp']['name']} ({round(max(0.0, self_sim) * 100, 1)}% < {int(SIMILARITY_THRESHOLD * 100)}%). Vui lòng nhìn thẳng vào camera."
                return jsonify({
                    "matched": False,
                    "unregistered": False,
                    "box": box_coords,
                    "similarity": round(max(0.0, self_sim), 4),
                    "similarity_pct": round(max(0.0, self_sim) * 100, 1),
                    "liveness_pct": liveness_pct,
                    "is_live": True,
                    "message": msg,
                })

        best_emp = target_data["emp"]
        best_sim = self_sim
    else:
        # Fallback tìm trên toàn bộ face_cache
        best_emp = None
        best_sim = -1.0
        for eid, data in face_cache.items():
            for emb_vec in data["embeddings"]:
                sim = cosine_similarity(query_emb, emb_vec)
                if sim > best_sim:
                    best_sim = sim
                    best_emp = data["emp"]

    now_ts = time.time()
    now_dt = datetime.now()
    is_matched = best_sim >= SIMILARITY_THRESHOLD and best_emp is not None

    if is_matched:
        emp_id = best_emp["id"]
        check_type_req = "Ra ca" if mode == "checkout" else "Vào ca"

        # Kiểm tra trạng thái hôm nay
        today_log = database.get_today_attendance(emp_id)

        # Nếu chọn Check-out nhưng hôm nay chưa Check-in
        if mode == "checkout" and not today_log:
            return jsonify({
                "matched": False,
                "box": box_coords,
                "message": "Bạn chưa chấm công Vào ca (Check-in) hôm nay! Vui lòng chọn Chấm công Vào ca trước.",
            })

        # Nếu đã Check-out rồi mà bấm Check-out tiếp trong 3 phút
        cooldown_key = (emp_id, mode)
        last_time = last_attendance_time.get(cooldown_key, 0)
        time_since = now_ts - last_time
        in_cooldown = time_since < ATTENDANCE_COOLDOWN_SEC
        cooldown_rem = max(0, int(ATTENDANCE_COOLDOWN_SEC - time_since))

        if in_cooldown:
            action_label = "Check-out Ra ca" if mode == "checkout" else "Check-in Vào ca"
            return jsonify({
                "matched": True,
                "already_checked_in": True,
                "box": box_coords,
                "emp_code": best_emp["emp_code"],
                "name": best_emp["name"],
                "department": best_emp.get("department", ""),
                "position": best_emp.get("position", ""),
                "avatar_file": best_emp.get("avatar_file", ""),
                "similarity": round(best_sim, 4),
                "similarity_pct": round(best_sim * 100, 1),
                "liveness_pct": liveness_pct,
                "is_live": True,
                "time": now_dt.strftime("%H:%M:%S"),
                "date": now_dt.strftime("%d/%m/%Y"),
                "location": location,
                "logged": False,
                "cooldown_remaining": cooldown_rem,
                "today_log": today_log,
                "message": f"Bạn vừa {action_label} rồi! Vui lòng không quét lại liên tục (chờ {cooldown_rem}s).",
            })

        # Nếu chọn Check-in nhưng hôm nay đã Check-in rồi (ngoài 3 phút) -> báo đã check-in, gợi ý chuyển sang Check-out
        if mode == "checkin" and today_log and not today_log.get("check_out_time"):
            return jsonify({
                "matched": True,
                "already_checked_in": True,
                "box": box_coords,
                "emp_code": best_emp["emp_code"],
                "name": best_emp["name"],
                "department": best_emp.get("department", ""),
                "position": best_emp.get("position", ""),
                "avatar_file": best_emp.get("avatar_file", ""),
                "similarity": round(best_sim, 4),
                "similarity_pct": round(best_sim * 100, 1),
                "liveness_pct": liveness_pct,
                "is_live": True,
                "time": today_log["time"],
                "date": now_dt.strftime("%d/%m/%Y"),
                "location": today_log.get("location", location),
                "logged": False,
                "cooldown_remaining": 0,
                "today_log": today_log,
                "message": f"Bạn đã Check-in Vào ca lúc {today_log['time']} ({today_log['status']}). Hãy chọn 'Quét Mặt Check-out' khi tan ca!",
            })

        # Ghi nhận Check-in hoặc Check-out kèm Vị trí & Ca làm
        log_data = database.log_attendance(
            emp_id=best_emp["id"],
            emp_code=best_emp["emp_code"],
            emp_name=best_emp["name"],
            similarity=round(best_sim, 4),
            check_type=check_type_req,
            status="Đúng giờ",
            note="",
            location=location,
        )
        last_attendance_time[cooldown_key] = now_ts

        attendance_status = log_data.get("status", "Đúng giờ")
        check_type = log_data.get("check_type", check_type_req)
        updated_today = database.get_today_attendance(emp_id)

        return jsonify({
            "matched": True,
            "already_checked_in": False,
            "box": box_coords,
            "emp_code": best_emp["emp_code"],
            "name": best_emp["name"],
            "department": best_emp.get("department", ""),
            "position": best_emp.get("position", ""),
            "avatar_file": best_emp.get("avatar_file", ""),
            "similarity": round(best_sim, 4),
            "similarity_pct": round(best_sim * 100, 1),
            "liveness_pct": liveness_pct,
            "is_live": True,
            "time": log_data.get("check_out_time") or log_data.get("time"),
            "date": now_dt.strftime("%d/%m/%Y"),
            "location": location,
            "shift_name": log_data.get("shift_name", ""),
            "work_hours": log_data.get("work_hours", 0.0),
            "logged": True,
            "cooldown_remaining": ATTENDANCE_COOLDOWN_SEC,
            "attendance_status": attendance_status,
            "check_type": check_type,
            "log": log_data,
            "today_log": updated_today,
        })
    else:
        if best_sim < 0.45 and len(face_cache) > 0:
            msg = "Khuôn mặt chưa được đăng ký trong hệ thống. Vui lòng liên hệ quản trị viên."
            unregistered = True
        else:
            msg = f"Chưa nhận diện rõ (độ tương đồng {round(max(0.0, best_sim) * 100, 1)}% < {int(SIMILARITY_THRESHOLD * 100)}%). Vui lòng nhìn thẳng vào camera."
            unregistered = False

        return jsonify({
            "matched": False,
            "unregistered": unregistered,
            "box": box_coords,
            "similarity": round(max(0.0, best_sim), 4),
            "similarity_pct": round(max(0.0, best_sim) * 100, 1),
            "threshold_pct": int(SIMILARITY_THRESHOLD * 100),
            "liveness_pct": liveness_pct,
            "is_live": True,
            "message": msg,
        })


@app.route("/api/config/liveness", methods=["GET", "POST"])
def api_toggle_liveness():
    global ENABLE_LIVENESS_CHECK
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        if "enabled" in data:
            ENABLE_LIVENESS_CHECK = bool(data["enabled"])
        else:
            ENABLE_LIVENESS_CHECK = not ENABLE_LIVENESS_CHECK
    return jsonify({"enabled": ENABLE_LIVENESS_CHECK})


@app.route("/api/attendance/recent", methods=["GET"])
def api_attendance_recent():
    limit = int(request.args.get("limit", 10))
    recent = database.get_recent_attendance(limit)
    return jsonify({"recent": recent})


# ── ROUTES: QUẢN LÝ NHÂN VIÊN (CRUD) ─────────────────────────────────────────

@app.route("/api/admin/employees", methods=["GET"])
@admin_required
def api_get_employees():
    employees = database.get_all_employees()
    return jsonify({"employees": employees, "count": len(employees)})


@app.route("/api/admin/employees", methods=["POST"])
@admin_required
def api_add_employee():
    emp_code = request.form.get("emp_code", "").strip().upper()
    name = request.form.get("name", "").strip()
    department = request.form.get("department", "").strip()
    position = request.form.get("position", "").strip()
    password = request.form.get("password", "123456").strip() or "123456"
    base_salary_str = request.form.get("base_salary", "9000000").strip()
    try:
        base_salary = float(base_salary_str)
    except Exception:
        base_salary = 9000000.0

    if not emp_code or not name:
        return jsonify({"error": "Vui lòng nhập Mã nhân viên và Họ tên."}), 400

    if database.get_employee_by_code(emp_code):
        return jsonify({"error": f"Mã nhân viên '{emp_code}' đã tồn tại trong hệ thống."}), 400

    frames_list = request.files.getlist("frames")
    single_avatar = request.files.get("avatar") or request.files.get("file") or request.files.get("file_front")
    file_left = request.files.get("file_left")
    file_right = request.files.get("file_right")

    extracted = []

    if frames_list and len(frames_list) >= 2:
        angle_names = ["front", "left", "right", "left_tilt", "right_tilt"]
        for idx, f in enumerate(frames_list):
            try:
                img = Image.open(io.BytesIO(f.read())).convert("RGB")
            except Exception:
                continue
            emb = extract_embedding(img)
            if emb is not None:
                ang = angle_names[idx] if idx < len(angle_names) else f"angle_{idx+1}"
                extracted.append((ang, img, emb))
        if len(extracted) == 0:
            return jsonify({"error": "Không thể trích xuất khuôn mặt từ luồng quét. Vui lòng quét lại."}), 422
    elif file_left and file_right and single_avatar:
        triplet = [("front", single_avatar), ("left", file_left), ("right", file_right)]
        for ang, f in triplet:
            try:
                img = Image.open(io.BytesIO(f.read())).convert("RGB")
            except Exception:
                return jsonify({"error": f"Không thể xử lý file ảnh góc {ang}."}), 400
            emb = extract_embedding(img)
            if emb is None:
                return jsonify({"error": f"Không phát hiện khuôn mặt rõ nét ở góc {ang}."}), 422
            extracted.append((ang, img, emb))
    elif single_avatar and single_avatar.filename != "":
        try:
            main_img = Image.open(io.BytesIO(single_avatar.read())).convert("RGB")
        except Exception:
            return jsonify({"error": "Không thể xử lý file ảnh tải lên."}), 400

        main_emb = extract_embedding(main_img)
        if main_emb is None:
            return jsonify({"error": "Không phát hiện khuôn mặt rõ nét trong ảnh chân dung. Vui lòng chọn ảnh khác."}), 422
        extracted.append(("front", main_img, main_emb))

        try:
            img_left = main_img.rotate(6, expand=False, resample=Image.BICUBIC)
            emb_left = extract_embedding(img_left)
            if emb_left is not None:
                extracted.append(("left", img_left, emb_left))
        except Exception:
            pass

        try:
            img_right = main_img.rotate(-6, expand=False, resample=Image.BICUBIC)
            emb_right = extract_embedding(img_right)
            if emb_right is not None:
                extracted.append(("right", img_right, emb_right))
        except Exception:
            pass
    else:
        return jsonify({"error": "Vui lòng quét khuôn mặt bằng Camera hoặc tải lên 1 ảnh chân dung."}), 400

    timestamp_prefix = datetime.now().strftime("%Y%m%d%H%M%S")
    shift_id = int(request.form.get("shift_id", 1))

    front_ang, front_img, front_emb = extracted[0]
    front_img_filename = f"{emp_code}_avatar_{timestamp_prefix}.jpg"
    front_emb_filename = f"{emp_code}_front_{timestamp_prefix}.npy"
    front_img.save(str(database.AVATAR_DIR / front_img_filename), quality=92)
    np.save(str(database.EMBEDDING_DIR / front_emb_filename), front_emb)

    new_id = database.add_employee(
        emp_code=emp_code,
        name=name,
        department=department,
        position=position,
        avatar_file=front_img_filename,
        embedding_file=front_emb_filename,
        shift_id=shift_id,
        password=password,
        base_salary=base_salary,
    )

    for ang, s_img, s_emb in extracted[1:]:
        s_img_filename = f"{emp_code}_{ang}_{timestamp_prefix}.jpg"
        s_emb_filename = f"{emp_code}_{ang}_{timestamp_prefix}.npy"
        s_img.save(str(database.AVATAR_DIR / s_img_filename), quality=90)
        np.save(str(database.EMBEDDING_DIR / s_emb_filename), s_emb)
        database.add_face_embedding(new_id, ang, s_emb_filename, s_img_filename)

    reload_face_cache()

    return jsonify({
        "success": True,
        "message": f"Thêm nhân viên {name} ({emp_code}) thành công!",
        "emp_id": new_id,
    })


@app.route("/api/admin/employees/<int:emp_id>", methods=["PUT", "POST"])
@admin_required
def api_update_employee(emp_id):
    emp = database.get_employee_by_id(emp_id)
    if not emp:
        return jsonify({"error": "Không tìm thấy nhân viên."}), 404

    emp_code = request.form.get("emp_code", "").strip().upper()
    name = request.form.get("name", "").strip()
    department = request.form.get("department", "").strip()
    position = request.form.get("position", "").strip()
    password = request.form.get("password", "").strip()
    base_salary_str = request.form.get("base_salary", "").strip()
    base_salary_val = None
    if base_salary_str:
        try:
            base_salary_val = float(base_salary_str)
        except Exception:
            pass

    if not emp_code or not name:
        return jsonify({"error": "Vui lòng nhập Mã nhân viên và Họ tên."}), 400

    existing = database.get_employee_by_code(emp_code)
    if existing and existing["id"] != emp_id:
        return jsonify({"error": f"Mã nhân viên '{emp_code}' đã bị trùng."}), 400

    avatar_filename = None
    emb_filename = None

    upload_file = request.files.get("file") or request.files.get("avatar")
    if upload_file and upload_file.filename != "":
        try:
            img = Image.open(io.BytesIO(upload_file.read())).convert("RGB")
        except Exception:
            return jsonify({"error": "Không thể xử lý ảnh mới."}), 400

        embedding = extract_embedding(img)
        if embedding is None:
            return jsonify({"error": "Không phát hiện khuôn mặt trong ảnh mới."}), 422

        timestamp_prefix = datetime.now().strftime("%Y%m%d%H%M%S")
        avatar_filename = f"{emp_code}_{timestamp_prefix}.jpg"
        avatar_path = database.AVATAR_DIR / avatar_filename
        img.save(str(avatar_path), quality=92)

        emb_filename = f"{emp_code}_{timestamp_prefix}.npy"
        emb_path = database.EMBEDDING_DIR / emb_filename
        np.save(str(emb_path), embedding)
        database.add_face_embedding(emp_id, "front", emb_filename, avatar_filename)

    shift_id_str = request.form.get("shift_id")
    shift_id_val = int(shift_id_str) if shift_id_str and shift_id_str.isdigit() else None

    database.update_employee(
        emp_id=emp_id,
        emp_code=emp_code,
        name=name,
        department=department,
        position=position,
        avatar_file=avatar_filename,
        embedding_file=emb_filename,
        shift_id=shift_id_val,
        password=password if password else None,
        base_salary=base_salary_val,
    )

    reload_face_cache()
    return jsonify({"success": True, "message": f"Cập nhật thông tin nhân viên {name} thành công!"})


@app.route("/api/admin/employees/<int:emp_id>", methods=["DELETE"])
@admin_required
def api_delete_employee(emp_id):
    emp = database.get_employee_by_id(emp_id)
    if not emp:
        return jsonify({"error": "Không tìm thấy nhân viên."}), 404

    database.delete_employee(emp_id)
    reload_face_cache()
    return jsonify({"success": True, "message": f"Đã xóa nhân viên: {emp['name']} ({emp['emp_code']})"})


# ── ROUTES: QUẢN LÝ LỊCH CHẤM CÔNG (XEM, SỬA, THÊM, XÓA, XUẤT) ───────────────

@app.route("/api/admin/attendance", methods=["GET"])
@admin_required
def api_get_attendance():
    filter_type = request.args.get("filter_type", "day")
    emp_id = request.args.get("emp_id", "")
    date_val = request.args.get("date", "")
    start_date = request.args.get("start_date", "")
    end_date = request.args.get("end_date", "")

    if filter_type == "day" and not date_val:
        date_val = datetime.now().strftime("%Y-%m-%d")
    elif filter_type == "month" and not date_val:
        date_val = datetime.now().strftime("%Y-%m")

    logs = database.query_attendance(
        filter_type=filter_type,
        date_val=date_val,
        start_date=start_date,
        end_date=end_date,
        emp_id=emp_id,
    )
    return jsonify({"logs": logs, "count": len(logs)})


@app.route("/api/admin/attendance", methods=["POST"])
@admin_required
def api_add_manual_attendance():
    data = request.get_json(silent=True) or request.form
    emp_id = data.get("emp_id")
    date_str = data.get("date", datetime.now().strftime("%Y-%m-%d")).strip()
    time_str = data.get("time", datetime.now().strftime("%H:%M:%S")).strip()
    check_type = data.get("check_type", "Vào ca").strip()
    status = data.get("status", "Đúng giờ").strip()
    note = data.get("note", "Bổ sung thủ công").strip()
    location = data.get("location", "Admin bổ sung").strip()

    if not emp_id:
        return jsonify({"error": "Vui lòng chọn nhân viên."}), 400

    try:
        new_id = database.add_manual_attendance(
            emp_id=int(emp_id),
            date_str=date_str,
            time_str=time_str,
            check_type=check_type,
            status=status,
            note=note,
            location=location,
        )
        return jsonify({"success": True, "message": "Đã thêm lượt chấm công mới.", "id": new_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/admin/attendance/<int:log_id>", methods=["PUT", "POST"])
@admin_required
def api_update_attendance_log(log_id):
    data = request.get_json(silent=True) or request.form
    check_type = data.get("check_type", "Vào ca").strip()
    status = data.get("status", "Đúng giờ").strip()
    note = data.get("note", "").strip()
    date_val = data.get("date")
    time_val = data.get("time")
    check_out_time = data.get("check_out_time")

    database.update_attendance_log(
        log_id=log_id,
        check_type=check_type,
        status=status,
        note=note,
        time_val=time_val,
        date_val=date_val,
        check_out_time=check_out_time,
    )
    return jsonify({"success": True, "message": "Cập nhật lượt chấm công thành công."})


@app.route("/api/admin/attendance/<int:log_id>", methods=["DELETE"])
@admin_required
def api_delete_attendance_log(log_id):
    database.delete_attendance_log(log_id)
    return jsonify({"success": True, "message": "Đã xóa bản ghi chấm công."})


@app.route("/api/admin/attendance/export", methods=["GET"])
@admin_required
def api_export_attendance():
    filter_type = request.args.get("filter_type", "day")
    emp_id = request.args.get("emp_id", "")
    date_val = request.args.get("date", "")
    start_date = request.args.get("start_date", "")
    end_date = request.args.get("end_date", "")

    logs = database.query_attendance(
        filter_type=filter_type,
        date_val=date_val,
        start_date=start_date,
        end_date=end_date,
        emp_id=emp_id,
    )

    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.writer(output)
    writer.writerow([
        "ID",
        "Mã Nhân Viên",
        "Họ và Tên",
        "Phòng Ban",
        "Chức Vụ",
        "Ngày",
        "Giờ Vào (Check-in)",
        "Giờ Ra (Check-out)",
        "Số Giờ Làm",
        "Ca Làm Việc",
        "Vị Trí Chấm Công",
        "Độ Tương Đồng (%)",
        "Trạng Thái",
        "Ghi Chú",
    ])

    for row in logs:
        sim_pct = f"{round(row.get('similarity', 0) * 100, 1)}%" if row.get("similarity") else "-"
        writer.writerow([
            row["id"],
            row["emp_code"],
            row["emp_name"],
            row.get("department", ""),
            row.get("position", ""),
            row["date"],
            row["time"],
            row.get("check_out_time") or "-",
            row.get("work_hours") or 0,
            row.get("shift_name") or "-",
            row.get("location") or "-",
            sim_pct,
            row["status"],
            row["note"],
        ])

    mem = io.BytesIO()
    mem.write(output.getvalue().encode("utf-8-sig"))
    mem.seek(0)

    filename = f"bang_cham_cong_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return send_file(
        mem,
        mimetype="text/csv",
        as_attachment=True,
        download_name=filename,
    )


# ── ROUTES: QUẢN LÝ CA LÀM VIỆC (B1) ────────────────────────────────────────

@app.route("/api/admin/shifts", methods=["GET"])
@admin_required
def api_get_shifts():
    return jsonify({"shifts": database.get_all_shifts()})


@app.route("/api/admin/shifts", methods=["POST"])
@admin_required
def api_add_shift():
    data = request.get_json(silent=True) or request.form
    shift_name = data.get("shift_name", "").strip()
    start_time = data.get("start_time", "").strip()
    end_time = data.get("end_time", "").strip()
    grace_minutes = int(data.get("grace_minutes", 15))
    description = data.get("description", "").strip()
    if not shift_name or not start_time or not end_time:
        return jsonify({"error": "Vui lòng điền đủ tên ca, giờ bắt đầu và giờ kết thúc."}), 400
    new_id = database.add_shift(shift_name, start_time, end_time, grace_minutes, description)
    return jsonify({"success": True, "message": f"Đã thêm ca '{shift_name}'.", "id": new_id})


@app.route("/api/admin/shifts/<int:shift_id>", methods=["PUT", "POST"])
@admin_required
def api_update_shift(shift_id):
    data = request.get_json(silent=True) or request.form
    database.update_shift(
        shift_id,
        data.get("shift_name", "").strip(),
        data.get("start_time", "").strip(),
        data.get("end_time", "").strip(),
        int(data.get("grace_minutes", 15)),
        data.get("description", "").strip(),
    )
    return jsonify({"success": True, "message": "Đã cập nhật ca làm việc."})


@app.route("/api/admin/shifts/<int:shift_id>", methods=["DELETE"])
@admin_required
def api_delete_shift(shift_id):
    database.delete_shift(shift_id)
    return jsonify({"success": True, "message": "Đã xóa ca làm việc."})


@app.route("/api/admin/employee-shifts", methods=["GET"])
@admin_required
def api_get_employee_shifts():
    return jsonify({"assignments": database.get_all_employee_shifts()})


@app.route("/api/admin/employee-shifts", methods=["POST"])
@admin_required
def api_assign_shift():
    data = request.get_json(silent=True) or request.form
    emp_id = data.get("emp_id")
    shift_id = data.get("shift_id")
    effective_date = data.get("effective_date", datetime.now().strftime("%Y-%m-%d")).strip()
    end_date = data.get("end_date", None)
    if not emp_id or not shift_id:
        return jsonify({"error": "Vui lòng chọn nhân viên và ca làm việc."}), 400
    new_id = database.assign_shift(int(emp_id), int(shift_id), effective_date, end_date or None)
    return jsonify({"success": True, "message": "Đã gán ca cho nhân viên.", "id": new_id})


@app.route("/api/admin/employee-shifts/<int:assignment_id>", methods=["DELETE"])
@admin_required
def api_delete_employee_shift(assignment_id):
    database.delete_employee_shift(assignment_id)
    return jsonify({"success": True, "message": "Đã xóa lịch gán ca."})


# ── ROUTES: THÊM NHIỀU EMBEDDING (B2) ─────────────────────────────────────────

@app.route("/api/admin/employees/<int:emp_id>/embeddings", methods=["GET"])
@admin_required
def api_get_embeddings(emp_id):
    embs = database.get_face_embeddings_by_emp(emp_id)
    return jsonify({"embeddings": embs, "count": len(embs)})


@app.route("/api/admin/employees/<int:emp_id>/embeddings", methods=["POST"])
@admin_required
def api_add_embedding(emp_id):
    emp = database.get_employee_by_id(emp_id)
    if not emp:
        return jsonify({"error": "Không tìm thấy nhân viên."}), 404

    angle = request.form.get("angle", "front").strip()
    if angle not in ("front", "left", "right", "up", "down"):
        angle = "front"

    if "file" not in request.files or request.files["file"].filename == "":
        return jsonify({"error": "Vui lòng gửi ảnh khuôn mặt."}), 400

    file = request.files["file"]
    try:
        img = Image.open(io.BytesIO(file.read())).convert("RGB")
    except Exception:
        return jsonify({"error": "Không thể đọc ảnh."}), 400

    embedding = extract_embedding(img)
    if embedding is None:
        return jsonify({"error": "Không phát hiện khuôn mặt trong ảnh."}), 422

    timestamp_prefix = datetime.now().strftime("%Y%m%d%H%M%S")
    emb_filename = f"{emp['emp_code']}_{angle}_{timestamp_prefix}.npy"
    emb_path = database.EMBEDDING_DIR / emb_filename
    np.save(str(emb_path), embedding)

    img_filename = f"{emp['emp_code']}_{angle}_{timestamp_prefix}.jpg"
    img.save(str(database.AVATAR_DIR / img_filename), quality=92)

    new_id = database.add_face_embedding(emp_id, angle, emb_filename, img_filename)
    reload_face_cache()
    return jsonify({
        "success": True,
        "message": f"Đã thêm embedding góc '{angle}' cho {emp['name']}.",
        "embed_id": new_id,
    })


@app.route("/api/admin/employees/<int:emp_id>/embeddings/<int:embed_id>", methods=["DELETE"])
@admin_required
def api_delete_embedding(emp_id, embed_id):
    database.delete_face_embedding(embed_id)
    reload_face_cache()
    return jsonify({"success": True, "message": "Đã xóa embedding."})


# ── ROUTES: NGHỈ PHÉP (BẮT BUỘC TRƯỚC >= 3 NGÀY & QUÉT MẶT XÁC THỰC) ──────────

@app.route("/api/leave-requests", methods=["GET"])
def api_kiosk_get_leave_by_empcode():
    """Nhân viên xem danh sách đơn nghỉ phép của chính mình."""
    emp_id = session.get("emp_id")
    if emp_id:
        reqs = database.get_leave_requests_by_emp(emp_id)
        return jsonify({"requests": reqs})

    emp_code = request.args.get("emp_code", "").strip().upper()
    if not emp_code:
        return jsonify({"error": "Vui lòng đăng nhập hoặc nhập mã nhân viên."}), 400
    emp = database.get_employee_by_code(emp_code)
    if not emp:
        return jsonify({"error": "Không tìm thấy nhân viên."}), 404
    reqs = database.get_leave_requests_by_emp(emp["id"])
    return jsonify({"requests": reqs})


@app.route("/api/leave-requests", methods=["POST"])
def api_submit_leave_request():
    """
    Nhân viên nộp đơn xin nghỉ phép:
      1. Bắt buộc ngày nộp đơn phải trước ngày nghỉ ít nhất 3 ngày (leave_date - today >= 3).
      2. Bắt buộc quét mặt xác thực sinh trắc học (Liveness + khớp khuôn mặt nhân viên đang đăng nhập).
    """
    data = request.form if request.files else (request.get_json(silent=True) or request.form)
    logged_emp_id = session.get("emp_id")

    if logged_emp_id:
        emp = database.get_employee_by_id(logged_emp_id)
    else:
        emp_code = data.get("emp_code", "").strip().upper()
        emp = database.get_employee_by_code(emp_code) if emp_code else None

    if not emp:
        return jsonify({"error": "Vui lòng đăng nhập tài khoản nhân viên trước khi gửi đơn."}), 401

    leave_type = data.get("leave_type", "Nghỉ phép năm").strip()
    leave_date = data.get("leave_date", "").strip()
    end_leave_date = data.get("end_leave_date", "").strip() or leave_date
    reason = data.get("reason", "").strip()

    if not leave_date or not reason:
        return jsonify({"error": "Vui lòng chọn ngày nghỉ và nhập lý do xin nghỉ phép."}), 400

    # Ràng buộc 1: Kiểm tra ngày nộp đơn phải trước ngày nghỉ ít nhất 3 ngày
    is_valid_date, delta_days, date_err_msg = database.validate_leave_advance_days(leave_date, min_days=3)
    if not is_valid_date:
        return jsonify({"error": date_err_msg}), 400

    # Tính số ngày xin nghỉ
    days_count = 1
    try:
        d_start = datetime.strptime(leave_date[:10], "%Y-%m-%d")
        d_end = datetime.strptime(end_leave_date[:10], "%Y-%m-%d")
        if d_end < d_start:
            end_leave_date = leave_date
            days_count = 1
        else:
            days_count = (d_end - d_start).days + 1
    except Exception:
        days_count = 1

    # Ràng buộc 2: Bắt buộc Quét mặt xác thực khi nộp đơn
    if "file" not in request.files or request.files["file"].filename == "":
        return jsonify({
            "error": "Bắt buộc phải quét khuôn mặt xác thực trực tiếp qua Camera để gửi đơn xin nghỉ phép!"
        }), 400

    face_file = request.files["file"]
    try:
        img = Image.open(io.BytesIO(face_file.read())).convert("RGB")
    except Exception:
        return jsonify({"error": "Không thể xử lý ảnh xác thực khuôn mặt."}), 400

    boxes, probs, landmarks = mtcnn.detect(img, landmarks=True)
    if boxes is None or len(boxes) == 0:
        return jsonify({"error": "Không phát hiện thấy khuôn mặt trong khung hình. Vui lòng nhìn rõ vào camera."}), 422

    best_box = boxes[0]
    best_lm = landmarks[0] if landmarks is not None and len(landmarks) > 0 else None

    if ENABLE_LIVENESS_CHECK:
        liveness_res = liveness_detector.check_liveness(img, best_box, best_lm)
        if not liveness_res["is_live"]:
            return jsonify({"error": f"Xác thực thất bại: {liveness_res['message']}"}), 422

    w_img, h_img = img.size
    box_coords = [int(v) for v in best_box]
    x1, y1 = max(0, box_coords[0]), max(0, box_coords[1])
    x2, y2 = min(w_img, box_coords[2]), min(h_img, box_coords[3])
    face_crop = img.crop((x1, y1, x2, y2)) if (x2 - x1) >= 20 and (y2 - y1) >= 20 else img

    query_emb = extract_embedding_from_crop(face_crop)
    if query_emb is None:
        return jsonify({"error": "Không thể trích xuất vector khuôn mặt."}), 422

    emp_id = emp["id"]
    if emp_id not in face_cache or not face_cache[emp_id]["embeddings"]:
        return jsonify({"error": "Tài khoản chưa có dữ liệu vector khuôn mặt."}), 422

    best_sim = max(cosine_similarity(query_emb, vec) for vec in face_cache[emp_id]["embeddings"])
    if best_sim < SIMILARITY_THRESHOLD:
        return jsonify({
            "error": f"Khuôn mặt quét không khớp với nhân viên {emp['name']} (độ tương đồng {round(max(0.0, best_sim) * 100, 1)}% < {int(SIMILARITY_THRESHOLD * 100)}%). Không thể gửi đơn hộ!"
        }), 422

    new_id = database.add_leave_request(
        emp_id=emp["id"],
        emp_code=emp["emp_code"],
        emp_name=emp["name"],
        leave_type=leave_type,
        leave_date=leave_date,
        reason=reason,
        end_leave_date=end_leave_date,
        days_count=days_count,
        face_verified=1,
        face_similarity=round(best_sim, 4),
    )
    return jsonify({
        "success": True,
        "similarity_pct": round(best_sim * 100, 1),
        "message": (
            f"✓ Xác thực khuôn mặt thành công ({round(best_sim * 100, 1)}%)! "
            f"Đã gửi đơn {leave_type} cho ngày {leave_date} (nộp trước {delta_days} ngày)."
        ),
        "request_id": new_id,
    })


@app.route("/api/admin/leave-requests", methods=["GET"])
@admin_required
def api_admin_get_leave_requests():
    status_filter = request.args.get("status", None)
    reqs = database.get_all_leave_requests(status_filter)
    return jsonify({"requests": reqs, "count": len(reqs)})


@app.route("/api/admin/leave-requests/<int:request_id>/review", methods=["POST"])
@admin_required
def api_review_leave_request(request_id):
    data = request.get_json(silent=True) or request.form
    action = data.get("action", "").lower()
    note = data.get("note", "").strip()
    if action not in ("approve", "reject"):
        return jsonify({"error": "Hành động không hợp lệ. Dùng 'approve' hoặc 'reject'."}), 400
    approved = action == "approve"
    database.review_leave_request(request_id, session["admin_id"], approved, note)
    msg = "Đã phê duyệt đơn nghỉ phép." if approved else "Đã từ chối đơn nghỉ phép."
    return jsonify({"success": True, "message": msg})


# ── ROUTES: BÁO CÁO ĐĂNG NHẬP & BẢNG LƯƠNG CÔNG TY (CHO QUẢN LÝ) ──────────────

@app.route("/api/admin/login-logs", methods=["GET"])
@admin_required
def api_admin_get_login_logs():
    user_type = request.args.get("user_type", "all")
    date_val = request.args.get("date", "").strip()
    limit = int(request.args.get("limit", 200))
    logs = database.get_login_logs(limit=limit, user_type=user_type, date_val=date_val or None)
    return jsonify({"logs": logs, "count": len(logs)})


@app.route("/api/admin/payroll", methods=["GET"])
@admin_required
def api_admin_get_payroll():
    month_str = request.args.get("month", datetime.now().strftime("%Y-%m")).strip()
    payroll_list = database.calculate_payroll(month_str=month_str)
    return jsonify({"payroll": payroll_list, "month": month_str, "count": len(payroll_list)})


# ── ROUTES: THỐNG KÊ (B1, B3) ─────────────────────────────────────────────────

@app.route("/api/admin/statistics", methods=["GET"])
@admin_required
def api_get_statistics():
    filter_type = request.args.get("filter_type", "day")
    date_val = request.args.get("date", "")
    start_date = request.args.get("start_date", "")
    end_date = request.args.get("end_date", "")
    department = request.args.get("department", "")

    if filter_type == "day" and not date_val:
        date_val = datetime.now().strftime("%Y-%m-%d")
    elif filter_type == "month" and not date_val:
        date_val = datetime.now().strftime("%Y-%m")

    stats = database.get_statistics(
        filter_type=filter_type,
        date_val=date_val or None,
        start_date=start_date or None,
        end_date=end_date or None,
        department=department or None,
    )
    return jsonify(stats)


@app.route("/api/status", methods=["GET"])
def api_status():
    employees = database.get_all_employees()
    return jsonify({
        "status": "online",
        "device": DEVICE,
        "model": ACTIVE_MODEL_PATH.name,
        "registered_persons": len(employees),
        "threshold_pct": int(SIMILARITY_THRESHOLD * 100),
        "cuda_available": torch.cuda.is_available(),
    })


if __name__ == "__main__":
    print("\n" + "=" * 62)
    print("  🚀 Website Chấm Công & Quản Trị Nhân Sự FaceID")
    print(f"  Model  : {ACTIVE_MODEL_PATH.name}")
    print(f"  Device : {DEVICE}")
    print(f"  Ngưỡng : {int(SIMILARITY_THRESHOLD * 100)}% (Similarity > 0.60)")
    print("  Login  : http://localhost:5000/login (NV: Mã NV / 123456 | Admin: admin / admin123)")
    print("  Portal : http://localhost:5000/ (Cổng Nhân Viên)")
    print("  Admin  : http://localhost:5000/admin (Cổng Quản Trị)")
    print("=" * 62 + "\n")
    app.run(debug=False, host="0.0.0.0", port=5000)
