"""
Database module cho hệ thống chấm công và quản lý nhân viên FaceID.
Sử dụng SQLite tích hợp sẵn trong Python.

Phiên bản 3 (Website Chấm công & Quản trị Nhân sự toàn diện):
  - Đăng nhập phân quyền: Nhân viên (emp_code + password) & Quản trị viên (username + password)
  - Bảng login_logs: Báo cáo lịch sử đăng nhập hệ thống
  - Bảng shifts + employee_shifts: Cấu hình ca linh hoạt, gán ca cho từng nhân viên
  - Bảng face_embeddings: Lưu 3-5 vector embedding đa góc cho mỗi nhân viên
  - Bảng attendance_logs: Ghi nhận Check-in, Check-out, Vị trí GPS, Ca làm việc, Số giờ làm, Trạng thái
  - Bảng leave_requests: Đơn xin nghỉ phép (bắt buộc nộp trước >= 3 ngày & quét mặt xác thực)
  - Tính toán ngày công & Bảng lương theo tháng cho từng nhân viên và toàn công ty
"""
import os
import sqlite3
import calendar
from datetime import datetime, timedelta
from pathlib import Path
from werkzeug.security import generate_password_hash, check_password_hash

PROJECT_ROOT = Path(__file__).resolve().parent
DB_PATH = PROJECT_ROOT / "data" / "attendance.db"
AVATAR_DIR = PROJECT_ROOT / "data" / "avatars"
EMBEDDING_DIR = PROJECT_ROOT / "data" / "face_db"

AVATAR_DIR.mkdir(parents=True, exist_ok=True)
EMBEDDING_DIR.mkdir(parents=True, exist_ok=True)

STANDARD_WORK_DAYS = 26  # Số ngày công chuẩn trong tháng
LATE_PENALTY_VND = 50000  # Mức phạt mỗi lần đi trễ (VNĐ)


def get_db_connection():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    c = conn.cursor()

    # 1. Bảng Quản trị viên
    c.execute("""
        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            full_name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 2. Bảng Nhân viên
    c.execute("""
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            emp_code TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            department TEXT DEFAULT '',
            position TEXT DEFAULT '',
            avatar_file TEXT DEFAULT '',
            embedding_file TEXT NOT NULL,
            shift_id INTEGER DEFAULT 1,
            password_hash TEXT DEFAULT '',
            base_salary REAL DEFAULT 9000000,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 3. Bảng Nhật ký chấm công (Check-in & Check-out, Vị trí, Ca làm)
    c.execute("""
        CREATE TABLE IF NOT EXISTS attendance_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            emp_id INTEGER,
            emp_code TEXT NOT NULL,
            emp_name TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            date TEXT NOT NULL,
            time TEXT NOT NULL,
            check_out_time TEXT DEFAULT '',
            check_type TEXT DEFAULT 'Vào ca',
            similarity REAL DEFAULT 0.0,
            status TEXT DEFAULT 'Đúng giờ',
            shift_name TEXT DEFAULT '',
            location TEXT DEFAULT '',
            checkout_location TEXT DEFAULT '',
            work_hours REAL DEFAULT 0.0,
            note TEXT DEFAULT '',
            FOREIGN KEY (emp_id) REFERENCES employees (id) ON DELETE SET NULL
        )
    """)

    # 4. Bảng Ca làm việc
    c.execute("""
        CREATE TABLE IF NOT EXISTS shifts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shift_name TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            grace_minutes INTEGER DEFAULT 15,
            description TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 5. Bảng Gán ca cho nhân viên
    c.execute("""
        CREATE TABLE IF NOT EXISTS employee_shifts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            emp_id INTEGER NOT NULL,
            shift_id INTEGER NOT NULL,
            effective_date TEXT NOT NULL,
            end_date TEXT DEFAULT NULL,
            FOREIGN KEY (emp_id) REFERENCES employees (id) ON DELETE CASCADE,
            FOREIGN KEY (shift_id) REFERENCES shifts (id) ON DELETE CASCADE
        )
    """)

    # 6. Bảng Nhiều embedding góc mặt (3-5 vector / nhân viên)
    c.execute("""
        CREATE TABLE IF NOT EXISTS face_embeddings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            emp_id INTEGER NOT NULL,
            angle TEXT DEFAULT 'front',
            embedding_file TEXT NOT NULL,
            image_file TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (emp_id) REFERENCES employees (id) ON DELETE CASCADE
        )
    """)

    # 7. Bảng Đơn nghỉ phép (kèm xác thực khuôn mặt & kiểm tra trước >= 3 ngày)
    c.execute("""
        CREATE TABLE IF NOT EXISTS leave_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            emp_id INTEGER NOT NULL,
            emp_code TEXT NOT NULL,
            emp_name TEXT NOT NULL,
            leave_type TEXT DEFAULT 'Nghỉ phép năm',
            request_date TEXT NOT NULL,
            leave_date TEXT NOT NULL,
            end_leave_date TEXT DEFAULT '',
            days_count INTEGER DEFAULT 1,
            reason TEXT DEFAULT '',
            face_verified INTEGER DEFAULT 1,
            face_similarity REAL DEFAULT 0.0,
            status TEXT DEFAULT 'Chờ duyệt',
            reviewed_by INTEGER DEFAULT NULL,
            reviewed_at TIMESTAMP DEFAULT NULL,
            note TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (emp_id) REFERENCES employees (id) ON DELETE CASCADE,
            FOREIGN KEY (reviewed_by) REFERENCES admins (id) ON DELETE SET NULL
        )
    """)

    # 8. Bảng Báo cáo đăng nhập (Login Audit Logs)
    c.execute("""
        CREATE TABLE IF NOT EXISTS login_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_type TEXT NOT NULL,
            user_id INTEGER DEFAULT NULL,
            username TEXT NOT NULL,
            full_name TEXT NOT NULL,
            department TEXT DEFAULT '',
            ip_address TEXT DEFAULT '',
            user_agent TEXT DEFAULT '',
            status TEXT DEFAULT 'Thành công',
            login_time TEXT NOT NULL
        )
    """)

    # Tạo tài khoản admin mặc định nếu chưa có
    c.execute("SELECT id FROM admins WHERE username = 'admin'")
    if not c.fetchone():
        c.execute(
            "INSERT INTO admins (username, password_hash, full_name) VALUES (?, ?, ?)",
            ("admin", generate_password_hash("admin123"), "Quản Trị Viên"),
        )

    # Tạo ca mặc định nếu chưa có
    c.execute("SELECT id FROM shifts LIMIT 1")
    if not c.fetchone():
        c.executemany(
            "INSERT INTO shifts (shift_name, start_time, end_time, grace_minutes, description) VALUES (?, ?, ?, ?, ?)",
            [
                ("Ca Sáng", "08:00", "12:00", 15, "Ca làm việc buổi sáng"),
                ("Ca Chiều", "13:00", "17:00", 15, "Ca làm việc buổi chiều"),
                ("Ca Toàn Ngày", "08:00", "17:00", 15, "Ca hành chính toàn thời gian"),
            ],
        )

    # Migration an toàn cho CSDL hiện có
    migrations = [
        "ALTER TABLE employees ADD COLUMN shift_id INTEGER DEFAULT 1",
        "ALTER TABLE employees ADD COLUMN password_hash TEXT DEFAULT ''",
        "ALTER TABLE employees ADD COLUMN base_salary REAL DEFAULT 9000000",
        "ALTER TABLE face_embeddings ADD COLUMN image_file TEXT DEFAULT ''",
        "ALTER TABLE attendance_logs ADD COLUMN check_out_time TEXT DEFAULT ''",
        "ALTER TABLE attendance_logs ADD COLUMN shift_name TEXT DEFAULT ''",
        "ALTER TABLE attendance_logs ADD COLUMN location TEXT DEFAULT ''",
        "ALTER TABLE attendance_logs ADD COLUMN checkout_location TEXT DEFAULT ''",
        "ALTER TABLE attendance_logs ADD COLUMN work_hours REAL DEFAULT 0.0",
        "ALTER TABLE leave_requests ADD COLUMN end_leave_date TEXT DEFAULT ''",
        "ALTER TABLE leave_requests ADD COLUMN days_count INTEGER DEFAULT 1",
        "ALTER TABLE leave_requests ADD COLUMN face_verified INTEGER DEFAULT 1",
        "ALTER TABLE leave_requests ADD COLUMN face_similarity REAL DEFAULT 0.0",
    ]
    for sql in migrations:
        try:
            c.execute(sql)
        except Exception:
            pass

    # Cấp mật khẩu mặc định '123456' cho nhân viên cũ nếu chưa có password_hash
    default_emp_hash = generate_password_hash("123456")
    c.execute("UPDATE employees SET password_hash = ? WHERE password_hash IS NULL OR password_hash = ''", (default_emp_hash,))
    c.execute("UPDATE employees SET base_salary = 9000000 WHERE base_salary IS NULL OR base_salary <= 0")

    # Đồng bộ file .npy sẵn có (tương thích ngược)
    for npy_file in EMBEDDING_DIR.glob("*.npy"):
        c.execute("SELECT id FROM face_embeddings WHERE embedding_file = ?", (npy_file.name,))
        if c.fetchone():
            continue
        c.execute("SELECT id FROM employees WHERE embedding_file = ?", (npy_file.name,))
        if not c.fetchone():
            c.execute("SELECT MAX(id) FROM employees")
            max_id = c.fetchone()[0] or 0
            curr_num = max_id + 1
            code = f"NV{curr_num:03d}"
            while True:
                c.execute("SELECT id FROM employees WHERE emp_code = ?", (code,))
                if not c.fetchone():
                    break
                curr_num += 1
                code = f"NV{curr_num:03d}"

            c.execute(
                """INSERT INTO employees
                   (emp_code, name, department, position, embedding_file, password_hash, base_salary)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (code, npy_file.stem, "Phòng Kỹ Thuật", "Nhân viên", npy_file.name, default_emp_hash, 9000000),
            )
            eid = c.lastrowid
            c.execute(
                "INSERT INTO face_embeddings (emp_id, angle, embedding_file) VALUES (?, ?, ?)",
                (eid, "front", npy_file.name),
            )

    conn.commit()
    conn.close()


# ── Xác thực & Báo cáo Đăng nhập ──────────────────────────────────────────────
def verify_admin(username, password):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM admins WHERE username = ?", (username,))
    admin = c.fetchone()
    conn.close()
    if admin and check_password_hash(admin["password_hash"], password):
        return dict(admin)
    return None


def verify_employee(emp_code, password):
    """Xác thực đăng nhập cho Nhân viên bằng Mã nhân viên và Mật khẩu."""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""
        SELECT e.*, s.shift_name, s.start_time, s.end_time, s.grace_minutes
        FROM employees e
        LEFT JOIN shifts s ON e.shift_id = s.id
        WHERE UPPER(e.emp_code) = UPPER(?)
    """, (emp_code.strip(),))
    emp = c.fetchone()
    conn.close()
    if not emp:
        return None
    emp_dict = dict(emp)
    pw_hash = emp_dict.get("password_hash") or ""
    if pw_hash and check_password_hash(pw_hash, password):
        return emp_dict
    # Fallback nếu mật khẩu trùng mã NV hoặc '123456' khi chưa khởi tạo hash
    if not pw_hash and password in ("123456", emp_dict["emp_code"]):
        return emp_dict
    return None


def log_login_event(user_type, user_id, username, full_name, department="", ip_address="", user_agent="", status="Thành công"):
    """Ghi nhật ký đăng nhập của Nhân viên hoặc Quản trị viên."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""
        INSERT INTO login_logs
            (user_type, user_id, username, full_name, department, ip_address, user_agent, status, login_time)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (user_type, user_id, username, full_name, department, ip_address, user_agent[:250], status, now_str))
    new_id = c.lastrowid
    conn.commit()
    conn.close()
    return new_id


def get_login_logs(limit=200, user_type=None, date_val=None):
    """Lấy danh sách lịch sử đăng nhập cho Quản lý xem báo cáo."""
    conn = get_db_connection()
    c = conn.cursor()
    conditions, params = [], []
    if user_type and user_type != "all":
        conditions.append("user_type = ?")
        params.append(user_type)
    if date_val:
        conditions.append("login_time LIKE ?")
        params.append(f"{date_val}%")
    where_sql = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params.append(limit)
    c.execute(f"SELECT * FROM login_logs {where_sql} ORDER BY id DESC LIMIT ?", params)
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Quản lý Nhân viên ─────────────────────────────────────────────────────────
def get_all_employees():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""
        SELECT e.*, COUNT(fe.id) as angle_count, s.shift_name, s.start_time, s.end_time, s.grace_minutes
        FROM employees e
        LEFT JOIN face_embeddings fe ON e.id = fe.emp_id
        LEFT JOIN shifts s ON e.shift_id = s.id
        GROUP BY e.id
        ORDER BY e.id DESC
    """)
    rows = c.fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        d.pop("password_hash", None)
        result.append(d)
    return result


def get_employee_by_id(emp_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""
        SELECT e.*, s.shift_name, s.start_time, s.end_time, s.grace_minutes
        FROM employees e
        LEFT JOIN shifts s ON e.shift_id = s.id
        WHERE e.id = ?
    """, (emp_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d.pop("password_hash", None)
    return d


def get_employee_by_code(emp_code):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""
        SELECT e.*, s.shift_name, s.start_time, s.end_time, s.grace_minutes
        FROM employees e
        LEFT JOIN shifts s ON e.shift_id = s.id
        WHERE UPPER(e.emp_code) = UPPER(?)
    """, (emp_code,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d.pop("password_hash", None)
    return d


def add_employee(emp_code, name, department, position, avatar_file, embedding_file, shift_id=1, password=None, base_salary=9000000):
    conn = get_db_connection()
    c = conn.cursor()
    raw_pw = password.strip() if (password and password.strip()) else "123456"
    pw_hash = generate_password_hash(raw_pw)
    c.execute(
        """INSERT INTO employees
           (emp_code, name, department, position, avatar_file, embedding_file, shift_id, password_hash, base_salary)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (emp_code, name, department, position, avatar_file, embedding_file, shift_id, pw_hash, float(base_salary or 9000000)),
    )
    new_id = c.lastrowid
    c.execute(
        "INSERT INTO face_embeddings (emp_id, angle, embedding_file, image_file) VALUES (?, ?, ?, ?)",
        (new_id, "front", embedding_file, avatar_file),
    )
    conn.commit()
    conn.close()
    return new_id


def update_employee(emp_id, emp_code, name, department, position, avatar_file=None, embedding_file=None, shift_id=None, password=None, base_salary=None):
    conn = get_db_connection()
    c = conn.cursor()
    updates = ["emp_code = ?", "name = ?", "department = ?", "position = ?"]
    params = [emp_code, name, department, position]
    if avatar_file and embedding_file:
        updates.extend(["avatar_file = ?", "embedding_file = ?"])
        params.extend([avatar_file, embedding_file])
    if shift_id is not None:
        updates.append("shift_id = ?")
        params.append(shift_id)
    if password is not None and str(password).strip() != "":
        updates.append("password_hash = ?")
        params.append(generate_password_hash(str(password).strip()))
    if base_salary is not None:
        updates.append("base_salary = ?")
        params.append(float(base_salary))
    params.append(emp_id)
    set_sql = ", ".join(updates)
    c.execute(f"UPDATE employees SET {set_sql} WHERE id = ?", params)
    conn.commit()
    conn.close()


def delete_employee(emp_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT avatar_file, embedding_file FROM employees WHERE id = ?", (emp_id,))
    emp = c.fetchone()
    if emp:
        for field in ("embedding_file", "avatar_file"):
            f = emp[field]
            if f:
                p = (EMBEDDING_DIR if field == "embedding_file" else AVATAR_DIR) / f
                if p.exists():
                    try:
                        p.unlink()
                    except Exception:
                        pass
    c.execute("SELECT embedding_file, image_file FROM face_embeddings WHERE emp_id = ?", (emp_id,))
    for row in c.fetchall():
        p = EMBEDDING_DIR / row["embedding_file"]
        if p.exists():
            try:
                p.unlink()
            except Exception:
                pass
        if row["image_file"]:
            img_p = AVATAR_DIR / row["image_file"]
            if img_p.exists():
                try:
                    img_p.unlink()
                except Exception:
                    pass
    c.execute("DELETE FROM employees WHERE id = ?", (emp_id,))
    conn.commit()
    conn.close()


# ── Nhiều embedding (B2) ───────────────────────────────────────────────────────
def add_face_embedding(emp_id: int, angle: str, embedding_file: str, image_file: str = "") -> int:
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        "INSERT INTO face_embeddings (emp_id, angle, embedding_file, image_file) VALUES (?, ?, ?, ?)",
        (emp_id, angle, embedding_file, image_file),
    )
    new_id = c.lastrowid
    conn.commit()
    conn.close()
    return new_id


def get_face_embeddings_by_emp(emp_id: int):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM face_embeddings WHERE emp_id = ? ORDER BY id", (emp_id,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_face_embeddings():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""
        SELECT fe.*, e.emp_code, e.name, e.department, e.position, e.avatar_file
        FROM face_embeddings fe
        JOIN employees e ON fe.emp_id = e.id
        ORDER BY fe.emp_id, fe.id
    """)
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_face_embedding(embed_id: int):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT embedding_file FROM face_embeddings WHERE id = ?", (embed_id,))
    row = c.fetchone()
    if row:
        p = EMBEDDING_DIR / row["embedding_file"]
        if p.exists():
            try:
                p.unlink()
            except Exception:
                pass
    c.execute("DELETE FROM face_embeddings WHERE id = ?", (embed_id,))
    conn.commit()
    conn.close()


# ── Ca làm việc (B1) ──────────────────────────────────────────────────────────
def get_all_shifts():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM shifts ORDER BY start_time")
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_shift(shift_name, start_time, end_time, grace_minutes=15, description=""):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        "INSERT INTO shifts (shift_name, start_time, end_time, grace_minutes, description) VALUES (?, ?, ?, ?, ?)",
        (shift_name, start_time, end_time, grace_minutes, description),
    )
    new_id = c.lastrowid
    conn.commit()
    conn.close()
    return new_id


def update_shift(shift_id, shift_name, start_time, end_time, grace_minutes=15, description=""):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        "UPDATE shifts SET shift_name=?, start_time=?, end_time=?, grace_minutes=?, description=? WHERE id=?",
        (shift_name, start_time, end_time, grace_minutes, description, shift_id),
    )
    conn.commit()
    conn.close()


def delete_shift(shift_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("DELETE FROM shifts WHERE id = ?", (shift_id,))
    conn.commit()
    conn.close()


def assign_shift(emp_id, shift_id, effective_date, end_date=None):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        "INSERT INTO employee_shifts (emp_id, shift_id, effective_date, end_date) VALUES (?, ?, ?, ?)",
        (emp_id, shift_id, effective_date, end_date),
    )
    new_id = c.lastrowid
    conn.commit()
    conn.close()
    return new_id


def get_employee_shift(emp_id, date_str=None):
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
    conn = get_db_connection()
    c = conn.cursor()

    # 1. Kiểm tra lịch phân ca riêng
    c.execute("""
        SELECT es.*, s.shift_name, s.start_time, s.end_time, s.grace_minutes
        FROM employee_shifts es
        JOIN shifts s ON es.shift_id = s.id
        WHERE es.emp_id = ?
          AND es.effective_date <= ?
          AND (es.end_date IS NULL OR es.end_date >= ?)
        ORDER BY es.effective_date DESC
        LIMIT 1
    """, (emp_id, date_str, date_str))
    row = c.fetchone()
    if row:
        conn.close()
        return dict(row)

    # 2. Lấy ca cố định của nhân viên từ bảng employees
    c.execute("""
        SELECT s.*, s.shift_name, s.start_time, s.end_time, s.grace_minutes
        FROM employees e
        JOIN shifts s ON e.shift_id = s.id
        WHERE e.id = ?
    """, (emp_id,))
    row = c.fetchone()
    if row:
        conn.close()
        return dict(row)

    # 3. Fallback ca đầu tiên
    c.execute("SELECT *, shift_name, start_time, end_time, grace_minutes FROM shifts ORDER BY id ASC LIMIT 1")
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_employee_shifts():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""
        SELECT es.*, e.emp_code, e.name, e.department,
               s.shift_name, s.start_time, s.end_time, s.grace_minutes
        FROM employee_shifts es
        JOIN employees e ON es.emp_id = e.id
        JOIN shifts s ON es.shift_id = s.id
        ORDER BY es.effective_date DESC
    """)
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_employee_shift(assignment_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("DELETE FROM employee_shifts WHERE id = ?", (assignment_id,))
    conn.commit()
    conn.close()


# ── Tính đúng giờ / đi trễ / về sớm ───────────────────────────────────────────
def compute_shift_status(check_time_str: str, shift_start: str, shift_end: str, grace_minutes: int):
    try:
        check_t = datetime.strptime(check_time_str[:5], "%H:%M")
        start_t = datetime.strptime(shift_start[:5], "%H:%M")
        deadline = start_t + timedelta(minutes=grace_minutes)
        if check_t <= deadline:
            return "Vào ca", "Đúng giờ"
        else:
            return "Vào ca", "Đi trễ"
    except Exception:
        return "Vào ca", "Hợp lệ"


def compute_checkout_status(checkin_time_str: str, checkout_time_str: str, shift_end: str, prev_status: str):
    """Tính số giờ làm việc và trạng thái khi Check-out."""
    work_hours = 0.0
    try:
        t_in = datetime.strptime(checkin_time_str[:8], "%H:%M:%S")
        t_out = datetime.strptime(checkout_time_str[:8], "%H:%M:%S")
        diff_sec = max(0.0, (t_out - t_in).total_seconds())
        work_hours = round(diff_sec / 3600.0, 2)
    except Exception:
        try:
            t_in = datetime.strptime(checkin_time_str[:5], "%H:%M")
            t_out = datetime.strptime(checkout_time_str[:5], "%H:%M")
            diff_sec = max(0.0, (t_out - t_in).total_seconds())
            work_hours = round(diff_sec / 3600.0, 2)
        except Exception:
            work_hours = 0.0

    try:
        out_hm = datetime.strptime(checkout_time_str[:5], "%H:%M")
        end_hm = datetime.strptime(shift_end[:5], "%H:%M")
        # Cho phép sai số 10 phút trước giờ kết thúc ca
        if out_hm < (end_hm - timedelta(minutes=10)):
            if prev_status in ("Đi trễ", "Đi muộn"):
                return work_hours, "Đi trễ & Về sớm"
            return work_hours, "Về sớm"
    except Exception:
        pass

    return work_hours, prev_status


def compute_punctuality(check_time_str: str, shift_start: str, grace_minutes: int) -> str:
    try:
        check_t = datetime.strptime(check_time_str[:5], "%H:%M")
        shift_t = datetime.strptime(shift_start[:5], "%H:%M")
        deadline = shift_t + timedelta(minutes=grace_minutes)
        return "Đúng giờ" if check_t <= deadline else "Đi trễ"
    except Exception:
        return "Không xác định"


# ── Chấm công Check-in / Check-out (Kèm Vị trí & Ca làm) ──────────────────────
def get_today_attendance(emp_id, date_str=None):
    """Lấy bản ghi chấm công hôm nay của nhân viên."""
    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""
        SELECT * FROM attendance_logs
        WHERE emp_id = ? AND date = ?
        ORDER BY id DESC LIMIT 1
    """, (emp_id, date_str))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


def log_attendance(emp_id, emp_code, emp_name, similarity,
                   check_type="Vào ca", status="Đúng giờ", note="", location=""):
    """
    Hỗ trợ cả Check-in (Vào ca) và Check-out (Ra ca), lưu vị trí GPS và Ca làm việc.
    """
    now = datetime.now()
    timestamp_str = now.strftime("%Y-%m-%d %H:%M:%S")
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M:%S")

    shift_info = get_employee_shift(emp_id, date_str)
    shift_label = ""
    if shift_info:
        shift_label = f"{shift_info['shift_name']} ({shift_info['start_time']}-{shift_info['end_time']})"

    conn = get_db_connection()
    c = conn.cursor()

    # Nếu là Check-out (Ra ca), kiểm tra xem hôm nay đã có bản ghi Vào ca chưa
    if check_type == "Ra ca":
        c.execute("""
            SELECT * FROM attendance_logs
            WHERE emp_id = ? AND date = ?
            ORDER BY id DESC LIMIT 1
        """, (emp_id, date_str))
        existing = c.fetchone()
        if existing:
            existing_dict = dict(existing)
            shift_end = shift_info["end_time"] if shift_info else "17:00"
            work_hours, updated_status = compute_checkout_status(
                existing_dict["time"], time_str, shift_end, existing_dict["status"]
            )
            loc_note = existing_dict.get("note") or f"Ca: {shift_label}"
            c.execute("""
                UPDATE attendance_logs
                SET check_out_time = ?,
                    checkout_location = ?,
                    work_hours = ?,
                    check_type = 'Hoàn thành ca',
                    status = ?,
                    note = ?
                WHERE id = ?
            """, (time_str, location, work_hours, updated_status, loc_note, existing_dict["id"]))
            conn.commit()
            conn.close()
            return {
                "id": existing_dict["id"],
                "emp_id": emp_id,
                "emp_code": emp_code,
                "emp_name": emp_name,
                "timestamp": timestamp_str,
                "date": date_str,
                "time": existing_dict["time"],
                "check_out_time": time_str,
                "check_type": "Ra ca",
                "similarity": similarity,
                "status": updated_status,
                "shift_name": existing_dict.get("shift_name") or shift_label,
                "location": location or existing_dict.get("location", ""),
                "work_hours": work_hours,
                "note": loc_note,
            }

    # Mặc định: Check-in (Vào ca)
    if shift_info:
        calc_type, calc_status = compute_shift_status(
            time_str,
            shift_info["start_time"],
            shift_info["end_time"],
            shift_info["grace_minutes"],
        )
        check_type = "Vào ca"
        status = calc_status
        if not note:
            note = f"Ca: {shift_label}"

    c.execute("""
        INSERT INTO attendance_logs
            (emp_id, emp_code, emp_name, timestamp, date, time, check_out_time,
             check_type, similarity, status, shift_name, location, work_hours, note)
        VALUES (?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?, ?, 0.0, ?)
    """, (emp_id, emp_code, emp_name, timestamp_str, date_str, time_str,
          check_type, similarity, status, shift_label, location, note))
    new_id = c.lastrowid
    conn.commit()
    conn.close()
    return {
        "id": new_id,
        "emp_id": emp_id,
        "emp_code": emp_code,
        "emp_name": emp_name,
        "timestamp": timestamp_str,
        "date": date_str,
        "time": time_str,
        "check_out_time": "",
        "check_type": check_type,
        "similarity": similarity,
        "status": status,
        "shift_name": shift_label,
        "location": location,
        "work_hours": 0.0,
        "note": note,
    }


def get_recent_attendance(limit=10):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""
        SELECT a.*, e.department, e.avatar_file
        FROM attendance_logs a
        LEFT JOIN employees e ON a.emp_id = e.id
        ORDER BY a.id DESC LIMIT ?
    """, (limit,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def query_attendance(filter_type="day", date_val=None, start_date=None,
                     end_date=None, emp_id=None, department=None):
    conn = get_db_connection()
    c = conn.cursor()
    conditions, params = [], []

    if emp_id and str(emp_id).strip() not in ("", "all"):
        conditions.append("a.emp_id = ?")
        params.append(emp_id)

    if department and str(department).strip() not in ("", "all"):
        conditions.append("e.department = ?")
        params.append(department)

    if filter_type == "day":
        target_date = date_val or datetime.now().strftime("%Y-%m-%d")
        conditions.append("a.date = ?")
        params.append(target_date)
    elif filter_type == "week" and start_date and end_date:
        conditions.append("a.date >= ? AND a.date <= ?")
        params.extend([start_date, end_date])
    elif filter_type == "month":
        target_month = date_val or datetime.now().strftime("%Y-%m")
        conditions.append("a.date LIKE ?")
        params.append(f"{target_month}%")

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    c.execute(f"""
        SELECT a.*, e.department, e.position, e.avatar_file
        FROM attendance_logs a
        LEFT JOIN employees e ON a.emp_id = e.id
        {where_clause}
        ORDER BY a.timestamp DESC
    """, params)
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_attendance_log(log_id, check_type, status, note, time_val=None, date_val=None, check_out_time=None):
    conn = get_db_connection()
    c = conn.cursor()
    updates = ["check_type = ?", "status = ?", "note = ?"]
    params = [check_type, status, note]
    if date_val and time_val:
        updates.extend(["date = ?", "time = ?", "timestamp = ?"])
        params.extend([date_val, time_val, f"{date_val} {time_val}"])
    elif time_val:
        c.execute("SELECT date FROM attendance_logs WHERE id = ?", (log_id,))
        row = c.fetchone()
        if row:
            curr_date = row["date"]
            updates.extend(["time = ?", "timestamp = ?"])
            params.extend([time_val, f"{curr_date} {time_val}"])
    if check_out_time is not None:
        updates.append("check_out_time = ?")
        params.append(check_out_time)
    params.append(log_id)
    set_clause = ", ".join(updates)
    c.execute(f"UPDATE attendance_logs SET {set_clause} WHERE id = ?", params)
    conn.commit()
    conn.close()


def add_manual_attendance(emp_id, date_str, time_str, check_type, status, note, location="Admin bổ sung"):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT emp_code, name FROM employees WHERE id = ?", (emp_id,))
    emp = c.fetchone()
    if not emp:
        conn.close()
        raise ValueError("Không tìm thấy nhân viên.")
    shift_info = get_employee_shift(emp_id, date_str)
    shift_label = f"{shift_info['shift_name']} ({shift_info['start_time']}-{shift_info['end_time']})" if shift_info else ""
    c.execute("""
        INSERT INTO attendance_logs
            (emp_id, emp_code, emp_name, timestamp, date, time, check_type, similarity, status, shift_name, location, note)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (emp_id, emp["emp_code"], emp["name"],
          f"{date_str} {time_str}", date_str, time_str, check_type, 1.0, status, shift_label, location, note))
    new_id = c.lastrowid
    conn.commit()
    conn.close()
    return new_id


def delete_attendance_log(log_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("DELETE FROM attendance_logs WHERE id = ?", (log_id,))
    conn.commit()
    conn.close()


# ── Đơn nghỉ phép (B3: Trước ít nhất 3 ngày & Quét mặt xác thực) ──────────────
def validate_leave_advance_days(leave_date_str: str, min_days: int = 3) -> tuple[bool, int, str]:
    """
    Kiểm tra ngày nộp đơn phải trước ngày nghỉ ít nhất min_days (3 ngày).
    Trả về (is_valid, delta_days, error_message).
    """
    try:
        today_dt = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        leave_dt = datetime.strptime(leave_date_str.strip()[:10], "%Y-%m-%d")
        delta_days = (leave_dt - today_dt).days
        if delta_days < min_days:
            min_valid_date = (today_dt + timedelta(days=min_days)).strftime("%d/%m/%Y")
            return (
                False,
                delta_days,
                f"Ngày nộp đơn phải trước ngày nghỉ ít nhất {min_days} ngày! "
                f"(Hôm nay chỉ được đăng ký nghỉ từ ngày {min_valid_date} trở đi).",
            )
        return True, delta_days, ""
    except Exception:
        return False, 0, "Định dạng ngày nghỉ không hợp lệ (YYYY-MM-DD)."


def add_leave_request(emp_id, emp_code, emp_name, leave_type, leave_date, reason,
                      end_leave_date="", days_count=1, face_verified=1, face_similarity=1.0):
    """Gửi đơn xin nghỉ phép đã xác thực khuôn mặt."""
    conn = get_db_connection()
    c = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    if not end_leave_date:
        end_leave_date = leave_date
    c.execute("""
        INSERT INTO leave_requests
            (emp_id, emp_code, emp_name, leave_type, request_date, leave_date,
             end_leave_date, days_count, reason, face_verified, face_similarity)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (emp_id, emp_code, emp_name, leave_type, today, leave_date,
          end_leave_date, int(days_count or 1), reason, int(face_verified), float(face_similarity or 0.0)))
    new_id = c.lastrowid
    conn.commit()
    conn.close()
    return new_id


def get_all_leave_requests(status_filter=None):
    conn = get_db_connection()
    c = conn.cursor()
    base = """
        SELECT lr.*, a.full_name as reviewer_name, e.department, e.avatar_file
        FROM leave_requests lr
        LEFT JOIN admins a ON lr.reviewed_by = a.id
        LEFT JOIN employees e ON lr.emp_id = e.id
    """
    if status_filter and status_filter != "all":
        c.execute(base + " WHERE lr.status = ? ORDER BY lr.created_at DESC", (status_filter,))
    else:
        c.execute(base + " ORDER BY lr.created_at DESC")
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_leave_requests_by_emp(emp_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""
        SELECT lr.*, a.full_name as reviewer_name
        FROM leave_requests lr
        LEFT JOIN admins a ON lr.reviewed_by = a.id
        WHERE lr.emp_id = ?
        ORDER BY lr.created_at DESC
    """, (emp_id,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def review_leave_request(request_id, admin_id, approved: bool, note=""):
    status = "Đã duyệt" if approved else "Từ chối"
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        "UPDATE leave_requests SET status=?, reviewed_by=?, reviewed_at=?, note=? WHERE id=?",
        (status, admin_id, now, note, request_id),
    )
    conn.commit()
    conn.close()


def is_leave_approved(emp_id, date_str) -> bool:
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""
        SELECT id FROM leave_requests
        WHERE emp_id = ?
          AND status = 'Đã duyệt'
          AND leave_date <= ?
          AND (CASE WHEN end_leave_date IS NULL OR end_leave_date = '' THEN leave_date ELSE end_leave_date END) >= ?
        LIMIT 1
    """, (emp_id, date_str, date_str))
    row = c.fetchone()
    conn.close()
    return row is not None


# ── Tính toán Ngày công & Bảng lương (Payroll & Workdays) ─────────────────────
def calculate_payroll(month_str=None, emp_id=None):
    """
    Tính toán chi tiết số ngày công và lương trong tháng (YYYY-MM) cho 1 hoặc tất cả nhân viên:
      - base_salary: Lương cơ bản (VNĐ/tháng)
      - standard_days: 26 ngày công chuẩn
      - daily_wage: Lương 1 ngày công = base_salary / 26
      - present_days: Số ngày thực tế có chấm công trong tháng
      - completed_days: Số ngày có đủ cả Check-in và Check-out
      - on_time_days: Số ngày đi làm đúng giờ
      - late_days: Số ngày đi trễ
      - early_days: Số ngày về sớm
      - approved_leave_days: Số ngày nghỉ phép đã được duyệt trong tháng
      - total_paid_days: Tổng ngày công hưởng lương = present_days + approved_leave_days
      - total_work_hours: Tổng số giờ làm việc thực tế
      - late_penalty: Phạt đi trễ (late_days * 50,000 VNĐ)
      - net_salary: Lương thực nhận tạm tính
    """
    if not month_str:
        month_str = datetime.now().strftime("%Y-%m")

    conn = get_db_connection()
    c = conn.cursor()
    if emp_id:
        c.execute("""
            SELECT e.*, s.shift_name, s.start_time, s.end_time
            FROM employees e
            LEFT JOIN shifts s ON e.shift_id = s.id
            WHERE e.id = ?
        """, (emp_id,))
    else:
        c.execute("""
            SELECT e.*, s.shift_name, s.start_time, s.end_time
            FROM employees e
            LEFT JOIN shifts s ON e.shift_id = s.id
            ORDER BY e.emp_code ASC
        """)
    emps = [dict(r) for r in c.fetchall()]

    year, mon = map(int, month_str.split("-"))
    _, days_in_month = calendar.monthrange(year, mon)
    month_dates = [f"{year:04d}-{mon:02d}-{d:02d}" for d in range(1, days_in_month + 1)]

    payroll_list = []
    for emp in emps:
        eid = emp["id"]
        base_salary = float(emp.get("base_salary") or 9000000)
        daily_wage = base_salary / STANDARD_WORK_DAYS

        c.execute("""
            SELECT * FROM attendance_logs
            WHERE emp_id = ? AND date LIKE ?
            ORDER BY date ASC, id ASC
        """, (eid, f"{month_str}%"))
        logs = [dict(r) for r in c.fetchall()]

        # Gom theo từng ngày (mỗi ngày tính 1 công nếu có check-in)
        by_date = {}
        for lg in logs:
            d_key = lg["date"]
            if d_key not in by_date:
                by_date[d_key] = lg
            else:
                # Ưu tiên bản ghi có check_out_time
                if lg.get("check_out_time") and not by_date[d_key].get("check_out_time"):
                    by_date[d_key] = lg

        present_days = len(by_date)
        completed_days = 0
        on_time_days = 0
        late_days = 0
        early_days = 0
        total_work_hours = 0.0

        for d_key, lg in by_date.items():
            if lg.get("check_out_time"):
                completed_days += 1
            total_work_hours += float(lg.get("work_hours") or 0.0)
            st = lg.get("status", "")
            if "Đi trễ" in st or "Đi muộn" in st:
                late_days += 1
            else:
                on_time_days += 1
            if "Về sớm" in st:
                early_days += 1

        # Đếm số ngày nghỉ phép đã duyệt trong tháng (không trùng ngày đi làm)
        approved_leave_days = 0
        for d_str in month_dates:
            if d_str not in by_date and is_leave_approved(eid, d_str):
                approved_leave_days += 1

        total_paid_days = present_days + approved_leave_days
        gross_pay = total_paid_days * daily_wage
        late_penalty = late_days * LATE_PENALTY_VND
        net_salary = max(0.0, round(gross_pay - late_penalty, 0))

        payroll_list.append({
            "emp_id": eid,
            "emp_code": emp["emp_code"],
            "name": emp["name"],
            "department": emp.get("department", ""),
            "position": emp.get("position", ""),
            "avatar_file": emp.get("avatar_file", ""),
            "shift_name": emp.get("shift_name") or "Ca Sáng",
            "month": month_str,
            "base_salary": round(base_salary, 0),
            "standard_days": STANDARD_WORK_DAYS,
            "daily_wage": round(daily_wage, 0),
            "present_days": present_days,
            "completed_days": completed_days,
            "on_time_days": on_time_days,
            "late_days": late_days,
            "early_days": early_days,
            "approved_leave_days": approved_leave_days,
            "total_paid_days": total_paid_days,
            "total_work_hours": round(total_work_hours, 2),
            "late_penalty": late_penalty,
            "net_salary": net_salary,
            "daily_logs": list(by_date.values()),
        })

    conn.close()
    return payroll_list[0] if (emp_id and payroll_list) else payroll_list


# ── Thống kê (B1, B3) ─────────────────────────────────────────────────────────
def get_statistics(filter_type="day", date_val=None, start_date=None, end_date=None, department=None):
    logs = query_attendance(filter_type=filter_type, date_val=date_val,
                            start_date=start_date, end_date=end_date, department=department)
    conn = get_db_connection()
    c = conn.cursor()

    if department and department != "all":
        c.execute("SELECT id, emp_code, name, department FROM employees WHERE department = ?", (department,))
    else:
        c.execute("SELECT id, emp_code, name, department FROM employees")
    all_emps = [dict(r) for r in c.fetchall()]
    conn.close()

    target_dates = _get_dates_in_range(filter_type, date_val, start_date, end_date)

    logged_emp_dates = set()
    on_time_count = 0
    late_count = 0
    early_count = 0

    for log in logs:
        logged_emp_dates.add((log["emp_id"], log["date"]))
        s = log.get("status", "")
        if "Đi trễ" in s or "Đi muộn" in s:
            late_count += 1
        elif s == "Về sớm":
            early_count += 1
        elif s in ("Đúng giờ", "Hợp lệ", "Hoàn thành"):
            on_time_count += 1

    absent_count = approved_leave_count = 0
    for emp in all_emps:
        eid = emp["id"]
        for d in target_dates:
            if (eid, d) not in logged_emp_dates:
                if is_leave_approved(eid, d):
                    approved_leave_count += 1
                elif get_employee_shift(eid, d):
                    absent_count += 1

    total_checked = on_time_count + late_count + early_count
    on_time_rate = round(on_time_count / total_checked * 100, 1) if total_checked > 0 else 0.0
    late_rate = round(late_count / total_checked * 100, 1) if total_checked > 0 else 0.0
    early_rate = round(early_count / total_checked * 100, 1) if total_checked > 0 else 0.0

    by_dept = {}
    for log in logs:
        dept = log.get("department") or "Chưa phân công"
        if dept not in by_dept:
            by_dept[dept] = {"on_time": 0, "late": 0, "early": 0, "total": 0}
        s = log.get("status", "")
        by_dept[dept]["total"] += 1
        if "Đi trễ" in s or "Đi muộn" in s:
            by_dept[dept]["late"] += 1
        elif s == "Về sớm":
            by_dept[dept]["early"] += 1
        elif s in ("Đúng giờ", "Hợp lệ", "Hoàn thành"):
            by_dept[dept]["on_time"] += 1

    return {
        "total_employees": len(all_emps),
        "total_logs": len(logs),
        "on_time": on_time_count,
        "late": late_count,
        "early": early_count,
        "absent": absent_count,
        "approved_leave": approved_leave_count,
        "on_time_rate": on_time_rate,
        "late_rate": late_rate,
        "early_rate": early_rate,
        "by_dept": by_dept,
    }


def _get_dates_in_range(filter_type, date_val, start_date, end_date):
    dates = []
    try:
        if filter_type == "day":
            dates = [date_val or datetime.now().strftime("%Y-%m-%d")]
        elif filter_type == "week" and start_date and end_date:
            cur = datetime.strptime(start_date, "%Y-%m-%d")
            end = datetime.strptime(end_date, "%Y-%m-%d")
            while cur <= end:
                dates.append(cur.strftime("%Y-%m-%d"))
                cur += timedelta(days=1)
        elif filter_type == "month":
            month = date_val or datetime.now().strftime("%Y-%m")
            year, mon = map(int, month.split("-"))
            _, days_in_month = calendar.monthrange(year, mon)
            dates = [f"{year:04d}-{mon:02d}-{d:02d}" for d in range(1, days_in_month + 1)]
    except Exception:
        pass
    return dates
