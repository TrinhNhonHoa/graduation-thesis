/**
 * FaceID Attendance System — Employee Portal & Live Cam Controller
 * Hỗ trợ:
 * 1. Quét mặt Vào ca (Check-in) & Ra ca (Check-out) kèm ghi nhận vị trí GPS, thời gian, ca làm.
 * 2. Nộp đơn xin nghỉ phép (bắt buộc trước >= 3 ngày & chụp mặt xác thực trực tiếp qua Camera).
 * 3. Xem số ngày công và bảng lương cá nhân theo tháng.
 */

// ── Biến trạng thái ──────────────────────────────────────────────────────────
let videoStream = null;
let isProcessingFrame = false;
let scanIntervalId = null;
let soundEnabled = true;
let currentFacingMode = 'user';
let lastMatchedCode = null;
let lastMatchedTime = 0;
let popupHideTimer = null;

// Chế độ chấm công hiện tại ('checkin' | 'checkout')
let currentAttendanceMode = 'checkin';
// Tọa độ / Vị trí GPS hiện tại
let currentGpsLocation = 'Văn phòng Công ty (Mặc định)';
// Tab hiện tại của cổng nhân viên ('attendance' | 'leave' | 'payroll')
let currentEmpTab = 'attendance';

// ── DOM Elements ────────────────────────────────────────────────────────────
const videoEl        = document.getElementById('kiosk-video');
const canvasEl       = document.getElementById('kiosk-canvas');
const camDot         = document.getElementById('cam-dot');
const camStatusText  = document.getElementById('cam-status-text');
const btnSwitchCam   = document.getElementById('btn-switch-camera');
const btnToggleSound = document.getElementById('btn-toggle-sound');
const soundIcon      = document.getElementById('sound-icon');
const matchPopup     = document.getElementById('match-popup');
const popupName      = document.getElementById('popup-name');
const popupCode      = document.getElementById('popup-code');
const popupDept      = document.getElementById('popup-dept');
const popupTime      = document.getElementById('popup-time');
const popupSim       = document.getElementById('popup-sim');
const popupSimBar    = document.getElementById('popup-sim-bar');
const popupAvatar    = document.getElementById('popup-avatar');
const mismatchBadge  = document.getElementById('mismatch-badge');
const mismatchText   = document.getElementById('mismatch-text');
const unregisteredBadge = document.getElementById('unregistered-badge');
let unregisteredHideTimer = null;
const cooldownWarningBadge = document.getElementById('cooldown-warning-badge');
const cooldownWarningText  = document.getElementById('cooldown-warning-text');
const popupStatusPill      = document.getElementById('popup-status-pill');
let cooldownHideTimer = null;
const hudGuide       = document.getElementById('hud-guide');

// Mode buttons & Today status
const btnModeCheckin   = document.getElementById('btn-mode-checkin');
const btnModeCheckout  = document.getElementById('btn-mode-checkout');
const todayCheckinEl   = document.getElementById('today-checkin-time');
const todayCheckoutEl  = document.getElementById('today-checkout-time');
const todayWorkHoursEl = document.getElementById('today-work-hours');
const latestStatus     = document.getElementById('latest-status');
const cardStatusBadge  = document.getElementById('card-status-badge');

// GPS Location elements
const gpsLocationText  = document.getElementById('gps-location-text');
const empLocDisplay    = document.getElementById('emp-loc-display');

// Canvas theo dấu khuôn mặt (Face Tracking Overlay)
const trackingCanvas = document.getElementById('face-tracking-canvas');
let clearTrackingTimer = null;

function drawFaceBox(box, label, color = '#10b981') {
  if (!trackingCanvas || !videoEl || !box) return;
  const ctx = trackingCanvas.getContext('2d');

  const rect = videoEl.getBoundingClientRect();
  trackingCanvas.width = rect.width;
  trackingCanvas.height = rect.height;

  ctx.clearRect(0, 0, trackingCanvas.width, trackingCanvas.height);

  const scaleX = rect.width / (canvasEl.width || 480);
  const scaleY = rect.height / (canvasEl.height || 360);

  const x1 = box[0] * scaleX;
  const y1 = box[1] * scaleY;
  const w = (box[2] - box[0]) * scaleX;
  const h = (box[3] - box[1]) * scaleY;

  ctx.save();
  ctx.strokeStyle = color;
  ctx.lineWidth = 2.5;
  ctx.shadowColor = color;
  ctx.shadowBlur = 8;

  ctx.beginPath();
  if (ctx.roundRect) {
    ctx.roundRect(x1, y1, w, h, 6);
  } else {
    ctx.rect(x1, y1, w, h);
  }
  ctx.stroke();

  const cLen = Math.min(18, w * 0.25, h * 0.25);
  ctx.lineWidth = 4;
  ctx.beginPath();
  ctx.moveTo(x1, y1 + cLen); ctx.lineTo(x1, y1); ctx.lineTo(x1 + cLen, y1);
  ctx.moveTo(x1 + w - cLen, y1); ctx.lineTo(x1 + w, y1); ctx.lineTo(x1 + w, y1 + cLen);
  ctx.moveTo(x1, y1 + h - cLen); ctx.lineTo(x1, y1 + h); ctx.lineTo(x1 + cLen, y1 + h);
  ctx.moveTo(x1 + w - cLen, y1 + h); ctx.lineTo(x1 + w, y1 + h); ctx.lineTo(x1 + w, y1 + h - cLen);
  ctx.stroke();

  if (label) {
    ctx.shadowBlur = 0;
    ctx.font = 'bold 13px Inter, sans-serif';
    const tagWidth = ctx.measureText(label).width + 16;
    const tagH = 24;
    const tagX = Math.max(0, x1);
    const tagY = Math.max(0, y1 - tagH - 4);

    ctx.fillStyle = color;
    ctx.beginPath();
    if (ctx.roundRect) ctx.roundRect(tagX, tagY, tagWidth, tagH, 4);
    else ctx.rect(tagX, tagY, tagWidth, tagH);
    ctx.fill();

    ctx.fillStyle = '#ffffff';
    ctx.fillText(label, tagX + 8, tagY + 16);
  }

  ctx.restore();

  clearTimeout(clearTrackingTimer);
  clearTrackingTimer = setTimeout(() => {
    ctx.clearRect(0, 0, trackingCanvas.width, trackingCanvas.height);
  }, 450);
}

function clearFaceBox() {
  if (!trackingCanvas) return;
  const ctx = trackingCanvas.getContext('2d');
  ctx.clearRect(0, 0, trackingCanvas.width, trackingCanvas.height);
}

// ── Đồng hồ thực tế ──────────────────────────────────────────────────────────
function updateClock() {
  const now = new Date();
  const timeStr = now.toLocaleTimeString('vi-VN', { hour12: false });
  const days = ['Chủ Nhật', 'Thứ Hai', 'Thứ Ba', 'Thứ Tư', 'Thứ Năm', 'Thứ Sáu', 'Thứ Bảy'];
  const dayName = days[now.getDay()];
  const dateStr = `${dayName}, ${String(now.getDate()).padStart(2, '0')}/${String(now.getMonth() + 1).padStart(2, '0')}/${now.getFullYear()}`;

  const ct = document.getElementById('clock-time');
  const cd = document.getElementById('clock-date');
  if (ct) ct.textContent = timeStr;
  if (cd) cd.textContent = dateStr;
}
setInterval(updateClock, 1000);
updateClock();

// ── Định vị GPS (Geolocation API) ────────────────────────────────────────────
function initGeolocation() {
  if (!navigator.geolocation) {
    setLocationDisplay('Trình duyệt không hỗ trợ GPS (Văn phòng)');
    return;
  }

  navigator.geolocation.getCurrentPosition(
    async (pos) => {
      const lat = pos.coords.latitude.toFixed(5);
      const lon = pos.coords.longitude.toFixed(5);
      let locStr = `GPS: ${lat}, ${lon}`;
      setLocationDisplay(locStr);

      try {
        const res = await fetch(`https://nominatim.openstreetmap.org/reverse?format=json&lat=${lat}&lon=${lon}&zoom=16`);
        if (res.ok) {
          const data = await res.json();
          if (data && data.display_name) {
            const shortAddr = data.display_name.split(',').slice(0, 3).join(',');
            locStr = `${shortAddr} (${lat}, ${lon})`;
            setLocationDisplay(locStr);
          }
        }
      } catch (e) {
        // Giữ nguyên tọa độ GPS nếu không gọi được reverse geocode
      }
    },
    (err) => {
      console.warn('Geolocation warning:', err.message);
      setLocationDisplay('Tại Văn phòng (Web Terminal)');
    },
    { enableHighAccuracy: true, timeout: 8000, maximumAge: 60000 }
  );
}

function setLocationDisplay(locText) {
  currentGpsLocation = locText;
  if (gpsLocationText) gpsLocationText.textContent = locText;
  if (empLocDisplay) empLocDisplay.textContent = locText;
}

// ── Chuyển đổi Chế độ Check-in / Check-out ───────────────────────────────────
function setAttendanceMode(mode) {
  currentAttendanceMode = mode;
  if (mode === 'checkout') {
    if (btnModeCheckout) btnModeCheckout.className = 'mode-switch-btn active-checkout';
    if (btnModeCheckin) btnModeCheckin.className = 'mode-switch-btn';
    if (hudGuide) hudGuide.textContent = 'Đưa khuôn mặt vào khung hình để QUÉT RA CA (CHECK-OUT)';
  } else {
    if (btnModeCheckin) btnModeCheckin.className = 'mode-switch-btn active-checkin';
    if (btnModeCheckout) btnModeCheckout.className = 'mode-switch-btn';
    if (hudGuide) hudGuide.textContent = 'Đưa khuôn mặt vào khung hình để QUÉT VÀO CA (CHECK-IN)';
  }
}

if (btnModeCheckin) btnModeCheckin.addEventListener('click', () => setAttendanceMode('checkin'));
if (btnModeCheckout) btnModeCheckout.addEventListener('click', () => setAttendanceMode('checkout'));

// ── Chuyển đổi Tab Cổng Nhân Viên ────────────────────────────────────────────
const empTabBtns          = document.querySelectorAll('.emp-tab-btn');
const empMainWorkspace    = document.getElementById('emp-main-workspace');
const empPayrollWorkspace = document.getElementById('emp-payroll-workspace');
const rightPanelAtt       = document.getElementById('right-panel-attendance');
const rightPanelLeave     = document.getElementById('right-panel-leave');

empTabBtns.forEach(btn => {
  btn.addEventListener('click', () => {
    empTabBtns.forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    currentEmpTab = btn.dataset.empTab;

    if (currentEmpTab === 'payroll') {
      if (empMainWorkspace) empMainWorkspace.classList.add('hidden');
      if (empPayrollWorkspace) empPayrollWorkspace.classList.remove('hidden');
      loadEmployeePayroll();
    } else {
      if (empMainWorkspace) empMainWorkspace.classList.remove('hidden');
      if (empPayrollWorkspace) empPayrollWorkspace.classList.add('hidden');

      if (currentEmpTab === 'leave') {
        if (rightPanelAtt) rightPanelAtt.classList.add('hidden');
        if (rightPanelLeave) rightPanelLeave.classList.remove('hidden');
        if (hudGuide) hudGuide.textContent = 'Nhìn thẳng vào camera khi bấm "Quét Mặt Xác Thực & Gửi Đơn"';
        loadMyLeaveRequests();
      } else {
        if (rightPanelAtt) rightPanelAtt.classList.remove('hidden');
        if (rightPanelLeave) rightPanelLeave.classList.add('hidden');
        setAttendanceMode(currentAttendanceMode);
      }
    }
  });
});

// ── Web Audio API: Âm thanh thông báo ───────────────────────────────────────
let audioCtx = null;
function playSuccessBeep() {
  if (!soundEnabled) return;
  try {
    if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    if (audioCtx.state === 'suspended') audioCtx.resume();

    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();

    osc.type = 'sine';
    osc.frequency.setValueAtTime(587.33, audioCtx.currentTime);
    osc.frequency.exponentialRampToValueAtTime(880, audioCtx.currentTime + 0.15);

    gain.gain.setValueAtTime(0.2, audioCtx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + 0.25);

    osc.connect(gain);
    gain.connect(audioCtx.destination);

    osc.start();
    osc.stop(audioCtx.currentTime + 0.25);
  } catch (e) {
    console.warn('Audio play error:', e);
  }
}

// ── Khởi động Camera ────────────────────────────────────────────────────────
async function startCamera() {
  if (videoStream) {
    videoStream.getTracks().forEach(track => track.stop());
  }

  camStatusText.textContent = 'Đang mở máy ảnh...';
  camDot.className = 'cam-dot warn';

  try {
    const constraints = {
      video: {
        width: { ideal: 640 },
        height: { ideal: 480 },
        facingMode: currentFacingMode
      },
      audio: false
    };

    videoStream = await navigator.mediaDevices.getUserMedia(constraints);
    videoEl.srcObject = videoStream;

    await new Promise(resolve => {
      videoEl.onloadedmetadata = () => {
        videoEl.play();
        resolve();
      };
    });

    camStatusText.textContent = 'Camera sẵn sàng · Đang quét';
    camDot.className = 'cam-dot live';
    startContinuousScanning();
  } catch (err) {
    console.error('Camera error:', err);
    camStatusText.textContent = 'Không thể truy cập camera';
    camDot.className = 'cam-dot';
    hudGuide.textContent = 'Vui lòng cấp quyền truy cập Camera trong trình duyệt.';
  }
}

// ── Quét và Nhận dạng liên tục (350ms) ──────────────────────────────────────
function startContinuousScanning() {
  if (scanIntervalId) clearInterval(scanIntervalId);
  scanIntervalId = setInterval(captureAndRecognize, 350);
}

async function captureFrameBlob() {
  if (!videoStream || videoEl.readyState < 2) return null;
  const targetW = 480;
  const targetH = 360;
  canvasEl.width = targetW;
  canvasEl.height = targetH;
  const ctx = canvasEl.getContext('2d');
  ctx.drawImage(videoEl, 0, 0, targetW, targetH);
  return await new Promise(resolve => canvasEl.toBlob(resolve, 'image/jpeg', 0.85));
}

async function captureAndRecognize() {
  // Chỉ tự động quét chấm công khi đang ở tab Chấm công ('attendance')
  if (currentEmpTab !== 'attendance') return;
  if (isProcessingFrame || !videoStream || videoEl.readyState < 2) return;

  isProcessingFrame = true;

  try {
    const blob = await captureFrameBlob();
    if (!blob) {
      isProcessingFrame = false;
      return;
    }

    const formData = new FormData();
    formData.append('file', blob, 'frame.jpg');
    formData.append('mode', currentAttendanceMode);
    formData.append('location', currentGpsLocation);

    const res = await fetch('/api/attendance/recognize', {
      method: 'POST',
      body: formData
    });

    if (res.ok) {
      const data = await res.json();
      handleRecognitionResult(data);
    }
  } catch (err) {
    console.warn('Frame recognition error:', err);
  } finally {
    isProcessingFrame = false;
  }
}

// ── Xử lý kết quả nhận dạng ─────────────────────────────────────────────────
const spoofWarningBadge = document.getElementById('spoof-warning-badge');
const spoofWarningText  = document.getElementById('spoof-warning-text');
const popupLiveness     = document.getElementById('popup-liveness');
let spoofHideTimer = null;

function handleRecognitionResult(data) {
  const now = Date.now();

  if (!data.box) {
    clearFaceBox();
  }

  // 1. PHÁT HIỆN GIẢ MẠO (ANTI-SPOOFING)
  if (data.is_spoof) {
    drawFaceBox(data.box, '🚫 GIẢ MẠO!', '#ef4444');
    matchPopup.classList.add('hidden');
    mismatchBadge.classList.add('hidden');

    spoofWarningText.textContent = `⚠️ PHÁT HIỆN GIẢ MẠO (Độ sống: ${data.liveness_pct}%) - ${data.message}`;
    spoofWarningBadge.classList.remove('hidden');

    clearTimeout(spoofHideTimer);
    spoofHideTimer = setTimeout(() => {
      spoofWarningBadge.classList.add('hidden');
    }, 2500);
    return;
  }

  // 2. KHUÔN MẶT KHÔNG KHỚP VỚI TÀI KHOẢN ĐANG ĐĂNG NHẬP (CHỐNG CHẤM CÔNG HỘ)
  if (data.wrong_account) {
    drawFaceBox(data.box, '🚫 Sai tài khoản NV!', '#ef4444');
    matchPopup.classList.add('hidden');
    if (unregisteredBadge) {
      const unregText = document.getElementById('unregistered-text');
      if (unregText) unregText.textContent = data.message;
      unregisteredBadge.classList.remove('hidden');
      clearTimeout(unregisteredHideTimer);
      unregisteredHideTimer = setTimeout(() => {
        unregisteredBadge.classList.add('hidden');
      }, 3500);
    }
    return;
  }

  // 3. COOLDOWN 3 PHÚT HOẶC CHƯA CHECK-IN MÀ BẤM CHECK-OUT
  if (data.matched && data.already_checked_in) {
    drawFaceBox(data.box, `${data.name} (Đã ghi nhận)`, '#ea580c');
    matchPopup.classList.add('hidden');
    mismatchBadge.classList.add('hidden');
    spoofWarningBadge.classList.add('hidden');
    if (unregisteredBadge) unregisteredBadge.classList.add('hidden');

    if (cooldownWarningBadge && cooldownWarningText) {
      cooldownWarningText.textContent = data.message || `⚠️ Bạn vừa thao tác rồi! Vui lòng chờ giây lát.`;
      cooldownWarningBadge.classList.remove('hidden');
      clearTimeout(cooldownHideTimer);
      cooldownHideTimer = setTimeout(() => {
        cooldownWarningBadge.classList.add('hidden');
      }, 3500);
    }
    return;
  }

  // 4. ĐIỂM DANH VÀO CA / RA CA THÀNH CÔNG
  if (data.matched && !data.already_checked_in) {
    if (cooldownWarningBadge) cooldownWarningBadge.classList.add('hidden');
    mismatchBadge.classList.add('hidden');
    spoofWarningBadge.classList.add('hidden');
    if (unregisteredBadge) unregisteredBadge.classList.add('hidden');

    const empCode = data.emp_code;
    const empName = data.name;
    const simPct  = data.similarity_pct;
    const livePct = data.liveness_pct || 92;
    const attStatus = data.attendance_status || 'Đúng giờ';
    const checkType = data.check_type || 'Vào ca';
    const isLateOrEarly = (attStatus === 'Đi trễ' || attStatus === 'Đi muộn' || attStatus === 'Về sớm');

    const boxColor = isLateOrEarly ? '#f59e0b' : '#10b981';
    drawFaceBox(data.box, `${empName} - ${checkType} (${attStatus})`, boxColor);

    if (empCode !== lastMatchedCode || (now - lastMatchedTime) > 5000) {
      playSuccessBeep();
      lastMatchedCode = empCode;
      lastMatchedTime = now;
    }

    popupName.textContent = empName;
    popupCode.textContent = empCode;
    popupDept.textContent = `${data.shift_name || 'Ca chuẩn'} · ${checkType}`;
    popupTime.textContent = data.time || '';
    popupSim.textContent = `${simPct}%`;
    popupSimBar.style.width = `${Math.min(simPct, 100)}%`;
    if (popupLiveness) {
      popupLiveness.textContent = `Liveness: ${livePct}% ✓`;
    }

    if (data.avatar_file) {
      popupAvatar.innerHTML = `<img src="/api/avatar/${data.avatar_file}" alt="${empName}" />`;
    } else {
      popupAvatar.textContent = empName.charAt(0).toUpperCase();
    }

    const popupBadge = document.getElementById('popup-badge');
    const popupBadgeText = document.getElementById('popup-badge-text');

    if (popupBadge && popupBadgeText) {
      if (isLateOrEarly) {
        popupBadge.className = 'popup-badge warning';
        popupBadgeText.textContent = `${checkType.toUpperCase()}: ${attStatus.toUpperCase()} ⚠️`;
      } else {
        popupBadge.className = 'popup-badge success';
        popupBadgeText.textContent = `${checkType.toUpperCase()}: ${attStatus.toUpperCase()} ✓`;
      }
    }

    if (popupStatusPill) {
      popupStatusPill.textContent = `${checkType}: ${attStatus}`;
      popupStatusPill.style.background = isLateOrEarly ? '#f59e0b' : '#10b981';
    }

    matchPopup.classList.remove('hidden');

    // Cập nhật thẻ trạng thái hôm nay bên cột phải
    if (checkType === 'Vào ca' && todayCheckinEl) {
      todayCheckinEl.textContent = data.time;
    }
    if (checkType === 'Ra ca') {
      if (todayCheckoutEl) todayCheckoutEl.textContent = data.time;
      if (todayWorkHoursEl && data.work_hours !== undefined) {
        todayWorkHoursEl.textContent = `${data.work_hours} giờ`;
      }
    }
    if (latestStatus) {
      latestStatus.textContent = `${checkType} - ${attStatus}`;
      latestStatus.style.color = isLateOrEarly ? '#f59e0b' : 'var(--success-light)';
    }
    if (cardStatusBadge) {
      cardStatusBadge.textContent = `${checkType}: ${attStatus}`;
      cardStatusBadge.style.color = isLateOrEarly ? '#f59e0b' : 'var(--success-light)';
    }

    clearTimeout(popupHideTimer);
    popupHideTimer = setTimeout(() => {
      matchPopup.classList.add('hidden');
    }, 4000);

  } else {
    // 5. CHƯA ĐẠT NGƯỠNG HOẶC CHƯA ĐĂNG KÝ
    matchPopup.classList.add('hidden');
    spoofWarningBadge.classList.add('hidden');

    if (data.unregistered) {
      drawFaceBox(data.box, 'Chưa đăng ký', '#ef4444');
      if (unregisteredBadge) {
        const unregText = document.getElementById('unregistered-text');
        if (unregText) unregText.textContent = data.message || '⚠️ Khuôn mặt chưa được đăng ký trong hệ thống!';
        unregisteredBadge.classList.remove('hidden');
        mismatchBadge.classList.add('hidden');
        clearTimeout(unregisteredHideTimer);
        unregisteredHideTimer = setTimeout(() => {
          unregisteredBadge.classList.add('hidden');
        }, 3500);
      }
    } else if (data.similarity_pct && data.similarity_pct > 20) {
      drawFaceBox(data.box, 'Đang nhận diện...', '#38bdf8');
      if (unregisteredBadge) unregisteredBadge.classList.add('hidden');
      mismatchText.textContent = `Độ khớp thấp (${data.similarity_pct}%). Vui lòng nhìn thẳng camera.`;
      mismatchBadge.classList.remove('hidden');
      setTimeout(() => mismatchBadge.classList.add('hidden'), 1800);
    } else if (data.box) {
      drawFaceBox(data.box, 'Khuôn mặt', '#94a3b8');
    }
  }
}

// ── Event Handlers Camera & Sound ───────────────────────────────────────────
btnSwitchCam.addEventListener('click', () => {
  currentFacingMode = currentFacingMode === 'user' ? 'environment' : 'user';
  startCamera();
});

btnToggleSound.addEventListener('click', () => {
  soundEnabled = !soundEnabled;
  soundIcon.textContent = soundEnabled ? '🔊' : '🔇';
});

const livenessPill = document.getElementById('liveness-status-pill');
const livenessBadgeText = document.getElementById('liveness-badge-text');
const livenessDot = document.getElementById('liveness-dot');

if (livenessPill) {
  livenessPill.addEventListener('click', async () => {
    try {
      const res = await fetch('/api/config/liveness', { method: 'POST' });
      const data = await res.json();
      if (data.enabled) {
        livenessBadgeText.textContent = 'BẬT ✓';
        livenessDot.style.background = '#06b6d4';
        livenessDot.style.boxShadow = '0 0 8px #06b6d4';
      } else {
        livenessBadgeText.textContent = 'TẮT ✕';
        livenessDot.style.background = '#94a3b8';
        livenessDot.style.boxShadow = 'none';
      }
    } catch (e) {
      console.warn('Toggle liveness error:', e);
    }
  });
}

// ════════════════════════════════════════════════════════════════════════════
// TAB 2: NỘP ĐƠN XIN NGHỈ PHÉP (TRƯỚC >= 3 NGÀY & QUÉT MẶT XÁC THỰC)
// ════════════════════════════════════════════════════════════════════════════
const btnSubmitLeave     = document.getElementById('btn-submit-leave');
const leaveType          = document.getElementById('leave-type');
const leaveDate          = document.getElementById('leave-date');
const leaveEndDate       = document.getElementById('leave-end-date');
const leaveReason        = document.getElementById('leave-reason');
const leaveResult        = document.getElementById('leave-result');
const lookupResultsList  = document.getElementById('lookup-results-list');
const btnRefreshMyLeaves = document.getElementById('btn-refresh-my-leaves');

// Thiết lập ngày tối thiểu = Hôm nay + 3 ngày
function initLeaveMinDate() {
  const minD = new Date();
  minD.setDate(minD.getDate() + 3);
  const minStr = minD.toISOString().split('T')[0];
  if (leaveDate) {
    leaveDate.min = minStr;
    leaveDate.value = minStr;
  }
  if (leaveEndDate) {
    leaveEndDate.min = minStr;
    leaveEndDate.value = minStr;
  }
}
initLeaveMinDate();

if (leaveDate && leaveEndDate) {
  leaveDate.addEventListener('change', () => {
    if (leaveEndDate.value < leaveDate.value) {
      leaveEndDate.value = leaveDate.value;
    }
    leaveEndDate.min = leaveDate.value;
  });
}

if (btnSubmitLeave) {
  btnSubmitLeave.addEventListener('click', async () => {
    const type = leaveType.value;
    const startDate = leaveDate.value;
    const endDate = leaveEndDate ? (leaveEndDate.value || startDate) : startDate;
    const reason = leaveReason.value.trim();

    if (!startDate || !reason) {
      leaveResult.innerHTML = '<span style="color:#ef4444;">⚠️ Vui lòng chọn ngày nghỉ và nhập lý do chi tiết.</span>';
      return;
    }

    // Kiểm tra nhanh phía client: ngày nghỉ >= hôm nay + 3 ngày
    const today0 = new Date();
    today0.setHours(0, 0, 0, 0);
    const leaveD0 = new Date(startDate + 'T00:00:00');
    const diffDays = Math.round((leaveD0 - today0) / (1000 * 60 * 60 * 24));
    if (diffDays < 3) {
      leaveResult.innerHTML = `<span style="color:#ef4444;">✕ Quy định: Ngày nộp đơn phải trước ngày nghỉ ít nhất 3 ngày (Hiện tại chỉ cách ${diffDays} ngày).</span>`;
      return;
    }

    // Chụp khung hình khuôn mặt từ Camera để xác thực danh tính
    const faceBlob = await captureFrameBlob();
    if (!faceBlob) {
      leaveResult.innerHTML = '<span style="color:#ef4444;">⚠️ Camera chưa sẵn sàng! Vui lòng bật Camera để quét mặt xác thực khi nộp đơn.</span>';
      return;
    }

    btnSubmitLeave.disabled = true;
    btnSubmitLeave.innerHTML = '<span>⏳ Đang quét mặt xác thực & gửi đơn...</span>';
    leaveResult.innerHTML = '';

    try {
      const formData = new FormData();
      formData.append('leave_type', type);
      formData.append('leave_date', startDate);
      formData.append('end_leave_date', endDate);
      formData.append('reason', reason);
      formData.append('file', faceBlob, 'leave_face_verify.jpg');

      const res = await fetch('/api/leave-requests', {
        method: 'POST',
        body: formData
      });
      const data = await res.json();

      if (res.ok && data.success) {
        playSuccessBeep();
        leaveResult.innerHTML = `<div style="padding:8px 12px;background:rgba(16,185,129,0.15);border:1px solid #10b981;border-radius:6px;color:#34d399;font-weight:600;">✓ ${data.message}</div>`;
        leaveReason.value = '';
        loadMyLeaveRequests();
      } else {
        leaveResult.innerHTML = `<div style="padding:8px 12px;background:rgba(239,68,68,0.15);border:1px solid #ef4444;border-radius:6px;color:#f87171;font-weight:600;">✕ ${data.error || 'Gửi đơn thất bại'}</div>`;
      }
    } catch (e) {
      leaveResult.innerHTML = '<span style="color:#ef4444;">✕ Lỗi kết nối đến máy chủ.</span>';
    } finally {
      btnSubmitLeave.disabled = false;
      btnSubmitLeave.innerHTML = '<span>📷 Quét Mặt Xác Thực & Gửi Đơn Xin Nghỉ</span>';
    }
  });
}

async function loadMyLeaveRequests() {
  if (!lookupResultsList) return;
  try {
    const empCode = window.CURRENT_EMPLOYEE ? window.CURRENT_EMPLOYEE.emp_code : '';
    const res = await fetch(`/api/leave-requests?emp_code=${encodeURIComponent(empCode)}`);
    const data = await res.json();
    const reqs = data.requests || [];

    if (reqs.length === 0) {
      lookupResultsList.innerHTML = '<div style="font-size:.82rem;color:var(--text-muted);padding:.5rem;text-align:center;">Bạn chưa gửi đơn xin nghỉ phép nào.</div>';
      return;
    }

    lookupResultsList.innerHTML = reqs.map(r => {
      let badgeBg = '#f59e0b';
      if (r.status === 'Đã duyệt') badgeBg = '#10b981';
      else if (r.status === 'Từ chối') badgeBg = '#ef4444';

      const dateRange = (r.end_leave_date && r.end_leave_date !== r.leave_date)
        ? `${r.leave_date} → ${r.end_leave_date} (${r.days_count || 1} ngày)`
        : `${r.leave_date} (${r.days_count || 1} ngày)`;

      const faceTag = r.face_verified
        ? `<span style="color:#34d399;font-size:.72rem;font-weight:600;">✓ Đã xác thực FaceID (${r.face_similarity ? (r.face_similarity * 100).toFixed(1) + '%' : ''})</span>`
        : '';

      return `
        <div style="background:var(--bg-card-2);padding:.65rem .8rem;border-radius:.45rem;border:1px solid var(--border);font-size:.82rem;">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:.25rem;">
            <strong style="color:var(--text);">${r.leave_type}: ${dateRange}</strong>
            <span style="background:${badgeBg};color:#fff;padding:2px 8px;border-radius:999px;font-size:.7rem;font-weight:700;">${r.status}</span>
          </div>
          <div style="color:var(--text-secondary);font-size:.78rem;">Lý do: ${r.reason}</div>
          <div style="display:flex;justify-content:space-between;align-items:center;margin-top:4px;">
            <span style="font-size:.72rem;color:var(--text-muted);">Ngày nộp: ${r.request_date}</span>
            ${faceTag}
          </div>
          ${r.note ? `<div style="color:#93c5fd;font-size:.75rem;margin-top:3px;">💬 Quản lý phản hồi: ${r.note}</div>` : ''}
        </div>
      `;
    }).join('');
  } catch (e) {
    lookupResultsList.innerHTML = `<div style="color:#ef4444;font-size:.82rem;padding:.5rem;">Lỗi tải danh sách đơn.</div>`;
  }
}

if (btnRefreshMyLeaves) btnRefreshMyLeaves.addEventListener('click', loadMyLeaveRequests);

// ════════════════════════════════════════════════════════════════════════════
// TAB 3: XEM SỐ NGÀY CÔNG & BẢNG LƯƠNG CÁ NHÂN
// ════════════════════════════════════════════════════════════════════════════
const empPayrollMonthInput = document.getElementById('emp-payroll-month');
const btnLoadEmpPayroll    = document.getElementById('btn-load-emp-payroll');
const empPayrollLogsTbody  = document.getElementById('emp-payroll-logs-tbody');

if (empPayrollMonthInput) {
  empPayrollMonthInput.value = new Date().toISOString().substring(0, 7);
}
if (btnLoadEmpPayroll) {
  btnLoadEmpPayroll.addEventListener('click', loadEmployeePayroll);
}

function formatVND(num) {
  return Number(num || 0).toLocaleString('vi-VN') + ' đ';
}

async function loadEmployeePayroll() {
  const month = empPayrollMonthInput ? empPayrollMonthInput.value : new Date().toISOString().substring(0, 7);
  try {
    const res = await fetch(`/api/employee/payroll?month=${encodeURIComponent(month)}`);
    if (!res.ok) throw new Error('Không thể tải bảng lương');
    const data = await res.json();
    const p = data.payroll;
    if (!p) return;

    document.getElementById('pay-base-salary').textContent = formatVND(p.base_salary);
    document.getElementById('pay-daily-wage').textContent = Number(p.daily_wage || 0).toLocaleString('vi-VN');
    document.getElementById('pay-present-days').textContent = `${p.present_days} ngày`;
    document.getElementById('pay-completed-days').textContent = p.completed_days;
    document.getElementById('pay-leave-days').textContent = `${p.approved_leave_days} ngày`;
    document.getElementById('pay-total-paid-days').textContent = p.total_paid_days;
    document.getElementById('pay-late-count').textContent = `${p.late_count} lần`;
    document.getElementById('pay-late-penalty').textContent = Number(p.late_penalty || 0).toLocaleString('vi-VN');
    document.getElementById('pay-net-salary').textContent = formatVND(p.net_salary);
    document.getElementById('pay-total-hours').textContent = p.total_work_hours || 0;

    // Bảng chi tiết từng ngày
    const logs = data.logs || [];
    if (logs.length === 0) {
      empPayrollLogsTbody.innerHTML = `<tr><td colspan="7" class="td-empty">Chưa có dữ liệu chấm công trong tháng ${month}.</td></tr>`;
    } else {
      empPayrollLogsTbody.innerHTML = logs.map(l => {
        const isLate = (l.status && (l.status.includes('Đi trễ') || l.status.includes('Đi muộn') || l.status.includes('Về sớm')));
        const badgeStyle = isLate
          ? 'background:rgba(245,158,11,0.18);color:#fbbf24;border:1px solid rgba(245,158,11,0.4);'
          : 'background:rgba(16,185,129,0.18);color:#34d399;border:1px solid rgba(16,185,129,0.4);';

        return `
          <tr>
            <td><strong>${l.date}</strong></td>
            <td>${l.shift_name || 'Ca chuẩn'}</td>
            <td style="color:#34d399;font-weight:700;">${l.time || '—'}</td>
            <td style="color:#fbbf24;font-weight:700;">${l.check_out_time || '<span class="text-muted">Chưa check-out</span>'}</td>
            <td><strong>${l.work_hours ? l.work_hours + ' giờ' : '—'}</strong></td>
            <td style="font-size:0.8rem;color:var(--text-secondary);max-width:240px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${l.location || ''}">
              📍 ${l.location || 'Văn phòng'}
            </td>
            <td><span style="padding:3px 9px;border-radius:999px;font-size:0.75rem;font-weight:700;${badgeStyle}">${l.status || 'Đúng giờ'}</span></td>
          </tr>
        `;
      }).join('');
    }
  } catch (err) {
    console.warn('Payroll error:', err);
  }
}

// ── Khởi động ứng dụng Cổng Nhân Viên ───────────────────────────────────────
window.addEventListener('DOMContentLoaded', () => {
  initGeolocation();
  startCamera();
  // Nếu hôm nay đã có giờ Check-in nhưng chưa có giờ Check-out thì gợi ý chuyển sang chế độ Check-out
  if (todayCheckinEl && todayCheckinEl.textContent.trim() !== '—' && todayCheckoutEl && todayCheckoutEl.textContent.trim() === '—') {
    setAttendanceMode('checkout');
  }
});
