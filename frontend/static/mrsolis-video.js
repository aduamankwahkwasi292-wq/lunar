'use strict';
// ══════════════════════════════════════════════════════════════════════
//   A VIDEO IN THE CHAT BOX (backend/video.py)
// ══════════════════════════════════════════════════════════════════════
// The student attaches a video or a recorded lecture (picture button, or drop it anywhere). MrSOLIS
// prepares it once — what is said (Parakeet) and frames spread over it — then answers questions about
// it. Unlike a picture it stays attached for follow-up questions until the student removes it. As soon
// as it is ready the brain reads it in the background, so the first answer comes quickly too.
const VID = { id: null, name: '', state: '', progress: 0, frames: 0, timer: null };
const vidChip = $('vid-chip');
const MEDIA_RE = /\.(mp4|mkv|webm|mov|avi|m4v|3gp|wmv|flv|mpg|mpeg|ts|mp3|m4a|wav|aac|ogg|opus|flac|wma|amr)$/i;

function isVideoFile(f) {
    return !!f && (/^(video|audio)\//.test(f.type || '') || MEDIA_RE.test(f.name || ''));
}

/** The file's place on this computer (desktop app), so a big video is read where it is, not copied. */
function filePath(f) {
    try {
        if (window.mrsolisFiles && window.mrsolisFiles.pathFor) return window.mrsolisFiles.pathFor(f) || '';
    } catch (e) { /* not the desktop app */ }
    return f.path || '';
}

const STATE_TEXT = {
    starting: 'Opening…', waiting: 'Waiting for another video…', probing: 'Opening…',
    listening: 'Listening to what is said…', watching: 'Looking at the frames…',
};

function drawVideo() {
    if (!VID.id && !VID.state) { vidChip.hidden = true; return; }
    vidChip.hidden = false;
    vidChip.querySelector('.vid-name').textContent = VID.name;
    const ready = VID.state === 'ready';
    const pct = Math.round(100 * (VID.progress || 0));
    vidChip.querySelector('.vid-state').textContent = ready
        ? (VID.frames ? 'Watched — ask anything about it' : 'Listened — ask anything about it')
        : `${STATE_TEXT[VID.state] || 'Opening…'}${pct ? ` ${pct}%` : ''}`;
    vidChip.classList.toggle('ready', ready);
    vidChip.querySelector('.vid-bar > i').style.width = `${ready ? 100 : pct}%`;
    const img = vidChip.querySelector('img');
    if (ready && VID.frames && img.hidden) {
        img.onload = () => { img.hidden = false; vidChip.querySelector('.vid-thumb .ico').style.display = 'none'; };
        img.src = `/api/video/${VID.id}/frame/0`;
    }
}

function applyStatus(st) {
    VID.state = st.state;
    VID.progress = st.progress || 0;
    VID.frames = st.frames || 0;
    if (st.name) VID.name = st.name;
    drawVideo();
}

async function pollVideo() {
    clearTimeout(VID.timer);
    const id = VID.id;
    if (!id) return;
    try {
        const st = await api(`/api/video/${id}`);
        if (id !== VID.id) return;
        if (st.state === 'error') { showToast(st.error || 'MrSOLIS couldn’t watch this video', 5000); clearVideo(); return; }
        if (st.state === 'missing') { clearVideo(); return; }
        applyStatus(st);
        if (st.state === 'ready') {
            api(`/api/video/${id}/warm`, { method: 'POST' }).catch(() => {});    // read it now, while they type
            return;
        }
    } catch (e) { /* the backend is busy: try again */ }
    VID.timer = setTimeout(pollVideo, 700);
}

async function attachVideo(file) {
    if (!isVideoFile(file)) return false;
    clearVideo();
    if (typeof clearPicture === 'function') clearPicture();          // one attachment at a time
    VID.name = file.name;
    VID.state = 'starting';
    drawVideo();
    try {
        const path = filePath(file);
        let st;
        if (path) {
            st = await api('/api/video/prepare', { method: 'POST', body: { path, name: file.name } });
        } else {                                                     // no path (e.g. a browser): send the file
            const fd = new FormData();
            fd.append('file', file);
            const res = await fetch('/api/video/upload', { method: 'POST', body: fd });
            st = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(st.detail || 'The video couldn’t be opened');
        }
        VID.id = st.id;
        applyStatus(st);
        lessonUi();
        chatInput.focus();
        if (st.state !== 'ready') pollVideo();
        else api(`/api/video/${st.id}/warm`, { method: 'POST' }).catch(() => {});
    } catch (e) {
        clearVideo();
        showToast(e.message, 5000);
    }
    return true;
}

function clearVideo() {
    clearTimeout(VID.timer);
    Object.assign(VID, { id: null, name: '', state: '', progress: 0, frames: 0, timer: null });
    vidChip.hidden = true;
    vidChip.classList.remove('ready');
    const img = vidChip.querySelector('img');
    img.hidden = true;
    img.removeAttribute('src');
    vidChip.querySelector('.vid-thumb .ico').style.display = '';
    if (typeof lessonUi === 'function') lessonUi();
}

vidChip.querySelector('button').addEventListener('click', clearVideo);
// the picture button takes videos too
picInput.addEventListener('change', () => {
    const f = picInput.files && picInput.files[0];
    if (f && isVideoFile(f)) { picInput.value = ''; attachVideo(f); }
}, true);
