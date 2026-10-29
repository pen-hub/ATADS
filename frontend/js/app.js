const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
const state = {
  page: 'overview',
  upload: null,
  status: null,
  eventOffset: 0,
  historyOffset: 0,
  ws: null,
  frameTimer: null,
  refreshTimer: null,
  toastTimer: null,
  previewLoaded: false,
  roiDirty: false,
  roiSaving: false,
  roiAnchor: "bottom_center",
  roiKey: null,
  roiPoints: [],
  roiEnabled: false,
  roiDrawing: false,
  roiOriginalPoints: [],
  roiOriginalEnabled: false
};

const pageNames = {
  overview: ['Tổng quan hệ thống', 'TỔNG QUAN'],
  monitor: ['Giám sát video', 'GIÁM SÁT VIDEO'],
  events: ['Trung tâm cảnh báo', 'CẢNH BÁO'],
  history: ['Lịch sử sự kiện', 'LỊCH SỬ'],
  reports: ['Báo cáo vận hành', 'BÁO CÁO'],
  system: ['Thông số hệ thống', 'HỆ THỐNG'],
  settings: ['Cấu hình hệ thống', 'CẤU HÌNH'],
  logs: ['Nhật ký vận hành', 'NHẬT KÝ']
};

function toast(message, error = false) {
  const el = $('#toast');
  if (!el) return;
  el.textContent = message;
  el.classList.toggle('error', error);
  el.classList.remove('hidden');
  clearTimeout(state.toastTimer);
  state.toastTimer = setTimeout(() => el.classList.add('hidden'), 4000);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      ...(options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
      ...(options.headers || {})
    }
  });
  if (!response.ok) {
    let message = `Lỗi HTTP ${response.status}`;
    try {
      const data = await response.json();
      message = data.detail || message;
    } catch {}
    throw new Error(message);
  }
  return response.headers.get('content-type')?.includes('application/json') ? response.json() : response;
}

function dateTime(value) {
  if (!value) return '—';
  const d = new Date(typeof value === 'number' ? value * 1000 : value);
  return Number.isNaN(d.valueOf()) ? String(value) : d.toLocaleString('vi-VN', { hour12: false });
}

function formatTimelineTimestamp(value, event) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return '—';
  const sourceStart = Number(event?.source_timestamp ?? event?.start_timestamp);
  const elapsed = numeric - sourceStart;
  const base = new Date(event?.started_at || event?.created_at || '');
  if (event?.source_time_origin && Number.isFinite(elapsed) && elapsed >= 0 && !Number.isNaN(base.valueOf())) {
    const clock = new Date(base.valueOf() + elapsed * 1000);
    return `${dateTime(clock)}${event.source_time_origin === 'video_seconds' ? ` · +${elapsed.toFixed(1)}s video` : ''}`;
  }
  if (numeric > 0 && numeric < 1000000000) {
    const fallback = new Date(event?.created_at || Date.now());
    return `${dateTime(fallback)} · +${numeric.toFixed(1)}s (thời gian tương đối)`;
  }
  return dateTime(numeric);
}

function timelineMarkup(event) {
  const timeline = event.verification?.timeline || event.detections || [];
  if (!Array.isArray(timeline) || !timeline.length) return '<div class="timeline-empty">Chưa có mẫu timeline.</div>';
  return `<div class="timeline-list">${timeline.map(entry => {
    const boxes = Array.isArray(entry.boxes) ? entry.boxes : [];
    const coords = boxes.map(box => Array.isArray(box.bbox) ? box.bbox.map(n => Number(n).toFixed(0)).join(', ') : '').filter(Boolean);
    const confidence = Number(entry.confidence);
    const confidenceText = Number.isFinite(confidence) ? `${(confidence * 100).toFixed(1)}%` : '—';
    return `<div class="timeline-entry"><time>${esc(formatTimelineTimestamp(entry.timestamp, event))}</time><span class="timeline-result ${entry.positive ? 'positive' : 'negative'}">${entry.positive ? 'Tín hiệu dương' : 'Chưa đạt'}</span><span>Confidence ${esc(confidenceText)}</span><span>${coords.length ? `BBox: ${esc(coords.join(' · '))}` : 'Không có bbox tai nạn'}</span></div>`;
  }).join('')}</div>`;
}

function statusPill(value) {
  const labels = { SUSPECTED: 'Đang xác minh', READY_FOR_REVIEW: 'Chờ người duyệt', UNCERTAIN: 'Thiếu bằng chứng', CONFIRMED: 'Đã xác nhận', REJECTED: 'Đã bác bỏ' };
  return `<span class="pill ${value}">${labels[value] || value || 'UNKNOWN'}</span>`;
}

function setPage(page) {
  state.page = page;
  $$('.page').forEach(x => x.classList.toggle('hidden', x.id !== `page-${page}`));
  $$('.nav').forEach(x => x.classList.toggle('active', x.dataset.page === page));
  $('#page-title').textContent = pageNames[page][0];
  $('#breadcrumb-page').textContent = pageNames[page][1];
  if (page === 'events') loadEvents();
  if (page === 'history') loadHistory();
  if (page === 'reports') loadReports();
  if (page === 'settings') loadConfig();
  if (page === 'logs') loadLogs();
  if (page === 'system') refreshStatus();
}

function renderTrackList(vehicles) {
  const list = $('#track-list');
  if (!list) return;
  if (!vehicles || !vehicles.length) {
    list.innerHTML = '<div class="empty-state">Chưa có detection.</div>';
    return;
  }
  const selId = state.status?.pipeline?.visualization?.selected_track_id;
  list.innerHTML = vehicles.map(x => {
    const isSel = x.track_id != null && String(x.track_id) === String(selId);
    const conf = Math.round((Number(x.confidence) || 0) * 100);
    const bboxText = (x.bbox || []).map(Math.round).join(', ');
    return `<div class="track-item ${isSel ? 'selected' : ''}" data-focus-track="${esc(x.track_id ?? '')}"><div><b>${esc(x.class_name)} · ${conf}%</b><small>class ID ${x.class_id} · bbox ${bboxText}</small></div><span class="track-id">ID ${x.track_id ?? '—'}</span></div>`;
  }).join('');
  updateTrackFocusOptions(vehicles);
}

function updateTrackFocusOptions(vehicles) {
  const sel = $('#track-focus');
  if (!sel) return;
  const cur = sel.value;
  const newIds = [...new Set((vehicles || []).map(x => x.track_id).filter(x => x != null).map(String))];
  const existingIds = [...sel.options].map(o => o.value).filter(v => v !== 'all');
  if (newIds.some(id => !existingIds.includes(id))) {
    const allIds = [...new Set([...existingIds, ...newIds])].sort((a, b) => Number(a) - Number(b));
    sel.innerHTML = '<option value="all">Tất cả track</option>' + allIds.map(id => `<option value="${esc(id)}">ID ${esc(id)}</option>`).join('');
    sel.value = cur;
  }
}

async function refreshStatus() {
  try {
    const d = await api('/api/status');
    state.status = d;
    const p = d.pipeline, e = d.events, m = d.models;
    updateSignal(d);
    $('#sidebar-backend').textContent = `Backend ${d.backend === 'online' ? 'trực tuyến' : 'lỗi'}`;
    $('#ov-backend').textContent = d.backend === 'online' ? 'ONLINE' : 'OFFLINE';
    $('#ov-uptime').textContent = `Pipeline ${p.state} · uptime ${p.uptime_seconds}s`;
    $('#ov-models').textContent = m.vehicle.loaded && m.accident.loaded ? '2 / 2' : 'LỖI';
    $('#ov-device').textContent = `${m.gpu || m.device || 'GPU'} · CUDA ${m.cuda_available ? 'sẵn sàng' : 'không khả dụng'}`;
    $('#ov-tracks').textContent = p.tracked_vehicles?.length || 0;
    $('#ov-source').textContent = p.source ? `${p.source} · ${p.state}` : 'Chưa có nguồn hoạt động';
    $('#ov-pending').textContent = (e.by_status.SUSPECTED || 0) + (e.by_status.UNCERTAIN || 0);
    $('#ov-total-events').textContent = `${e.total} sự kiện đã lưu cục bộ`;

    $('#ov-fps').textContent = `FPS ${p.output_fps ? Number(p.output_fps).toFixed(1) : '—'}`;
    $('#ov-frame-state').innerHTML = `<i class="small-dot"></i>Pipeline ${p.state}`;
    $('#nav-alert-count').textContent = (e.by_status.SUSPECTED || 0) + (e.by_status.UNCERTAIN || 0);
    $('#vehicle-classes').textContent = Object.values(m.vehicle.classes || {}).join(', ') || 'Chưa tải';
    $('#accident-classes').textContent = Object.values(m.accident.classes || {}).join(', ') || 'Chưa tải';
    $('#model-paths').textContent = `${m.vehicle.path || ''} · ${m.accident.path || ''}`;
    $('#gpu-summary').textContent = `GPU ${m.gpu || m.device || 'N/A'}`;

    $('#pipeline-pill').textContent = `● ${p.state}`;
    $('#pipeline-pill').className = `pill ${p.state === 'RUNNING' ? 'CONFIRMED' : ''}`;
    $('#monitor-subtitle').textContent = p.source ? `${p.source} · ${p.width}×${p.height} · nguồn ${p.source_fps || 'N/A'} FPS` : 'Chọn video từ máy tính để bắt đầu.';

    const hasFrame = p.processed > 0 || state.previewLoaded;
    $('#monitor-placeholder').classList.toggle('hidden', hasFrame);
    $('#monitor-frame').classList.toggle('hidden', !hasFrame);
    if (p.processed > 0 && !$('#monitor-frame').src.includes('/api/pipeline/stream')) {
      $('#monitor-frame').src = `/api/pipeline/stream?t=${Date.now()}`;
    }

    const isRunningOrPaused = ['RUNNING', 'PAUSED'].includes(p.state);
    $('#start-btn').disabled = ($('#source-mode').value === 'video' ? !state.upload : $('#source-mode').value === 'ip-camera' ? !$('#camera-url').value.trim() : false) || state.roiDrawing || isRunningOrPaused;
    $('#pause-btn').disabled = !isRunningOrPaused;
    $('#pause-btn').textContent = p.state === 'PAUSED' ? '▶ Tiếp tục' : 'Ⅱ Tạm dừng';
    $('#stop-btn').disabled = !isRunningOrPaused;

    const fpsVal = Number(p.output_fps || 0);
    const latencyVal = Number(p.output_latency_ms || 0);
    $('#live-fps').textContent = fpsVal > 0 ? fpsVal.toFixed(1) : (isRunningOrPaused ? '...' : '0');
    $('#live-latency').textContent = latencyVal > 0 ? `${latencyVal.toFixed(1)} ms` : (isRunningOrPaused ? '...' : '0 ms');
    $('#live-tracks').textContent = p.tracked_vehicles?.length || 0;
    $('#live-frame').textContent = p.frame_index != null ? p.frame_index : '—';

    const vis = p.visualization || {};
    $('#trajectory-toggle').checked = vis.trajectory_enabled ?? true;
    $('#track-id-toggle').checked = vis.show_track_ids ?? true;
    $('#direction-toggle').checked = vis.show_direction ?? true;
    $('#trajectory-history').value = String(vis.history_seconds || 6);

    renderTrackList(p.tracked_vehicles || []);
    updateVerificationCard(p);
    renderFrequencyChart(p.frequency_bins || []);

    $('#sys-cpu').textContent = d.system.cpu_percent == null ? 'N/A' : `${d.system.cpu_percent}%`;
    $('#sys-ram').textContent = d.system.ram_percent == null ? 'N/A' : `${d.system.ram_percent}%`;
    $('#sys-gpu').textContent = d.gpu.name || 'N/A';
    $('#sys-vram').textContent = d.gpu.vram_total_mb ? `${d.gpu.vram_used_mb || 0} / ${d.gpu.vram_total_mb} MB` : 'N/A';
    $('#sys-sourcefps').textContent = p.source_fps || 'N/A';
    $('#sys-procfps').textContent = p.output_fps || 'N/A';
    $('#sys-latency').textContent = p.output_latency_ms || 'N/A';
    $('#sys-vehicle-ms').textContent = m.vehicle.inference_ms || 'N/A';
    $('#sys-accident-ms').textContent = m.accident.inference_ms || 'N/A';
    $('#sys-queue').textContent = p.queue_size ?? 'N/A';
    $('#sys-dropped').textContent = `${p.dropped_frames ?? 'N/A'} tác vụ xác minh bị loại bỏ`;
    $('#system-state').textContent = `${p.state} · ${p.source || 'Không có nguồn'} · ${p.width}×${p.height}`;
    $('#system-error').textContent = p.last_error || '';
    refreshRoiControls();
  } catch (err) {
    $('#sidebar-backend').textContent = 'Backend chưa sẵn sàng';
    $('#ov-backend').textContent = 'OFFLINE';
    $('#ov-uptime').textContent = err.message;
  }
}

function updateVerificationCard(p) {
  const card = $('#verify-card'),
        status = $('#verify-status'),
        badge = $('#verify-badge'),
        icon = $('#verify-icon'),
        confidence = $('#verify-confidence');
  if (!card) return;

  let level = 'normal', label = 'BÌNH THƯỜNG', message = 'Chưa có dấu hiệu', score = null;
  const v = p.last_verification, s = p.last_suspicion;

  if (v) {
    const value = String(v.status || '').toUpperCase();
    const hasPositive = (v.positive_frames || v.positive_observations || 0) > 0 || v.review_ready;
    level = ['ALERT', 'ACCIDENT', 'CONFIRMED'].includes(value) || hasPositive ? 'alert' : ['SUSPECTED', 'UNCERTAIN', 'WARNING', 'VERIFYING'].includes(value) ? 'warning' : 'normal';
    label = level === 'alert' ? 'CẢNH BÁO TAI NẠN' : level === 'warning' ? 'ĐANG XÁC MINH' : 'BÌNH THƯỜNG';
    message = `${v.status || 'NORMAL'} · ${v.positive_frames ?? v.positive_observations ?? 0} mẫu accident`;
    score = Number.isFinite(Number(v.max_confidence)) ? Number(v.max_confidence) : null;
    $('#verify-detail').textContent = v.reason || 'Kết quả tổng hợp từ model và thời gian.';
  } else if (s) {
    level = 'warning';
    label = 'ĐANG XÁC MINH';
    message = `SUSPECTED · ${s.track_ids?.length || 0} phương tiện liên quan`;
    score = Number.isFinite(Number(s.score)) ? Number(s.score) : null;
    $('#verify-detail').textContent = (s.reasons || []).join('; ') || 'Đang chờ mô hình xác minh.';
  } else if (p.accident_detections && p.accident_detections.length > 0) {
    level = 'alert';
    label = 'CẢNH BÁO TAI NẠN';
    const maxConf = Math.max(...p.accident_detections.map(d => Number(d.confidence) || 0));
    message = `ACCIDENT · ${p.accident_detections.length} bounding box phát hiện`;
    score = Number.isFinite(maxConf) && maxConf > 0 ? maxConf : null;
    $('#verify-detail').textContent = 'Phát hiện tai nạn trong khung hình; đang gọi mô hình xác minh theo thời gian.';
  } else {
    $('#verify-detail').textContent = 'Khi bộ phân tích ghi nhận dấu hiệu đáng ngờ, mô hình thứ hai sẽ được gọi để xác minh theo thời gian.';
  }

  card.classList.remove('normal', 'warning', 'alert');
  card.classList.add(level);
  icon.textContent = level === 'alert' ? '⚠' : level === 'warning' ? '◷' : '⚑';
  status.textContent = message;
  badge.textContent = level === 'normal' ? '' : label;
  badge.classList.toggle('hidden', level === 'normal');
  confidence.textContent = score === null ? '' : `Độ tin cậy: ${(score * 100).toFixed(0)}%`;
  confidence.classList.toggle('hidden', score === null);
}

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

async function loadRecent() {
  try {
    const d = await api('/api/events?limit=5');
    $('#overview-events').innerHTML = d.items.length ? d.items.map(e => `<div class="event-row" data-event="${esc(e.event_id)}"><img class="event-thumb" src="${e.evidence?.image ? `/api/events/${encodeURIComponent(e.event_id)}/evidence/image` : ''}" onerror="this.outerHTML='<div class=\'event-thumb\'>⚑</div>'"><div class="event-main"><b>${esc(e.event_id)}</b><small>${esc(e.source || 'Nguồn cục bộ')} · ${dateTime(e.created_at)}</small></div>${statusPill(e.status)}</div>`).join('') : '<div class="empty-state">Chưa ghi nhận sự kiện.</div>';
  } catch {}
}

async function loadEvents() {
  try {
    const params = new URLSearchParams({ offset: String(state.eventOffset), limit: '20' });
    if ($('#event-status-filter').value) params.set('status', $('#event-status-filter').value);
    if ($('#event-search').value) params.set('q', $('#event-search').value);
    const d = await api(`/api/events?${params}`);
    $('#alerts-list').innerHTML = d.items.length ? d.items.map(e => `<article class="alert-card"><img src="${e.evidence?.image ? `/api/events/${encodeURIComponent(e.event_id)}/evidence/image` : ''}" onerror="this.style.visibility='hidden'"><div><h3>${esc(e.event_id)}</h3>${statusPill(e.status)}<p>${dateTime(e.created_at)} · ${esc(e.source || 'Nguồn video')}</p><p>${esc((e.reasons || []).join('; '))} · Confidence ${e.max_confidence ? `${(e.max_confidence * 100).toFixed(1)}%` : 'chưa có'}</p></div><div class="alert-actions"><button class="button outline" data-event="${esc(e.event_id)}">Chi tiết</button><button class="button primary" data-review="CONFIRMED" data-id="${esc(e.event_id)}">Xác nhận</button><button class="button outline" data-review="REJECTED" data-id="${esc(e.event_id)}">Bác bỏ</button><button class="button outline" data-review="UNCERTAIN" data-id="${esc(e.event_id)}">Thiếu bằng chứng</button></div></article>`).join('') : '<div class="panel empty-state">Chưa có sự kiện phù hợp bộ lọc.</div>';
    pagination('#events-pagination', state.eventOffset, d.total, 20, 'events');
  } catch (err) {
    $('#alerts-list').innerHTML = `<div class="empty-state">${esc(err.message)}</div>`;
  }
}

async function loadHistory() {
  try {
    const p = new URLSearchParams({ offset: String(state.historyOffset), limit: '30' });
    if ($('#history-status-filter').value) p.set('status', $('#history-status-filter').value);
    if ($('#history-search').value) p.set('q', $('#history-search').value);
    if ($('#history-source').value) p.set('source', $('#history-source').value);
    const d = await api(`/api/events?${p}`);
    $('#history-body').innerHTML = d.items.length ? d.items.map(e => `<tr><td class="mono">${esc(e.event_id)}</td><td>${dateTime(e.created_at)}</td><td>${esc(e.source || '—')}</td><td>${statusPill(e.status)}</td><td>${e.max_confidence ? `${(e.max_confidence * 100).toFixed(1)}%` : 'N/A'}</td><td><button class="text-button" data-event="${esc(e.event_id)}">Chi tiết →</button></td></tr>`).join('') : '<tr><td colspan="6" class="empty-state">Không có bản ghi.</td></tr>';
    pagination('#history-pagination', state.historyOffset, d.total, 30, 'history');
  } catch (err) {
    $('#history-body').innerHTML = `<tr><td colspan="6">${esc(err.message)}</td></tr>`;
  }
}

function pagination(selector, offset, total, size, kind) {
  const prev = offset > 0 ? `<button class="button outline" data-page-offset="${Math.max(0, offset - size)}" data-kind="${kind}">← Trước</button>` : '';
  const next = offset + size < total ? `<button class="button outline" data-page-offset="${offset + size}" data-kind="${kind}">Sau →</button>` : '';
  $(selector).innerHTML = `${prev}<span>${total ? offset + 1 : 0}–${Math.min(offset + size, total)} / ${total}</span>${next}`;
}

function setSignalLamp(color, caption) {
  for (const name of ['red', 'yellow', 'green']) {
    $(`#signal-${name}`)?.classList.toggle('active', name === color.toLowerCase());
  }
  const cap = $('#signal-caption');
  if (cap) {
    cap.textContent = caption;
    const c = color.toLowerCase();
    cap.style.borderColor = c === 'red' ? 'rgba(239,68,68,0.4)' : c === 'yellow' ? 'rgba(245,158,11,0.4)' : 'rgba(16,185,129,0.4)';
    cap.style.color = c === 'red' ? '#fca5a5' : c === 'yellow' ? '#fde68a' : '#a7f3d0';
  }
}

function updateSignal(p) {
  const mode = $('#signal-mode')?.value || 'auto', manual = $('#signal-manual')?.value || 'GREEN';
  const lbl = $('#signal-mode-label');
  if (lbl) {
    lbl.textContent = mode === 'auto' ? 'TỰ ĐỘNG' : 'THỦ CÔNG';
    lbl.classList.toggle('manual', mode === 'manual');
  }
  $('#signal-manual-wrap')?.classList.toggle('hidden', mode !== 'manual');
  if (mode === 'manual') {
    setSignalLamp(manual, `Đèn ${manual === 'RED' ? 'đỏ' : manual === 'YELLOW' ? 'vàng' : 'xanh'} · chế độ thủ công`);
    return;
  }
  const pending = Number(p?.events?.by_status?.SUSPECTED || 0) + Number(p?.events?.by_status?.UNCERTAIN || 0);
  if (pending > 0) setSignalLamp('RED', `Đỏ · ${pending} sự kiện chờ duyệt`);
  else if (['RUNNING', 'PAUSED'].includes(p?.pipeline?.state)) setSignalLamp('GREEN', 'Xanh · chưa có cảnh báo cần duyệt');
  else setSignalLamp('YELLOW', 'Vàng · pipeline đang dừng');
}

function playAlertTone() {
  if (!$('#alert-sound-toggle')?.checked) return;
  try {
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    if (!AudioContext) return;
    const ctx = new AudioContext(), osc = ctx.createOscillator(), gain = ctx.createGain();
    osc.type = 'sine';
    osc.frequency.value = 880;
    gain.gain.setValueAtTime(.0001, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(.18, ctx.currentTime + .03);
    gain.gain.exponentialRampToValueAtTime(.0001, ctx.currentTime + .35);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + .36);
    osc.onended = () => ctx.close();
  } catch {}
}

function renderFrequencyChart(bins) {
  const root = $('#frequency-chart');
  if (!root) return;
  if (!bins.length) {
    root.innerHTML = '<div class="empty-state">Chưa có dữ liệu phương tiện.</div>';
    return;
  }
  const limit = Number($('#frequency-window')?.value || 10), selected = bins.slice(-limit), max = Math.max(1, ...selected.map(x => x.vehicle_count));
  root.innerHTML = selected.map(x => `<div class="frequency-bar"><span>${Math.floor(x.start_seconds / 60)}:${String(x.start_seconds % 60).padStart(2, '0')}</span><div><i style="width:${Math.max(3, x.vehicle_count / max * 100)}%"></i></div><b>${x.vehicle_count}</b></div>`).join('');
}

async function showEvent(id) {
  try {
    const e = await api(`/api/events/${encodeURIComponent(id)}`);
    const img = e.evidence?.image ? `<img class="detail-media" src="/api/events/${encodeURIComponent(id)}/evidence/image">` : '';
    const location = e.location || {};
    const technical = e.technical_status === 'READY_FOR_REVIEW' ? 'Chờ người duyệt' : e.technical_status === 'UNCERTAIN' ? 'Thiếu bằng chứng' : 'Đang thu thập bằng chứng';
    const issues = (e.evidence_issues || []).map(issue => typeof issue === 'string' ? issue : issue.reason).filter(Boolean);
    $('#event-detail').innerHTML = `<div class="detail-head"><h2>${esc(e.event_id)}</h2>${statusPill(e.status)} <small>${dateTime(e.created_at)}</small></div>${img}<div class="detail-row"><span>Trạng thái kỹ thuật:</span> ${esc(technical)} · Quyết định reviewer: ${esc(e.review_status || 'PENDING')} · Evidence: ${esc(e.processing_status || 'COLLECTING')}</div><div class="detail-row"><span>Nguồn:</span> ${esc(e.source || '—')}</div><div class="detail-row"><span>Track ID:</span> ${esc((e.related_track_ids || []).join(', ') || 'N/A')}</div><div class="detail-row"><span>Lý do nghi ngờ:</span> ${esc((e.reasons || []).join('; ') || '—')}</div><div class="detail-row"><span>Confidence accident tối đa:</span> ${e.max_confidence ? `${(e.max_confidence * 100).toFixed(2)}%` : 'N/A'}</div><div class="detail-row"><span>Số mẫu đã lưu:</span> ${(e.verification_samples || []).length}</div>${issues.length ? `<div class="detail-row"><span>Mẫu/bằng chứng thiếu:</span> ${esc(issues.join('; '))}</div>` : ''}<div class="detail-row timeline-section"><b>Timeline xác minh</b>${timelineMarkup(e)}</div><div class="detail-row"><span>Chất lượng quan sát:</span> ${esc(e.observation_quality || 'unknown')}</div><div class="detail-row"><span>Lý do đánh giá:</span> ${esc(e.decision_reason || '—')}</div><div class="event-meta-fields"><label>Mức độ sự cố<select id="detail-severity"><option value="UNASSESSED" ${!e.severity || e.severity === 'UNASSESSED' ? 'selected' : ''}>Chưa đánh giá</option><option value="LOW" ${e.severity === 'LOW' ? 'selected' : ''}>Nhẹ</option><option value="MODERATE" ${e.severity === 'MODERATE' ? 'selected' : ''}>Trung bình</option><option value="HIGH" ${e.severity === 'HIGH' ? 'selected' : ''}>Nặng</option><option value="CRITICAL" ${e.severity === 'CRITICAL' ? 'selected' : ''}>Rất nghiêm trọng</option></select></label><label>Vĩ độ GPS<input id="detail-latitude" type="number" step="any" min="-90" max="90" placeholder="Chưa có GPS" value="${location.latitude ?? ''}"></label><label>Kinh độ GPS<input id="detail-longitude" type="number" step="any" min="-180" max="180" placeholder="Chưa có GPS" value="${location.longitude ?? ''}"></label><small>Tọa độ nhập thủ công (WGS84); hệ thống không suy ra GPS từ bbox ảnh.</small></div><label class="form-panel">Ghi chú<input id="detail-notes" maxlength="4000" value="${esc(e.notes || '')}"></label><div class="detail-actions"><button class="button primary" data-review="CONFIRMED" data-id="${esc(id)}">Xác nhận</button><button class="button outline" data-review="REJECTED" data-id="${esc(id)}">Bác bỏ</button><button class="button outline" data-review="UNCERTAIN" data-id="${esc(id)}">Thiếu bằng chứng</button><button class="button outline" id="save-note" data-id="${esc(id)}">Lưu cập nhật</button><a class="button outline" href="/api/events/${encodeURIComponent(id)}/evidence/image" download>Ảnh ↧</a></div>`;
    $('#event-dialog').showModal();
  } catch (err) {
    toast(err.message, true);
  }
}

async function reviewEvent(id, status) {
  try {
    const notes = $('#detail-notes')?.value, severity = $('#detail-severity')?.value, lat = $('#detail-latitude')?.value, lon = $('#detail-longitude')?.value;
    const body = {
      ...(status ? { status } : {}),
      ...(notes !== undefined ? { notes } : {}),
      ...(severity ? { severity } : {}),
      ...(lat !== '' && lon !== '' ? { latitude: Number(lat), longitude: Number(lon) } : {})
    };
    await api(`/api/events/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify(body) });
    toast(status ? `Đã lưu ${status} và thông tin sự kiện.` : 'Đã lưu thông tin sự kiện.');
    $('#event-dialog').close();
    loadEvents();
    loadHistory();
    loadRecent();
    refreshStatus();
  } catch (err) {
    toast(err.message, true);
  }
}

async function loadReports() {
  try {
    const d = await api('/api/reports'), counts = {};
    Object.values(d.events_by_day).forEach(x => Object.entries(x).forEach(([k, v]) => counts[k] = (counts[k] || 0) + v));
    $('#report-total').textContent = d.total_events;
    $('#report-confirmed').textContent = counts.CONFIRMED || 0;
    $('#report-rejected').textContent = counts.REJECTED || 0;
    $('#report-disclaimer').textContent = d.disclaimer;
    const days = Object.entries(d.events_by_day).sort(([a], [b]) => b.localeCompare(a));
    $('#report-days').innerHTML = days.length ? days.map(([day, values]) => `<div class="report-day"><b>${day}</b><span>${Object.entries(values).map(([k, v]) => `${k}: ${v}`).join(' · ')}</span></div>`).join('') : '<div class="empty-state">Chưa có dữ liệu.</div>';
  } catch (err) {
    toast(err.message, true);
  }
}

function applyConfigForm(d) {
  const s = d.settings, r = d.rules, fields = {
    'cfg-vehicle-model': s.vehicle_model,
    'cfg-accident-model': s.accident_model,
    'cfg-vehicle-conf': s.vehicle_confidence,
    'cfg-accident-conf': s.accident_confidence,
    'cfg-vehicle-size': s.vehicle_imgsz,
    'cfg-accident-size': s.accident_imgsz,
    'cfg-device': s.device,
    'cfg-interval': s.verification_interval_seconds,
    'cfg-queue': s.verification_queue_size,
    'cfg-iou': r.suspicion_iou_threshold,
    'cfg-distance': r.suspicion_distance_ratio,
    'cfg-consecutive': r.suspicion_consecutive_frames,
    'cfg-positive': r.verifier_min_positive_frames,
    'cfg-verify-conf': r.verifier_min_confidence,
    'cfg-window': r.verifier_window_seconds,
    'cfg-uncertain': r.uncertain_after_seconds,
    'cfg-upload': r.upload_max_mb,
    'cfg-sample': r.verifier_sample_interval_seconds,
    'cfg-trajectory-turn': r.trajectory_turn_threshold_degrees,
    'cfg-trajectory-min': r.trajectory_min_displacement_ratio,
    'cfg-trajectory-history': s.trajectory_history_seconds,
    'cfg-trajectory-gap': s.trajectory_max_gap_seconds,
    'cfg-trajectory-points': s.trajectory_max_points,
    'cfg-direction-pixels': s.trajectory_min_direction_pixels
  };
  Object.entries(fields).forEach(([id, value]) => {
    if ($('#' + id)) $('#' + id).value = value ?? '';
  });
}

async function loadConfig() {
  try {
    applyConfigForm(await api('/api/config'));
  } catch (err) {
    toast(err.message, true);
  }
}

async function restoreDefaultConfig() {
  try {
    applyConfigForm(await api('/api/config/defaults'));
    toast('Đã nạp thông số mặc định vào form. Bấm “Lưu cấu hình” để áp dụng.');
  } catch (err) {
    toast(err.message, true);
  }
}

async function saveConfig() {
  if (['RUNNING', 'PAUSED'].includes(state.status?.pipeline?.state)) {
    toast('Hãy dừng pipeline trước khi lưu cấu hình.', true);
    return;
  }
  const text = id => $('#' + id).value.trim(), number = id => {
    const value = text(id);
    if (!value) throw Error(`Vui lòng nhập ${$('#' + id).closest('label')?.firstChild?.textContent?.trim() || id}.`);
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) throw Error(`Giá trị không hợp lệ: ${id}.`);
    return parsed;
  };
  try {
    const body = {
      settings: {
        vehicle_model: text('cfg-vehicle-model'),
        accident_model: text('cfg-accident-model'),
        device: text('cfg-device'),
        vehicle_confidence: number('cfg-vehicle-conf'),
        accident_confidence: number('cfg-accident-conf'),
        vehicle_imgsz: number('cfg-vehicle-size'),
        accident_imgsz: number('cfg-accident-size'),
        verification_interval_seconds: number('cfg-interval'),
        verification_queue_size: number('cfg-queue'),
        trajectory_history_seconds: number('cfg-trajectory-history'),
        trajectory_max_gap_seconds: number('cfg-trajectory-gap'),
        trajectory_max_points: number('cfg-trajectory-points'),
        trajectory_min_direction_pixels: number('cfg-direction-pixels')
      },
      rules: {
        suspicion_iou_threshold: number('cfg-iou'),
        suspicion_distance_ratio: number('cfg-distance'),
        suspicion_consecutive_frames: number('cfg-consecutive'),
        verifier_min_positive_frames: number('cfg-positive'),
        verifier_min_confidence: number('cfg-verify-conf'),
        verifier_window_seconds: number('cfg-window'),
        uncertain_after_seconds: number('cfg-uncertain'),
        upload_max_mb: number('cfg-upload'),
        verifier_sample_interval_seconds: number('cfg-sample'),
        trajectory_turn_threshold_degrees: number('cfg-trajectory-turn'),
        trajectory_min_displacement_ratio: number('cfg-trajectory-min')
      }
    };
    const result = await api('/api/config', { method: 'PUT', body: JSON.stringify(body) });
    await loadConfig();
    if (result.restart_required) {
      toast('Đã lưu. Khởi động lại backend để nạp model hoặc thiết bị mới.');
    } else {
      toast('Đã lưu và áp dụng cấu hình.');
    }
    refreshStatus();
  } catch (err) {
    toast(err.message, true);
  }
}

async function loadLogs() {
  try {
    const q = $('#log-search').value;
    const d = await api(`/api/logs?limit=500${q ? `&q=${encodeURIComponent(q)}` : ''}`);
    $('#log-output').textContent = d.items.join('\n') || 'Chưa có log.';
    $('#log-output').scrollTop = $('#log-output').scrollHeight;
  } catch (err) {
    $('#log-output').textContent = err.message;
  }
}

function roiContentRect() {
  const canvas = $('#roi-canvas'), img = $('#monitor-frame'), box = canvas.getBoundingClientRect();
  if (!img.naturalWidth || !img.naturalHeight || !box.width || !box.height) return null;
  const imageBox = img.getBoundingClientRect();
  const scale = Math.min(imageBox.width / img.naturalWidth, imageBox.height / img.naturalHeight),
        width = img.naturalWidth * scale,
        height = img.naturalHeight * scale;
  return { left: imageBox.left - box.left + (imageBox.width - width) / 2,
           top: imageBox.top - box.top + (imageBox.height - height) / 2, width, height, box };
}

function drawRoi() {
  const canvas = $('#roi-canvas'), box = canvas.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
  if (!box.width || !box.height) return;
  canvas.width = Math.round(box.width * dpr);
  canvas.height = Math.round(box.height * dpr);
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, box.width, box.height);
  const rect = roiContentRect();
  if (!rect) return;
  const coords = state.roiPoints.map(([x, y]) => [rect.left + x * rect.width, rect.top + y * rect.height]);
  if (coords.length > 1) {
    ctx.beginPath();
    coords.forEach(([x, y], i) => i ? ctx.lineTo(x, y) : ctx.moveTo(x, y));
    if (coords.length >= 3) ctx.closePath();
    ctx.strokeStyle = state.roiEnabled ? '#37e0bc' : '#ffc46b';
    ctx.lineWidth = 2.5;
    ctx.setLineDash(state.roiDrawing ? [7, 5] : []);
    ctx.stroke();
    ctx.setLineDash([]);
    if (coords.length >= 3 && !state.roiDrawing) {
      ctx.fillStyle = state.roiEnabled ? 'rgba(55,224,188,.14)' : 'rgba(255,196,107,.10)';
      ctx.fill();
      ctx.beginPath();
      ctx.rect(rect.left,rect.top,rect.width,rect.height);
      ctx.moveTo(coords[0][0],coords[0][1]);
      coords.slice(1).forEach(([x,y])=>ctx.lineTo(x,y));
      ctx.closePath();
      ctx.fillStyle='rgba(0,0,0,.35)';
      ctx.fill('evenodd');
    }
  }
  for (const [x, y] of coords) {
    ctx.beginPath();
    ctx.arc(x, y, 5, 0, Math.PI * 2);
    ctx.fillStyle = '#f4fbff';
    ctx.fill();
    ctx.strokeStyle = '#0d161b';
    ctx.lineWidth = 2;
    ctx.stroke();
  }
}

function refreshRoiControls() {
  const ready = Boolean(state.upload) && $('#source-mode').value === 'video',
        valid = state.roiPoints.length >= 3,
        locked = state.roiSaving || ['RUNNING', 'PAUSED'].includes(state.status?.pipeline?.state);
  $('#roi-draw').disabled = !ready || locked;
  $('#roi-undo').disabled = !state.roiDrawing || !state.roiPoints.length || locked;
  $('#roi-finish').disabled = !state.roiDrawing || !valid || locked;
  $('#roi-cancel').disabled = !state.roiDrawing || locked;
  $('#roi-enabled').disabled = !ready || !valid || state.roiDrawing || locked;
  $('#roi-enabled').checked = state.roiEnabled;
  $('#roi-save').disabled = !ready || state.roiDrawing || locked || (state.roiEnabled && !valid);
  $('#roi-clear').disabled = !ready || state.roiDrawing || locked;
  $('#roi-anchor').disabled = !ready || locked;
  $('#roi-canvas').classList.toggle('drawing', ready && !locked);
  $('#roi-hint').textContent = $('#source-mode').value !== 'video'
    ? 'ROI hiện chỉ cấu hình cho video tải lên; camera đang phân tích toàn khung hình.'
    : state.roiDrawing
      ? `Đã chọn ${state.roiPoints.length} điểm. Bấm “Hoàn tất” khi polygon có ít nhất 3 điểm.`
      : state.roiEnabled
        ? 'ROI đã lưu: YOLO nhận ảnh cắt và che ngoài vùng; ByteTrack chỉ nhận xe hợp lệ. Kéo đỉnh để sửa vùng.'
        : 'Chọn video, bấm “Vẽ vùng ROI”, rồi bấm các điểm quanh khu vực cần theo dõi.';
  if (state.roiEnabled && !state.roiDirty) $('#roi-hint').textContent = locked ? 'Đang áp dụng ROI cho YOLO và ByteTrack.' : 'ROI đã lưu; sẽ áp dụng ở lần chạy tiếp theo. Kéo đỉnh để chỉnh sửa.';
  if (state.roiDirty) $('#roi-hint').textContent = 'Chưa lưu ROI. Bấm Lưu và áp dụng ROI trước khi chạy.';
  if (state.roiSaving) $('#roi-hint').textContent = 'Đang lưu ROI…';
  drawRoi();
}

async function loadRoi() {
  if (!state.upload) return;
  try {
    const roi = await api(`/api/roi/${encodeURIComponent(state.roiKey)}`);
    state.roiDirty = false;
    state.roiAnchor = roi.anchor || "bottom_center";
    $("#roi-anchor").value = state.roiAnchor;
    state.roiPoints = roi.points || [];
    state.roiEnabled = Boolean(roi.enabled);
  } catch (err) {
    toast(err.message, true);
  }
}

async function saveRoi() {
  if (!state.upload || state.roiSaving || state.roiDrawing) return false;
  state.roiSaving = true;
  refreshRoiControls();
  try {
    const roi = await api(`/api/roi/${encodeURIComponent(state.roiKey)}`, {
      method: 'PUT',
      body: JSON.stringify({ enabled: state.roiEnabled, points: state.roiPoints, anchor: state.roiAnchor })
    });
    state.roiDirty = false;
    state.roiPoints = roi.points;
    state.roiEnabled = roi.enabled;
    refreshRoiControls();
    toast('ROI đã lưu. Vùng sẽ áp dụng khi bắt đầu chạy.');
    return true;
  } catch (err) {
    state.roiDirty = true;
    toast(err.message, true);
    return false;
  } finally {
    state.roiSaving = false;
    refreshRoiControls();
  }
}

function roiCanvasClick(event) {
  if (!state.roiDrawing) return;
  const rect = roiContentRect();
  if (!rect) return;
  const x = (event.clientX - rect.box.left - rect.left) / rect.width,
        y = (event.clientY - rect.box.top - rect.top) / rect.height;
  if (x < 0 || x > 1 || y < 0 || y > 1) return;
  if (state.roiPoints.length >= 32) {
    toast('ROI tối đa 32 điểm.', true);
    return;
  }
  state.roiDirty = true;
  state.roiPoints.push([x, y]);
  refreshRoiControls();
}

async function uploadVideo(file) {
  if (['RUNNING', 'PAUSED'].includes(state.status?.pipeline?.state)) {
    toast('Dừng video hiện tại trước khi chọn video khác.', true);
    return;
  }
  const form = new FormData();
  form.append('file', file);
  state.previewLoaded = false;
  try {
    const d = await api('/api/videos/upload', { method: 'POST', body: form });
    state.upload = d.upload_id;
    $('#source-mode').value = 'video';
    $('#source-mode').dispatchEvent(new Event('change'));
    state.roiKey = d.roi_key;
    state.roiPoints = [];
    state.roiEnabled = false;
    $('#selected-file').textContent = `${d.filename} · ${d.metadata.width}×${d.metadata.height} · ${d.metadata.fps.toFixed(1)} FPS`;
    $('#monitor-frame').src = `/api/videos/${encodeURIComponent(state.upload)}/preview?t=${Date.now()}`;
    $('#monitor-frame').classList.remove('hidden');
    $('#monitor-placeholder').classList.add('hidden');
    state.previewLoaded = true;
    await loadRoi();
    refreshRoiControls();
    toast('Video đã tải. Bạn có thể vẽ ROI trên frame xem trước trước khi chạy.');
  } catch (err) {
    toast(err.message, true);
  }
}

async function pipeline(action) {
  try {
    let body;
    if (action === 'start') {
      const mode = $('#source-mode').value;
      if (mode === 'video' && (state.roiDirty || state.roiSaving || state.roiDrawing)) throw Error('Hoàn tất và lưu ROI thành công trước khi chạy.');
      body = mode === 'video'
        ? { source_type: 'video', upload_id: state.upload, roi_key: state.roiKey }
        : { source_type: 'camera', camera_source: mode === 'webcam' ? $('#webcam-index').value : $('#camera-url').value.trim() };
      if (mode === 'ip-camera' && !body.camera_source) throw Error('Nhập URL RTSP/HTTP của camera IP.');
    }
    await api(action === 'start' ? '/api/pipeline/start' : `/api/pipeline/${action}`, {
      method: 'POST',
      ...(body ? { body: JSON.stringify(body) } : {})
    });
    refreshStatus();
  } catch (err) {
    toast(err.message, true);
  }
}

async function exportFile(kind) {
  try {
    const response = await fetch(`/api/export/${kind}`);
    if (!response.ok) throw Error('Không thể xuất báo cáo');
    const blob = await response.blob(), url = URL.createObjectURL(blob), a = document.createElement('a');
    a.href = url;
    a.download = `atads-events.${kind}`;
    a.click();
    URL.revokeObjectURL(url);
  } catch (err) {
    toast(err.message, true);
  }
}

function connectSocket() {
  const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
  state.ws = new WebSocket(`${scheme}://${location.host}/api/ws`);
  state.ws.onmessage = event => {
    try {
      const m = JSON.parse(event.data);
      if (m.type === 'event' || m.type === 'event_update') {
        if (m.type === 'event') playAlertTone();
        loadRecent();
        if (state.page === 'events') loadEvents();
        refreshStatus();
      }
      if (m.type === 'state') {
        refreshStatus();
      }
      if (m.type === 'metrics') {
        const fps = Number(m.processing_fps ?? 0);
        const lat = Number(m.output_latency_ms ?? 0);
        const vehs = m.vehicles || [];
        if (fps > 0) $('#live-fps').textContent = fps.toFixed(1);
        if (lat > 0) $('#live-latency').textContent = `${lat.toFixed(1)} ms`;
        $('#live-tracks').textContent = vehs.length;
        if (m.frame_index != null) $('#live-frame').textContent = m.frame_index;

        if (state.status?.pipeline) {
          state.status.pipeline.output_fps = fps;
          state.status.pipeline.output_latency_ms = lat;
          state.status.pipeline.tracked_vehicles = vehs;
          state.status.pipeline.frame_index = m.frame_index;
          if (m.suspicion) {
            state.status.pipeline.last_suspicion = m.suspicion;
            if (!state.status.pipeline.last_verification) {
              updateVerificationCard(state.status.pipeline);
            }
          }
        }
        renderTrackList(vehs);
        renderFrequencyChart(m.frequency_bins || state.status?.pipeline?.frequency_bins || []);
      }
      if (m.type === 'verification') {
        const detections = m.detections || [];
        const pipelineState = {
          ...(state.status?.pipeline || {}),
          last_verification: { ...m.result, max_confidence: m.result.max_confidence ?? m.result.confidence },
          accident_detections: detections.filter(d => (d.class_name || '').toLowerCase() === 'accident')
        };
        if (state.status) state.status.pipeline = pipelineState;
        updateVerificationCard(pipelineState);
      }
      if (m.type === 'error') toast(m.message, true);
    } catch (e) {
      console.error('WS message parse error', e);
    }
  };
  state.ws.onclose = () => setTimeout(connectSocket, 2500);
}

async function saveVisualization() {
  const body = {
    trajectory_enabled: $('#trajectory-toggle').checked,
    show_track_ids: $('#track-id-toggle').checked,
    show_direction: $('#direction-toggle').checked,
    history_seconds: Number($('#trajectory-history').value),
    selected_track_id: $('#track-focus').value
  };
  try {
    await api('/api/pipeline/visualization', { method: 'PUT', body: JSON.stringify(body) });
  } catch (err) {
    toast(err.message, true);
  }
}

async function clearTrajectories() {
  try {
    await api('/api/pipeline/trajectories/clear', { method: 'POST' });
    toast('Đã xóa lịch sử quỹ đạo hiện tại.');
  } catch (err) {
    toast(err.message, true);
  }
}

// Event Listeners Setup
$('#signal-mode')?.addEventListener('change', () => updateSignal(state.status));
$('#signal-manual')?.addEventListener('change', () => updateSignal(state.status));
$('#trajectory-toggle').addEventListener('change', saveVisualization);
$('#track-id-toggle').addEventListener('change', saveVisualization);
$('#direction-toggle').addEventListener('change', saveVisualization);
$('#trajectory-history').addEventListener('change', saveVisualization);
$('#track-focus').addEventListener('change', saveVisualization);
$('#clear-trajectories').addEventListener('click', clearTrajectories);

$('#track-list').addEventListener('click', event => {
  const item = event.target.closest('[data-focus-track]');
  if (item && item.dataset.focusTrack) {
    const id = item.dataset.focusTrack;
    $('#track-focus').value = ($('#track-focus').value === id) ? 'all' : id;
    saveVisualization();
  }
});

$$('.nav').forEach(b => b.addEventListener('click', () => setPage(b.dataset.page)));
$$('[data-go]').forEach(b => b.addEventListener('click', () => setPage(b.dataset.go)));

$('#source-mode').addEventListener('change', () => {
  const mode = $('#source-mode').value;
  $('#webcam-source-wrap').classList.toggle('hidden', mode !== 'webcam');
  $('#ip-camera-source-wrap').classList.toggle('hidden', mode !== 'ip-camera');
  $('#selected-file').textContent = mode === 'video' ? (state.upload ? $('#selected-file').textContent : 'Chưa chọn file') : mode === 'webcam' ? 'Webcam ' + $('#webcam-index').value : 'Camera IP';
  $('#start-btn').disabled = mode === 'video' ? !state.upload : mode === 'ip-camera' ? !$('#camera-url').value.trim() : false;
  refreshRoiControls();
});

$('#webcam-index').addEventListener('change', () => {
  $('#selected-file').textContent = 'Webcam ' + $('#webcam-index').value;
});

$('#camera-url').addEventListener('input', () => {
  $('#start-btn').disabled = !$('#camera-url').value.trim();
});

$('#video-file').addEventListener('change', e => {
  if (e.target.files[0]) uploadVideo(e.target.files[0]);
});

$('#monitor-frame').addEventListener('load', drawRoi);
$('#roi-canvas').addEventListener('click', roiCanvasClick);

$('#roi-draw').addEventListener('click', () => {
  if (['RUNNING', 'PAUSED'].includes(state.status?.pipeline?.state)) {
    toast('Dừng video trước khi sửa ROI.', true);
    return;
  }
  state.roiOriginalPoints = structuredClone(state.roiPoints);
  state.roiOriginalEnabled = state.roiEnabled;
  state.roiOriginalDirty = state.roiDirty;
  state.roiPoints = [];
  state.roiEnabled = false;
  state.roiDrawing = true;
  refreshRoiControls();
});

$('#roi-undo').addEventListener('click', () => {
  state.roiDirty = true;
  state.roiPoints.pop();
  refreshRoiControls();
});

$('#roi-finish').addEventListener('click', () => {
  if (state.roiPoints.length < 3) return;
  state.roiDrawing = false;
  state.roiDirty = true;
  refreshRoiControls();
});

$('#roi-cancel').addEventListener('click', () => {
  state.roiPoints = state.roiOriginalPoints;
  state.roiEnabled = state.roiOriginalEnabled;
  state.roiDirty = state.roiOriginalDirty;
  state.roiDrawing = false;
  refreshRoiControls();
});

$('#roi-enabled').addEventListener('change', async e => {
  state.roiDirty = true;
  state.roiEnabled = e.target.checked;
  refreshRoiControls();
  refreshRoiControls();
});

$('#roi-save').textContent = 'Lưu và áp dụng ROI';
$('#roi-save').addEventListener('click', saveRoi);
$('#roi-anchor').addEventListener('change', e => { state.roiAnchor=e.target.value; state.roiDirty=true; refreshRoiControls(); });

$('#roi-clear').addEventListener('click', async () => {
  state.roiPoints = [];
  state.roiDirty = true;
  state.roiEnabled = false;
  state.roiDrawing = false;
  refreshRoiControls();
  await saveRoi();
});

window.addEventListener('resize', drawRoi);

$('#start-btn').addEventListener('click', () => pipeline('start'));
$('#pause-btn').addEventListener('click', () => pipeline(state.status?.pipeline?.state === 'PAUSED' ? 'resume' : 'pause'));
$('#stop-btn').addEventListener('click', () => pipeline('stop'));

$('#frequency-window').addEventListener('change', () => renderFrequencyChart(state.status?.pipeline?.frequency_bins || []));



$('#refresh-events').addEventListener('click', loadEvents);
$('#refresh-status').addEventListener('click', refreshStatus);
$('#refresh-logs').addEventListener('click', loadLogs);

// NOTE: Fixed selector from $$ to $ so it doesn't crash
$('#save-settings').addEventListener('click', saveConfig);
document.querySelector('#restore-default-settings').addEventListener('click', restoreDefaultConfig);

$('#event-status-filter').addEventListener('change', () => {
  state.eventOffset = 0;
  loadEvents();
});

$('#history-status-filter').addEventListener('change', () => {
  state.historyOffset = 0;
  loadHistory();
});

$('#event-search').addEventListener('input', debounce(loadEvents, 250));
$('#history-search').addEventListener('input', debounce(loadHistory, 250));
$('#history-source').addEventListener('input', debounce(loadHistory, 250));
$('#log-search').addEventListener('input', debounce(loadLogs, 250));

document.addEventListener('click', e => {
  const ev = e.target.closest('[data-event]');
  if (ev) showEvent(ev.dataset.event);
  const review = e.target.closest('[data-review]');
  if (review) reviewEvent(review.dataset.id, review.dataset.review);
  const pg = e.target.closest('[data-page-offset]');
  if (pg) {
    state[pg.dataset.kind === 'events' ? 'eventOffset' : 'historyOffset'] = Number(pg.dataset.pageOffset);
    pg.dataset.kind === 'events' ? loadEvents() : loadHistory();
  }
  const ex = e.target.closest('[data-export]');
  if (ex) exportFile(ex.dataset.export);
  if (e.target.id === 'save-note') reviewEvent(e.target.dataset.id, undefined);
});

function debounce(fn, ms) {
  let timer;
  return () => {
    clearTimeout(timer);
    timer = setTimeout(fn, ms);
  };
}

function tick() {
  const d = new Date();
  const el = $('#clock');
  if (el) el.textContent = d.toLocaleString('vi-VN', { hour12: false });
}

// App Initialization
refreshRoiControls();
tick();
setInterval(tick, 1000);
refreshStatus();
loadRecent();
connectSocket();
state.refreshTimer = setInterval(() => {
  refreshStatus();
  loadRecent();
}, 1800);

// Drag existing vertices after finishing; use pointer capture to keep drags stable.
let roiDrag = -1;
$('#roi-canvas').addEventListener('pointerdown', e => {
  e.preventDefault();
  window.getSelection()?.removeAllRanges();
  if (state.roiDrawing || ['RUNNING','PAUSED'].includes(state.status?.pipeline?.state)) return;
  const r=roiContentRect(); if (!r) return;
  roiDrag=state.roiPoints.findIndex(([x,y]) => Math.hypot(e.clientX-r.box.left-r.left-x*r.width,e.clientY-r.box.top-r.top-y*r.height)<12);
  if(roiDrag>=0) e.target.setPointerCapture(e.pointerId);
});
$('#roi-canvas').addEventListener('pointermove', e => {
  if(roiDrag<0) return;
  const r=roiContentRect();
  state.roiPoints[roiDrag]=[Math.max(0,Math.min(1,(e.clientX-r.box.left-r.left)/r.width)),Math.max(0,Math.min(1,(e.clientY-r.box.top-r.top)/r.height))];
  state.roiDirty=true; drawRoi();
});
$('#roi-canvas').addEventListener('pointerup', () => { roiDrag=-1; refreshRoiControls(); });
$('#roi-canvas').addEventListener('pointercancel', () => { roiDrag=-1; refreshRoiControls(); });

new ResizeObserver(drawRoi).observe($('#monitor-stage'));
$('#monitor-frame').draggable = false;
