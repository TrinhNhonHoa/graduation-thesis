"""
Database module cho hệ thống chấm công và quản lý nhân viên FaceID.
Sử dụng SQLite tích hợp sẵn trong Python.
"""
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from werkzeug.security import generate_password_hash, check_password_hash

PROJECT_ROOT = Path(__file__).resolve().parent
DB_PATH = PROJECT_ROOT / "data" / "attendance.db"
AVATAR_DIR = PROJECT_ROOT / "data" / "avatars"
EMBEDDING_DIR = PROJECT_ROOT / "data" / "face_db"

AVATAR_DIR.mkdir(parents=True, exist_ok=True)
EMBEDDING_DIR.mkdir(parents=True, exist_ok=True)


def get_db_connection():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Bảng Quản trị viên
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            full_name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Bảng Nhân viên
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            emp_code TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            department TEXT DEFAULT '',
            position TEXT DEFAULT '',
            avatar_file TEXT DEFAULT '',
            embedding_file TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Bảng Nhật ký chấm công
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS attendance_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            emp_id INTEGER,
            emp_code TEXT NOT NULL,
            emp_name TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            date TEXT NOT NULL,
            time TEXT NOT NULL,
            check_type TEXT DEFAULT 'Điểm danh',
            similarity REAL DEFAULT 0.0,
            status TEXT DEFAULT 'Hợp lệ',
            note TEXT DEFAULT '',
            FOREIGN KEY (emp_id) REFERENCES employees (id) ON DELETE SET NULL
        )
    """)

    # Tạo tài khoản admin mặc định nếu chưa có
    cursor.execute("SELECT id FROM admins WHERE username = 'admin'")
    if not cursor.fetchone():
        hashed = generate_password_hash("admin123")
        cursor.execute("""
            INSERT INTO admins (username, password_hash, full_name)
            VALUES (?, ?, ?)
        """, ("admin", hashed, "Quản Trị Viên"))

    # Tự động đồng bộ các file .npy có sẵn trong data/face_db (ví dụ Hòa.npy)
    for npy_file in EMBEDDING_DIR.glob("*.npy"):
        stem_name = npy_file.stem
        cursor.execute("SELECT id FROM employees WHERE embedding_file = ?", (npy_file.name,))
        if not cursor.fetchone():
            # Sinh mã nhân viên NV001, NV002...
            cursor.execute("SELECT COUNT(*) FROM employees")
            count = cursor.fetchone()[0] + 1
            code = f"NV{count:03d}"
            cursor.execute("""
                INSERT INTO employees (emp_code, name, department, position, embedding_file)
                VALUES (?, ?, ?, ?, ?)
            """, (code, stem_name, "Phòng Kỹ Thuật", "Nhân viên", npy_file.name))

    conn.commit()
    conn.close()


# ── Quản trị viên ─────────────────────────────────────────────────────────────
def verify_admin(username, password):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM admins WHERE username = ?", (username,))
    admin = cursor.fetchone()
    conn.close()
    if admin and check_password_hash(admin["password_hash"], password):
        return dict(admin)
    return None


# ── Nhân viên ─────────────────────────────────────────────────────────────────
def get_all_employees():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM employees ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_employee_by_id(emp_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM employees WHERE id = ?", (emp_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_employee_by_code(emp_code):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM employees WHERE emp_code = ?", (emp_code,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def add_employee(emp_code, name, department, position, avatar_file, embedding_file):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO employees (emp_code, name, department, position, avatar_file, embedding_file)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (emp_code, name, department, position, avatar_file, embedding_file))
    new_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return new_id


def update_employee(emp_id, emp_code, name, department, position, avatar_file=None, embedding_file=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    if avatar_file and embedding_file:
        cursor.execute("""
            UPDATE employees
            SET emp_code = ?, name = ?, department = ?, position = ?, avatar_file = ?, embedding_file = ?
            WHERE id = ?
        """, (emp_code, name, department, position, avatar_file, embedding_file, emp_id))
    else:
        cursor.execute("""
            UPDATE employees
            SET emp_code = ?, name = ?, department = ?, position = ?
            WHERE id = ?
        """, (emp_code, name, department, position, emp_id))
    conn.commit()
    conn.close()


def delete_employee(emp_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT avatar_file, embedding_file FROM employees WHERE id = ?", (emp_id,))
    emp = cursor.fetchone()
    if emp:
        # Xóa file npy
        if emp["embedding_file"]:
            npy_path = EMBEDDING_DIR / emp["embedding_file"]
            if npy_path.exists():
                try:
                    npy_path.unlink()
                except Exception:
                    pass
        # Xóa file ảnh đại diện
        if emp["avatar_file"]:
            av_path = AVATAR_DIR / emp["avatar_file"]
            if av_path.exists():
                try:
                    av_path.unlink()
                except Exception:
                    pass
    cursor.execute("DELETE FROM employees WHERE id = ?", (emp_id,))
    conn.commit()
    conn.close()


# ── Chấm công ─────────────────────────────────────────────────────────────────
def log_attendance(emp_id, emp_code, emp_name, similarity, check_type="Điểm danh", status="Hợp lệ", note=""):
    now = datetime.now()
    timestamp_str = now.strftime("%Y-%m-%d %H:%M:%S")
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M:%S")

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO attendance_logs (emp_id, emp_code, emp_name, timestamp, date, time, check_type, similarity, status, note)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (emp_id, emp_code, emp_name, timestamp_str, date_str, time_str, check_type, similarity, status, note))
    new_id = cursor.lastrowid
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
        "check_type": check_type,
        "similarity": similarity,
        "status": status,
        "note": note
    }


def get_recent_attendance(limit=10):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT a.*, e.department, e.avatar_file
        FROM attendance_logs a
        LEFT JOIN employees e ON a.emp_id = e.id
        ORDER BY a.id DESC LIMIT ?
    """, (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def query_attendance(filter_type="day", date_val=None, start_date=None, end_date=None, emp_id=None):
    """
    Truy vấn lịch chấm công theo:
      - filter_type: 'day', 'week', 'month', 'all'
      - date_val: ngày cụ thể YYYY-MM-DD hoặc tháng YYYY-MM
      - start_date, end_date: cho khoảng tuần / tùy chọn
      - emp_id: lọc theo nhân viên cụ thể
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    conditions = []
    params = []

    if emp_id and str(emp_id).strip() != "" and str(emp_id) != "all":
        conditions.append("a.emp_id = ?")
        params.append(emp_id)

    if filter_type == "day":
        target_date = date_val or datetime.now().strftime("%Y-%m-%d")
        conditions.append("a.date = ?")
        params.append(target_date)
    elif filter_type == "week":
        if start_date and end_date:
            conditions.append("a.date >= ? AND a.date <= ?")
            params.extend([start_date, end_date])
    elif filter_type == "month":
        target_month = date_val or datetime.now().strftime("%Y-%m")
        conditions.append("a.date LIKE ?")
        params.append(f"{target_month}%")

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    query = f"""
        SELECT a.*, e.department, e.position, e.avatar_file
        FROM attendance_logs a
        LEFT JOIN employees e ON a.emp_id = e.id
        {where_clause}
        ORDER BY a.timestamp DESC
    """

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_attendance_log(log_id, check_type, status, note, time_val=None, date_val=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    updates = ["check_type = ?", "status = ?", "note = ?"]
    params = [check_type, status, note]

    if date_val and time_val:
        timestamp_str = f"{date_val} {time_val}"
        updates.extend(["date = ?", "time = ?", "timestamp = ?"])
        params.extend([date_val, time_val, timestamp_str])
    elif time_val:
        cursor.execute("SELECT date FROM attendance_logs WHERE id = ?", (log_id,))
        row = cursor.fetchone()
        if row:
            curr_date = row["date"]
            updates.extend(["time = ?", "timestamp = ?"])
            params.extend([time_val, f"{curr_date} {time_val}"])

    params.append(log_id)
    cursor.execute(f"UPDATE attendance_logs SET {', '.join(updates)} WHERE id = ?", params)
    conn.commit()
    conn.close()


def add_manual_attendance(emp_id, date_str, time_str, check_type, status, note):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT emp_code, name FROM employees WHERE id = ?", (emp_id,))
    emp = cursor.fetchone()
    if not emp:
        conn.close()
        raise ValueError("Không tìm thấy nhân viên.")

    timestamp_str = f"{date_str} {time_str}"
    cursor.execute("""
        INSERT INTO attendance_logs (emp_id, emp_code, emp_name, timestamp, date, time, check_type, similarity, status, note)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (emp_id, emp["emp_code"], emp["name"], timestamp_str, date_str, time_str, check_type, 1.0, status, note))
    new_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return new_id


def delete_attendance_log(log_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM attendance_logs WHERE id = ?", (log_id,))
    conn.commit()
    conn.close()
