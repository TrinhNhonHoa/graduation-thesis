/**
 * FaceID Attendance System — Admin Dashboard Controller
 * Quản lý Nhân viên (CRUD) và Quản lý Lịch Chấm công (Xem, Sửa, Thêm, In, Xuất CSV)
 */

let allEmployees = [];
let allAttendanceLogs = [];
let currentFilterMode = 'day';
let modalCameraStream = null;
let currentPhotoBlob = null;

// ── DOM References ──────────────────────────────────────────────────────────
const toastEl = document.getElementById('toast');
let toastTimer = null;

function showToast(msg, type = 'info') {
  toastEl.textContent = msg;
  toastEl.className = `toast ${type}`;
  toastEl.classList.remove('hidden');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toastEl.classList.add('hidden'), 3500);
}

// ── Tab Navigation ──────────────────────────────────────────────────────────
document.querySelectorAll('.admin-tabs .tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const tabName = btn.dataset.tab;
    document.querySelectorAll('.admin-tabs .tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));

    btn.classList.add('active');
    document.getElementById(`tab-${tabName}`).classList.add('active');

    if (tabName === 'employees') loadEmployees();
    if (tabName === 'attendance') {
      populateEmployeeFilterOptions();
      loadAttendance();
    }
    if (tabName === 'overview') loadOverviewStats();
  });
});

// ════════════════════════════════════════════════════════════════════════════
// QUẢN LÝ NHÂN VIÊN (CRUD)
// ════════════════════════════════════════════════════════════════════════════
const employeesTbody = document.getElementById('employees-tbody');
const empSearchInput = document.getElementById('employee-search');

const empModal        = document.getElementById('employee-modal');
const empModalTitle   = document.getElementById('employee-modal-title');
const empForm         = document.getElementById('employee-form');
const empFormId       = document.getElementById('emp-form-id');
const empFormCode     = document.getElementById('emp-form-code');
const empFormName     = document.getElementById('emp-form-name');
const empFormDept     = document.getElementById('emp-form-dept');
const empFormPos      = document.getElementById('emp-form-pos');
const empFormAlert    = document.getElementById('emp-form-alert');
const btnSaveEmp      = document.getElementById('btn-save-emp');
const empPhotoRequired= document.getElementById('emp-photo-required');

// Photo capture elements inside modal
const tabCapUpload     = document.getElementById('tab-cap-upload');
const tabCapCamera     = document.getElementById('tab-cap-camera');
const panelCapUpload   = document.getElementById('panel-cap-upload');
const panelCapCamera   = document.getElementById('panel-cap-camera');
const empDropZone      = document.getElementById('emp-drop-zone');
const empFileInput     = document.getElementById('emp-file-input');
const modalCamVideo    = document.getElementById('modal-cam-video');
const modalCamCanvas   = document.getElementById('modal-cam-canvas');
const btnModalCamStart = document.getElementById('btn-modal-cam-start');
const btnModalCamSnap  = document.getElementById('btn-modal-cam-snap');
const empPhotoPreviewW = document.getElementById('emp-photo-preview-wrap');
const empPhotoPreview  = document.getElementById('emp-photo-preview');
const empPhotoName     = document.getElementById('emp-photo-name');
const btnRemovePhoto   = document.getElementById('btn-remove-photo');

async function loadEmployees() {
  try {
    const res = await fetch('/api/admin/employees');
    if (!res.ok) throw new Error('Không thể tải danh sách');
    const data = await res.json();
    allEmployees = data.employees || [];
    renderEmployeesTable(allEmployees);
    document.getElementById('stat-total-emp').textContent = allEmployees.length;
  } catch (err) {
    employeesTbody.innerHTML = `<tr><td colspan="7" class="td-empty">${err.message}</td></tr>`;
  }
}

function renderEmployeesTable(list) {
  if (list.length === 0) {
    employeesTbody.innerHTML = `<tr><td colspan="7" class="td-empty">Chưa có nhân viên nào. Hãy bấm "Thêm Nhân Viên Mới".</td></tr>`;
    return;
  }

  employeesTbody.innerHTML = list.map(emp => {
    const avatarHtml = emp.avatar_file
      ? `<img src="/api/avatar/${emp.avatar_file}" alt="${emp.name}" />`
      : emp.name.charAt(0).toUpperCase();

    const created = emp.created_at ? emp.created_at.split(' ')[0] : '—';

    return `
      <tr>
        <td><div class="table-avatar">${avatarHtml}</div></td>
        <td><span class="code-badge">${emp.emp_code}</span></td>
        <td><strong>${emp.name}</strong></td>
        <td>${emp.department || '<span class="text-muted">—</span>'}</td>
        <td>${emp.position || '<span class="text-muted">—</span>'}</td>
        <td>${created}</td>
        <td>
          <div class="action-buttons">
            <button class="btn-sm-edit" onclick="openEditEmployeeModal(${emp.id})">Sửa</button>
            <button class="btn-sm-delete" onclick="deleteEmployee(${emp.id}, '${emp.name}')">Xóa</button>
          </div>
        </td>
      </tr>
    `;
  }).join('');
}

// Search
empSearchInput.addEventListener('input', (e) => {
  const q = e.target.value.toLowerCase().trim();
  const filtered = allEmployees.filter(emp =>
    emp.name.toLowerCase().includes(q) || emp.emp_code.toLowerCase().includes(q)
  );
  renderEmployeesTable(filtered);
});

// Modal: Mở Thêm nhân viên
document.getElementById('btn-open-add-emp').addEventListener('click', () => {
  empForm.reset();
  empFormId.value = '';
  empModalTitle.textContent = 'Thêm Nhân Viên Mới';
  empPhotoRequired.classList.remove('hidden');
  currentPhotoBlob = null;
  empPhotoPreviewW.classList.add('hidden');
  empFormAlert.classList.add('hidden');
  stopModalCamera();
  switchCapTab('upload');
  empModal.classList.remove('hidden');
});

// Modal: Mở Sửa nhân viên
window.openEditEmployeeModal = function(id) {
  const emp = allEmployees.find(e => e.id === id);
  if (!emp) return;

  empForm.reset();
  empFormId.value = emp.id;
  empFormCode.value = emp.emp_code;
  empFormName.value = emp.name;
  empFormDept.value = emp.department || '';
  empFormPos.value = emp.position || '';

  empModalTitle.textContent = `Chỉnh Sửa Nhân Viên: ${emp.name}`;
  empPhotoRequired.classList.add('hidden'); // Khi sửa không bắt buộc đổi ảnh
  empFormAlert.classList.add('hidden');
  currentPhotoBlob = null;

  if (emp.avatar_file) {
    empPhotoPreview.src = `/api/avatar/${emp.avatar_file}`;
    empPhotoName.textContent = 'Ảnh hiện tại (giữ nguyên nếu không chọn ảnh mới)';
    empPhotoPreviewW.classList.remove('hidden');
  } else {
    empPhotoPreviewW.classList.add('hidden');
  }

  stopModalCamera();
  switchCapTab('upload');
  empModal.classList.remove('hidden');
};

// Đóng modal nhân viên
function closeEmpModal() {
  empModal.classList.add('hidden');
  stopModalCamera();
}
document.getElementById('btn-close-emp-modal').addEventListener('click', closeEmpModal);
document.getElementById('btn-cancel-emp').addEventListener('click', closeEmpModal);

// Chuyển tab ảnh (Upload / Camera)
function switchCapTab(tab) {
  if (tab === 'upload') {
    tabCapUpload.classList.add('active');
    tabCapCamera.classList.remove('active');
    panelCapUpload.classList.remove('hidden');
    panelCapCamera.classList.add('hidden');
    stopModalCamera();
  } else {
    tabCapUpload.classList.remove('active');
    tabCapCamera.classList.add('active');
    panelCapUpload.classList.add('hidden');
    panelCapCamera.classList.remove('hidden');
  }
}
tabCapUpload.addEventListener('click', () => switchCapTab('upload'));
tabCapCamera.addEventListener('click', () => switchCapTab('camera'));

// Xử lý kéo thả / chọn file
empDropZone.addEventListener('click', () => empFileInput.click());
empFileInput.addEventListener('change', () => {
  if (empFileInput.files[0]) handleSelectedPhoto(empFileInput.files[0]);
});
empDropZone.addEventListener('dragover', e => { e.preventDefault(); empDropZone.style.borderColor = 'var(--accent)'; });
empDropZone.addEventListener('dragleave', () => { empDropZone.style.borderColor = ''; });
empDropZone.addEventListener('drop', e => {
  e.preventDefault();
  empDropZone.style.borderColor = '';
  if (e.dataTransfer.files[0]) handleSelectedPhoto(e.dataTransfer.files[0]);
});

function handleSelectedPhoto(file) {
  currentPhotoBlob = file;
  empPhotoPreview.src = URL.createObjectURL(file);
  empPhotoName.textContent = file.name || 'Ảnh đã chọn';
  empPhotoPreviewW.classList.remove('hidden');
}

btnRemovePhoto.addEventListener('click', () => {
  currentPhotoBlob = null;
  empFileInput.value = '';
  empPhotoPreview.src = '';
  empPhotoPreviewW.classList.add('hidden');
});

// Camera trong modal
btnModalCamStart.addEventListener('click', async () => {
  try {
    modalCameraStream = await navigator.mediaDevices.getUserMedia({ video: { width: 480, height: 360 } });
    modalCamVideo.srcObject = modalCameraStream;
    btnModalCamStart.classList.add('hidden');
    btnModalCamSnap.classList.remove('hidden');
  } catch (err) {
    showToast('Không thể mở camera cho modal', 'error');
  }
});

btnModalCamSnap.addEventListener('click', () => {
  modalCamCanvas.width = modalCamVideo.videoWidth || 480;
  modalCamCanvas.height = modalCamVideo.videoHeight || 360;
  const ctx = modalCamCanvas.getContext('2d');
  ctx.drawImage(modalCamVideo, 0, 0, modalCamCanvas.width, modalCamCanvas.height);

  modalCamCanvas.toBlob(blob => {
    currentPhotoBlob = new File([blob], 'avatar_snapshot.jpg', { type: 'image/jpeg' });
    empPhotoPreview.src = URL.createObjectURL(blob);
    empPhotoName.textContent = 'Ảnh chụp từ webcam';
    empPhotoPreviewW.classList.remove('hidden');
    stopModalCamera();
    switchCapTab('upload');
  }, 'image/jpeg', 0.92);
});

function stopModalCamera() {
  if (modalCameraStream) {
    modalCameraStream.getTracks().forEach(t => t.stop());
    modalCameraStream = null;
  }
  btnModalCamStart.classList.remove('hidden');
  btnModalCamSnap.classList.add('hidden');
}

// Lưu nhân viên (Thêm mới / Cập nhật)
empForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  empFormAlert.classList.add('hidden');

  const empId   = empFormId.value;
  const empCode = empFormCode.value.trim().toUpperCase();
  const name    = empFormName.value.trim();
  const dept    = empFormDept.value.trim();
  const pos     = empFormPos.value.trim();

  if (!empId && !currentPhotoBlob) {
    empFormAlert.textContent = 'Vui lòng tải lên hoặc chụp ảnh khuôn mặt cho nhân viên mới.';
    empFormAlert.classList.remove('hidden');
    return;
  }

  btnSaveEmp.disabled = true;
  btnSaveEmp.innerHTML = '<span>Đang trích xuất đặc trưng AI...</span>';

  const formData = new FormData();
  formData.append('emp_code', empCode);
  formData.append('name', name);
  formData.append('department', dept);
  formData.append('position', pos);
  if (currentPhotoBlob) {
    formData.append('file', currentPhotoBlob);
  }

  try {
    const url = empId ? `/api/admin/employees/${empId}` : '/api/admin/employees';
    const method = 'POST';

    const res = await fetch(url, { method, body: formData });
    const data = await res.json();

    if (res.ok) {
      showToast(data.message || 'Thao tác thành công!', 'success');
      closeEmpModal();
      loadEmployees();
    } else {
      empFormAlert.textContent = data.error || 'Có lỗi xảy ra khi lưu nhân viên.';
      empFormAlert.classList.remove('hidden');
    }
  } catch (err) {
    empFormAlert.textContent = 'Lỗi kết nối tới máy chủ.';
    empFormAlert.classList.remove('hidden');
  } finally {
    btnSaveEmp.disabled = false;
    btnSaveEmp.innerHTML = '<span>Lưu Nhân Viên</span>';
  }
});

// Xóa nhân viên
window.deleteEmployee = async function(id, name) {
  if (!confirm(`Bạn có chắc chắn muốn xóa nhân viên "${name}" khỏi hệ thống?`)) return;

  try {
    const res = await fetch(`/api/admin/employees/${id}`, { method: 'DELETE' });
    const data = await res.json();
    if (res.ok) {
      showToast(data.message || 'Đã xóa nhân viên.', 'success');
      loadEmployees();
    } else {
      showToast(data.error || 'Không thể xóa nhân viên.', 'error');
    }
  } catch (err) {
    showToast('Lỗi kết nối tới máy chủ.', 'error');
  }
};

// ════════════════════════════════════════════════════════════════════════════
// QUẢN LÝ LỊCH CHẤM CÔNG (XEM, IN, SỬA, THÊM THỦ CÔNG)
// ════════════════════════════════════════════════════════════════════════════
const attendanceTbody   = document.getElementById('attendance-tbody');
const filterDateInput   = document.getElementById('filter-date');
const filterMonthInput  = document.getElementById('filter-month');
const filterWeekStart   = document.getElementById('filter-week-start');
const filterWeekEnd     = document.getElementById('filter-week-end');
const filterEmpSelect   = document.getElementById('filter-employee');
const filterDayWrap     = document.getElementById('filter-day-wrap');
const filterWeekWrap    = document.getElementById('filter-week-wrap');
const filterMonthWrap   = document.getElementById('filter-month-wrap');

// Khởi tạo ngày mặc định
const todayStr = new Date().toISOString().split('T')[0];
filterDateInput.value = todayStr;
filterMonthInput.value = todayStr.substring(0, 7);

// Tính thứ 2 đến chủ nhật tuần này
const now = new Date();
const currentDayOfWeek = (now.getDay() + 6) % 7; // Thứ 2 = 0
const monday = new Date(now);
monday.setDate(now.getDate() - currentDayOfWeek);
const sunday = new Date(monday);
sunday.setDate(monday.getDate() + 6);
filterWeekStart.value = monday.toISOString().split('T')[0];
filterWeekEnd.value = sunday.toISOString().split('T')[0];

// Chuyển chế độ lọc (Theo Ngày / Tuần / Tháng / Tất cả)
document.querySelectorAll('.filter-mode-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.filter-mode-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    currentFilterMode = btn.dataset.mode;

    filterDayWrap.classList.add('hidden');
    filterWeekWrap.classList.add('hidden');
    filterMonthWrap.classList.add('hidden');

    if (currentFilterMode === 'day') filterDayWrap.classList.remove('hidden');
    if (currentFilterMode === 'week') filterWeekWrap.classList.remove('hidden');
    if (currentFilterMode === 'month') filterMonthWrap.classList.remove('hidden');
  });
});

document.getElementById('btn-apply-filter').addEventListener('click', loadAttendance);

function populateEmployeeFilterOptions() {
  const prevVal = filterEmpSelect.value;
  filterEmpSelect.innerHTML = '<option value="all">-- Tất cả nhân viên --</option>';
  allEmployees.forEach(emp => {
    filterEmpSelect.innerHTML += `<option value="${emp.id}">${emp.emp_code} - ${emp.name}</option>`;
  });
  filterEmpSelect.value = prevVal || 'all';

  // Dropdown trong modal thêm thủ công
  const manualEmpSelect = document.getElementById('manual-att-emp');
  if (manualEmpSelect) {
    manualEmpSelect.innerHTML = '<option value="">-- Chọn nhân viên --</option>';
    allEmployees.forEach(emp => {
      manualEmpSelect.innerHTML += `<option value="${emp.id}">${emp.emp_code} - ${emp.name}</option>`;
    });
  }
}

async function loadAttendance() {
  const empId = filterEmpSelect.value;
  let params = new URLSearchParams({
    filter_type: currentFilterMode,
    emp_id: empId
  });

  if (currentFilterMode === 'day') {
    params.append('date', filterDateInput.value);
  } else if (currentFilterMode === 'week') {
    params.append('start_date', filterWeekStart.value);
    params.append('end_date', filterWeekEnd.value);
  } else if (currentFilterMode === 'month') {
    params.append('date', filterMonthInput.value);
  }

  // Cập nhật tóm tắt in ấn
  updatePrintSummary();

  try {
    const res = await fetch(`/api/admin/attendance?${params.toString()}`);
    if (!res.ok) throw new Error('Không thể tải lịch chấm công');
    const data = await res.json();
    allAttendanceLogs = data.logs || [];
    renderAttendanceTable(allAttendanceLogs);
    document.getElementById('stat-today-logs').textContent = allAttendanceLogs.length;
  } catch (err) {
    attendanceTbody.innerHTML = `<tr><td colspan="11" class="td-empty">${err.message}</td></tr>`;
  }
}

function updatePrintSummary() {
  const printSumEl = document.getElementById('print-filter-summary');
  const empText = filterEmpSelect.options[filterEmpSelect.selectedIndex]?.text || 'Tất cả';

  let periodText = '';
  if (currentFilterMode === 'day') {
    periodText = `Ngày: ${filterDateInput.value}`;
  } else if (currentFilterMode === 'week') {
    periodText = `Tuần: Từ ${filterWeekStart.value} đến ${filterWeekEnd.value}`;
  } else if (currentFilterMode === 'month') {
    periodText = `Tháng: ${filterMonthInput.value}`;
  } else {
    periodText = 'Toàn bộ thời gian';
  }

  printSumEl.textContent = `Kỳ chấm công: ${periodText} · Nhân viên: ${empText}`;
  document.getElementById('print-export-time').textContent = `Ngày in: ${new Date().toLocaleDateString('vi-VN')} ${new Date().toLocaleTimeString('vi-VN')}`;
}

function renderAttendanceTable(logs) {
  if (logs.length === 0) {
    attendanceTbody.innerHTML = `<tr><td colspan="11" class="td-empty">Không tìm thấy dữ liệu chấm công cho khoảng thời gian này.</td></tr>`;
    return;
  }

  attendanceTbody.innerHTML = logs.map((log, index) => {
    let statusClass = 'valid';
    if (log.status === 'Đi muộn' || log.status === 'Về sớm') statusClass = 'warning';
    if (log.status === 'Quên quẹt thẻ' || log.status === 'Không hợp lệ') statusClass = 'danger';

    const simText = log.similarity ? `${(log.similarity * 100).toFixed(1)}%` : 'Thủ công';

    return `
      <tr>
        <td style="text-align: center; color: var(--text-muted);">${index + 1}</td>
        <td><span class="code-badge">${log.emp_code}</span></td>
        <td><strong>${log.emp_name}</strong></td>
        <td>${log.department || '—'}</td>
        <td>${log.date}</td>
        <td style="font-weight: 600;">${log.time}</td>
        <td>${log.check_type || 'Điểm danh'}</td>
        <td style="color: var(--success-light); font-weight: 600;">${simText}</td>
        <td><span class="tag-status ${statusClass}">${log.status || 'Hợp lệ'}</span></td>
        <td style="color: var(--text-secondary); font-size: 0.82rem;">${log.note || '—'}</td>
        <td class="no-print">
          <div class="action-buttons">
            <button class="btn-sm-edit" onclick="openEditAttendanceModal(${log.id})">Sửa</button>
            <button class="btn-sm-delete" onclick="deleteAttendanceLog(${log.id})">Xóa</button>
          </div>
        </td>
      </tr>
    `;
  }).join('');
}

// ── In Bảng Chấm Công ───────────────────────────────────────────────────────
document.getElementById('btn-print-report').addEventListener('click', () => {
  updatePrintSummary();
  window.print();
});

// ── Xuất File CSV ───────────────────────────────────────────────────────────
document.getElementById('btn-export-csv').addEventListener('click', () => {
  const empId = filterEmpSelect.value;
  let params = new URLSearchParams({
    filter_type: currentFilterMode,
    emp_id: empId
  });

  if (currentFilterMode === 'day') {
    params.append('date', filterDateInput.value);
  } else if (currentFilterMode === 'week') {
    params.append('start_date', filterWeekStart.value);
    params.append('end_date', filterWeekEnd.value);
  } else if (currentFilterMode === 'month') {
    params.append('date', filterMonthInput.value);
  }

  window.location.href = `/api/admin/attendance/export?${params.toString()}`;
});

// ── Modal: Sửa lượt chấm công ───────────────────────────────────────────────
const editAttModal    = document.getElementById('edit-attendance-modal');
const editAttForm     = document.getElementById('edit-attendance-form');
const editAttId       = document.getElementById('edit-att-id');
const editAttEmpName  = document.getElementById('edit-att-emp-name');
const editAttDate     = document.getElementById('edit-att-date');
const editAttTime     = document.getElementById('edit-att-time');
const editAttType     = document.getElementById('edit-att-type');
const editAttStatus   = document.getElementById('edit-att-status');
const editAttNote     = document.getElementById('edit-att-note');

window.openEditAttendanceModal = function(id) {
  const log = allAttendanceLogs.find(l => l.id === id);
  if (!log) return;

  editAttId.value = log.id;
  editAttEmpName.textContent = `${log.emp_name} (${log.emp_code})`;
  editAttDate.value = log.date;
  editAttTime.value = log.time;
  editAttType.value = log.check_type || 'Điểm danh';
  editAttStatus.value = log.status || 'Hợp lệ';
  editAttNote.value = log.note || '';

  editAttModal.classList.remove('hidden');
};

function closeEditAttModal() {
  editAttModal.classList.add('hidden');
}
document.getElementById('btn-close-att-modal').addEventListener('click', closeEditAttModal);
document.getElementById('btn-cancel-att').addEventListener('click', closeEditAttModal);

editAttForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const logId = editAttId.value;

  try {
    const res = await fetch(`/api/admin/attendance/${logId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        date: editAttDate.value,
        time: editAttTime.value,
        check_type: editAttType.value,
        status: editAttStatus.value,
        note: editAttNote.value
      })
    });
    const data = await res.json();
    if (res.ok) {
      showToast('Đã cập nhật lượt chấm công.', 'success');
      closeEditAttModal();
      loadAttendance();
    } else {
      showToast(data.error || 'Lỗi cập nhật.', 'error');
    }
  } catch (err) {
    showToast('Lỗi kết nối máy chủ.', 'error');
  }
});

// Xóa lượt chấm công
window.deleteAttendanceLog = async function(id) {
  if (!confirm('Bạn có chắc muốn xóa bản ghi chấm công này?')) return;
  try {
    const res = await fetch(`/api/admin/attendance/${id}`, { method: 'DELETE' });
    const data = await res.json();
    if (res.ok) {
      showToast('Đã xóa bản ghi chấm công.', 'success');
      loadAttendance();
    } else {
      showToast(data.error || 'Không thể xóa.', 'error');
    }
  } catch (err) {
    showToast('Lỗi kết nối máy chủ.', 'error');
  }
};

// ── Modal: Thêm chấm công thủ công ──────────────────────────────────────────
const addManualAttModal   = document.getElementById('add-manual-att-modal');
const addManualAttForm    = document.getElementById('add-manual-att-form');
const manualAttEmpSelect  = document.getElementById('manual-att-emp');
const manualAttDateInput  = document.getElementById('manual-att-date');
const manualAttTimeInput  = document.getElementById('manual-att-time');
const manualAttTypeSelect = document.getElementById('manual-att-type');
const manualAttStatus     = document.getElementById('manual-att-status');
const manualAttNote       = document.getElementById('manual-att-note');

document.getElementById('btn-open-add-attendance').addEventListener('click', () => {
  addManualAttForm.reset();
  manualAttDateInput.value = new Date().toISOString().split('T')[0];
  const now = new Date();
  manualAttTimeInput.value = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}:${String(now.getSeconds()).padStart(2, '0')}`;
  addManualAttModal.classList.remove('hidden');
});

function closeManualAttModal() {
  addManualAttModal.classList.add('hidden');
}
document.getElementById('btn-close-manual-att').addEventListener('click', closeManualAttModal);
document.getElementById('btn-cancel-manual-att').addEventListener('click', closeManualAttModal);

addManualAttForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const empId = manualAttEmpSelect.value;
  if (!empId) {
    showToast('Vui lòng chọn nhân viên.', 'error');
    return;
  }

  try {
    const res = await fetch('/api/admin/attendance', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        emp_id: empId,
        date: manualAttDateInput.value,
        time: manualAttTimeInput.value,
        check_type: manualAttTypeSelect.value,
        status: manualAttStatus.value,
        note: manualAttNote.value
      })
    });
    const data = await res.json();
    if (res.ok) {
      showToast('Đã thêm lượt chấm công mới.', 'success');
      closeManualAttModal();
      loadAttendance();
    } else {
      showToast(data.error || 'Lỗi thêm chấm công.', 'error');
    }
  } catch (err) {
    showToast('Lỗi kết nối máy chủ.', 'error');
  }
});

// ── Overview Stats ──────────────────────────────────────────────────────────
async function loadOverviewStats() {
  document.getElementById('stat-total-emp').textContent = allEmployees.length;
}

// ── Khởi động ───────────────────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', async () => {
  await loadEmployees();
  populateEmployeeFilterOptions();
  loadAttendance();
});
