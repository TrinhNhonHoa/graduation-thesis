/* ── Tab switching ───────────────────────────────────────────────── */
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const target = btn.dataset.tab;
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById(`tab-${target}`).classList.add('active');
    if (target === 'database') loadDatabase();
  });
});

/* ── Status check ────────────────────────────────────────────────── */
async function checkStatus() {
  try {
    const res = await fetch('/api/status');
    const data = await res.json();
    document.getElementById('status-dot').classList.add('online');
    document.getElementById('status-text').textContent =
      `${data.registered_persons} người đã đăng ký · ${data.device.toUpperCase()}`;
    document.getElementById('count-badge').textContent =
      `${data.registered_persons} người đã đăng ký`;
  } catch {
    document.getElementById('status-text').textContent = 'Mất kết nối';
  }
}
checkStatus();
setInterval(checkStatus, 10000);

/* ── Toast ───────────────────────────────────────────────────────── */
let toastTimer;
function showToast(msg, type = 'info') {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = `toast ${type}`;
  el.classList.remove('hidden');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add('hidden'), 3500);
}

/* ── Shared: file input + drag-drop binding ──────────────────────── */
function bindDropZone(dropEl, fileInput, onFile) {
  dropEl.addEventListener('click', e => {
    if (e.target !== fileInput && !e.target.closest('label')) fileInput.click();
  });
  fileInput.addEventListener('change', () => {
    if (fileInput.files[0]) onFile(fileInput.files[0]);
  });
  dropEl.addEventListener('dragover', e => { e.preventDefault(); dropEl.classList.add('dragging'); });
  dropEl.addEventListener('dragleave', () => dropEl.classList.remove('dragging'));
  dropEl.addEventListener('drop', e => {
    e.preventDefault();
    dropEl.classList.remove('dragging');
    const f = e.dataTransfer.files[0];
    if (f && f.type.startsWith('image/')) onFile(f);
  });
}

function fileToDataURL(file) {
  return new Promise((resolve) => {
    const reader = new FileReader();
    reader.onload = e => resolve(e.target.result);
    reader.readAsDataURL(file);
  });
}

/* ══════════════════════════════════════════════════════════════════
   IDENTIFY TAB
══════════════════════════════════════════════════════════════════ */
let identifyFile = null;

const identifyDrop     = document.getElementById('identify-drop');
const identifyFileInput= document.getElementById('identify-file');
const identifyPreviewW = document.getElementById('identify-preview-wrap');
const identifyPreview  = document.getElementById('identify-preview');
const identifyBtn      = document.getElementById('identify-btn');

bindDropZone(identifyDrop, identifyFileInput, setIdentifyFile);

async function setIdentifyFile(file) {
  identifyFile = file;
  const url = await fileToDataURL(file);
  identifyPreview.src = url;
  identifyPreviewW.classList.remove('hidden');
  resetResult();
}

// ── Camera ────────────────────────────────────────────────────────
let cameraStream = null;

document.getElementById('toggle-camera').addEventListener('click', async () => {
  const container = document.getElementById('camera-container');
  if (container.classList.contains('hidden')) {
    try {
      cameraStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user' } });
      document.getElementById('video').srcObject = cameraStream;
      container.classList.remove('hidden');
      document.getElementById('toggle-camera').textContent = '✕ Tắt Camera';
    } catch {
      showToast('Không thể truy cập camera', 'error');
    }
  } else {
    stopCamera();
  }
});

function stopCamera() {
  if (cameraStream) { cameraStream.getTracks().forEach(t => t.stop()); cameraStream = null; }
  document.getElementById('camera-container').classList.add('hidden');
  document.getElementById('toggle-camera').innerHTML = `
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/>
      <circle cx="12" cy="13" r="4"/>
    </svg> Dùng Camera`;
}

document.getElementById('capture-btn').addEventListener('click', () => {
  const video  = document.getElementById('video');
  const canvas = document.getElementById('canvas');
  canvas.width  = video.videoWidth;
  canvas.height = video.videoHeight;
  canvas.getContext('2d').drawImage(video, 0, 0);
  canvas.toBlob(blob => {
    const file = new File([blob], 'capture.jpg', { type: 'image/jpeg' });
    setIdentifyFile(file);
    stopCamera();
  }, 'image/jpeg', .92);
});

// ── Nhận dạng ─────────────────────────────────────────────────────
identifyBtn.addEventListener('click', async () => {
  if (!identifyFile) return;

  const loading = document.getElementById('result-loading');
  const placeholder = document.getElementById('result-placeholder');
  const content = document.getElementById('result-content');

  loading.classList.remove('hidden');
  placeholder.classList.add('hidden');
  content.classList.add('hidden');

  const form = new FormData();
  form.append('file', identifyFile);

  try {
    const res = await fetch('/api/identify', { method: 'POST', body: form });
    const data = await res.json();
    loading.classList.add('hidden');

    if (!res.ok) { showToast(data.error || 'Lỗi không xác định', 'error'); placeholder.classList.remove('hidden'); return; }

    renderResult(data);
    content.classList.remove('hidden');
  } catch (e) {
    loading.classList.add('hidden');
    placeholder.classList.remove('hidden');
    showToast('Không kết nối được server', 'error');
  }
});

function renderResult(data) {
  const banner   = document.getElementById('match-banner');
  const avatar   = document.getElementById('result-avatar');
  const name     = document.getElementById('result-name');
  const simPct   = document.getElementById('result-sim-pct');
  const simFill  = document.getElementById('result-sim-fill');
  const top5Body = document.getElementById('top5-body');

  if (data.matched) {
    banner.textContent = `✓ Nhận dạng thành công!`;
    banner.className = 'match-banner matched';
  } else {
    banner.textContent = '✗ Không nhận ra khuôn mặt này';
    banner.className = 'match-banner no-match';
  }

  const displayName = data.matched ? data.best_match : 'Không rõ';
  name.textContent = displayName;
  avatar.textContent = displayName.charAt(0).toUpperCase();

  const pct = Math.min(data.similarity * 125, 100).toFixed(1);
  simPct.textContent = `${(data.similarity * 100).toFixed(1)}%`;
  setTimeout(() => { simFill.style.width = `${pct}%`; }, 50);
  simFill.style.background = data.matched
    ? 'linear-gradient(90deg, #22c55e, #4ade80)'
    : 'linear-gradient(90deg, #ef4444, #f87171)';

  // Top-5
  top5Body.innerHTML = '';
  (data.all_results || []).forEach((r, i) => {
    const tr = document.createElement('tr');
    const simValue = (r.similarity * 100).toFixed(1);
    const color = i === 0 && data.matched ? 'var(--success)' : 'var(--text-secondary)';
    tr.innerHTML = `
      <td style="color:var(--text-muted)">${i + 1}</td>
      <td style="font-weight:${i===0?'600':'400'}">${r.name}</td>
      <td style="color:${color}">${simValue}%</td>`;
    top5Body.appendChild(tr);
  });
}

function resetResult() {
  document.getElementById('result-placeholder').classList.remove('hidden');
  document.getElementById('result-content').classList.add('hidden');
  document.getElementById('result-loading').classList.add('hidden');
  document.getElementById('result-sim-fill').style.width = '0%';
}

/* ══════════════════════════════════════════════════════════════════
   REGISTER TAB
══════════════════════════════════════════════════════════════════ */
let registerFile = null;

const registerDrop      = document.getElementById('register-drop');
const registerFileInput = document.getElementById('register-file');
const registerPreviewW  = document.getElementById('register-preview-wrap');
const registerPreview   = document.getElementById('register-preview');

bindDropZone(registerDrop, registerFileInput, setRegisterFile);

async function setRegisterFile(file) {
  registerFile = file;
  const url = await fileToDataURL(file);
  registerPreview.src = url;
  registerPreviewW.classList.remove('hidden');
}

document.getElementById('register-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const name = document.getElementById('register-name').value.trim();
  const toast = document.getElementById('register-result');

  if (!name) { toast.textContent = 'Vui lòng nhập tên.'; toast.className = 'result-toast error'; toast.classList.remove('hidden'); return; }
  if (!registerFile) { toast.textContent = 'Vui lòng chọn ảnh.'; toast.className = 'result-toast error'; toast.classList.remove('hidden'); return; }

  const btn = document.getElementById('register-btn');
  btn.disabled = true;
  btn.textContent = 'Đang đăng ký...';

  const form = new FormData();
  form.append('name', name);
  form.append('file', registerFile);

  try {
    const res = await fetch('/api/register', { method: 'POST', body: form });
    const data = await res.json();

    if (res.ok) {
      toast.textContent = `✓ ${data.message}`;
      toast.className = 'result-toast success';
      showToast(`Đã đăng ký: ${data.name}`, 'success');
      document.getElementById('register-name').value = '';
      registerFile = null;
      registerPreviewW.classList.add('hidden');
      registerPreview.src = '';
      checkStatus();
    } else {
      toast.textContent = `✗ ${data.error}`;
      toast.className = 'result-toast error';
    }
  } catch {
    toast.textContent = '✗ Không kết nối được server';
    toast.className = 'result-toast error';
  }

  toast.classList.remove('hidden');
  btn.disabled = false;
  btn.innerHTML = `
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/>
      <line x1="19" y1="8" x2="19" y2="14"/><line x1="22" y1="11" x2="16" y2="11"/>
    </svg> Đăng Ký`;
});

/* ══════════════════════════════════════════════════════════════════
   DATABASE TAB
══════════════════════════════════════════════════════════════════ */
async function loadDatabase() {
  const grid  = document.getElementById('db-grid');
  const empty = document.getElementById('db-empty');

  try {
    const res  = await fetch('/api/persons');
    const data = await res.json();

    if (!data.persons || data.persons.length === 0) {
      grid.classList.add('hidden');
      empty.classList.remove('hidden');
      return;
    }

    empty.classList.add('hidden');
    grid.classList.remove('hidden');
    grid.innerHTML = data.persons.map(name => `
      <div class="person-card" id="card-${name}">
        <div class="avatar">${name.charAt(0).toUpperCase()}</div>
        <div class="pname">${name}</div>
        <button class="btn-delete" onclick="deletePerson('${name}')">Xóa</button>
      </div>`).join('');
  } catch {
    showToast('Không tải được danh sách', 'error');
  }
}

async function deletePerson(name) {
  if (!confirm(`Xóa "${name}" khỏi database?`)) return;
  try {
    const res = await fetch(`/api/person/${name}`, { method: 'DELETE' });
    const data = await res.json();
    if (res.ok) {
      document.getElementById(`card-${name}`)?.remove();
      showToast(`Đã xóa: ${name}`, 'info');
      checkStatus();
      const grid = document.getElementById('db-grid');
      if (!grid.children.length) {
        grid.classList.add('hidden');
        document.getElementById('db-empty').classList.remove('hidden');
      }
    } else { showToast(data.error, 'error'); }
  } catch { showToast('Lỗi khi xóa', 'error'); }
}

document.getElementById('refresh-db').addEventListener('click', loadDatabase);
