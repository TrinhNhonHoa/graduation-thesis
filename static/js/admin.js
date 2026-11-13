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
    const targetPane = document.getElementById(`tab-${tabName}`);
    if (targetPane) targetPane.classList.add('active');

    if (tabName === 'employees') loadEmployees();
    if (tabName === 'shifts') {
      loadShifts();
      loadEmployeeShifts();
      populateShiftAssignOptions();
    }
    if (tabName === 'leaves') loadLeaveRequests();
    if (tabName === 'attendance') {
      populateEmployeeFilterOptions();
      loadAttendance();
    }
    if (tabName === 'stats') {
      populateStatsDeptOptions();
      loadAdvancedStats();
    }
    if (tabName === 'payroll') loadAdminPayroll();
    if (tabName === 'login-logs') loadAdminLoginLogs();
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
const empFormShift    = document.getElementById('emp-form-shift');
const empFormPassword = document.getElementById('emp-form-password');
const empFormSalary   = document.getElementById('emp-form-salary');
const empFormAlert    = document.getElementById('emp-form-alert');
const btnSaveEmp      = document.getElementById('btn-save-emp');
const empPhotoRequired= document.getElementById('emp-photo-required');

// 3-Angle Capture elements inside modal
const tabCapCamera     = document.getElementById('tab-cap-camera');
const tabCapUpload       = document.getElementById('tab-cap-upload');
const panelCapCamera     = document.getElementById('panel-cap-camera');
const panelCapUpload     = document.getElementById('panel-cap-upload');
const modalCamVideo      = document.getElementById('modal-cam-video');
const modalCamCanvas     = document.getElementById('modal-cam-canvas');
const btnStartFaceScan   = document.getElementById('btn-start-face-scan');
const btnStopFaceScan    = document.getElementById('btn-stop-face-scan');
const modalCamOval       = document.getElementById('modal-cam-oval');
const modalCamInstruction= document.getElementById('modal-cam-instruction');
const modalCamCountdown  = document.getElementById('modal-cam-countdown');
const scanProgressWrap   = document.getElementById('scan-progress-wrap');
const scanProgressFill   = document.getElementById('scan-progress-fill');
const scanStepPercent    = document.getElementById('scan-step-percent');
const scanStepLabel      = document.getElementById('scan-step-label');
const inputSingleAvatar  = document.getElementById('input-single-avatar');
const enrollmentResultCard=document.getElementById('enrollment-result-card');
const avatarPreviewImg   = document.getElementById('avatar-preview-img');
const vectorStatusDesc   = document.getElementById('vector-status-desc');
const btnRescanFace      = document.getElementById('btn-rescan-face');

// Dữ liệu thu thập từ luồng quét hoặc upload ảnh
const faceEnrollmentData = {
  avatarBlob: null,
  frames: []
};

// Âm thanh beep hỗ trợ hướng dẫn người dùng
function playEnrollmentBeep(freq = 600, duration = 120) {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.frequency.value = freq;
    osc.type = 'sine';
    gain.gain.setValueAtTime(0.15, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + duration / 1000);
    osc.start();
    osc.stop(ctx.currentTime + duration / 1000);
  } catch (e) {}
}

function setEnrollmentAvatar(fileOrBlob, descText) {
  faceEnrollmentData.avatarBlob = fileOrBlob;
  if (avatarPreviewImg && fileOrBlob) {
    avatarPreviewImg.src = URL.createObjectURL(fileOrBlob);
  }
  if (vectorStatusDesc && descText) {
    vectorStatusDesc.textContent = descText;
  }
  if (enrollmentResultCard) {
    enrollmentResultCard.classList.remove('hidden');
  }
}

function resetEnrollmentData() {
  faceEnrollmentData.avatarBlob = null;
  faceEnrollmentData.frames = [];
  if (enrollmentResultCard) enrollmentResultCard.classList.add('hidden');
  if (scanProgressWrap) scanProgressWrap.classList.add('hidden');
  if (scanProgressFill) scanProgressFill.style.width = '0%';
  if (scanStepPercent) scanStepPercent.textContent = '0%';
  if (inputSingleAvatar) inputSingleAvatar.value = '';
  if (modalCamOval) modalCamOval.className = 'face-scan-oval';
  if (modalCamInstruction) {
    modalCamInstruction.textContent = 'Bấm "Bắt Đầu Quét Khuôn Mặt" và quay nhẹ mặt theo hướng dẫn';
    modalCamInstruction.style.color = '#38bdf8';
    modalCamInstruction.style.borderColor = 'rgba(56,189,248,0.4)';
  }
  if (btnStartFaceScan) {
    btnStartFaceScan.classList.remove('hidden');
    btnStartFaceScan.innerHTML = '🎥 Bắt Đầu Quét Khuôn Mặt';
    btnStartFaceScan.disabled = false;
  }
  if (btnStopFaceScan) btnStopFaceScan.classList.add('hidden');
}

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
        <td><span class="badge" style="background:var(--bg-elevated);border:1px solid var(--border);font-size:.76rem;font-weight:600;">${emp.shift_name || 'Ca Sáng'}</span></td>
        <td style="font-weight:700;color:#34d399;">${Number(emp.base_salary || 9000000).toLocaleString('vi-VN')} đ</td>
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
  if (empFormShift) empFormShift.value = 1;
  if (empFormPassword) empFormPassword.value = '123456';
  if (empFormSalary) empFormSalary.value = 9000000;
  empModalTitle.textContent = 'Thêm Nhân Viên Mới';
  empPhotoRequired.classList.remove('hidden');
  resetEnrollmentData();
  empFormAlert.classList.add('hidden');
  stopModalCamera();
  switchCapTab('camera');
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
  if (empFormShift) empFormShift.value = emp.shift_id || 1;

  empModalTitle.textContent = `Chỉnh Sửa Nhân Viên: ${emp.name}`;
  empPhotoRequired.classList.add('hidden'); // Khi sửa không bắt buộc đổi ảnh
  empFormAlert.classList.add('hidden');
  resetEnrollmentData();

  if (emp.avatar_file) {
    setEnrollmentAvatar(null, 'Nhân viên đã có ảnh đại diện và bộ vector embedding đa góc.');
    if (avatarPreviewImg) avatarPreviewImg.src = `/api/avatar/${emp.avatar_file}`;
  }

  if (btnStartFaceScan) {
    btnStartFaceScan.innerHTML = '🎥 Quét Lại Khuôn Mặt';
  }

  stopModalCamera();
  switchCapTab('camera');
  empModal.classList.remove('hidden');
};

// Đóng modal nhân viên
function closeEmpModal() {
  empModal.classList.add('hidden');
  stopModalCamera();
}
document.getElementById('btn-close-emp-modal').addEventListener('click', closeEmpModal);
document.getElementById('btn-cancel-emp').addEventListener('click', closeEmpModal);

// Chuyển tab ảnh (Camera / Upload)
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
if (tabCapUpload) tabCapUpload.addEventListener('click', () => switchCapTab('upload'));
if (tabCapCamera) tabCapCamera.addEventListener('click', () => switchCapTab('camera'));

// Xử lý chọn 1 file ảnh đại diện (Tab Upload)
if (inputSingleAvatar) {
  inputSingleAvatar.addEventListener('change', () => {
    const file = inputSingleAvatar.files[0];
    if (file) {
      setEnrollmentAvatar(file, 'Đã chọn ảnh chân dung. Hệ thống sẽ tự động tạo bộ vector embedding đa góc.');
      showToast('✓ Đã chọn ảnh chân dung!', 'success');
    }
  });
}

// Bắt đầu luồng quét liên tục Face Scan (Hướng dẫn quay nhẹ mặt: thẳng, trái, phải)
let isScanningFace   = false;
let scanTimer        = null;

function captureCurrentFrame() {
  modalCamCanvas.width = modalCamVideo.videoWidth || 480;
  modalCamCanvas.height = modalCamVideo.videoHeight || 360;
  const ctx = modalCamCanvas.getContext('2d');
  ctx.drawImage(modalCamVideo, 0, 0, modalCamCanvas.width, modalCamCanvas.height);
  return new Promise(resolve => {
    modalCamCanvas.toBlob(blob => {
      resolve(new File([blob], 'face_frame.jpg', { type: 'image/jpeg' }));
    }, 'image/jpeg', 0.92);
  });
}

function updateScanStep(percent, label, ovalClass, instruction, borderColor) {
  if (scanStepPercent) scanStepPercent.textContent = `${percent}%`;
  if (scanProgressFill) scanProgressFill.style.width = `${percent}%`;
  if (scanStepLabel) scanStepLabel.textContent = label;
  if (modalCamOval) modalCamOval.className = `face-scan-oval ${ovalClass}`;
  if (modalCamInstruction) {
    modalCamInstruction.textContent = instruction;
    modalCamInstruction.style.borderColor = borderColor;
  }
}

async function startFaceScanEnrollment() {
  if (isScanningFace) return;
  isScanningFace = true;
  faceEnrollmentData.frames = [];

  try {
    modalCameraStream = await navigator.mediaDevices.getUserMedia({ video: { width: 480, height: 360 } });
    modalCamVideo.srcObject = modalCameraStream;
    if (btnStartFaceScan) btnStartFaceScan.classList.add('hidden');
    if (btnStopFaceScan) btnStopFaceScan.classList.remove('hidden');
    if (scanProgressWrap) scanProgressWrap.classList.remove('hidden');

    // Bước 1: Nhìn thẳng mặt
    updateScanStep(20, 'Bước 1/3: Nhìn thẳng', 'scan-straight', '👤 Giữ thẳng mặt nhìn vào camera...', '#38bdf8');
    playEnrollmentBeep(520, 100);
    await new Promise(r => setTimeout(r, 1200));
    const frameFront = await captureCurrentFrame();
    faceEnrollmentData.avatarBlob = frameFront;
    faceEnrollmentData.frames.push(frameFront);
    updateScanStep(35, 'Đã lưu góc thẳng', 'scan-straight', '✓ Đã nhận diện góc thẳng! Chuẩn bị quay mặt...', '#10b981');
    playEnrollmentBeep(680, 100);

    // Bước 2: Quay nhẹ sang trái
    await new Promise(r => setTimeout(r, 600));
    updateScanStep(50, 'Bước 2/3: Quay nhẹ sang trái', 'scan-left', '👈 Quay nhẹ mặt sang TRÁI (15-30°)...', '#a855f7');
    await new Promise(r => setTimeout(r, 1200));
    const frameLeft = await captureCurrentFrame();
    faceEnrollmentData.frames.push(frameLeft);
    updateScanStep(70, 'Đã lưu góc trái', 'scan-left', '✓ Đã nhận diện góc trái! Chuẩn bị quay sang phải...', '#10b981');
    playEnrollmentBeep(680, 100);

    // Bước 3: Quay nhẹ sang phải
    await new Promise(r => setTimeout(r, 600));
    updateScanStep(85, 'Bước 3/3: Quay nhẹ sang phải', 'scan-right', '👉 Quay nhẹ mặt sang PHẢI (15-30°)...', '#ec4899');
    await new Promise(r => setTimeout(r, 1200));
    const frameRight = await captureCurrentFrame();
    faceEnrollmentData.frames.push(frameRight);
    updateScanStep(100, 'Hoàn thành quét', 'scan-success', '🎉 Hoàn tất thu nhận vector khuôn mặt!', '#10b981');
    playEnrollmentBeep(880, 150);
    setTimeout(() => playEnrollmentBeep(1050, 200), 160);

    // Hoàn tất: Dừng camera và hiển thị kết quả 1 ảnh Avatar duy nhất
    await new Promise(r => setTimeout(r, 500));
    stopModalCamera();
    setEnrollmentAvatar(frameFront, 'Đã trích xuất đủ 3–5 vector embedding đa góc (Thẳng, Nghiêng trái, Nghiêng phải) sẵn sàng lưu vào CSDL.');
    showToast('🎉 Quét khuôn mặt hoàn tất! Đã trích xuất đủ 3-5 vector embedding.', 'success');

  } catch (err) {
    showToast('Lỗi khi quét camera: ' + err.message, 'error');
    stopModalCamera();
  } finally {
    isScanningFace = false;
    if (btnStartFaceScan) {
      btnStartFaceScan.classList.remove('hidden');
      btnStartFaceScan.innerHTML = '🔄 Quét Lại Khuôn Mặt';
    }
    if (btnStopFaceScan) btnStopFaceScan.classList.add('hidden');
  }
}

if (btnStartFaceScan) {
  btnStartFaceScan.addEventListener('click', startFaceScanEnrollment);
}
if (btnStopFaceScan) {
  btnStopFaceScan.addEventListener('click', () => {
    stopModalCamera();
    showToast('Đã dừng quét khuôn mặt.', 'info');
  });
}
if (btnRescanFace) {
  btnRescanFace.addEventListener('click', () => {
    resetEnrollmentData();
    switchCapTab('camera');
    startFaceScanEnrollment();
  });
}

function stopModalCamera() {
  clearInterval(scanTimer);
  isScanningFace = false;
  if (modalCameraStream) {
    modalCameraStream.getTracks().forEach(t => t.stop());
    modalCameraStream = null;
  }
  if (btnStartFaceScan) btnStartFaceScan.classList.remove('hidden');
  if (btnStopFaceScan) btnStopFaceScan.classList.add('hidden');
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

  // Khi thêm mới: kiểm tra đã có ảnh đại diện từ camera hoặc upload chưa
  if (!empId) {
    if (!faceEnrollmentData.avatarBlob) {
      empFormAlert.textContent = 'Vui lòng quét khuôn mặt bằng Camera hoặc tải lên 1 ảnh chân dung.';
      empFormAlert.classList.remove('hidden');
      return;
    }
  }

  btnSaveEmp.disabled = true;
  btnSaveEmp.innerHTML = '<span>Đang trích xuất vector khuôn mặt...</span>';

  const formData = new FormData();
  formData.append('emp_code', empCode);
  formData.append('name', name);
  formData.append('department', dept);
  formData.append('position', pos);
  formData.append('shift_id', empFormShift ? empFormShift.value : 1);
  if (empFormPassword && empFormPassword.value.trim()) {
    formData.append('password', empFormPassword.value.trim());
  }
  if (empFormSalary) {
    formData.append('base_salary', empFormSalary.value || 9000000);
  }

  // Đính kèm ảnh đại diện chính
  if (faceEnrollmentData.avatarBlob) {
    formData.append('avatar', faceEnrollmentData.avatarBlob, 'avatar.jpg');
    formData.append('file', faceEnrollmentData.avatarBlob, 'avatar.jpg');
  }

  // Đính kèm các khung hình đã lấy mẫu trong luồng quay mặt
  if (faceEnrollmentData.frames.length > 0) {
    faceEnrollmentData.frames.forEach((frameBlob, idx) => {
      formData.append('frames', frameBlob, `frame_${idx}.jpg`);
    });
    if (faceEnrollmentData.frames[0]) formData.append('file_front', faceEnrollmentData.frames[0]);
    if (faceEnrollmentData.frames[1]) formData.append('file_left', faceEnrollmentData.frames[1]);
    if (faceEnrollmentData.frames[2]) formData.append('file_right', faceEnrollmentData.frames[2]);
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
    empFormAlert.textContent = 'Lỗi kết nối đến máy chủ.';
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
    if (log.status && (log.status.includes('Đi trễ') || log.status.includes('Đi muộn') || log.status.includes('Về sớm'))) statusClass = 'warning';
    if (log.status && (log.status.includes('Quên') || log.status.includes('Không hợp lệ'))) statusClass = 'danger';

    const locText = log.location || 'Văn phòng';
    const workHours = log.work_hours ? `${log.work_hours}h` : '—';

    return `
      <tr>
        <td style="text-align: center; color: var(--text-muted);">${index + 1}</td>
        <td><span class="code-badge">${log.emp_code}</span></td>
        <td><strong>${log.emp_name}</strong><br/><small class="text-muted">${log.department || ''}</small></td>
        <td><span style="font-size:0.8rem;font-weight:600;color:#93c5fd;">${log.shift_name || 'Ca chuẩn'}</span></td>
        <td>${log.date}</td>
        <td style="font-weight: 700; color: #34d399;">${log.time || '—'}</td>
        <td style="font-weight: 700; color: #fbbf24;">${log.check_out_time || '<span class="text-muted">—</span>'}</td>
        <td><strong>${workHours}</strong></td>
        <td style="font-size: 0.78rem; color: var(--text-secondary); max-width: 190px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${locText}">📍 ${locText}</td>
        <td><span class="tag-status ${statusClass}">${log.status || 'Đúng giờ'}</span></td>
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

// ════════════════════════════════════════════════════════════════════════════
// QUẢN LÝ CA LÀM VIỆC & PHÂN CÔNG
// ════════════════════════════════════════════════════════════════════════════
let allShifts = [];
const shiftsTbody         = document.getElementById('shifts-tbody');
const shiftModal          = document.getElementById('shift-modal');
const shiftModalTitle     = document.getElementById('shift-modal-title');
const shiftForm           = document.getElementById('shift-form');
const shiftFormId         = document.getElementById('shift-form-id');
const shiftFormName       = document.getElementById('shift-form-name');
const shiftFormStart      = document.getElementById('shift-form-start');
const shiftFormEnd        = document.getElementById('shift-form-end');
const shiftFormGrace      = document.getElementById('shift-form-grace');
const shiftFormDesc       = document.getElementById('shift-form-desc');
const employeeShiftsTbody = document.getElementById('employee-shifts-tbody');
const assignShiftEmp      = document.getElementById('assign-shift-emp');
const assignShiftId       = document.getElementById('assign-shift-id');
const assignShiftDate     = document.getElementById('assign-shift-date');
const assignShiftEnd      = document.getElementById('assign-shift-end');
const btnAssignShift      = document.getElementById('btn-assign-shift');

async function loadShifts() {
  try {
    const res = await fetch('/api/admin/shifts');
    if (!res.ok) throw new Error('Không thể tải ca làm việc');
    const data = await res.json();
    allShifts = data.shifts || [];
    renderShiftsTable(allShifts);
  } catch (err) {
    shiftsTbody.innerHTML = `<tr><td colspan="7" class="td-empty">${err.message}</td></tr>`;
  }
}

function renderShiftsTable(list) {
  if (list.length === 0) {
    shiftsTbody.innerHTML = `<tr><td colspan="7" class="td-empty">Chưa có ca làm việc nào. Hãy thêm ca mới.</td></tr>`;
    return;
  }
  shiftsTbody.innerHTML = list.map(s => `
    <tr>
      <td>${s.id}</td>
      <td><strong>${s.shift_name}</strong></td>
      <td><span class="code-badge" style="background:rgba(16,185,129,.15);color:#34d399;">${s.start_time}</span></td>
      <td><span class="code-badge" style="background:rgba(59,130,246,.15);color:#60a5fa;">${s.end_time}</span></td>
      <td>${s.grace_minutes} phút</td>
      <td>${s.description || '<span class="text-muted">—</span>'}</td>
      <td>
        <div class="action-buttons">
          <button class="btn-sm-edit" onclick="openEditShiftModal(${s.id})">Sửa</button>
          <button class="btn-sm-delete" onclick="deleteShift(${s.id}, '${s.shift_name}')">Xóa</button>
        </div>
      </td>
    </tr>
  `).join('');
}

document.getElementById('btn-open-add-shift').addEventListener('click', () => {
  shiftForm.reset();
  shiftFormId.value = '';
  shiftModalTitle.textContent = 'Thêm Ca Làm Việc';
  shiftModal.classList.remove('hidden');
});

function closeShiftModal() {
  shiftModal.classList.add('hidden');
}
document.getElementById('btn-close-shift-modal').addEventListener('click', closeShiftModal);
document.getElementById('btn-cancel-shift-modal').addEventListener('click', closeShiftModal);

function openEditShiftModal(id) {
  const s = allShifts.find(x => x.id === id);
  if (!s) return;
  shiftFormId.value = s.id;
  shiftFormName.value = s.shift_name;
  shiftFormStart.value = s.start_time;
  shiftFormEnd.value = s.end_time;
  shiftFormGrace.value = s.grace_minutes;
  shiftFormDesc.value = s.description || '';
  shiftModalTitle.textContent = 'Chỉnh Sửa Ca Làm Việc';
  shiftModal.classList.remove('hidden');
}

shiftForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const id = shiftFormId.value;
  const payload = {
    shift_name: shiftFormName.value.trim(),
    start_time: shiftFormStart.value,
    end_time: shiftFormEnd.value,
    grace_minutes: shiftFormGrace.value,
    description: shiftFormDesc.value.trim()
  };

  try {
    const url = id ? `/api/admin/shifts/${id}` : '/api/admin/shifts';
    const method = id ? 'PUT' : 'POST';
    const res = await fetch(url, {
      method: method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (res.ok) {
      showToast(data.message || 'Lưu ca thành công.', 'success');
      closeShiftModal();
      loadShifts();
      populateShiftAssignOptions();
    } else {
      showToast(data.error || 'Lỗi lưu ca.', 'error');
    }
  } catch (err) {
    showToast('Lỗi kết nối máy chủ.', 'error');
  }
});

async function deleteShift(id, name) {
  if (!confirm(`Bạn có chắc muốn xóa ca làm việc "${name}"?`)) return;
  try {
    const res = await fetch(`/api/admin/shifts/${id}`, { method: 'DELETE' });
    const data = await res.json();
    if (res.ok) {
      showToast(data.message || 'Đã xóa ca.', 'success');
      loadShifts();
      populateShiftAssignOptions();
    } else {
      showToast(data.error || 'Lỗi xóa ca.', 'error');
    }
  } catch (err) {
    showToast('Lỗi kết nối máy chủ.', 'error');
  }
}

// Gán Ca cho Nhân Viên
function populateShiftAssignOptions() {
  assignShiftEmp.innerHTML = '<option value="">-- Chọn nhân viên --</option>' +
    allEmployees.map(e => `<option value="${e.id}">${e.emp_code} - ${e.name} (${e.department || 'NV'})</option>`).join('');

  assignShiftId.innerHTML = '<option value="">-- Chọn ca --</option>' +
    allShifts.map(s => `<option value="${s.id}">${s.shift_name} (${s.start_time} - ${s.end_time})</option>`).join('');

  if (!assignShiftDate.value) {
    assignShiftDate.value = new Date().toISOString().split('T')[0];
  }
}

async function loadEmployeeShifts() {
  try {
    const res = await fetch('/api/admin/employee-shifts');
    if (!res.ok) throw new Error('Không thể tải lịch gán ca');
    const data = await res.json();
    renderEmployeeShiftsTable(data.assignments || []);
  } catch (err) {
    employeeShiftsTbody.innerHTML = `<tr><td colspan="8" class="td-empty">${err.message}</td></tr>`;
  }
}

function renderEmployeeShiftsTable(list) {
  if (list.length === 0) {
    employeeShiftsTbody.innerHTML = `<tr><td colspan="8" class="td-empty">Chưa có lịch gán ca nào.</td></tr>`;
    return;
  }
  employeeShiftsTbody.innerHTML = list.map(item => `
    <tr>
      <td><span class="code-badge">${item.emp_code}</span></td>
      <td><strong>${item.name}</strong></td>
      <td>${item.department || '<span class="text-muted">—</span>'}</td>
      <td><span style="font-weight:600;color:var(--accent);">${item.shift_name}</span></td>
      <td>${item.start_time} - ${item.end_time}</td>
      <td>${item.effective_date}</td>
      <td>${item.end_date || 'Vô thời hạn'}</td>
      <td style="text-align:center;">
        <button class="btn-sm-delete" onclick="deleteEmployeeShift(${item.id})">Xóa</button>
      </td>
    </tr>
  `).join('');
}

btnAssignShift.addEventListener('click', async () => {
  const empId = assignShiftEmp.value;
  const shiftId = assignShiftId.value;
  const effDate = assignShiftDate.value;
  const endDate = assignShiftEnd.value;

  if (!empId || !shiftId || !effDate) {
    showToast('Vui lòng chọn nhân viên, ca làm và ngày hiệu lực.', 'error');
    return;
  }

  try {
    const res = await fetch('/api/admin/employee-shifts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ emp_id: empId, shift_id: shiftId, effective_date: effDate, end_date: endDate || null })
    });
    const data = await res.json();
    if (res.ok) {
      showToast(data.message || 'Đã gán ca thành công.', 'success');
      loadEmployeeShifts();
    } else {
      showToast(data.error || 'Lỗi gán ca.', 'error');
    }
  } catch (err) {
    showToast('Lỗi kết nối máy chủ.', 'error');
  }
});

async function deleteEmployeeShift(id) {
  if (!confirm('Xóa lịch gán ca này?')) return;
  try {
    const res = await fetch(`/api/admin/employee-shifts/${id}`, { method: 'DELETE' });
    const data = await res.json();
    if (res.ok) {
      showToast(data.message || 'Đã xóa gán ca.', 'success');
      loadEmployeeShifts();
    }
  } catch (err) {
    showToast('Lỗi kết nối.', 'error');
  }
}

// ════════════════════════════════════════════════════════════════════════════
// DUYỆT ĐƠN NGHỈ PHÉP
// ════════════════════════════════════════════════════════════════════════════
let allLeaveRequests = [];
const leavesTbody       = document.getElementById('leaves-tbody');
const leaveStatusFilter = document.getElementById('leave-status-filter');
const btnRefreshLeaves  = document.getElementById('btn-refresh-leaves');

async function loadLeaveRequests() {
  try {
    const status = leaveStatusFilter.value;
    const url = status ? `/api/admin/leave-requests?status=${encodeURIComponent(status)}` : '/api/admin/leave-requests';
    const res = await fetch(url);
    if (!res.ok) throw new Error('Không thể tải danh sách đơn');
    const data = await res.json();
    allLeaveRequests = data.requests || [];
    renderLeaveRequestsTable(allLeaveRequests);
  } catch (err) {
    leavesTbody.innerHTML = `<tr><td colspan="10" class="td-empty">${err.message}</td></tr>`;
  }
}

function renderLeaveRequestsTable(list) {
  if (list.length === 0) {
    leavesTbody.innerHTML = `<tr><td colspan="10" class="td-empty">Không có đơn xin nghỉ phép nào.</td></tr>`;
    return;
  }

  leavesTbody.innerHTML = list.map(req => {
    let statusBadge = '';
    if (req.status === 'Đã duyệt') {
      statusBadge = '<span class="status-badge valid">Đã duyệt</span>';
    } else if (req.status === 'Từ chối') {
      statusBadge = '<span class="status-badge invalid">Từ chối</span>';
    } else {
      statusBadge = '<span class="status-badge late">Chờ duyệt</span>';
    }

    const faceBadge = req.face_verified
      ? `<div style="margin-top:3px;font-size:0.72rem;color:#34d399;font-weight:600;">✓ Xác thực FaceID (${req.face_similarity ? (req.face_similarity * 100).toFixed(1) + '%' : 'Hợp lệ'})</div>`
      : '';

    const dateRange = (req.end_leave_date && req.end_leave_date !== req.leave_date)
      ? `${req.leave_date} → ${req.end_leave_date} <br/><small class="text-muted">(${req.days_count || 1} ngày)</small>`
      : `${req.leave_date} <br/><small class="text-muted">(${req.days_count || 1} ngày)</small>`;

    const reviewerInfo = req.reviewer_name
      ? `${req.reviewer_name} <br/><small class="text-muted">${req.reviewed_at || ''}</small>`
      : '<span class="text-muted">—</span>';

    const actions = req.status === 'Chờ duyệt' ? `
      <div class="action-buttons">
        <button class="btn-sm-edit" style="background:#10b981;border-color:#10b981;color:#fff;" onclick="quickReviewLeave(${req.id}, 'approve')">Duyệt</button>
        <button class="btn-sm-delete" onclick="quickReviewLeave(${req.id}, 'reject')">Từ Chối</button>
      </div>
    ` : '<span class="text-muted">Đã xử lý</span>';

    return `
      <tr>
        <td>${req.id}</td>
        <td><span class="code-badge">${req.emp_code}</span></td>
        <td><strong>${req.emp_name}</strong>${faceBadge}</td>
        <td><span style="font-weight:600;color:var(--accent);">${req.leave_type}</span></td>
        <td>${req.request_date}</td>
        <td><strong style="color:#60a5fa;">${dateRange}</strong></td>
        <td>${req.reason || '<span class="text-muted">—</span>'}</td>
        <td>${statusBadge}</td>
        <td>${reviewerInfo}</td>
        <td style="text-align:center;">${actions}</td>
      </tr>
    `;
  }).join('');
}

leaveStatusFilter.addEventListener('change', loadLeaveRequests);
btnRefreshLeaves.addEventListener('click', loadLeaveRequests);

async function quickReviewLeave(requestId, action) {
  const actionText = action === 'approve' ? 'Phê duyệt' : 'Từ chối';
  const note = prompt(`Nhập ghi chú cho việc ${actionText} đơn (có thể để trống):`, '');
  if (note === null) return; // Hủy bấm Cancel

  try {
    const res = await fetch(`/api/admin/leave-requests/${requestId}/review`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: action, note: note })
    });
    const data = await res.json();
    if (res.ok) {
      showToast(data.message || 'Đã cập nhật trạng thái đơn.', 'success');
      loadLeaveRequests();
    } else {
      showToast(data.error || 'Lỗi xử lý đơn.', 'error');
    }
  } catch (err) {
    showToast('Lỗi kết nối máy chủ.', 'error');
  }
}

// ════════════════════════════════════════════════════════════════════════════
// THỐNG KÊ BÁO CÁO
// ════════════════════════════════════════════════════════════════════════════
let currentStatsPeriod = 'day';
const statsFilterBtns   = document.querySelectorAll('.stats-filter-btn');
const statsDateWrap     = document.getElementById('stats-date-wrap');
const statsWeekWrap     = document.getElementById('stats-week-wrap');
const statsMonthWrap    = document.getElementById('stats-month-wrap');
const statsDateInput    = document.getElementById('stats-date-input');
const statsWeekStart    = document.getElementById('stats-week-start');
const statsWeekEnd      = document.getElementById('stats-week-end');
const statsMonthInput   = document.getElementById('stats-month-input');
const statsDeptFilter   = document.getElementById('stats-dept-filter');
const btnLoadStats      = document.getElementById('btn-load-stats');
const statOntimeRate    = document.getElementById('stat-ontime-rate');
const statOntimeCount   = document.getElementById('stat-ontime-count');
const statLateCount     = document.getElementById('stat-late-count');
const statAbsentCount   = document.getElementById('stat-absent-count');
const statLeaveCount    = document.getElementById('stat-leave-count');
const statsDeptTbody    = document.getElementById('stats-dept-tbody');

// Đặt ngày mặc định cho thống kê
const statsTodayStr = new Date().toISOString().split('T')[0];
statsDateInput.value = statsTodayStr;
statsMonthInput.value = statsTodayStr.substring(0, 7);

// Tính đầu tuần và cuối tuần hiện tại
const currD = new Date();
const firstDayOfWeek = new Date(currD.setDate(currD.getDate() - currD.getDay() + 1));
const lastDayOfWeek  = new Date(currD.setDate(currD.getDate() - currD.getDay() + 7));
statsWeekStart.value = firstDayOfWeek.toISOString().split('T')[0];
statsWeekEnd.value   = lastDayOfWeek.toISOString().split('T')[0];

statsFilterBtns.forEach(btn => {
  btn.addEventListener('click', () => {
    statsFilterBtns.forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    currentStatsPeriod = btn.dataset.type;

    statsDateWrap.classList.add('hidden');
    statsWeekWrap.classList.add('hidden');
    statsMonthWrap.classList.add('hidden');

    if (currentStatsPeriod === 'day') statsDateWrap.classList.remove('hidden');
    else if (currentStatsPeriod === 'week') statsWeekWrap.classList.remove('hidden');
    else if (currentStatsPeriod === 'month') statsMonthWrap.classList.remove('hidden');
  });
});

function populateStatsDeptOptions() {
  const depts = [...new Set(allEmployees.map(e => e.department).filter(Boolean))];
  statsDeptFilter.innerHTML = '<option value="all">Tất cả phòng ban</option>' +
    depts.map(d => `<option value="${d}">${d}</option>`).join('');
}

async function loadAdvancedStats() {
  let url = `/api/admin/statistics?filter_type=${currentStatsPeriod}`;
  if (currentStatsPeriod === 'day') url += `&date=${statsDateInput.value}`;
  else if (currentStatsPeriod === 'week') url += `&start_date=${statsWeekStart.value}&end_date=${statsWeekEnd.value}`;
  else if (currentStatsPeriod === 'month') url += `&date=${statsMonthInput.value}`;

  const dept = statsDeptFilter.value;
  if (dept && dept !== 'all') url += `&department=${encodeURIComponent(dept)}`;

  try {
    const res = await fetch(url);
    if (!res.ok) throw new Error('Không thể tải thống kê');
    const data = await res.json();

    const statEarlyCount = document.getElementById('stat-early-count');
    statOntimeRate.textContent = `${data.on_time_rate}%`;
    statOntimeCount.textContent = data.on_time;
    statLateCount.textContent = data.late;
    if (statEarlyCount) statEarlyCount.textContent = data.early || 0;
    statAbsentCount.textContent = data.absent;
    statLeaveCount.textContent = data.approved_leave;

    // Render bảng phân bổ phòng ban (Yêu cầu B1: có Về sớm)
    const byDept = data.by_dept || {};
    const deptKeys = Object.keys(byDept);
    if (deptKeys.length === 0) {
      statsDeptTbody.innerHTML = `<tr><td colspan="6" class="td-empty">Không có lượt chấm công nào trong kỳ này.</td></tr>`;
    } else {
      statsDeptTbody.innerHTML = deptKeys.map(d => {
        const item = byDept[d];
        const rate = item.total > 0 ? ((item.on_time / item.total) * 100).toFixed(1) : '0.0';
        return `
          <tr>
            <td><strong>${d}</strong></td>
            <td style="text-align:center;color:#10b981;font-weight:700;">${item.on_time}</td>
            <td style="text-align:center;color:#f59e0b;font-weight:700;">${item.late}</td>
            <td style="text-align:center;color:#f97316;font-weight:700;">${item.early || 0}</td>
            <td style="text-align:center;">${item.total}</td>
            <td style="text-align:center;"><strong style="color:${rate >= 80 ? '#10b981' : '#f59e0b'};">${rate}%</strong></td>
          </tr>
        `;
      }).join('');
    }
  } catch (err) {
    showToast(err.message, 'error');
  }
}

btnLoadStats.addEventListener('click', loadAdvancedStats);


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
