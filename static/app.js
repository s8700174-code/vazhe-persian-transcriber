const $ = id => document.getElementById(id);
let file = null, jobId = null, segments = [], audioUrl = null, busy = false, polling = false;
let maxFileBytes = 10 * 1024 * 1024 * 1024;
const GROUP_SECONDS = 180;
const audioGroups = new Map();
let activeGroup = null, playbackTimer = null;
const controls = ['file', 'model', 'device', 'prompt', 'vad', 'api-key', 'zero-retention', 'cloud-consent'];
let persianReady = false;
function updateEngineUI() {
  const cloud = $('model').value === 'scribe-v2';
  $('cloud-settings').hidden = !cloud;
  ['device','prompt','vad'].forEach(id => $(id).disabled = busy || cloud);
  $('privacy-title').textContent = cloud ? 'پردازش آنلاین با تأیید شما' : 'پردازش محلی';
  $('privacy-text').textContent = cloud ? 'صوت برای تبدیل به ElevenLabs ارسال می‌شود. تنظیم نگه‌داری داده را پیش از شروع بررسی کنید.' : 'صوت در مدل‌های محلی روی همین دستگاه پردازش می‌شود و به سرویس ابری ارسال نمی‌شود.';
  $('privacy-badge').textContent = cloud ? 'ElevenLabs · آنلاین' : 'روی دستگاه شما';
  $('download-note').textContent = cloud ? 'کلید API و اعتبار ElevenLabs لازم است. انتخاب پردازندهٔ سیستم در این حالت اثری ندارد.' : 'هر مدل محلی به وزن‌های خودش نیاز دارد؛ پس از آماده‌سازی، تبدیل آفلاین است.';
  const note = $('engine-note'); note.replaceChildren();
  if ($('model').value === 'persian-v4' && !persianReady) {
    note.append('مدل جدید هنوز آماده نشده است. ');
    const link = document.createElement('a'); link.href = '/static/models.html'; link.target = '_blank'; link.textContent = 'راهنمای نصب Persian v4'; note.append(link);
  } else if ($('model').value === 'persian-v4') note.textContent = 'وزن‌های محلی Persian v4 آماده‌اند؛ دقت روی فایل شما باید مقایسه شود.';
}
$('model').addEventListener('change', () => { $('cloud-consent').checked = false; updateEngineUI(); });
const labels = {queued:'در صف', loading:'آماده‌سازی', transcribing:'در حال تبدیل', done:'تکمیل شد', error:'خطا', cancelled:'متوقف شد'};

function toast(message) { $('toast').textContent = message; $('toast').hidden = false; clearTimeout(toast.timer); toast.timer = setTimeout(() => $('toast').hidden = true, 3500); }
function showError(message) { $('error').textContent = message; $('error').hidden = false; }
function setBusy(value) { busy = value; controls.forEach(id => $(id).disabled = value); $('start').disabled = value || !file; $('start').textContent = value ? 'در حال پردازش…' : 'شروع تبدیل ←'; updateEngineUI(); }
function selectFile(selected) {
  if (!selected || busy) return;
  if (!selected.size) return showError(`فایل «${selected.name}» خالی است (صفر بایت). نسخهٔ کامل فایل صوتی را انتخاب کنید.`);
  if (selected.size > maxFileBytes) return showError(`حجم فایل «${selected.name}» برابر ${(selected.size / 1024 ** 3).toLocaleString('fa-IR', {maximumFractionDigits: 2})} گیگابایت است؛ سقف مجاز ${(maxFileBytes / 1024 ** 3).toLocaleString('fa-IR')} گیگابایت است.`);
  if (!/\.(mp3|wav|m4a|ogg|flac|aac|mp4|webm|wma|opus)$/i.test(selected.name)) return showError('این فرمت پشتیبانی نمی‌شود.');
  if (segments.length && !confirm('با انتخاب فایل جدید، متن فعلی پاک می‌شود. خروجی را ذخیره کرده‌اید؟')) return;
  // Vocabulary belongs to this recording, never to unrelated uploads.
  $('prompt').value = '';
  $('cloud-consent').checked = false;
  resetGroups();
  file = selected; jobId = null; segments = []; sessionStorage.removeItem('v2t-job'); $('segments').replaceChildren(); $('empty').hidden = false; $('progress-area').hidden = true;
  ['copy','txt','srt','vtt'].forEach(id => $(id).disabled = true);
  $('status-pill').textContent = 'آماده'; $('result-meta').textContent = 'آماده برای اولین واژه';
  $('error').hidden = true; $('file-title').textContent = file.name;
  $('file-subtitle').textContent = `${(file.size / 1024 / 1024).toFixed(1)} MB — برای تغییر کلیک کنید`;
  if (audioUrl) URL.revokeObjectURL(audioUrl);
  audioUrl = URL.createObjectURL(file); $('audio').src = audioUrl; $('audio').hidden = false; $('start').disabled = false;
}
$('file').addEventListener('change', e => selectFile(e.target.files[0]));
$('attach-audio').addEventListener('change', e => {
  const source = e.target.files[0]; if (!source) return;
  let expected = file;
  if (!expected) { try { expected = JSON.parse(sessionStorage.getItem('v2t-source')); } catch {} }
  if (expected && (source.name !== expected.name || source.size !== expected.size)) {
    e.target.value = ''; return toast('برای تطبیق زمان‌ها، همان فایل صوتی اصلی را انتخاب کنید.');
  }
  if (!source.size) return toast('فایل صوتی خالی است.');
  $('audio').pause(); activeGroup = null;
  if (audioUrl) URL.revokeObjectURL(audioUrl);
  audioUrl = URL.createObjectURL(source); $('audio').src = audioUrl; $('audio').hidden = false;
  file = source; updatePlayers(); toast('صوت متصل شد؛ متن و ویرایش‌ها حفظ شدند.');
});
['dragover','dragenter'].forEach(name => $('dropzone').addEventListener(name, e => { e.preventDefault(); if (!busy) $('dropzone').classList.add('drag'); }));
['dragleave','drop'].forEach(name => $('dropzone').addEventListener(name, e => { e.preventDefault(); $('dropzone').classList.remove('drag'); }));
$('dropzone').addEventListener('drop', e => selectFile(e.dataTransfer.files[0]));

async function api(url, options = {}) {
  const response = await fetch(url, {...options, headers: {'X-V2T-Client':'local', ...(options.headers || {})}});
  if (!response.ok) { let data; try { data = await response.json(); } catch {} throw new Error(typeof data?.detail === 'string' ? data.detail : `خطای ارتباط (${response.status})`); }
  return response.json();
}
function stamp(seconds, separator = ',') { const ms = Math.max(0, Math.round(seconds * 1000)); return `${String(Math.floor(ms / 3600000)).padStart(2,'0')}:${String(Math.floor(ms / 60000) % 60).padStart(2,'0')}:${String(Math.floor(ms / 1000) % 60).padStart(2,'0')}${separator}${String(ms % 1000).padStart(3,'0')}`; }
function resetGroups() {
  $('audio').pause(); activeGroup = null; audioGroups.clear();
  clearInterval(playbackTimer);
}
function updatePlayers() {
  const audio = $('audio');
  if (activeGroup && audio.currentTime >= activeGroup.end) {
    audio.pause(); activeGroup = null;
  }
  for (const group of audioGroups.values()) {
    const playing = activeGroup === group && !audio.paused;
    group.play.textContent = playing ? 'Ⅱ مکث' : '▶ پخش این بخش';
    group.play.setAttribute('aria-pressed', String(playing));
    if (activeGroup === group) group.seek.value = Math.min(group.end, Math.max(group.start, audio.currentTime));
  }
}
async function playGroup(group, from = null) {
  if (!audioUrl) return toast('صوت این صفحه در دسترس نیست. برای بازشنوی، فایل صوتی را با دکمهٔ «اتصال صوت» انتخاب کنید.');
  const audio = $('audio');
  if (from === null && activeGroup === group && !audio.paused) { audio.pause(); updatePlayers(); return; }
  const resume = activeGroup === group && audio.currentTime >= group.start && audio.currentTime < group.end;
  activeGroup = group;
  audio.currentTime = from ?? (resume ? audio.currentTime : group.start);
  try { await audio.play(); } catch { toast('پخش صوت ممکن نیست؛ فرمت فایل و اتصال صوت را بررسی کنید.'); }
  updatePlayers();
}
$('audio').addEventListener('play', () => { clearInterval(playbackTimer); playbackTimer = setInterval(updatePlayers, 50); updatePlayers(); });
$('audio').addEventListener('pause', () => { clearInterval(playbackTimer); updatePlayers(); });
$('audio').addEventListener('ended', () => { activeGroup = null; updatePlayers(); });
$('audio').addEventListener('timeupdate', updatePlayers);
function groupFor(item) {
  const key = Math.floor(item.start / GROUP_SECONDS);
  if (!audioGroups.has(key)) {
    const box = document.createElement('section'); box.className = 'transcript-group';
    const header = document.createElement('div'); header.className = 'group-header';
    const title = document.createElement('strong'); title.textContent = `بخش ${(audioGroups.size + 1).toLocaleString('fa-IR')}`;
    const times = document.createElement('span'); times.className = 'group-times';
    const play = document.createElement('button'); play.className = 'group-play'; play.textContent = '▶ پخش این بخش';
    const seek = document.createElement('input'); seek.type = 'range'; seek.step = '0.1'; seek.className = 'group-seek';
    seek.setAttribute('aria-label', `جابه‌جایی در صوت ${title.textContent}`);
    const body = document.createElement('div'); body.className = 'group-body';
    const group = {start:item.start, end:item.end, body, times, play, seek};
    seek.min = item.start; seek.value = item.start;
    play.addEventListener('click', () => playGroup(group));
    seek.addEventListener('input', () => {
      if (!audioUrl) return toast('ابتدا فایل صوتی را با دکمهٔ اتصال صوت انتخاب کنید.');
      activeGroup = group; $('audio').currentTime = Number(seek.value); updatePlayers();
    });
    header.append(title, times, play); box.append(header, seek, body); $('segments').append(box);
    audioGroups.set(key, group);
  }
  const group = audioGroups.get(key);
  group.end = Math.max(group.end, item.end); group.seek.max = group.end;
  group.times.textContent = `${stamp(group.start).slice(0,8)} — ${stamp(group.end).slice(0,8)}`;
  return group;
}
function renderSegments(incoming) {
  incoming.slice(segments.length).forEach(item => {
    const index = segments.length; segments.push({...item});
    const group = groupFor(item);
    const row = document.createElement('div'); row.className = 'segment';
    const top = document.createElement('div'); top.className = 'segment-top';
    const timestamp = document.createElement('button'); timestamp.className = 'timestamp'; timestamp.textContent = stamp(item.start).slice(0,8); timestamp.title = 'پخش از این زمان';
    timestamp.addEventListener('click', () => playGroup(group, item.start));
    top.append(timestamp);
    if (item.review) { const badge = document.createElement('span'); badge.className = 'review-label'; badge.textContent = '● نیازمند بازبینی'; top.append(badge); }
    const editor = document.createElement('textarea'); editor.value = item.text; editor.setAttribute('aria-label', `متن بخش ${index+1}`); editor.rows = Math.max(2, Math.ceil(item.text.length / 65));
    editor.addEventListener('input', () => { segments[index].text = editor.value; updateMeta(); });
    row.append(top, editor); group.body.append(row);
  });
  $('empty').hidden = segments.length > 0;
  ['copy','txt','srt','vtt'].forEach(id => $(id).disabled = !segments.length);
  updateMeta();
}
function plainText() { return segments.map(s => s.text.trim()).filter(Boolean).join('\n'); }
function updateMeta() { const words = plainText().split(/\s+/).filter(Boolean).length; $('result-meta').textContent = `${audioGroups.size.toLocaleString('fa-IR')} باکس · ${words.toLocaleString('fa-IR')} واژه · بخش‌های حدود ۳ دقیقه`; }
$('start').addEventListener('click', async () => {
  if (!file || busy) return;
  const cloud = $('model').value === 'scribe-v2';
  if (cloud && (!$('cloud-consent').checked || !$('api-key').value.trim())) return showError('کلید API و تأیید ارسال همین فایل به ElevenLabs لازم است.');
  if ($('model').value === 'persian-v4' && !persianReady) return showError('ابتدا Persian v4 را با راهنمای نصب آماده کنید و سپس صفحه را تازه‌سازی کنید. فایل صوتی هنوز برای پردازش دریافت نشده است.');
  if (cloud && file.size >= 5000000000) return showError('فایل Scribe باید کمتر از ۵ میلیارد بایت باشد.');
  if (segments.length && !confirm('متن قبلی با نتیجهٔ جدید جایگزین می‌شود. ادامه می‌دهید؟')) return;
  $('error').hidden = true; setBusy(true); $('progress-area').hidden = false; $('progress').removeAttribute('value'); $('progress-message').textContent = 'در حال دریافت فایل…'; $('cancel').disabled = true;
  const data = new FormData(); data.append('file',file); data.append('model',$('model').value); data.append('device',$('device').value); data.append('prompt',cloud ? '' : $('prompt').value); data.append('vad',String($('vad').checked));
  if (cloud) { data.append('api_key',$('api-key').value.trim()); data.append('cloud_consent',String($('cloud-consent').checked)); data.append('zero_retention',String($('zero-retention').checked)); }
  try { const result = await api('/api/jobs',{method:'POST',body:data}); jobId = result.id; $('api-key').value = ''; $('cloud-consent').checked = false; sessionStorage.setItem('v2t-job',jobId); sessionStorage.setItem('v2t-source', JSON.stringify({name:file.name,size:file.size})); resetGroups(); segments = []; $('segments').replaceChildren(); renderSegments([]); $('cancel').disabled = false; poll(); }
  catch (e) { showError(e.message); setBusy(false); $('progress-area').hidden = true; }
});
async function poll() {
  if (polling || !jobId) return; polling = true;
  let failures = 0;
  try {
    while (jobId) {
      let job;
      try { job = await api(`/api/jobs/${jobId}`); failures = 0; $('error').hidden = true; }
      catch (e) { failures++; showError(`${e.message} — تلاش دوباره برای اتصال…`); if (failures >= 10) { setBusy(false); $('progress-area').hidden = true; showError('ارتباط با برنامه قطع شد. صفحه را تازه‌سازی کنید تا وضعیت پردازش بازیابی شود.'); break; } await new Promise(r => setTimeout(r,2000)); continue; }
      $('status-pill').textContent = labels[job.status] || job.status;
      $('progress-message').textContent = job.message;
      if (job.status === 'loading' || job.status === 'queued' || (job.model === 'scribe-v2' && job.status === 'transcribing')) $('progress').removeAttribute('value'); else $('progress').value = job.progress;
      renderSegments(job.segments);
      if (['done','error','cancelled'].includes(job.status)) {
        setBusy(false); $('progress-area').hidden = true;
        if (job.status === 'error') showError(job.message);
        else if (job.status === 'done' && !segments.length) showError('گفتاری پیدا نشد. فایل را بررسی کنید یا تشخیص سکوت را خاموش کنید.');
        else toast(job.status === 'done' ? 'متن شما آماده است.' : 'پردازش متوقف شد.');
        break;
      }
      setBusy(true); $('progress-area').hidden = false; $('cancel').disabled = job.cancel_requested;
      await new Promise(r => setTimeout(r,1200));
    }
  } finally { polling = false; }
}
$('cancel').addEventListener('click', async () => { if (!jobId) return; try { await api(`/api/jobs/${jobId}`, {method:'DELETE'}); $('cancel').disabled = true; $('progress-message').textContent = 'در انتظار توقف بخش جاری…'; } catch(e) { showError(e.message); } });
$('copy').addEventListener('click', async () => { try { await navigator.clipboard.writeText(plainText()); toast('متن کپی شد.'); } catch { showError('کپی مجاز نیست؛ از دریافت TXT استفاده کنید.'); } });
function download(kind) {
  let text = plainText();
  if (kind !== 'txt') { const active = segments.filter(s => s.text.trim()); text = (kind === 'vtt' ? 'WEBVTT\n\n' : '') + active.map((s,i) => `${kind === 'srt' ? `${i+1}\n` : ''}${stamp(s.start,kind === 'vtt' ? '.' : ',')} --> ${stamp(s.end,kind === 'vtt' ? '.' : ',')}\n${s.text.trim().replace(/\n\s*\n/g,'\n')}\n`).join('\n'); }
  const blob = new Blob([kind === 'txt' ? '\uFEFF' : '',text], {type:kind === 'vtt' ? 'text/vtt;charset=utf-8' : 'text/plain;charset=utf-8'});
  const link = document.createElement('a'); const url = URL.createObjectURL(blob); link.href = url; link.download = `${file?.name.replace(/\.[^.]+$/,'') || 'transcript'}.${kind}`; link.click(); setTimeout(() => URL.revokeObjectURL(url),1000);
}
['txt','srt','vtt'].forEach(kind => $(kind).addEventListener('click', () => download(kind)));
window.addEventListener('beforeunload', e => { if (busy || segments.length) { e.preventDefault(); e.returnValue = ''; } });
api('/api/health').then(health => { persianReady = Boolean(health.persian_ready); updateEngineUI(); maxFileBytes = health.max_bytes || health.max_mb * 1024 * 1024; $('size-limit').textContent = `تا ${(maxFileBytes / 1024 ** 3).toLocaleString('fa-IR')} گیگابایت`; $('connection').textContent = 'اتصال به برنامهٔ محلی برقرار است'; }).catch(() => $('connection').textContent = 'ارتباط برقرار نیست');
jobId = sessionStorage.getItem('v2t-job'); if (jobId) { setBusy(true); poll(); }
