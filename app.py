"""
Flask backend cho Hệ thống Chấm công & Quản lý Nhân viên bằng Nhận diện Khuôn mặt FaceID.
Tích hợp ArcFace IR-SE50 + MTCNN và SQLite Database.

Gồm 2 khu vực chính:
  1. Trang Live Kiosk (/): Camera chạy liên tục, khi độ tương đồng > 60% hiển thị Tên và Mã nhân viên, tự động chấm công.
  2. Trang Quản lý (/admin): Đăng nhập bảo mật, Thêm/Sửa/Xóa nhân viên, Xem/Sửa/In/Xuất lịch chấm công theo Ngày/Tuần/Tháng.
"""
import csv
import io
import os
import sys
import time
from datetime import datetime
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
ATTENDANCE_COOLDOWN_SEC = 25  # Tránh ghi log trùng lặp liên tục trong vòng 25s

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = "faceid_secure_system_key_2026_rf92"
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB

# Khởi tạo cơ sở dữ liệu
database.init_db()

# ── Khởi tạo module chống giả mạo khuôn mặt (Face Anti-Spoofing / Liveness) ──
from src.utils.liveness import liveness_detector
ENABLE_LIVENESS_CHECK = True  # Mặc định bật để bảo vệ hệ thống khỏi gian lận ảnh tĩnh/màn hình


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
face_cache = {}  # {emp_id: {"emp": dict, "embedding": np.ndarray}}
last_attendance_time = {}  # {emp_id: float_timestamp}


def reload_face_cache():
    global face_cache
    new_cache = {}
    employees = database.get_all_employees()
    for emp in employees:
        emb_file = emp.get("embedding_file")
        if emb_file:
            npy_path = database.EMBEDDING_DIR / emb_file
            if npy_path.exists():
                try:
                    new_cache[emp["id"]] = {
                        "emp": emp,
                        "embedding": np.load(str(npy_path)),
                    }
                except Exception as e:
                    print(f"Lỗi nạp embedding {emb_file}: {e}")
    face_cache = new_cache
    print(f"✓ Đã đồng bộ cache khuôn mặt: {len(face_cache)} nhân viên")


reload_face_cache()


# ── Hàm tiện ích xử lý ảnh ───────────────────────────────────────────────────
def extract_embedding(pil_img: Image.Image):
    """Trích xuất 512-d ArcFace embedding từ ảnh PIL."""
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


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_id"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "Vui lòng đăng nhập với quyền quản lý."}), 401
            return redirect(url_for("admin_login_page"))
        return f(*args, **kwargs)
    return decorated


# ── ROUTES: TRANG GIAO DIỆN ──────────────────────────────────────────────────

@app.route("/")
def kiosk_page():
    """Trang Live Cam Chấm công / Kiosk nhận dạng liên tục."""
    return render_template(
        "kiosk.html",
        model_name=ACTIVE_MODEL_PATH.name,
        device=DEVICE,
        threshold_pct=int(SIMILARITY_THRESHOLD * 100),
    )


@app.route("/admin/login")
def admin_login_page():
    """Trang đăng nhập dành riêng cho Quản lý."""
    if session.get("admin_id"):
        return redirect(url_for("admin_dashboard_page"))
    return render_template("admin_login.html")


@app.route("/admin")
@app.route("/admin/dashboard")
@admin_required
def admin_dashboard_page():
    """Trang Quản lý: Nhân viên, Lịch chấm công, Thống kê."""
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


# ── ROUTES: XÁC THỰC ADMIN ───────────────────────────────────────────────────

@app.route("/api/admin/login", methods=["POST"])
def api_admin_login():
    data = request.get_json(silent=True) or request.form
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()

    if not username or not password:
        return jsonify({"error": "Vui lòng nhập đầy đủ tên đăng nhập và mật khẩu."}), 400

    admin = database.verify_admin(username, password)
    if not admin:
        return jsonify({"error": "Sai tên đăng nhập hoặc mật khẩu quản trị."}), 401

    session["admin_id"] = admin["id"]
    session["admin_name"] = admin["full_name"]
    session["admin_user"] = admin["username"]

    return jsonify({
        "success": True,
        "message": f"Chào mừng {admin['full_name']}!",
        "redirect": "/admin",
    })


@app.route("/api/admin/logout", methods=["POST", "GET"])
def api_admin_logout():
    session.clear()
    return redirect(url_for("admin_login_page"))


@app.route("/api/admin/me", methods=["GET"])
def api_admin_me():
    if not session.get("admin_id"):
        return jsonify({"logged_in": False})
    return jsonify({
        "logged_in": True,
        "admin_id": session.get("admin_id"),
        "admin_name": session.get("admin_name"),
    })


# ── ROUTES: NHẬN DIỆN LIÊN TỤC & CHẤM CÔNG (KIOSK) ────────────────────────────

@app.route("/api/attendance/recognize", methods=["POST"])
def api_attendance_recognize():
    """
    Nhận dạng khuôn mặt từ live camera feed.
    Quy trình kiểm tra 2 lớp:
      Lớp 1: Anti-Spoofing / Liveness Detection (Chống gian lận ảnh in / màn hình điện thoại).
      Lớp 2: Trích xuất ArcFace embedding và so khớp Cosine Similarity (> 60%).
    """
    global ENABLE_LIVENESS_CHECK

    if "file" not in request.files or request.files["file"].filename == "":
        return jsonify({"error": "Không nhận được frame ảnh từ camera."}), 400

    file = request.files["file"]
    try:
        img = Image.open(io.BytesIO(file.read())).convert("RGB")
    except Exception:
        return jsonify({"error": "Lỗi định dạng ảnh gửi lên."}), 400

    # ── Phát hiện khuôn mặt và điểm mốc (Face Detection & Alignment) ─────────
    boxes, probs, landmarks = mtcnn.detect(img, landmarks=True)
    if boxes is None or len(boxes) == 0:
        return jsonify({"matched": False, "message": "Không tìm thấy khuôn mặt rõ ràng."}), 200

    best_box = boxes[0]
    best_lm = landmarks[0] if landmarks is not None and len(landmarks) > 0 else None

    # ── Lớp 1: Kiểm tra Khuôn mặt sống (Face Anti-Spoofing / Liveness) ────────
    liveness_pct = 100.0
    if ENABLE_LIVENESS_CHECK:
        liveness_res = liveness_detector.check_liveness(img, best_box, best_lm)
        liveness_pct = liveness_res["liveness_pct"]

        if not liveness_res["is_live"]:
            return jsonify({
                "matched": False,
                "is_spoof": True,
                "liveness_pct": liveness_pct,
                "message": liveness_res["message"],
                "details": liveness_res.get("details", {}),
            }), 200

    # ── Lớp 2: Trích xuất vector đặc trưng ArcFace 512-d ─────────────────────
    query_emb = extract_embedding(img)
    if query_emb is None:
        return jsonify({"matched": False, "message": "Không thể trích xuất đặc trưng khuôn mặt."}), 200

    if not face_cache:
        return jsonify({
            "matched": False,
            "message": "Hệ thống chưa có nhân viên nào được đăng ký.",
        }), 200

    best_emp = None
    best_sim = -1.0

    for emp_id, data in face_cache.items():
        sim = cosine_similarity(query_emb, data["embedding"])
        if sim > best_sim:
            best_sim = sim
            best_emp = data["emp"]

    now_ts = time.time()
    now_dt = datetime.now()

    # Điều kiện nhận dạng theo yêu cầu: > 60%
    is_matched = best_sim >= SIMILARITY_THRESHOLD and best_emp is not None

    if is_matched:
        emp_id = best_emp["id"]
        last_time = last_attendance_time.get(emp_id, 0)
        cooldown_rem = max(0, int(ATTENDANCE_COOLDOWN_SEC - (now_ts - last_time)))

        logged = False
        log_data = None
        if cooldown_rem == 0:
            # Ghi nhận chấm công
            log_data = database.log_attendance(
                emp_id=best_emp["id"],
                emp_code=best_emp["emp_code"],
                emp_name=best_emp["name"],
                similarity=round(best_sim, 4),
                check_type="Điểm danh",
                status="Hợp lệ",
                note=f"Live Cam (Liveness: {liveness_pct}%)",
            )
            last_attendance_time[emp_id] = now_ts
            logged = True

        return jsonify({
            "matched": True,
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
            "logged": logged,
            "cooldown_remaining": cooldown_rem,
            "log": log_data,
        })
    else:
        return jsonify({
            "matched": False,
            "similarity": round(max(0.0, best_sim), 4),
            "similarity_pct": round(max(0.0, best_sim) * 100, 1),
            "threshold_pct": int(SIMILARITY_THRESHOLD * 100),
            "liveness_pct": liveness_pct,
            "is_live": True,
            "message": f"Chưa đạt ngưỡng {int(SIMILARITY_THRESHOLD * 100)}%",
        })


@app.route("/api/config/liveness", methods=["GET", "POST"])
def api_toggle_liveness():
    """Lấy hoặc chuyển đổi trạng thái Anti-Spoofing / Liveness Detection."""
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
    """Lấy danh sách 10 lượt chấm công gần nhất để hiển thị Live Feed."""
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

    if not emp_code or not name:
        return jsonify({"error": "Vui lòng nhập Mã nhân viên và Họ tên."}), 400

    # Kiểm tra mã NV đã tồn tại chưa
    if database.get_employee_by_code(emp_code):
        return jsonify({"error": f"Mã nhân viên '{emp_code}' đã tồn tại trong hệ thống."}), 400

    if "file" not in request.files or request.files["file"].filename == "":
        return jsonify({"error": "Vui lòng tải lên hoặc chụp ảnh khuôn mặt."}), 400

    file = request.files["file"]
    try:
        img = Image.open(io.BytesIO(file.read())).convert("RGB")
    except Exception:
        return jsonify({"error": "Không thể xử lý định dạng file ảnh."}), 400

    embedding = extract_embedding(img)
    if embedding is None:
        return jsonify({"error": "Không phát hiện khuôn mặt hợp lệ trong ảnh. Vui lòng chọn ảnh rõ nét hơn."}), 422

    # Lưu ảnh đại diện
    timestamp_prefix = datetime.now().strftime("%Y%m%d%H%M%S")
    avatar_filename = f"{emp_code}_{timestamp_prefix}.jpg"
    avatar_path = database.AVATAR_DIR / avatar_filename
    img.save(str(avatar_path), quality=92)

    # Lưu vector đặc trưng embedding (.npy)
    emb_filename = f"{emp_code}_{timestamp_prefix}.npy"
    emb_path = database.EMBEDDING_DIR / emb_filename
    np.save(str(emb_path), embedding)

    new_id = database.add_employee(
        emp_code=emp_code,
        name=name,
        department=department,
        position=position,
        avatar_file=avatar_filename,
        embedding_file=emb_filename,
    )

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

    if not emp_code or not name:
        return jsonify({"error": "Vui lòng nhập Mã nhân viên và Họ tên."}), 400

    # Nếu đổi mã NV, kiểm tra xem trùng người khác không
    existing = database.get_employee_by_code(emp_code)
    if existing and existing["id"] != emp_id:
        return jsonify({"error": f"Mã nhân viên '{emp_code}' đã bị trùng."}), 400

    avatar_filename = None
    emb_filename = None

    # Nếu có ảnh mới được gửi kèm
    if "file" in request.files and request.files["file"].filename != "":
        file = request.files["file"]
        try:
            img = Image.open(io.BytesIO(file.read())).convert("RGB")
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

        # Xóa file npy và avatar cũ
        if emp.get("avatar_file"):
            old_av = database.AVATAR_DIR / emp["avatar_file"]
            if old_av.exists():
                try:
                    old_av.unlink()
                except Exception:
                    pass
        if emp.get("embedding_file"):
            old_emb = database.EMBEDDING_DIR / emp["embedding_file"]
            if old_emb.exists():
                try:
                    old_emb.unlink()
                except Exception:
                    pass

    database.update_employee(
        emp_id=emp_id,
        emp_code=emp_code,
        name=name,
        department=department,
        position=position,
        avatar_file=avatar_filename,
        embedding_file=emb_filename,
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
    """
    Lấy danh sách chấm công lọc theo:
      - filter_type: 'day', 'week', 'month', 'all'
      - date: YYYY-MM-DD
      - month: YYYY-MM
      - start_date, end_date (cho tuần)
      - emp_id: nhân viên cụ thể
    """
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
    check_type = data.get("check_type", "Điểm danh").strip()
    status = data.get("status", "Hợp lệ").strip()
    note = data.get("note", "Bổ sung thủ công").strip()

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
        )
        return jsonify({"success": True, "message": "Đã thêm lượt chấm công mới.", "id": new_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/admin/attendance/<int:log_id>", methods=["PUT", "POST"])
@admin_required
def api_update_attendance_log(log_id):
    data = request.get_json(silent=True) or request.form
    check_type = data.get("check_type", "Điểm danh").strip()
    status = data.get("status", "Hợp lệ").strip()
    note = data.get("note", "").strip()
    date_val = data.get("date")
    time_val = data.get("time")

    database.update_attendance_log(
        log_id=log_id,
        check_type=check_type,
        status=status,
        note=note,
        time_val=time_val,
        date_val=date_val,
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
    """Xuất file CSV bảng chấm công kèm UTF-8 BOM cho Excel."""
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
    # Ghi BOM UTF-8 để Microsoft Excel mở tiếng Việt không bị lỗi font
    output.write("\ufeff")
    writer = csv.writer(output)
    writer.writerow([
        "ID",
        "Mã Nhân Viên",
        "Họ và Tên",
        "Phòng Ban",
        "Chức Vụ",
        "Ngày",
        "Giờ",
        "Loại",
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
            row["check_type"],
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


# ── API TRẠNG THÁI HỆ THỐNG ──────────────────────────────────────────────────

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
    print("\n" + "=" * 55)
    print("  🚀 FaceID Chấm Công & Quản Lý Nhân Viên")
    print(f"  Model  : {ACTIVE_MODEL_PATH.name}")
    print(f"  Device : {DEVICE}")
    print(f"  Ngưỡng : {int(SIMILARITY_THRESHOLD * 100)}% (Similarity > 0.60)")
    print("  Kiosk  : http://localhost:5000 (Trang Live Cam Chấm Công)")
    print("  Admin  : http://localhost:5000/admin (Tài khoản: admin / admin123)")
    print("=" * 55 + "\n")
    app.run(debug=False, host="0.0.0.0", port=5000)
