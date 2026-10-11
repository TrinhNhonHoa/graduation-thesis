/**
 * FaceID Attendance System — Kiosk Live Cam Controller
 * Chạy camera liên tục, nhận diện khuôn mặt và hiển thị Tên + Mã NV khi > 60%
 */

// ── Biến trạng thái ──────────────────────────────────────────────────────────
let videoStream = null;
let isScanning = false;
let isProcessingFrame = false;
let scanIntervalId = null;
let soundEnabled = true;
let currentFacingMode = 'user';
let lastMatchedCode = null;
let lastMatchedTime = 0;
let popupHideTimer = null;

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
const popupLogStatus = document.getElementById('popup-log-status');
const mismatchBadge  = document.getElementById('mismatch-badge');
const mismatchText   = document.getElementById('mismatch-text');
const hudGuide       = document.getElementById('hud-guide');

// Sidebar Elements
const latestPlaceholder = document.getElementById('latest-placeholder');
const latestInfoView    = document.getElementById('latest-info-view');
const latestAvatar      = document.getElementById('latest-avatar');
const latestName        = document.getElementById('latest-name');
const latestCode        = document.getElementById('latest-code');
const latestRole        = document.getElementById('latest-role');
const latestSim         = document.getElementById('latest-sim');
const latestTime        = document.getElementById('latest-time');
const latestStatus      = document.getElementById('latest-status');
const cardStatusBadge   = document.getElementById('card-status-badge');
const recentFeedList    = document.getElementById('recent-feed-list');
const btnRefreshFeed    = document.getElementById('btn-refresh-feed');

// ── Đồng hồ thực tế ──────────────────────────────────────────────────────────
function updateClock() {
  const now = new Date();
  const timeStr = now.toLocaleTimeString('vi-VN', { hour12: false });
  const days = ['Chủ Nhật', 'Thứ Hai', 'Thứ Ba', 'Thứ Tư', 'Thứ Năm', 'Thứ Sáu', 'Thứ Bảy'];
  const dayName = days[now.getDay()];
  const dateStr = `${dayName}, ${String(now.getDate()).padStart(2, '0')}/${String(now.getMonth() + 1).padStart(2, '0')}/${now.getFullYear()}`;

  document.getElementById('clock-time').textContent = timeStr;
  document.getElementById('clock-date').textContent = dateStr;
}
setInterval(updateClock, 1000);
updateClock();

// ── Web Audio API: Âm thanh thông báo không cần file ngoài ──────────────────
let audioCtx = null;
function playSuccessBeep() {
  if (!soundEnabled) return;
  try {
    if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    if (audioCtx.state === 'suspended') audioCtx.resume();

    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();

    osc.type = 'sine';
    osc.frequency.setValueAtTime(587.33, audioCtx.currentTime); // D5
    osc.frequency.exponentialRampToValueAtTime(880, audioCtx.currentTime + 0.15); // A5

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

// ── Quét và Nhận dạng liên tục ──────────────────────────────────────────────
function startContinuousScanning() {
  if (scanIntervalId) clearInterval(scanIntervalId);

  // Quét mỗi 900ms để cân bằng độ mượt và hiệu năng CPU/GPU
  scanIntervalId = setInterval(captureAndRecognize, 900);
}

async function captureAndRecognize() {
  // Nếu đang xử lý frame trước hoặc camera chưa sẵn sàng thì bỏ qua frame này
  if (isProcessingFrame || !videoStream || videoEl.readyState < 2) return;

  isProcessingFrame = true;

  try {
    const width = videoEl.videoWidth || 640;
    const height = videoEl.videoHeight || 480;

    canvasEl.width = width;
    canvasEl.height = height;
    const ctx = canvasEl.getContext('2d');
    ctx.drawImage(videoEl, 0, 0, width, height);

    const blob = await new Promise(resolve => canvasEl.toBlob(resolve, 'image/jpeg', 0.85));
    if (!blob) {
      isProcessingFrame = false;
      return;
    }

    const formData = new FormData();
    formData.append('file', blob, 'frame.jpg');

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

  // ── TRƯỜNG HỢP 1: PHÁT HIỆN GIẢ MẠO (ANTI-SPOOFING KÍCH HOẠT) ──
  if (data.is_spoof) {
    matchPopup.classList.add('hidden');
    mismatchBadge.classList.add('hidden');

    spoofWarningText.textContent = `⚠️ PHÁT HIỆN GIẢ MẠO (Độ sống: ${data.liveness_pct}%) - ${data.message}`;
    spoofWarningBadge.classList.remove('hidden');

    cardStatusBadge.textContent = 'Cảnh báo giả mạo!';
    cardStatusBadge.style.color = '#ef4444';

    clearTimeout(spoofHideTimer);
    spoofHideTimer = setTimeout(() => {
      spoofWarningBadge.classList.add('hidden');
    }, 2500);
    return;
  }

  // ── TRƯỜNG HỢP 2: NHẬN DẠNG THÀNH CÔNG VỚI ĐỘ TƯƠNG ĐỒNG > 60% ──
  if (data.matched) {
    mismatchBadge.classList.add('hidden');
    spoofWarningBadge.classList.add('hidden');

    const empCode = data.emp_code;
    const empName = data.name;
    const simPct  = data.similarity_pct;
    const livePct = data.liveness_pct || 90;

    // Phát âm thanh nếu là người mới hoặc đã qua cooldown
    if (empCode !== lastMatchedCode || (now - lastMatchedTime) > 8000) {
      playSuccessBeep();
      lastMatchedCode = empCode;
      lastMatchedTime = now;
    }

    // Cập nhật Popup nổi bật trên màn hình cam
    popupName.textContent = empName;
    popupCode.textContent = empCode;
    popupDept.textContent = data.department || 'Nhân viên';
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

    if (data.logged) {
      popupLogStatus.textContent = '✓ Đã ghi nhận lịch chấm công hôm nay';
      popupLogStatus.style.color = 'var(--success-light)';
      loadRecentFeed(); // Cập nhật ngay feed bên phải
    } else if (data.cooldown_remaining > 0) {
      popupLogStatus.textContent = `ℹ Đã điểm danh (lần quét tiếp theo sau ${data.cooldown_remaining}s)`;
      popupLogStatus.style.color = '#93c5fd';
    }

    matchPopup.classList.remove('hidden');

    // Cập nhật Card "Nhân viên vừa nhận diện" bên cột phải
    latestPlaceholder.classList.add('hidden');
    latestInfoView.classList.remove('hidden');
    latestName.textContent = empName;
    latestCode.textContent = `Mã NV: ${empCode}`;
    latestRole.textContent = `${data.department || ''} ${data.position ? '· ' + data.position : ''}`;
    latestSim.textContent = `${simPct}% (Live: ${livePct}%)`;
    latestTime.textContent = data.time || '';
    cardStatusBadge.textContent = 'Xác thực ✓';
    cardStatusBadge.style.color = 'var(--success-light)';

    if (data.avatar_file) {
      latestAvatar.innerHTML = `<img src="/api/avatar/${data.avatar_file}" alt="${empName}" />`;
    } else {
      latestAvatar.textContent = empName.charAt(0).toUpperCase();
    }

    // Tự động ẩn popup sau 3.5 giây nếu không còn người trong khung
    clearTimeout(popupHideTimer);
    popupHideTimer = setTimeout(() => {
      matchPopup.classList.add('hidden');
    }, 3500);

  } else {
    // Không nhận diện được hoặc < 60%
    if (data.similarity_pct && data.similarity_pct > 25) {
      mismatchText.textContent = `Độ tương đồng ${data.similarity_pct}% (chưa đạt ngưỡng 60%)`;
      mismatchBadge.classList.remove('hidden');
      setTimeout(() => mismatchBadge.classList.add('hidden'), 1500);
    }
  }
}


// ── Nạp danh sách điểm danh gần đây (Live Feed) ─────────────────────────────
async function loadRecentFeed() {
  try {
    const res = await fetch('/api/attendance/recent?limit=10');
    if (!res.ok) return;
    const data = await res.json();
    const list = data.recent || [];

    if (list.length === 0) {
      recentFeedList.innerHTML = '<div class="feed-empty">Chưa có lượt điểm danh nào hôm nay.</div>';
      return;
    }

    recentFeedList.innerHTML = list.map(item => {
      const avatarHtml = item.avatar_file
        ? `<img src="/api/avatar/${item.avatar_file}" alt="${item.emp_name}" />`
        : item.emp_name.charAt(0).toUpperCase();

      const simPct = item.similarity ? `${(item.similarity * 100).toFixed(1)}%` : 'Thủ công';

      return `
        <div class="feed-item">
          <div class="feed-avatar">${avatarHtml}</div>
          <div class="feed-info">
            <div class="feed-name">${item.emp_name}</div>
            <div class="feed-meta">Mã: <strong>${item.emp_code}</strong> · ${item.department || 'Nhân viên'}</div>
          </div>
          <div class="feed-time-col">
            <div class="feed-time">${item.time}</div>
            <div class="feed-sim">${simPct}</div>
          </div>
        </div>
      `;
    }).join('');
  } catch (err) {
    console.warn('Load feed error:', err);
  }
}

// ── Event Handlers ──────────────────────────────────────────────────────────
btnSwitchCam.addEventListener('click', () => {
  currentFacingMode = currentFacingMode === 'user' ? 'environment' : 'user';
  startCamera();
});

btnToggleSound.addEventListener('click', () => {
  soundEnabled = !soundEnabled;
  soundIcon.textContent = soundEnabled ? '🔊' : '🔇';
});

btnRefreshFeed.addEventListener('click', loadRecentFeed);

// Toggle Anti-Spoofing / Liveness Check
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

// ── Khởi động ứng dụng Kiosk ────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', () => {
  startCamera();
  loadRecentFeed();
  // Định kỳ tự động làm mới feed mỗi 12 giây
  setInterval(loadRecentFeed, 12000);

});
