const API_BASE = ''

// Stream newline-delimited JSON (NDJSON) objects from a POST endpoint,
// invoking onObject(obj) for each line as it arrives.
async function streamNDJSON(url, body, onObject, signal) {
    const res = await fetch(`${API_BASE}${url}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal
    });
    if (!res.ok || !res.body) {
        let detail = `Request failed (${res.status})`;
        try { detail = (await res.json()).detail || detail; } catch (e) {}
        throw new Error(detail);
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let idx;
        while ((idx = buffer.indexOf('\n')) >= 0) {
            const line = buffer.slice(0, idx).trim();
            buffer = buffer.slice(idx + 1);
            if (line) { try { onObject(JSON.parse(line)); } catch (e) {} }
        }
    }
    const tail = buffer.trim();
    if (tail) { try { onObject(JSON.parse(tail)); } catch (e) {} }
}

// State
let state = {
    sessionId: null,
    providers: {},
    currentProvider: null,
    questions: [],
    quiz: [],
    currentQuestionIndex: 0,
    score: 0,
    answers: {},
    timerInterval: null,
    timeRemaining: 0,
    abortController: null,
    topics: [],
    selectedTopics: [],
    weakAreas: [],
    quizType: 'mcq',
    viewedSolutions: new Set(),
    // Voice mode state
    userName: localStorage.getItem('lunar_user_name') || '',
    voiceMode: false,
    currentAudio: null,
    voiceQueue: [],
    isPlaying: false,
    currentLectureTopic: '',
    // Conversation state: 'intro', 'conversation', 'lecturing'
    conversationState: 'intro',
    lectureChunks: [],
    currentChunkIndex: 0,
    lectureData: null,
    awaitingResponse: false,
    askLunarMessages: [],
    voiceHistory: []
};

// On-device voice configuration (local Whisper STT + Piper TTS — no API keys)
const VOICE_CONFIG = {
    sttEndpoint: '/api/stt',
    ttsEndpoint: '/api/tts',
    targetSampleRate: 16000,
    // Voice-activity detection (turn-taking + barge-in)
    silenceThreshold: 0.012,   // RMS below this counts as silence
    speechThreshold: 0.02,     // RMS above this counts as speech
    silenceHangoverMs: 900,    // trailing silence that ends an utterance
    minSpeechMs: 350,          // ignore blips shorter than this
    bargeInMs: 280,            // sustained speech needed to interrupt Lunar
    maxUtteranceMs: 15000      // safety cap on a single utterance
};

// On-device speech recognition state
let isListening = false;
let duplexListening = false;   // always-on listening mode
let audioStream = null;
let audioContext = null;
let micSource = null;
let processorNode = null;
let currentTTSAudio = null;    // current TTS audio (for interruption)
let isProcessingUtterance = false;
// VAD buffers / timers
let vadBuffer = [];            // collected Float32 frames for the current utterance
let vadSpeaking = false;
let vadSpeechMs = 0;
let vadSilenceMs = 0;
let vadBargeMs = 0;
let captureSampleRate = 48000;

// Local STT — start always-on listening using the mic + RMS voice-activity detection
async function startDuplexListening() {
    if (!state.voiceMode) return;
    stopDuplexListening();
    try {
        audioStream = await navigator.mediaDevices.getUserMedia({
            audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true }
        });
        const AudioCtx = window.AudioContext || window.webkitAudioContext;
        audioContext = new AudioCtx();
        captureSampleRate = audioContext.sampleRate || 48000;
        micSource = audioContext.createMediaStreamSource(audioStream);
        processorNode = audioContext.createScriptProcessor(4096, 1, 1);

        resetVad();
        duplexListening = true;
        isListening = true;
        if (lunarStatusText) lunarStatusText.textContent = '🎤 Listening...';

        processorNode.onaudioprocess = (e) => {
            if (!state.voiceMode || isProcessingUtterance) return;
            handleAudioFrame(e.inputBuffer.getChannelData(0));
        };
        micSource.connect(processorNode);
        processorNode.connect(audioContext.destination);
    } catch (err) {
        console.error('Failed to start microphone:', err);
        if (lunarStatusText) lunarStatusText.textContent = 'Microphone access denied';
    }
}

function resetVad() {
    vadBuffer = [];
    vadSpeaking = false;
    vadSpeechMs = 0;
    vadSilenceMs = 0;
    vadBargeMs = 0;
}

// Process one audio frame: RMS-based VAD for endpointing + barge-in.
function handleAudioFrame(frame) {
    const frameMs = (frame.length / captureSampleRate) * 1000;
    let sum = 0;
    for (let i = 0; i < frame.length; i++) sum += frame[i] * frame[i];
    const rms = Math.sqrt(sum / frame.length);

    // Barge-in: user speaking while Lunar talks -> interrupt.
    if ((isSpeaking || currentTTSAudio) && rms > VOICE_CONFIG.speechThreshold) {
        vadBargeMs += frameMs;
        if (vadBargeMs >= VOICE_CONFIG.bargeInMs) {
            interruptLunar();
            vadBargeMs = 0;
        }
    } else if (rms < VOICE_CONFIG.silenceThreshold) {
        vadBargeMs = 0;
    }

    if (rms > VOICE_CONFIG.speechThreshold) {
        vadSpeaking = true;
        vadSilenceMs = 0;
        vadSpeechMs += frameMs;
        vadBuffer.push(new Float32Array(frame));
    } else if (vadSpeaking) {
        vadBuffer.push(new Float32Array(frame));
        vadSilenceMs += frameMs;
        const bufferedMs = vadSpeechMs + vadSilenceMs;
        if (vadSilenceMs >= VOICE_CONFIG.silenceHangoverMs || bufferedMs >= VOICE_CONFIG.maxUtteranceMs) {
            const enoughSpeech = vadSpeechMs >= VOICE_CONFIG.minSpeechMs;
            const samples = flattenVad();
            resetVad();
            if (enoughSpeech) finalizeUtterance(samples);
        }
    }
}

function flattenVad() {
    let total = 0;
    for (const b of vadBuffer) total += b.length;
    const out = new Float32Array(total);
    let off = 0;
    for (const b of vadBuffer) { out.set(b, off); off += b.length; }
    return out;
}

// Send a captured utterance to local STT, then drive the conversation.
async function finalizeUtterance(samples) {
    if (isProcessingUtterance || !state.voiceMode) return;
    isProcessingUtterance = true;
    try {
        if (lunarStatusText) lunarStatusText.textContent = 'Transcribing...';
        const wavBlob = encodeWav(downsampleTo16k(samples, captureSampleRate), VOICE_CONFIG.targetSampleRate);
        const form = new FormData();
        form.append('file', wavBlob, 'utterance.wav');
        const res = await fetch(`${API_BASE}${VOICE_CONFIG.sttEndpoint}`, { method: 'POST', body: form });
        if (!res.ok) throw new Error('Speech recognition failed');
        const data = await res.json();
        const transcript = (data.transcript || '').trim();
        if (!transcript) {
            if (lunarStatusText && state.voiceMode) lunarStatusText.textContent = '🎤 Listening...';
            return;
        }
        await interruptLunar();
        const userMessage = document.createElement('div');
        userMessage.className = 'voice-paragraph user-message';
        userMessage.innerHTML = `<strong>You:</strong> ${escapeHtml(transcript)}`;
        if (voiceTranscript) {
            voiceTranscript.appendChild(userMessage);
            voiceTranscript.parentElement.scrollTop = voiceTranscript.parentElement.scrollHeight;
        }
        await respondToUser(transcript);
    } catch (err) {
        console.error('Utterance handling error:', err);
        if (lunarStatusText && state.voiceMode) lunarStatusText.textContent = '🎤 Listening...';
    } finally {
        isProcessingUtterance = false;
    }
}

// Downsample a Float32 PCM buffer to 16 kHz (linear interpolation).
function downsampleTo16k(samples, inRate) {
    const outRate = VOICE_CONFIG.targetSampleRate;
    if (!inRate || inRate === outRate) return samples;
    const ratio = inRate / outRate;
    const outLen = Math.floor(samples.length / ratio);
    const out = new Float32Array(outLen);
    for (let i = 0; i < outLen; i++) {
        const idx = i * ratio;
        const i0 = Math.floor(idx);
        const i1 = Math.min(i0 + 1, samples.length - 1);
        const frac = idx - i0;
        out[i] = samples[i0] * (1 - frac) + samples[i1] * frac;
    }
    return out;
}

// Encode Float32 PCM samples as a 16-bit mono WAV Blob.
function encodeWav(samples, sampleRate) {
    const buffer = new ArrayBuffer(44 + samples.length * 2);
    const view = new DataView(buffer);
    const writeStr = (offset, str) => { for (let i = 0; i < str.length; i++) view.setUint8(offset + i, str.charCodeAt(i)); };
    writeStr(0, 'RIFF');
    view.setUint32(4, 36 + samples.length * 2, true);
    writeStr(8, 'WAVE');
    writeStr(12, 'fmt ');
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, 1, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * 2, true);
    view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);
    writeStr(36, 'data');
    view.setUint32(40, samples.length * 2, true);
    let offset = 44;
    for (let i = 0; i < samples.length; i++) {
        const s = Math.max(-1, Math.min(1, samples[i]));
        view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
        offset += 2;
    }
    return new Blob([view], { type: 'audio/wav' });
}

function restartDuplexListening() {
    if (!state.voiceMode) return;
    startDuplexListening();
}

// Stop listening and release the microphone.
function stopDuplexListening() {
    duplexListening = false;
    isListening = false;
    isProcessingUtterance = false;
    resetVad();
    if (processorNode) { try { processorNode.disconnect(); } catch (e) {} processorNode.onaudioprocess = null; }
    processorNode = null;
    if (micSource) { try { micSource.disconnect(); } catch (e) {} }
    micSource = null;
    if (audioContext) { try { audioContext.close(); } catch (e) {} }
    audioContext = null;
    if (audioStream) { audioStream.getTracks().forEach(t => t.stop()); }
    audioStream = null;
}

// Track active speech for interruption
let isSpeaking = false;
let currentSpeakingText = ''; // Track exactly what Lunar is currently speaking
let currentTTSResolve = null;
let currentTTSUrl = null;
let interruptSignal = false;

// Interrupt Lunar immediately when user speaks
async function interruptLunar() {
    console.log('Interrupting Lunar...');
    interruptSignal = true;
    
    // Stop TTS audio
    if (currentTTSAudio) {
        currentTTSAudio.onended = null;
        currentTTSAudio.onerror = null;
        currentTTSAudio.pause();
        currentTTSAudio = null;
    }
    if (currentTTSUrl) {
        URL.revokeObjectURL(currentTTSUrl);
        currentTTSUrl = null;
    }
    if (currentTTSResolve) {
        currentTTSResolve();
        currentTTSResolve = null;
    }
    isSpeaking = false;
    currentSpeakingText = '';
    
    // Stop any other audio
    if (state.currentAudio) {
        state.currentAudio.pause();
        state.currentAudio.currentTime = 0;
    }
    
    // Pause voice waves animation
    if (voiceWaves) {
        voiceWaves.classList.add('paused');
    }
    
    lunarStatusText.textContent = 'Listening to you...';
}

// DOM Elements
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const uploadZone = $('#upload-zone');
const fileInput = $('#file-input');
const fileInfo = $('#file-info');
const fileName = $('#file-name');
const fileSize = $('#file-size');
const removeFile = $('#remove-file');
const textPreview = $('#text-preview');
const previewContent = $('#preview-content');
const aiStatusChip = $('#ai-status-chip');
const numQuestions = $('#num-questions');
const difficultySelect = $('#difficulty-select');
const generateBtn = $('#generate-btn');
const stepQuestions = $('#step-questions');
const questionCount = $('#question-count');
const questionsList = $('#questions-list');
const quizMcqBtn = $('#quiz-mcq-btn');
const quizFillBtn = $('#quiz-fill-btn');
const stepQuiz = $('#step-quiz');
const stepTopics = $('#step-topics');
const topicsContainer = $('#topics-container');
const topicsLoading = $('#topics-loading');

// Voice Mode DOM Elements
const voiceModeModal = $('#voice-mode-modal');
const voiceTranscript = $('#voice-transcript');
const lunarStatusText = $('#lunar-status-text');
const nameInputSection = $('#name-input-section');
const userNameInput = $('#user-name-input');
const submitNameBtn = $('#submit-name-btn');
const voiceTopicTitle = $('#voice-topic-title');
const quitVoiceBtn = $('#quit-voice-btn');
const pauseVoiceBtn = $('#pause-voice-btn');
const micBtn = $('#mic-btn');
const micBtnText = $('#mic-btn-text');
const voiceWaves = document.querySelector('.voice-waves');

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    loadProviders();
    setupEventListeners();
    setupVoiceModeListeners();
    
    // Pre-fill user name if saved
    if (state.userName) {
        userNameInput.value = state.userName;
    }
});

// The app is fully on-device. Probe the local AI engine and reflect its
// readiness in the status chip instead of asking for any API keys.
async function loadProviders() {
    if (!aiStatusChip) return;
    try {
        const res = await fetch(`${API_BASE}/api/health`);
        const data = await res.json();
        const ttsLabel = data?.voice?.tts === 'piper' ? 'Piper' : 'system voice';
        if (data.ok) {
            aiStatusChip.classList.add('ready');
            aiStatusChip.classList.remove('error');
            aiStatusChip.innerHTML =
                `<span class="status-dot"></span> On-device AI ready · ${escapeHtml(data.chat_model || 'local model')} · voice: ${escapeHtml(ttsLabel)}`;
        } else {
            throw new Error(data.error || 'engine offline');
        }
    } catch (err) {
        aiStatusChip.classList.add('error');
        aiStatusChip.classList.remove('ready');
        aiStatusChip.innerHTML =
            '<span class="status-dot"></span> On-device AI engine not detected — start Ollama and reload';
        console.error('Local AI health check failed:', err);
    }
}

function setupEventListeners() {
    // Upload
    uploadZone.addEventListener('click', () => fileInput.click());
    uploadZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        uploadZone.classList.add('drag-over');
    });
    uploadZone.addEventListener('dragleave', () => {
        uploadZone.classList.remove('drag-over');
    });
    uploadZone.addEventListener('drop', (e) => {
        e.preventDefault();
        uploadZone.classList.remove('drag-over');
        if (e.dataTransfer.files.length) {
            handleFileUpload(e.dataTransfer.files[0]);
        }
    });
    fileInput.addEventListener('change', () => {
        if (fileInput.files.length) handleFileUpload(fileInput.files[0]);
    });
    removeFile.addEventListener('click', resetUpload);

    // Return to the classroom (shown once a document has been opened)
    const returnBtn = $('#return-classroom-btn');
    if (returnBtn) returnBtn.addEventListener('click', resumeClassroom);
}

function updateGenerateButton() { /* question generation removed */ }

async function handleFileUpload(file) {
    const formData = new FormData();
    formData.append('file', file);

    uploadZone.style.display = 'none';
    fileInfo.style.display = 'flex';
    fileName.textContent = file.name;
    fileSize.textContent = formatFileSize(file.size);

    // Step into the classroom immediately with a "reading your slides" state so
    // the user knows it's working while the file is parsed/OCR'd.
    crEnterReading(file.name);

    try {
        const res = await fetch(`${API_BASE}/api/upload`, {
            method: 'POST',
            body: formData
        });
        const data = await res.json();

        if (!res.ok || data.warning) {
            crExit();
            alert((data && data.warning) || 'Could not read that file. Please try another.');
            resetUpload();
            return;
        }

        state.sessionId = data.session_id;

        // Slides are read — walk into class and start learning.
        enterClassroom(file.name);
    } catch (err) {
        crExit();
        alert('Failed to upload file. Please try again.');
        resetUpload();
        console.error(err);
    }
}

function renderTopicsPlaceholder() {
    topicsContainer.innerHTML = `
        <div class="topics-prompt">
            <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="var(--primary)" stroke-width="2">
                <circle cx="11" cy="11" r="8"/>
                <line x1="21" y1="21" x2="16.65" y2="16.65"/>
            </svg>
            <p>Click below to scan your file and find the topics covered.</p>
            <p class="help-text">This uses your API key to analyze the content.</p>
            <button class="btn btn-primary" id="analyze-topics-btn">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/>
                    <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>
                </svg>
                Scan for Topics
            </button>
        </div>
    `;
    $('#analyze-topics-btn').addEventListener('click', handleAnalyzeTopics);
}

function resetUpload() {
    state.sessionId = null;
    fileInput.value = '';
    uploadZone.style.display = 'block';
    fileInfo.style.display = 'none';
    if (textPreview) textPreview.style.display = 'none';
    const ret = $('#return-classroom-btn'); if (ret) ret.style.display = 'none';
}

async function handleAnalyzeTopics() {
    if (!state.sessionId) {
        alert('Please upload a document first.');
        return;
    }

    const analyzeBtn = $('#analyze-topics-btn');
    if (analyzeBtn) {
        analyzeBtn.disabled = true;
        analyzeBtn.innerHTML = '<div class="btn-loader" style="display:inline-block;"></div> Scanning content...';
    }

    // Reset and stream topic chips in live as they're found.
    state.topics = [];
    state.selectedTopics = [];
    topicsContainer.innerHTML = '';

    try {
        await streamNDJSON('/api/topics_stream', { session_id: state.sessionId }, (msg) => {
            if (msg.error) throw new Error(msg.error);
            if (msg.topic) {
                const i = state.topics.length;
                state.topics.push(msg.topic);
                appendTopicChip(msg.topic, i);
            }
        });

        if (!state.topics.length) {
            topicsContainer.innerHTML = '<p class="topic-subtitle">No distinct topics could be identified. You can still generate questions that cover all content.</p>';
        }
    } catch (err) {
        console.error('Topic extraction error:', err);
        if (!state.topics.length) {
            topicsContainer.innerHTML = `
                <div class="topics-prompt">
                    <p style="color:var(--danger);">Failed: ${escapeHtml(err.message)}</p>
                    <button class="btn btn-secondary" id="analyze-topics-btn">Retry Scan</button>
                </div>
            `;
            $('#analyze-topics-btn').addEventListener('click', handleAnalyzeTopics);
        }
    }
}

function appendTopicChip(topic, i) {
    const wrapper = document.createElement('div');
    wrapper.className = 'topic-wrapper';

    const chip = document.createElement('div');
    chip.className = 'topic-chip';
    chip.dataset.index = i;
    chip.innerHTML = `<span class="chip-check"></span><span>${escapeHtml(topic)}</span>`;
    chip.addEventListener('click', () => toggleTopic(i, chip));

    const lectureBtn = document.createElement('button');
    lectureBtn.className = 'btn btn-lecture';
    lectureBtn.innerHTML = `
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/>
            <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>
        </svg>
        Lecture?
    `;
    lectureBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        getLecture(topic);
    });

    wrapper.appendChild(chip);
    wrapper.appendChild(lectureBtn);
    topicsContainer.appendChild(wrapper);
}

function renderTopics() {
    topicsContainer.innerHTML = '';
    if (!state.topics.length) {
        topicsContainer.innerHTML = '<p class="topic-subtitle">No specific topics detected. Questions will cover all content.</p>';
        return;
    }
    state.topics.forEach((topic, i) => appendTopicChip(topic, i));
}

function toggleTopic(index, chip) {
    const topic = state.topics[index];
    const pos = state.selectedTopics.indexOf(topic);

    if (pos === -1) {
        state.selectedTopics.push(topic);
        chip.classList.add('selected');
    } else {
        state.selectedTopics.splice(pos, 1);
        chip.classList.remove('selected');
    }
}

function selectAllTopics() {
    state.selectedTopics = [...state.topics];
    topicsContainer.querySelectorAll('.topic-chip').forEach(c => c.classList.add('selected'));
}

function clearTopics() {
    state.selectedTopics = [];
    topicsContainer.querySelectorAll('.topic-chip').forEach(c => c.classList.remove('selected'));
}

async function handleGenerate() {
    if (!state.sessionId) return;

    // Start continuous warp drive effect
    if (window.startWarpEffect) {
        window.startWarpEffect();
    }

    state.abortController = new AbortController();

    generateBtn.disabled = true;
    const btnText = generateBtn.querySelector('.btn-text');
    const btnLoader = generateBtn.querySelector('.btn-loader');
    btnText.textContent = 'Generating...';
    btnLoader.style.display = 'inline-block';
    $('#cancel-generate-btn').style.display = 'inline-flex';

    // Reset and reveal the questions panel so cards stream in live.
    state.questions = [];
    questionsList.innerHTML = '';
    questionCount.textContent = '0';
    stepQuestions.style.display = 'block';
    stepQuestions.scrollIntoView({ behavior: 'smooth' });

    try {
        await streamNDJSON('/api/generate_stream', {
            session_id: state.sessionId,
            num_questions: parseInt(numQuestions.value) || 5,
            difficulty: difficultySelect.value,
            topics: state.selectedTopics
        }, (msg) => {
            if (state.abortController && state.abortController.signal.aborted) return;
            if (msg.error) throw new Error(msg.error);
            if (msg.question) {
                const i = state.questions.length;
                state.questions.push(msg.question);
                appendQuestionCard(msg.question, i);
                questionCount.textContent = state.questions.length;
            }
        }, state.abortController.signal);

        if (!state.questions.length) {
            questionsList.innerHTML = '<p class="topic-subtitle">Could not generate grounded questions from this material. Try a different document or topic.</p>';
        }
    } catch (err) {
        if (err.name === 'AbortError') {
            console.log('Generation cancelled by user');
        } else {
            alert(`Error: ${err.message}`);
            console.error(err);
        }
    } finally {
        // Stop warp effect when done
        if (window.stopWarpEffect) {
            window.stopWarpEffect();
        }
        btnText.textContent = 'Generate Questions';
        btnLoader.style.display = 'none';
        generateBtn.disabled = false;
        $('#cancel-generate-btn').style.display = 'none';
        state.abortController = null;
    }
}

function cancelGenerate() {
    if (state.abortController) {
        state.abortController.abort();
    }
}

function appendQuestionCard(q, i) {
    const item = document.createElement('div');
    item.className = 'question-item';
    item.innerHTML = `
        <div class="q-number">Question ${i + 1}</div>
        <div class="q-text">${escapeHtml(q.question)}</div>
        <div class="q-solution-container" id="solution-container-${i}">
            <button class="btn btn-solution" onclick="getSolution(${i})">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="12" r="10"/>
                    <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/>
                    <line x1="12" y1="17" x2="12.01" y2="17"/>
                </svg>
                Get Solution from Lunar
            </button>
            <div class="q-solution" id="solution-${i}" style="display:none;"></div>
        </div>
        <span class="q-difficulty ${q.difficulty || 'medium'}">${(q.difficulty || 'medium').toUpperCase()}</span>
    `;
    questionsList.appendChild(item);
}

function renderQuestions() {
    questionCount.textContent = state.questions.length;
    questionsList.innerHTML = '';
    state.questions.forEach((q, i) => appendQuestionCard(q, i));
}

async function handleCreateQuiz(quizType) {
    state.quizType = quizType;

    // Start continuous warp drive effect
    if (window.startWarpEffect) {
        window.startWarpEffect();
    }

    try {
        // Check if any questions have viewed solutions - need to regenerate them
        const viewedIndices = Array.from(state.viewedSolutions);
        const viewedQuestions = viewedIndices.map(i => state.questions[i]).filter(q => q);
        
        const res = await fetch(`${API_BASE}/api/quiz`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                session_id: state.sessionId,
                quiz_type: quizType,
                viewed_questions: viewedQuestions.map(q => ({
                    question: q.question,
                    answer: q.answer,
                    topic: q.topic || '',
                    difficulty: q.difficulty || 'medium'
                })),
            })
        });

        if (!res.ok) {
            let errorMsg = 'Quiz creation failed';
            try {
                const err = await res.json();
                errorMsg = err.detail || errorMsg;
            } catch (e) {
                errorMsg = `Server error (${res.status})`;
            }
            throw new Error(errorMsg);
        }

        const data = await res.json();
        state.quiz = data.questions;
        state.currentQuestionIndex = 0;
        state.score = 0;
        state.answers = {};
        
        // Clear viewed solutions for next round
        state.viewedSolutions.clear();

        stepQuiz.style.display = 'block';
        stepQuiz.scrollIntoView({ behavior: 'smooth' });
        $('#quiz-total').textContent = state.quiz.length;

        renderQuizQuestion();
    } catch (err) {
        alert(`Error: ${err.message}`);
        console.error(err);
    } finally {
        // Stop warp effect when done
        if (window.stopWarpEffect) {
            window.stopWarpEffect();
        }
    }
}

function renderQuizQuestion() {
    const q = state.quiz[state.currentQuestionIndex];
    if (!q) return;

    // Reset UI
    $('#quiz-current').textContent = state.currentQuestionIndex + 1;
    $('#quiz-difficulty').textContent = q.difficulty.toUpperCase();
    $('#quiz-difficulty').className = `quiz-difficulty-badge q-difficulty ${q.difficulty}`;
    $('#quiz-question').textContent = q.question;
    $('#quiz-feedback').style.display = 'none';
    $('#submit-answer-btn').style.display = 'inline-flex';
    $('#next-question-btn').style.display = 'none';
    $('#quiz-score').style.display = 'none';
    $('#quiz-options-container').style.display = 'flex';
    $('#cancel-quiz-btn').style.display = 'inline-flex';

    const container = $('#quiz-options-container');

    if (q.type === 'mcq') {
        const letters = ['A', 'B', 'C', 'D'];
        container.innerHTML = q.options.map((opt, i) => `
            <div class="quiz-option" data-index="${i}">
                <span class="option-letter">${letters[i] || i + 1}</span>
                <span class="option-text">${escapeHtml(opt)}</span>
            </div>
        `).join('');

        container.querySelectorAll('.quiz-option').forEach(el => {
            el.addEventListener('click', () => {
                container.querySelectorAll('.quiz-option').forEach(o => o.classList.remove('selected'));
                el.classList.add('selected');
                $('#submit-answer-btn').disabled = false;
            });
        });
    } else {
        container.innerHTML = `
            <input type="text" class="fill-in-input" id="fill-answer" placeholder="Type your answer here..." autocomplete="off">
        `;
        const fillInput = $('#fill-answer');
        fillInput.addEventListener('input', () => {
            $('#submit-answer-btn').disabled = !fillInput.value.trim();
        });
        fillInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && fillInput.value.trim()) {
                handleSubmitAnswer();
            }
        });
        fillInput.focus();
    }

    startTimer(q.time_limit || 60);
}

function startTimer(seconds) {
    clearInterval(state.timerInterval);
    state.timeRemaining = seconds;
    const total = seconds;

    updateTimerDisplay(total);

    state.timerInterval = setInterval(() => {
        state.timeRemaining--;
        updateTimerDisplay(total);

        if (state.timeRemaining <= 0) {
            clearInterval(state.timerInterval);
            handleTimeUp();
        }
    }, 1000);
}

function updateTimerDisplay(total) {
    const display = $('#timer-display');
    const fill = $('#timer-fill');
    display.textContent = state.timeRemaining;
    fill.style.width = `${(state.timeRemaining / total) * 100}%`;

    if (state.timeRemaining <= 10) {
        display.style.color = 'var(--danger)';
    } else if (state.timeRemaining <= 20) {
        display.style.color = 'var(--warning)';
    } else {
        display.style.color = 'var(--success)';
    }
}

function handleTimeUp() {
    const q = state.quiz[state.currentQuestionIndex];
    state.answers[q.id] = { answer: null, correct: false, timedOut: true };
    showFeedback(false, q.correct_answer || q.correct_text, true);
}

async function handleSubmitAnswer() {
    clearInterval(state.timerInterval);
    const q = state.quiz[state.currentQuestionIndex];
    let answer;

    if (q.type === 'mcq') {
        const selected = document.querySelector('.quiz-option.selected');
        if (!selected) return;
        answer = selected.dataset.index;
    } else {
        const fillInput = $('#fill-answer');
        answer = fillInput.value.trim();
        if (!answer) return;
    }

    try {
        const res = await fetch(`${API_BASE}/api/answer`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                session_id: state.sessionId,
                question_id: q.id,
                answer: answer
            })
        });

        const data = await res.json();
        const isCorrect = data.correct;

        if (isCorrect) state.score++;
        state.answers[q.id] = { answer, correct: isCorrect };

        // Highlight correct/incorrect
        if (q.type === 'mcq') {
            const options = document.querySelectorAll('.quiz-option');
            options.forEach((opt, i) => {
                opt.style.pointerEvents = 'none';
                if (i === q.correct_answer) opt.classList.add('correct');
                if (opt.classList.contains('selected') && i !== q.correct_answer) {
                    opt.classList.add('incorrect');
                }
            });
        } else {
            const fillInput = $('#fill-answer');
            fillInput.disabled = true;
            fillInput.classList.add(isCorrect ? 'correct' : 'incorrect');
        }

        showFeedback(isCorrect, data.correct_answer);
    } catch (err) {
        console.error(err);
    }
}

function showFeedback(isCorrect, correctAnswer, timedOut = false) {
    const feedback = $('#quiz-feedback');
    feedback.style.display = 'block';

    if (timedOut) {
        feedback.className = 'quiz-feedback incorrect';
        feedback.innerHTML = `Time's up! The correct answer was: <strong>${escapeHtml(correctAnswer)}</strong>`;
    } else if (isCorrect) {
        feedback.className = 'quiz-feedback correct';
        feedback.innerHTML = 'Correct!';
    } else {
        feedback.className = 'quiz-feedback incorrect';
        feedback.innerHTML = `Incorrect. The correct answer was: <strong>${escapeHtml(correctAnswer)}</strong>`;
    }

    $('#submit-answer-btn').style.display = 'none';

    if (state.currentQuestionIndex < state.quiz.length - 1) {
        $('#next-question-btn').style.display = 'inline-flex';
    } else {
        showQuizScore();
    }
}

function handleNextQuestion() {
    state.currentQuestionIndex++;
    renderQuizQuestion();
}

function cancelQuiz() {
    clearInterval(state.timerInterval);
    state.quiz = [];
    state.currentQuestionIndex = 0;
    state.score = 0;
    state.answers = {};
    stepQuiz.style.display = 'none';
    stepQuestions.scrollIntoView({ behavior: 'smooth' });
}

function cancelQuestions() {
    state.questions = [];
    state.quiz = [];
    state.currentQuestionIndex = 0;
    state.score = 0;
    
    stepQuestions.style.display = 'none';
    stepQuiz.style.display = 'none';
    
    // Smooth scroll to config
    stepConfig.scrollIntoView({ behavior: 'smooth' });
}

// ==========================================
// ASK LUNAR & DOWNLOAD QUESTIONS
// ==========================================

function openAskLunarModal() {
    const modal = document.getElementById('ask-lunar-modal');
    modal.style.display = 'flex';
    document.getElementById('ask-lunar-input').value = '';
    renderAskLunarChat();
    document.getElementById('ask-lunar-input').focus();
}

function closeAskLunarModal() {
    const modal = document.getElementById('ask-lunar-modal');
    modal.style.display = 'none';
}

function handleAskLunarInputKeydown(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        submitAskLunarQuestion();
    }
}

function getAskLunarHistory() {
    return state.askLunarMessages
        .filter(message => message && !message.pending && (message.role === 'user' || message.role === 'assistant'))
        .map(message => ({ role: message.role, content: message.content }));
}

function formatAskLunarError(detail) {
    if (!detail) return 'Something went wrong while contacting Lunar.';
    if (Array.isArray(detail)) {
        return detail.map(item => {
            if (!item) return '';
            if (typeof item === 'string') return item;
            const location = Array.isArray(item.loc) ? `${item.loc.join(' > ')}: ` : '';
            return `${location}${item.msg || JSON.stringify(item)}`;
        }).filter(Boolean).join('\n');
    }
    if (typeof detail === 'object') {
        if (typeof detail.detail === 'string') return detail.detail;
        if (typeof detail.message === 'string') return detail.message;
        return JSON.stringify(detail);
    }
    return String(detail);
}

function renderAskLunarChat() {
    const responseDiv = document.getElementById('ask-lunar-response');
    if (!responseDiv) return;

    const messages = state.askLunarMessages.length > 0
        ? state.askLunarMessages
        : [{ role: 'assistant', content: "Hi, I'm Lunar. Ask me anything at all. If you've uploaded a file, I'll use it whenever it's helpful." }];

    responseDiv.innerHTML = '';

    messages.forEach(message => {
        const wrapper = document.createElement('div');
        wrapper.className = `ask-lunar-message ${message.role === 'user' ? 'ask-lunar-user' : 'ask-lunar-assistant'}${message.pending ? ' ask-lunar-pending' : ''}`;

        const role = document.createElement('div');
        role.className = 'ask-lunar-role';
        role.textContent = message.role === 'user' ? 'You' : 'Lunar';

        const content = document.createElement('div');
        content.className = 'ask-lunar-content';
        content.textContent = message.content;

        wrapper.appendChild(role);
        wrapper.appendChild(content);
        responseDiv.appendChild(wrapper);
    });

    responseDiv.scrollTop = responseDiv.scrollHeight;
}

async function submitAskLunarQuestion() {
    const inputElement = document.getElementById('ask-lunar-input');
    const questionInput = inputElement.value.trim();
    if (!questionInput) return;

    const btn = document.getElementById('submit-ask-lunar-btn');
    const btnText = btn.querySelector('.btn-text');
    const loader = btn.querySelector('.btn-loader');
    const history = getAskLunarHistory().slice(-10);

    state.askLunarMessages.push({ role: 'user', content: questionInput });
    inputElement.value = '';

    state.askLunarMessages.push({ role: 'assistant', content: 'Thinking...', pending: true });
    renderAskLunarChat();

    btn.disabled = true;
    btnText.style.display = 'none';
    loader.style.display = 'inline-block';

    try {
        const payload = {
            question: questionInput,
            history,
        };

        if (state.sessionId) {
            payload.session_id = state.sessionId;
        }

        const res = await fetch(`${API_BASE}/api/ask_lunar`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        if (!res.ok) {
            let errorMsg = 'Failed to get answer from Lunar';
            try {
                const errData = await res.json();
                errorMsg = formatAskLunarError(errData.detail || errData) || errorMsg;
            } catch(e) {
                errorMsg = `${res.status} ${res.statusText}`;
            }
            throw new Error(errorMsg);
        }

        const data = await res.json();
        const responseText = typeof data.response === 'string' ? data.response.trim() : '';

        if (!responseText) {
            throw new Error('Lunar returned an empty response.');
        }

        state.askLunarMessages[state.askLunarMessages.length - 1] = { role: 'assistant', content: responseText };
        renderAskLunarChat();

    } catch (error) {
        console.error('Ask Lunar error:', error);
        state.askLunarMessages[state.askLunarMessages.length - 1] = {
            role: 'assistant',
            content: `I couldn't answer that because ${error.message || 'something went wrong.'}`
        };
        renderAskLunarChat();
    } finally {
        btn.disabled = false;
        btnText.style.display = 'inline-block';
        loader.style.display = 'none';
    }
}

function downloadQuestions() {
    if (!state.questions || state.questions.length === 0) {
        alert("No questions available to download.");
        return;
    }

    let fileContent = "Generated Questions\n===================\n\n";

    state.questions.forEach((q, i) => {
        fileContent += `Question ${i + 1}: ${q.question}\n`;
        fileContent += `Difficulty: ${q.difficulty.toUpperCase()}\n`;
        
        if (q.type === 'mcq') {
            fileContent += "Options:\n";
            q.options.forEach((opt, j) => {
                const letter = String.fromCharCode(65 + j);
                fileContent += `  ${letter}) ${opt}\n`;
            });
            fileContent += `Correct Answer: ${q.correct_answer}\n`;
        } else if (q.type === 'fill_in') {
            fileContent += `Correct Answer: ${q.correct_answer}\n`;
        }
        
        fileContent += `Explanation: ${q.explanation}\n\n`;
        fileContent += "-------------------\n\n";
    });

    const blob = new Blob([fileContent], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `lunar_questions_${new Date().getTime()}.txt`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

function showQuizScore() {
    $('#quiz-options-container').style.display = 'none';
    $('#quiz-feedback').style.display = 'none';
    $('#next-question-btn').style.display = 'none';
    $('#submit-answer-btn').style.display = 'none';

    const total = state.quiz.length;
    const correct = state.score;
    const incorrect = total - correct;
    const timedOut = Object.values(state.answers).filter(a => a.timedOut).length;
    const percentage = Math.round((correct / total) * 100);

    $('#quiz-score').style.display = 'block';
    $('#score-value').textContent = percentage;
    $('#score-detail').textContent = `You answered ${correct} out of ${total} questions correctly.`;

    const statsHtml = `
        <div class="stat-row">
            <span class="stat-label">Correct</span>
            <span class="stat-value stat-correct">${correct}</span>
        </div>
        <div class="stat-row">
            <span class="stat-label">Incorrect</span>
            <span class="stat-value stat-incorrect">${incorrect}</span>
        </div>
        <div class="stat-row">
            <span class="stat-label">Timed Out</span>
            <span class="stat-value stat-timeout">${timedOut}</span>
        </div>
        <div class="stat-row">
            <span class="stat-label">Total Questions</span>
            <span class="stat-value">${total}</span>
        </div>
    `;
    $('#score-stats').innerHTML = statsHtml;

    const circle = $('#score-circle');
    if (percentage >= 80) {
        circle.style.borderColor = 'var(--success)';
        circle.style.background = 'rgba(16, 185, 129, 0.1)';
    } else if (percentage >= 50) {
        circle.style.borderColor = 'var(--warning)';
        circle.style.background = 'rgba(245, 158, 11, 0.1)';
    } else {
        circle.style.borderColor = 'var(--danger)';
        circle.style.background = 'rgba(239, 68, 68, 0.1)';
    }
    
    // Lunar Performance Analysis
    analyzeLunarPerformance(percentage, incorrect, timedOut);
}

function analyzeLunarPerformance(percentage, incorrect, timedOut) {
    const analysisDiv = $('#lunar-analysis');
    const messageEl = $('#lunar-message');
    const weakAreasContainer = $('#weak-areas-container');
    const weakAreasList = $('#weak-areas-list');
    
    analysisDiv.style.display = 'block';
    
    // Identify weak areas by TOPIC (not question text)
    state.weakAreas = [];
    const topicMap = {};
    
    state.quiz.forEach(q => {
        const answer = state.answers[q.id];
        if (answer && (!answer.correct || answer.timedOut)) {
            // Use the topic field from the question
            const topic = q.topic || "General Concepts";
            
            if (!topicMap[topic]) {
                topicMap[topic] = { count: 0, timedOut: 0 };
            }
            topicMap[topic].count++;
            if (answer.timedOut) topicMap[topic].timedOut++;
            
            state.weakAreas.push({
                topic: topic,
                difficulty: q.difficulty,
                timedOut: answer.timedOut || false
            });
        }
    });
    
    // Generate Lunar's message based on performance
    let message = '';
    if (percentage >= 90) {
        message = "Outstanding performance! 🌟 You've demonstrated excellent mastery of this material. Keep up the fantastic work!";
    } else if (percentage >= 70) {
        message = "Good job! You have a solid understanding of most concepts. Let's focus on strengthening a few areas to achieve mastery.";
    } else if (percentage >= 50) {
        message = "You're making progress! I've identified some topics where additional practice would be beneficial. Let's work on these together.";
    } else {
        message = "Don't worry - learning is a journey! I've analyzed your responses and identified key topics that need attention. Focused practice will help you improve significantly.";
    }
    
    messageEl.textContent = message;
    
    // Show weak areas (topics/concepts) if there are any
    const uniqueTopics = Object.keys(topicMap);
    if (uniqueTopics.length > 0) {
        weakAreasContainer.style.display = 'block';
        
        // Render weak topics/concepts
        let listHtml = '';
        uniqueTopics.forEach(topic => {
            const data = topicMap[topic];
            let detail = '';
            if (data.timedOut > 0) {
                detail = `${data.count} question(s) - needs more practice (${data.timedOut} timed out)`;
            } else {
                detail = `${data.count} question(s) - review this concept`;
            }
            listHtml += `
                <li>
                    <span class="weak-topic">${escapeHtml(topic)}</span>
                    <span class="weak-detail">${detail}</span>
                </li>
            `;
        });
        weakAreasList.innerHTML = listHtml;
    } else {
        weakAreasContainer.style.display = 'none';
    }
}

async function practiceWeakAreas() {
    if (!state.weakAreas || state.weakAreas.length === 0) return;
    
    // Start continuous warp effect
    if (window.startWarpEffect) {
        window.startWarpEffect();
    }
    
    const btn = $('#practice-weak-btn');
    btn.disabled = true;
    btn.innerHTML = `
        <span class="btn-loader"></span>
        Generating...
    `;
    
    try {
        // Get unique weak topics
        const weakTopics = [...new Set(state.weakAreas.map(a => a.topic))];
        
        const res = await fetch(`${API_BASE}/api/practice-weak-areas`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                session_id: state.sessionId,
                weak_topics: weakTopics,
                weak_questions: [],
                num_questions: Math.min(weakTopics.length * 2 + 2, 10),
                difficulty: 'mixed',
            })
        });
        
        if (!res.ok) {
            let errorMsg = 'Failed to generate practice questions';
            try {
                const err = await res.json();
                errorMsg = err.detail || errorMsg;
            } catch (e) {
                errorMsg = `Server error (${res.status})`;
            }
            throw new Error(errorMsg);
        }
        
        const data = await res.json();
        state.quiz = data.questions;
        state.currentQuestionIndex = 0;
        state.score = 0;
        state.answers = {};
        state.weakAreas = [];
        
        // Reset and show quiz
        $('#quiz-score').style.display = 'none';
        $('#lunar-analysis').style.display = 'none';
        $('#quiz-options-container').style.display = 'flex';
        $('#quiz-total').textContent = state.quiz.length;
        
        renderQuizQuestion();
    } catch (err) {
        alert(`Error: ${err.message}`);
        console.error(err);
    } finally {
        // Stop warp effect when done
        if (window.stopWarpEffect) {
            window.stopWarpEffect();
        }
        btn.disabled = false;
        btn.innerHTML = `
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>
            </svg>
            Practice Weak Areas
        `;
    }
}

async function getSolution(questionIndex) {
    const question = state.questions[questionIndex];
    if (!question) return;
    
    const container = document.getElementById(`solution-container-${questionIndex}`);
    const solutionDiv = document.getElementById(`solution-${questionIndex}`);
    const btn = container.querySelector('.btn-solution');
    
    // Check if solution is already loaded and visible - toggle hide
    if (solutionDiv.style.display === 'block' && solutionDiv.innerHTML) {
        solutionDiv.style.display = 'none';
        btn.innerHTML = `
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
                <circle cx="12" cy="12" r="3"/>
            </svg>
            Show Solution
        `;
        btn.classList.remove('btn-hide');
        return;
    }
    
    // Check if solution was already fetched - just show it
    if (solutionDiv.innerHTML && solutionDiv.style.display === 'none') {
        solutionDiv.style.display = 'block';
        btn.innerHTML = `
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"/>
                <line x1="1" y1="1" x2="23" y2="23"/>
            </svg>
            Hide Solution
        `;
        btn.classList.add('btn-hide');
        return;
    }
    
    // Show loading state
    btn.disabled = true;
    btn.innerHTML = `
        <span class="btn-loader"></span>
        Lunar is thinking...
    `;
    
    try {
        const res = await fetch(`${API_BASE}/api/get-solution`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                session_id: state.sessionId,
                question: question.question,
                answer: question.answer,
                topic: question.topic || '',
            })
        });
        
        if (!res.ok) {
            let errorMsg = 'Failed to get solution';
            try {
                const err = await res.json();
                errorMsg = err.detail || errorMsg;
            } catch (e) {
                errorMsg = `Server error (${res.status})`;
            }
            throw new Error(errorMsg);
        }
        
        const data = await res.json();
        
        // Mark this question as having its solution viewed
        state.viewedSolutions.add(questionIndex);
        
        // Display the solution
        solutionDiv.innerHTML = `
            <div class="lunar-solution-header">
                <span class="lunar-icon">🌙</span>
                <span>Lunar's Solution</span>
            </div>
            <div class="solution-content">${formatSolution(data.explanation)}</div>
            <div class="solution-answer">
                <strong>Answer:</strong> ${escapeHtml(question.answer)}
            </div>
        `;
        solutionDiv.style.display = 'block';
        
        // Change button to "Hide Solution"
        btn.disabled = false;
        btn.innerHTML = `
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"/>
                <line x1="1" y1="1" x2="23" y2="23"/>
            </svg>
            Hide Solution
        `;
        btn.classList.add('btn-hide');
        
        // Mark the question item as viewed
        const questionItem = container.closest('.question-item');
        if (questionItem) {
            questionItem.classList.add('solution-viewed');
        }
        
    } catch (err) {
        alert(`Error: ${err.message}`);
        console.error(err);
        btn.disabled = false;
        btn.innerHTML = `
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="10"/>
                <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/>
                <line x1="12" y1="17" x2="12.01" y2="17"/>
            </svg>
            Get Solution from Lunar
        `;
    }
}

function formatSolution(text) {
    // Convert markdown-like formatting to HTML
    return text
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\n\n/g, '</p><p>')
        .replace(/\n/g, '<br>')
        .replace(/^/, '<p>')
        .replace(/$/, '</p>')
        .replace(/Step (\d+)/g, '<span class="solution-step">Step $1</span>');
}

function formatFileSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// Lecture feature
async function getLecture(topic) {
    if (!state.sessionId) {
        alert('Please upload a document first.');
        return;
    }

    // Interactive on-device voice lecture (local STT/TTS). Falls back to the
    // text lecture modal if the microphone/voice mode can't start.
    const started = await startVoiceMode(topic);
    if (started) return;

    // Fallback to text-only lecture mode
    // Start continuous warp effect
    if (window.startWarpEffect) {
        window.startWarpEffect();
    }
    
    // Show lecture modal
    const modal = $('#lecture-modal');
    const modalTitle = $('#lecture-topic-title');
    const modalContent = $('#lecture-content');
    
    modalTitle.textContent = topic;
    modalContent.innerHTML = `
        <div class="lecture-loading">
            <span class="btn-loader"></span>
            <p>Lunar is preparing your lecture on "${escapeHtml(topic)}"...</p>
        </div>
    `;
    modal.style.display = 'flex';
    
    try {
        // Stream the lecture in live, re-rendering markdown as text arrives.
        let full = '';
        let cached = false;
        modalContent.innerHTML = '<div class="lunar-lecture"></div>';
        const lectureBody = modalContent.querySelector('.lunar-lecture');

        await streamNDJSON('/api/lecture_stream', {
            session_id: state.sessionId,
            topic: topic
        }, (msg) => {
            if (msg.error) throw new Error(msg.error);
            if (msg.cached) cached = true;
            if (msg.token) {
                full += msg.token;
                lectureBody.innerHTML = formatLecture(full);
                modalContent.scrollTop = modalContent.scrollHeight;
            }
        });

        if (cached) {
            modalContent.innerHTML =
                '<span class="lecture-cached-badge">⚡ From Cache (Instant)</span>' +
                `<div class="lunar-lecture">${formatLecture(full)}</div>`;
        }
    } catch (err) {
        modalContent.innerHTML = `
            <div class="lecture-error">
                <p style="color: var(--danger);">Error: ${escapeHtml(err.message)}</p>
                <button class="btn btn-secondary" onclick="closeLectureModal()">Close</button>
            </div>
        `;
        console.error(err);
    } finally {
        // Stop warp effect
        if (window.stopWarpEffect) {
            window.stopWarpEffect();
        }
    }
}

// Lunar's small model sometimes ignores "no diagrams" and emits ASCII number
// lines / trees / tables (rows of bare digits, slashes and pipes). Strip them
// deterministically so they never reach the board: drop fenced code blocks and
// any run of 3+ consecutive "wordless" lines (a real paragraph always has words).
function crStripDiagrams(text) {
    text = (text || '').replace(/```[\s\S]*?```/g, ' ');
    const lines = text.split('\n');
    const weak = lines.map(l => {
        const t = l.trim();
        if (!t) return false;                       // blank line separates runs
        return !/[A-Za-z]{3,}/.test(t);             // no real word → diagram-ish
    });
    const drop = new Array(lines.length).fill(false);
    let i = 0;
    while (i < lines.length) {
        if (weak[i]) {
            let j = i;
            while (j < lines.length && weak[j]) j++;
            if (j - i >= 3) { for (let k = i; k < j; k++) drop[k] = true; }
            i = j;
        } else { i++; }
    }
    return lines.filter((_, k) => !drop[k]).join('\n')
        .replace(/^[ \t]*`+[ \t]*$/gm, '')          // leftover stray code-fence lines
        .replace(/\n{3,}/g, '\n\n');
}

function formatLecture(text) {
    text = crStripDiagrams(text);
    // First make LaTeX/math readable on the board (no raw \frac, \(, ≤ as \leq, etc.)
    text = (text || '')
        .replace(/\$\$?/g, '')                         // $...$ / $$...$$ delimiters
        .replace(/\\\s*[\[\]()]/g, '')                 // \( \) \[ \] (even "\ (")
        .replace(/\\text\s*\{([^}]*)\}/g, '$1')
        .replace(/\\frac\s*\{([^}]*)\}\s*\{([^}]*)\}/g, '($1)/($2)')
        .replace(/\\sqrt\s*\{([^}]*)\}/g, '√($1)')
        // common LaTeX commands → unicode, BEFORE the catch-all strip below
        .replace(/\\(leq|le)\b/g, '≤').replace(/\\(geq|ge)\b/g, '≥')
        .replace(/\\(neq|ne)\b/g, '≠').replace(/\\approx\b/g, '≈')
        .replace(/\\times\b/g, '×').replace(/\\div\b/g, '÷')
        .replace(/\\(cdot|ast)\b/g, '·').replace(/\\pm\b/g, '±')
        .replace(/\\infty\b/g, '∞').replace(/\\sqrt\b/g, '√')
        .replace(/\\(Rightarrow|implies)\b/g, '⇒').replace(/\\(rightarrow|to)\b/g, '→')
        .replace(/\\sum\b/g, 'Σ').replace(/\\int\b/g, '∫').replace(/\\partial\b/g, '∂')
        .replace(/\\alpha\b/g, 'α').replace(/\\beta\b/g, 'β').replace(/\\gamma\b/g, 'γ')
        .replace(/\\delta\b/g, 'δ').replace(/\\theta\b/g, 'θ').replace(/\\lambda\b/g, 'λ')
        .replace(/\\mu\b/g, 'μ').replace(/\\pi\b/g, 'π').replace(/\\sigma\b/g, 'σ')
        .replace(/\\(phi|varphi)\b/g, 'φ').replace(/\\Omega\b/g, 'Ω').replace(/\\omega\b/g, 'ω')
        .replace(/\\(?:,|;|!|quad|qquad|left|right|displaystyle)\b/g, ' ')
        .replace(/\\[a-zA-Z]+/g, '')                    // drop any remaining commands
        .replace(/\\(?=\s|$)/g, '')                     // stray lone backslashes
        .replace(/[{}]/g, '')
        // superscript digits: n^2 → n², x^(3) → x³
        .replace(/\^\(?(\d)\)?/g, (m, d) => '⁰¹²³⁴⁵⁶⁷⁸⁹'[+d])
        // a*b → a × b, same line only, never touching a ** bold marker
        .replace(/([0-9A-Za-z)])[ \t]*(?<!\*)\*(?!\*)[ \t]*([0-9A-Za-z(])/g, '$1 × $2');
    // Convert markdown-like formatting to HTML
    return text
        .replace(/^#{4,6} (.*?)$/gm, '<strong>$1</strong>')
        .replace(/^### (.*?)$/gm, '<h3>$1</h3>')
        .replace(/^## (.*?)$/gm, '<h2>$1</h2>')
        .replace(/^# (.*?)$/gm, '<h1>$1</h1>')
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.*?)\*/g, '<em>$1</em>')
        .replace(/`(.*?)`/g, '<code>$1</code>')
        .replace(/^\- (.*?)$/gm, '<li>$1</li>')
        .replace(/^\d+\. (.*?)$/gm, '<li>$1</li>')
        .replace(/(<li>.*<\/li>)/s, '<ul>$1</ul>')
        .replace(/\n\n/g, '</p><p>')
        .replace(/\n/g, '<br>')
        .replace(/^/, '<p>')
        .replace(/$/, '</p>')
        .replace(/<p><h/g, '<h')
        .replace(/<\/h(\d)><\/p>/g, '</h$1>')
        .replace(/<p><ul>/g, '<ul>')
        .replace(/<\/ul><\/p>/g, '</ul>');
}

function closeLectureModal() {
    const modal = $('#lecture-modal');
    modal.style.display = 'none';
}

// ============================================
// VOICE MODE - On-device STT/TTS
// ============================================

function setupVoiceModeListeners() {
    // Submit name button
    if (submitNameBtn) {
        submitNameBtn.addEventListener('click', handleNameSubmit);
        userNameInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') handleNameSubmit();
        });
    }
    
    // Quit voice mode
    if (quitVoiceBtn) {
        quitVoiceBtn.addEventListener('click', quitVoiceMode);
    }
    
    // Pause voice
    if (pauseVoiceBtn) {
        pauseVoiceBtn.addEventListener('click', toggleVoicePause);
    }
    
    // Microphone button for voice input
    if (micBtn) {
        micBtn.addEventListener('click', toggleMicrophoneInput);
    }
    
    // Clear cache button
    const clearCacheBtn = document.getElementById('clear-cache-btn');
    if (clearCacheBtn) {
        clearCacheBtn.addEventListener('click', async () => {
            try {
                const btnOriginalText = clearCacheBtn.innerHTML;
                clearCacheBtn.innerHTML = `
                    <div class="btn-loader" style="width: 14px; height: 14px; border-width: 2px;"></div>
                    Clearing...
                `;
                
                const res = await fetch(`${API_BASE}/api/clear_cache`, {
                    method: 'POST'
                });
                
                if (res.ok) {
                    clearCacheBtn.innerHTML = `
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M20 6L9 17l-5-5"/>
                        </svg>
                        Cleared!
                    `;
                    setTimeout(() => {
                        clearCacheBtn.innerHTML = btnOriginalText;
                    }, 2000);
                } else {
                    throw new Error('Failed to clear');
                }
            } catch (err) {
                console.error(err);
                alert('Failed to clear cache');
                clearCacheBtn.innerHTML = `
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M3 6h18"/>
                        <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                    </svg>
                    Clear Cache
                `;
            }
        });
    }
}

async function startVoiceMode(topic) {
    // Voice runs fully on-device (local Whisper STT + Piper TTS) — no keys.
    state.voiceMode = true;
    state.currentLectureTopic = topic;
    state.voiceQueue = [];
    state.isPlaying = false;
    state.voiceHistory = []; // Clear conversation history for new session
    
    // Show voice mode modal
    voiceModeModal.style.display = 'flex';
    voiceTopicTitle.textContent = topic;
    voiceTranscript.innerHTML = '';
    
    // Start warp effect
    if (window.startWarpEffect) {
        window.startWarpEffect();
    }
    
    // Reset conversation state
    state.conversationState = 'intro';
    state.lectureChunks = [];
    state.currentChunkIndex = 0;
    state.awaitingResponse = false;
    
    // Start always-on duplex listening (user can interrupt anytime)
    startDuplexListening();
    
    // Check if we need to ask for name
    if (!state.userName) {
        nameInputSection.style.display = 'block';
        lunarStatusText.textContent = '🎤 Listening... (say your name or type it)';
        
        // Speak introduction
        await speakAndType("Hello! I'm Lunar, your AI study assistant. Before we begin, I'd love to know who I'm speaking with today. Just say your name, or type it below. You can interrupt me anytime by speaking!");
    } else {
        // User already known - enter conversation mode
        nameInputSection.style.display = 'none';
        state.conversationState = 'conversation';
        
        // Stop warp effect since we're just chatting
        if (window.stopWarpEffect) {
            window.stopWarpEffect();
        }
        
        // Greet returning user and invite conversation
        await speakAndType(`Hey ${state.userName}, great to see you again! Today we're going to explore ${topic}. Before I start the lecture, is there anything specific you'd like me to focus on? Or any questions you have going in? Just say "let's start" or "begin" whenever you're ready. Remember, you can interrupt me anytime!`);
    }
    
    return true;
}

// Toggle microphone - on-device VAD handles continuous listening
function toggleMicrophoneInput() {
    if (!state.voiceMode) return;

    if (duplexListening) {
        // Stop listening
        stopDuplexListening();
        if (micBtn) micBtn.classList.remove('listening');
        if (micBtnText) micBtnText.textContent = 'Speak';
        lunarStatusText.textContent = 'Microphone off';
    } else {
        // Start listening
        startDuplexListening();
        if (micBtn) micBtn.classList.add('listening');
        if (micBtnText) micBtnText.textContent = 'Listening...';
    }
}

async function respondToUser(userInput) {
    lunarStatusText.textContent = 'Lunar is thinking...';
    state.awaitingResponse = false;
    
    const input = userInput.toLowerCase();
    const name = state.userName || 'friend';
    
    // Check if user wants to START the lecture
    if (state.conversationState === 'conversation') {
        if (input.includes('start') || input.includes('begin') || input.includes("let's go") || 
            input.includes('ready') || input.includes('lecture') || input.includes('teach me') ||
            input.includes("let's start") || input.includes('go ahead')) {
            await speakAndType(`Perfect, ${name}! Let me prepare your lecture on ${state.currentLectureTopic}. This is going to be comprehensive, so feel free to stop me anytime if you have questions or need clarification.`);
            state.conversationState = 'lecturing';
            await fetchAndDeliverLecture(state.currentLectureTopic);
            return;
        }
    }
    
    // Handle lecture-specific navigation commands
    if (state.conversationState === 'lecturing') {
        if (input.includes('continue') || input.includes('go on') || input.includes('next') || input.includes('yes') || input.includes('okay') || input.includes('ok')) {
            await speakAndType(`Great, let's continue!`);
            await continueNextChunk();
            return;
        }
        
        if (input.includes('repeat') || input.includes('again') || input.includes('say that again')) {
            await speakAndType(`Of course! Let me go over that again for you.`);
            if (state.currentChunkIndex > 0) {
                state.currentChunkIndex--;
                await continueNextChunk();
            }
            return;
        }
    }
    
    // Call the smart API for all other conversational inputs
    try {
        const lectureContext = state.conversationState === 'lecturing' && state.lectureChunks.length > 0 
            ? state.lectureChunks[Math.max(0, state.currentChunkIndex - 1)] 
            : "";
            
        const res = await fetch(`${API_BASE}/api/voice_response`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                session_id: state.sessionId,
                user_message: userInput,
                current_topic: state.currentLectureTopic,
                conversation_state: state.conversationState,
                lecture_context: lectureContext,
                history: state.voiceHistory
            })
        });

        if (!res.ok) {
            let errorText = 'Failed to get smart response';
            try {
                const errorData = await res.json();
                errorText = errorData.detail || errorText;
            } catch(e) {}
            throw new Error(errorText);
        }

        const data = await res.json();
        
        // Update conversation history
        if (data.history) {
            state.voiceHistory = data.history;
        }
        
        // If we were in the intro and Lunar acknowledged their name, update our state
        if (state.conversationState === 'intro') {
            const detectedName = userInput.replace(/my name is|i am|i'm|call me/gi, '').trim().split(' ')[0];
            if (detectedName && detectedName.length > 1) {
                const formattedName = detectedName.charAt(0).toUpperCase() + detectedName.slice(1);
                state.userName = formattedName;
                localStorage.setItem('lunar_user_name', formattedName);
                nameInputSection.style.display = 'none';
                state.conversationState = 'conversation';
            }
        }
        
        await speakAndType(data.response);
        
    } catch (err) {
        console.error('Smart voice response failed:', err.message);
        
        // Always speak the backend error if available, otherwise use fallback
        if (err.message && err.message !== 'Failed to fetch' && err.message !== 'Failed to get smart response') {
            await speakAndType(`I encountered an error trying to process that: ${err.message}`);
        } else {
            // Fallback response if completely disconnected
            await speakAndType(`I'm sorry, I'm having a little trouble connecting to my knowledge base right now. Could you repeat that?`);
        }
    }
    
    // Duplex listening is always on - no need to restart
    if (!interruptSignal) {
        lunarStatusText.textContent = '🎤 Always listening...';
    }
}

async function handleNameSubmit() {
    const name = userNameInput.value.trim();
    if (!name) {
        userNameInput.focus();
        return;
    }
    
    state.userName = name;
    localStorage.setItem('lunar_user_name', name);
    
    nameInputSection.style.display = 'none';
    
    // Enter conversation mode - don't jump to lecture
    state.conversationState = 'conversation';
    
    // Greet the user and invite conversation
    await speakAndType(`Wonderful to meet you, ${name}! I'll remember your name for our future sessions together.`);
    await delay(500);
    
    // Offer to chat before starting
    await speakAndType(`So ${name}, today we'll be exploring ${state.currentLectureTopic}. But before we dive in, feel free to ask me anything or tell me if there's something specific you'd like me to focus on. When you're ready to start the lecture, just say "let's start" or "begin". I'm all ears!`);
}

async function startLectureWithGreeting(topic) {
    lunarStatusText.textContent = 'Lunar is speaking...';
    
    // Personalized greeting
    const greeting = `Alright ${state.userName}, let's dive into today's topic: ${topic}. Get comfortable, because I'm going to give you a comprehensive lecture that will help you truly understand this material.`;
    
    await speakAndType(greeting);
    await delay(800);
    
    // Now fetch and deliver the lecture
    await fetchAndDeliverLecture(topic);
}

async function fetchAndDeliverLecture(topic) {
    lunarStatusText.textContent = 'Lunar is preparing your lecture...';
    
    try {
        const res = await fetch(`${API_BASE}/api/lecture`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                session_id: state.sessionId,
                topic: topic,
            })
        });

        if (!res.ok) {
            throw new Error('Failed to generate lecture');
        }

        const data = await res.json();
        
        // Stop warp effect
        if (window.stopWarpEffect) {
            window.stopWarpEffect();
        }
        
        // Deliver the lecture in chunks
        await deliverLectureInChunks(data.lecture);
        
    } catch (err) {
        console.error('Lecture fetch error:', err);
        const apology = state.userName 
            ? `I apologize ${state.userName}, but I encountered an error while preparing your lecture. Please try again.`
            : `I apologize, but I encountered an error while preparing your lecture. Please try again.`;
        await speakAndType(apology);
        
        if (window.stopWarpEffect) {
            window.stopWarpEffect();
        }
    }
}

async function deliverLectureInChunks(lectureText) {
    if (!state.voiceMode) return;
    
    lunarStatusText.textContent = 'Lunar is lecturing...';
    pauseVoiceBtn.style.display = 'inline-flex';
    
    // Split lecture into manageable chunks and store in state
    state.lectureChunks = splitLectureIntoChunks(lectureText);
    state.currentChunkIndex = 0;
    
    // Start delivering chunks with periodic checks
    await deliverNextChunksWithChecks();
}

async function deliverNextChunksWithChecks() {
    if (!state.voiceMode) return;
    
    const name = state.userName || 'friend';
    const chunks = state.lectureChunks;
    const totalChunks = chunks.length;
    
    // Deliver 3-4 chunks at a time, then check understanding
    const chunksPerSection = 3;
    let chunksDelivered = 0;
    
    while (state.currentChunkIndex < totalChunks && state.voiceMode) {
        const chunk = chunks[state.currentChunkIndex];
        
        if (chunk.trim()) {
            // Add example prompts for certain sections
            let enhancedChunk = chunk;
            if (chunk.toLowerCase().includes('formula') || chunk.toLowerCase().includes('equation')) {
                enhancedChunk += `\n\nLet me give you a quick example of how this formula works in practice.`;
            }
            
            await speakAndType(enhancedChunk);
            await delay(400);
            chunksDelivered++;
        }
        
        state.currentChunkIndex++;
        
        // If Lunar asks a direct calculation question, wait for the user's answer immediately
        if (chunk.toLowerCase().includes("what do you think the answer is") || 
            chunk.toLowerCase().includes("i'll wait for you to solve it")) {
            state.awaitingResponse = true;
            lunarStatusText.textContent = '🎤 Waiting for your calculation...';
            return; // Pause lecture to let user answer the calculation
        }

        // Periodic understanding check every few chunks
        if (chunksDelivered >= chunksPerSection && state.currentChunkIndex < totalChunks) {
            chunksDelivered = 0;
            
            // Check understanding
            const checkMessages = [
                `Alright ${name}, let me pause here for a moment. Are you following along okay? Say "continue" if you're good, or let me know if you need me to clarify anything.`,
                `${name}, I want to make sure you're with me so far. Does this make sense? Just say "yes" or "continue" to move on, or ask me to explain something differently.`,
                `Quick check-in, ${name}! How are we doing? Is everything clear, or would you like me to go over any part again?`,
                `Let's pause for a second, ${name}. Any questions so far? If not, just say "continue" and we'll keep going.`
            ];
            const checkMessage = checkMessages[Math.floor(Math.random() * checkMessages.length)];
            
            await speakAndType(checkMessage);
            state.awaitingResponse = true;
            lunarStatusText.textContent = '🎤 Waiting for your response...';
            
            // Duplex listening is always on - just wait for user response
            return; // Exit and wait for user response - continueNextChunk will resume
        }
    }
    
    // Lecture complete
    if (state.voiceMode && state.currentChunkIndex >= totalChunks) {
        await delay(500);
        await speakAndType(`And that concludes our lecture on ${state.currentLectureTopic}, ${name}. I hope you found this helpful! Feel free to ask me any questions, or we can discuss specific parts you'd like to understand better.`);
        
        state.conversationState = 'conversation';
        lunarStatusText.textContent = '🎤 Lecture complete! Still listening...';
        pauseVoiceBtn.style.display = 'none';
        
        // Duplex listening is always on - ready for follow-up questions
    }
}

async function continueNextChunk() {
    if (!state.voiceMode) return;
    
    state.awaitingResponse = false;
    await deliverNextChunksWithChecks();
}

function splitLectureIntoChunks(text) {
    // Split by double newlines (paragraphs) or by headers
    const chunks = [];
    const sections = text.split(/\n\n+/);
    
    for (const section of sections) {
        // If section is too long, split by sentences
        if (section.length > 500) {
            const sentences = section.match(/[^.!?]+[.!?]+/g) || [section];
            let currentChunk = '';
            
            for (const sentence of sentences) {
                if (currentChunk.length + sentence.length > 400) {
                    if (currentChunk) chunks.push(currentChunk.trim());
                    currentChunk = sentence;
                } else {
                    currentChunk += ' ' + sentence;
                }
            }
            if (currentChunk) chunks.push(currentChunk.trim());
        } else {
            chunks.push(section);
        }
    }
    
    return chunks.filter(c => c.trim().length > 0);
}

// Prepare text for TTS - handle numbers, symbols, and special cases
function prepareTextForTTS(text) {
    if (!text) return '';
    
    let processed = text;
    
    // Remove markdown formatting first
    processed = processed
        .replace(/^#+\s*/gm, '')
        .replace(/\*\*/g, '')
        .replace(/\*/g, '')
        .replace(/`/g, '')
        .replace(/\n/g, ' ');
    
    // Handle number ranges like "1-10", "5-20" -> "1 to 10", "5 to 20"
    // Match digit(s)-digit(s) but not dates or other patterns
    processed = processed.replace(/\b(\d{1,3})-(\d{1,4})\b/g, '$1 to $2');
    
    // Convert standalone small numbers (0-20) to words for better pronunciation
    const numToWord = {
        '0': 'zero', '1': 'one', '2': 'two', '3': 'three', '4': 'four',
        '5': 'five', '6': 'six', '7': 'seven', '8': 'eight', '9': 'nine',
        '10': 'ten', '11': 'eleven', '12': 'twelve', '13': 'thirteen',
        '14': 'fourteen', '15': 'fifteen', '16': 'sixteen', '17': 'seventeen',
        '18': 'eighteen', '19': 'nineteen', '20': 'twenty'
    };
    
    // Replace standalone numbers (surrounded by spaces or at start/end)
    Object.keys(numToWord).forEach(num => {
        const regex = new RegExp(`(^|\\s)${num}(?=\\s|$|[,;:!?.])`, 'g');
        processed = processed.replace(regex, `$1${numToWord[num]}`);
    });
    
    // Handle common mathematical symbols
    processed = processed
        .replace(/\s*=\s*/g, ' equals ')
        .replace(/\s*\+\s*/g, ' plus ')
        .replace(/\s*×\s*/g, ' times ')
        .replace(/\s*÷\s*/g, ' divided by ')
        .replace(/\s*±\s*/g, ' plus or minus ')
        .replace(/\s*≈\s*/g, ' approximately ')
        .replace(/\s*≠\s*/g, ' not equal to ')
        .replace(/\s*≤\s*/g, ' less than or equal to ')
        .replace(/\s*≥\s*/g, ' greater than or equal to ')
        .replace(/\s*<\s*/g, ' less than ')
        .replace(/\s*>\s*/g, ' greater than ');
    
    // Handle multiplication/division notation
    processed = processed.replace(/\*/g, ' times ');
    processed = processed.replace(/\//g, ' divided by ');
    
    // Keep compound word hyphens but remove other standalone hyphens
    // A hyphen between letters is kept (compound words)
    // A hyphen at start/end or between numbers is already handled
    
    // Remove extra spaces
    processed = processed.replace(/\s+/g, ' ').trim();
    
    return processed;
}

async function speakAndType(text) {
    if (!state.voiceMode) return;
    
    // Reset interrupt signal before speaking
    interruptSignal = false;
    isSpeaking = true;
    currentSpeakingText = text.toLowerCase();
    
    // Prepare text for speech (convert numbers, symbols, etc.)
    const cleanText = prepareTextForTTS(text);
    
    if (!cleanText) return;
    
    // Start typewriter effect
    const typewriterPromise = typewriterEffect(text);
    
    // Start on-device TTS
    const speechPromise = speakWithLocalTTS(cleanText);
    
    // Wait for both to complete
    await Promise.all([typewriterPromise, speechPromise]);
    isSpeaking = false;
    currentSpeakingText = '';
}

// Local TTS — synthesize speech via the on-device engine (/api/tts) and play it.
async function speakWithLocalTTS(text) {
    if (!state.voiceMode || interruptSignal) return;

    // Stop any current TTS audio
    if (currentTTSAudio) {
        currentTTSAudio.onended = null;
        currentTTSAudio.onerror = null;
        currentTTSAudio.pause();
        currentTTSAudio = null;
    }
    if (currentTTSUrl) {
        URL.revokeObjectURL(currentTTSUrl);
        currentTTSUrl = null;
    }
    if (currentTTSResolve) {
        currentTTSResolve();
        currentTTSResolve = null;
    }

    if (voiceWaves && !interruptSignal) voiceWaves.classList.remove('paused');
    if (!interruptSignal && lunarStatusText) lunarStatusText.textContent = 'Lunar is speaking...';

    try {
        const response = await fetch(`${API_BASE}${VOICE_CONFIG.ttsEndpoint}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text })
        });
        if (!response.ok) throw new Error(`TTS error: ${response.status}`);
        if (interruptSignal) return;

        const audioBlob = await response.blob();
        const audioUrl = URL.createObjectURL(audioBlob);
        currentTTSUrl = audioUrl;

        return new Promise((resolve) => {
            currentTTSResolve = resolve;
            if (interruptSignal) {
                currentTTSResolve = null;
                resolve();
                return;
            }
            const audio = new Audio(audioUrl);
            currentTTSAudio = audio;

            audio.onended = () => {
                if (!interruptSignal) {
                    if (voiceWaves) voiceWaves.classList.add('paused');
                    if (lunarStatusText) lunarStatusText.textContent = '🎤 Listening...';
                }
                if (currentTTSUrl === audioUrl) { URL.revokeObjectURL(audioUrl); currentTTSUrl = null; }
                currentTTSAudio = null;
                currentTTSResolve = null;
                resolve();
            };
            audio.onerror = () => {
                if (voiceWaves) voiceWaves.classList.add('paused');
                if (!interruptSignal && lunarStatusText) lunarStatusText.textContent = '🎤 Listening...';
                if (currentTTSUrl === audioUrl) { URL.revokeObjectURL(audioUrl); currentTTSUrl = null; }
                currentTTSAudio = null;
                currentTTSResolve = null;
                resolve();
            };
            audio.play().catch(err => {
                console.error('Failed to play TTS:', err);
                if (voiceWaves) voiceWaves.classList.add('paused');
                if (!interruptSignal && lunarStatusText) lunarStatusText.textContent = '🎤 Listening...';
                currentTTSAudio = null;
                currentTTSResolve = null;
                resolve();
            });
        });
    } catch (error) {
        console.error('Local TTS error:', error);
        if (voiceWaves) voiceWaves.classList.add('paused');
        if (!interruptSignal && lunarStatusText) lunarStatusText.textContent = '🎤 Listening...';
    }
}

async function typewriterEffect(text) {
    if (!state.voiceMode || interruptSignal) return;
    
    // Format the text for display
    const formattedText = formatLectureForVoice(text);
    
    // Create a new paragraph element
    const paragraph = document.createElement('div');
    paragraph.className = 'voice-paragraph';
    voiceTranscript.appendChild(paragraph);
    
    // Add cursor
    const cursor = document.createElement('span');
    cursor.className = 'typing-cursor';
    paragraph.appendChild(cursor);
    
    // Type out character by character
    const chars = formattedText.split('');
    const baseSpeed = 30; // ms per character
    
    for (let i = 0; i < chars.length; i++) {
        if (!state.voiceMode || interruptSignal) {
            // Stop typing immediately
            cursor.remove();
            
            // Add interruption indicator
            if (interruptSignal) {
                const interrupted = document.createElement('span');
                interrupted.style.color = '#64748b';
                interrupted.style.fontStyle = 'italic';
                interrupted.textContent = ' [interrupted]';
                paragraph.appendChild(interrupted);
            }
            break;
        }
        
        // Insert character before cursor
        const charSpan = document.createTextNode(chars[i]);
        paragraph.insertBefore(charSpan, cursor);
        
        // Auto-scroll
        voiceTranscript.parentElement.scrollTop = voiceTranscript.parentElement.scrollHeight;
        
        // Variable speed for natural feel
        const speed = chars[i] === ' ' ? baseSpeed / 2 : 
                      /[.!?]/.test(chars[i]) ? baseSpeed * 3 : baseSpeed;
        
        await delay(speed);
    }
    
    // Remove cursor when done
    if (!interruptSignal) {
        cursor.remove();
        // Add spacing
        paragraph.innerHTML += '<br>';
    }
}

function formatLectureForVoice(text) {
    return text
        .replace(/^#+\s*/gm, '\n')
        .replace(/\*\*(.*?)\*\*/g, '$1')
        .replace(/\*(.*?)\*/g, '$1')
        .replace(/`(.*?)`/g, '$1')
        .replace(/^\- /gm, '• ')
        .trim();
}

function toggleVoicePause() {
    // Handle TTS pause/resume
    if (currentTTSAudio) {
        if (currentTTSAudio.paused) {
            currentTTSAudio.play();
            pauseVoiceBtn.innerHTML = `
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <rect x="6" y="4" width="4" height="16"/>
                    <rect x="14" y="4" width="4" height="16"/>
                </svg>
                Pause
            `;
            if (voiceWaves) voiceWaves.classList.remove('paused');
            lunarStatusText.textContent = 'Lunar is speaking...';
        } else {
            currentTTSAudio.pause();
            pauseVoiceBtn.innerHTML = `
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <polygon points="5 3 19 12 5 21 5 3"/>
                </svg>
                Resume
            `;
            if (voiceWaves) voiceWaves.classList.add('paused');
            lunarStatusText.textContent = 'Paused';
        }
    }
}

function quitVoiceMode() {
    state.voiceMode = false;
    isListening = false;
    
    // Stop listening
    stopDuplexListening();

    // Stop TTS playback
    if (currentTTSAudio) {
        currentTTSAudio.pause();
        currentTTSAudio = null;
    }
    
    // Stop any playing audio
    if (state.currentAudio) {
        state.currentAudio.pause();
        state.currentAudio = null;
    }
    
    // Stop warp effect
    if (window.stopWarpEffect) {
        window.stopWarpEffect();
    }
    
    // Hide modal
    voiceModeModal.style.display = 'none';
    
    // Reset state
    state.voiceQueue = [];
    state.isPlaying = false;
    pauseVoiceBtn.style.display = 'none';
    
    lunarStatusText.textContent = 'Lunar is listening...';
}

function delay(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}


// ============================================================
// THE CLASSROOM — slide-by-slide tutor (board + chat + voice)
// ============================================================
const cr = {
    active: false,
    slideCount: 0,
    slideIndex: 0,
    state: 'idle',        // idle | teaching | awaiting | responding
    last: false,
    voice: false,
    history: [],
    boardRaw: '',
    prefixHTML: '',        // verbatim board content (typed text + inline media)
    noteBuf: '',           // Lunar's short note, buffered while verbatim types
    verbatimDone: false,
    typeGen: 0,            // bumped on slide change to abort stale typing
    slideExaminable: true,
    activeAbort: null,     // the controller driving the current LLM stream
    stopReq: false,        // true when the user hit Stop (vs. slide-nav abort)
};

const crEls = {};
function crInit() {
    crEls.root = document.getElementById('classroom');
    if (!crEls.root) return;
    crEls.board = document.getElementById('cr-board');
    crEls.dots = document.getElementById('cr-dots');
    crEls.slideLabel = document.getElementById('cr-slide-label');
    crEls.status = document.getElementById('cr-status');
    crEls.bubbles = document.getElementById('cr-bubbles');
    crEls.input = document.getElementById('cr-input');
    crEls.filename = document.getElementById('cr-filename');
    crEls.sendBtn = document.getElementById('cr-send-btn');
    crEls.stopBtn = document.getElementById('cr-stop-btn');
    crEls.nextBtn = document.getElementById('cr-next-btn');
    crEls.prevBtn = document.getElementById('cr-prev-btn');
    crEls.exitBtn = document.getElementById('cr-exit-btn');
    crEls.searchInput = document.getElementById('cr-search-input');
    crEls.searchResults = document.getElementById('cr-search-results');
    crEls.roomWrap = document.querySelector('.cr-room-wrap');
    crEls.roomImg = document.querySelector('.cr-room');

    crFitRoom();
    window.addEventListener('resize', crFitRoom);
    if (crEls.roomImg) crEls.roomImg.addEventListener('load', crFitRoom);

    crEls.sendBtn.addEventListener('click', () => crSubmitInput());
    if (crEls.stopBtn) crEls.stopBtn.addEventListener('click', () => crStopGeneration());
    crEls.input.addEventListener('keydown', (e) => { if (e.key === 'Enter') crSubmitInput(); });
    crEls.nextBtn.addEventListener('click', () => crNextSlide());
    if (crEls.prevBtn) crEls.prevBtn.addEventListener('click', () => crPrevSlide());
    crEls.exitBtn.addEventListener('click', () => crExit());

    // Find Anything — semantic search across the deck
    if (crEls.searchInput) {
        crEls.searchInput.addEventListener('input', crSearchDebounced);
        crEls.searchInput.addEventListener('keydown', (e) => { if (e.key === 'Escape') crCloseSearch(); });
        document.addEventListener('click', (e) => {
            if (crEls.searchResults && !e.target.closest('.cr-search')) crCloseSearch();
        });
    }

    // Highlight → Explain / Solve
    crEls.selTools = document.getElementById('cr-sel-tools');
    crEls.explainBtn = document.getElementById('cr-explain-btn');
    crEls.solveBtn = document.getElementById('cr-solve-btn');
    if (crEls.explainBtn) crEls.explainBtn.addEventListener('click', () => crExplainSelection(cr.lastSelection, 'explain'));
    if (crEls.solveBtn) crEls.solveBtn.addEventListener('click', () => crExplainSelection(cr.lastSelection, 'solve'));
    document.addEventListener('mouseup', (e) => {
        if (e.target.closest && e.target.closest('#cr-sel-tools')) return;  // let the button click run
        setTimeout(crUpdateSelTools, 0);
    });
    if (crEls.board) crEls.board.addEventListener('scroll', crHideSelTools);
}

// Show the Explain/Solve buttons when the student highlights board text (after
// the lecture). The selection text is captured so the button still works even
// if the click collapses the selection.
function crUpdateSelTools() {
    const tools = crEls.selTools;
    if (!tools || !cr.active) return;
    if (CR_BUSY.includes(cr.state)) { crHideSelTools(); return; }
    const sel = window.getSelection();
    const text = (sel && sel.toString) ? sel.toString().trim() : '';
    if (!text || text.length < 2 || !sel.rangeCount || sel.isCollapsed) {
        crHideSelTools(); return;
    }
    // Show the tools as long as the selection lives inside the board — works for the
    // lecture text AND the slide's text layer (whose image endpoint is unselectable).
    const range = sel.getRangeAt(0);
    if (!crEls.board || !crEls.board.contains(range.commonAncestorContainer)) {
        crHideSelTools(); return;
    }
    cr.lastSelection = text;
    const rect = range.getBoundingClientRect();
    tools.style.display = 'flex';
    const tw = tools.offsetWidth || 150, th = tools.offsetHeight || 38;
    let left = Math.max(8, Math.min(rect.left + rect.width / 2 - tw / 2, window.innerWidth - tw - 8));
    let top = rect.top - th - 8;
    if (top < 64) top = rect.bottom + 8;   // flip below if too close to the top
    tools.style.left = left + 'px';
    tools.style.top = top + 'px';
}
function crHideSelTools() { if (crEls.selTools) crEls.selTools.style.display = 'none'; }

// Lunar explains (or solves) the highlighted portion, prefaced with a quick ack.
async function crExplainSelection(sel, mode) {
    sel = (sel || '').trim();
    if (!sel || CR_BUSY.includes(cr.state)) return;
    crHideSelTools();
    try { window.getSelection().removeAllRanges(); } catch (e) {}
    cr.history.push({ role: 'user', content: (mode === 'solve' ? 'Solve: ' : 'Explain: ') + sel });
    cr.state = 'responding';
    crSetStatus(mode === 'solve' ? 'Lunar is solving…' : 'Lunar is explaining…');
    crUpdateProgress();
    const shown = sel.length > 160 ? sel.slice(0, 160) + '…' : sel;
    const preface = mode === 'solve'
        ? `\n\n**Aight, solving:** "${shown}"\n\n`
        : `\n\n**Aight, I'll explain that.**\n\n`;
    crAppendBoard(preface);
    let buf = '';
    const startLen = cr.boardRaw.length;
    crShowThinking(cr.boardRaw.slice(0, startLen));
    cr.stopReq = false;
    cr.activeAbort = new AbortController();
    try {
        await streamNDJSON('/api/classroom/explain', {
            session_id: state.sessionId, slide_index: cr.slideIndex, selection: sel, mode
        }, (msg) => {
            if (msg.error) throw new Error(msg.error);
            if (msg.token) { buf += msg.token; crRenderBoardStreaming(cr.boardRaw.slice(0, startLen) + buf); }
        }, cr.activeAbort.signal);
    } catch (e) {
        if (cr.stopReq && buf.trim()) { /* user stopped — keep what we have */ }
        else if (buf.trim().length < 8) buf = "Let me come back to that one.";
    }
    cr.boardRaw = cr.boardRaw.slice(0, startLen) + buf;
    crRenderBoard(cr.boardRaw, false);
    cr.history.push({ role: 'assistant', content: crStripMd(buf).slice(0, 400) });
    cr.state = 'awaiting';
    crSetStatus(cr.last ? 'Last slide — highlight, ask, or review' : 'Highlight to Explain/Solve, ask, or hit Next');
    crUpdateProgress();
}

// Size the u7.png scene to COVER the viewport (any ratio) so it fills the screen
// and the board overlay stays aligned to the hologram. Re-fit on resize.
const CR_ROOM_AR = 1672 / 941;
function crFitRoom() {
    const wrap = crEls.roomWrap;
    if (!wrap) return;
    const W = window.innerWidth, H = window.innerHeight;
    let w, h;
    if (W / H >= CR_ROOM_AR) { w = W; h = Math.ceil(W / CR_ROOM_AR); }
    else { h = H; w = Math.ceil(H * CR_ROOM_AR); }
    wrap.style.width = w + 'px';
    wrap.style.height = h + 'px';
    wrap.style.left = Math.round((W - w) / 2) + 'px';
    wrap.style.top = Math.round((H - h) / 2) + 'px';
}

// ---- Find Anything: semantic search across the whole deck ----
let crSearchTimer = null;
function crSearchDebounced() {
    clearTimeout(crSearchTimer);
    crSearchTimer = setTimeout(crRunSearch, 280);
}
async function crRunSearch() {
    if (CR_BUSY.includes(cr.state)) { crCloseSearch(); return; }   // not while teaching
    const q = (crEls.searchInput.value || '').trim();
    if (q.length < 2) { crCloseSearch(); return; }
    crEls.searchResults.innerHTML = '<div class="cr-search-empty">Searching…</div>';
    crEls.searchResults.classList.add('open');
    let data;
    try {
        const res = await fetch(`${API_BASE}/api/classroom/search`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id: state.sessionId, query: q })
        });
        data = await res.json();
    } catch (e) { data = { results: [] }; }
    const results = (data && data.results) || [];
    if (!results.length) {
        crEls.searchResults.innerHTML = '<div class="cr-search-empty">Nothing matched that on your slides.</div>';
        return;
    }
    crEls.searchResults.innerHTML = '';
    for (const r of results) {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'cr-search-item';
        btn.innerHTML = `<span class="cr-si-title"><span class="cr-si-num">Slide ${r.index + 1}</span>${escapeHtml(r.title || '')}</span>` +
            (r.snippet ? `<span class="cr-si-snip">${escapeHtml(r.snippet)}</span>` : '');
        btn.addEventListener('click', () => {
            crCloseSearch();
            crEls.searchInput.value = '';
            if (!CR_BUSY.includes(cr.state)) crTeachSlide(r.index);
        });
        crEls.searchResults.appendChild(btn);
    }
}
function crCloseSearch() {
    if (crEls.searchResults) crEls.searchResults.classList.remove('open');
}

// Clean text for speech: remove markdown/LaTeX markers and turn a few math
// symbols into words, so TTS never reads "asterisk asterisk" or "backslash frac".
function crStripMd(t) {
    return (t || '')
        // LaTeX
        .replace(/\\\[|\\\]|\\\(|\\\)/g, ' ')
        .replace(/\\text\s*\{([^}]*)\}/g, '$1')
        .replace(/\\frac\s*\{([^}]*)\}\s*\{([^}]*)\}/g, ' $1 over $2 ')
        .replace(/\\Omega/gi, ' ohms ')
        .replace(/\\times/g, ' times ')
        .replace(/\\(?:,|;|!|quad|qquad)/g, ' ')
        .replace(/\\[a-zA-Z]+/g, ' ')
        .replace(/[{}]/g, ' ')
        // markdown markers (headings, bold, italic, code, quotes, lists)
        .replace(/\*\*/g, '')
        .replace(/__/g, '')
        .replace(/`/g, '')
        .replace(/^[ \t]*#{1,6}\s*/gm, '')
        .replace(/#+/g, ' ')
        .replace(/^[ \t]*[-•]\s+/gm, '')
        .replace(/_/g, ' ')
        .replace(/[>~]/g, ' ')
        // math symbols → spoken words
        .replace(/\s\*\s/g, ' times ')
        .replace(/\*/g, '')
        .replace(/×/g, ' times ')
        .replace(/÷/g, ' divided by ')
        .replace(/Ω/g, ' ohms ')
        .replace(/µ|μ/g, ' micro')
        .replace(/\s*=\s*/g, ' equals ')
        .replace(/\^2\b/g, ' squared ')
        .replace(/\^3\b/g, ' cubed ')
        .replace(/\s+/g, ' ')
        .trim();
}

let crRenderTimer = null, crRenderPending = null;
function crRenderBoard(text, streaming) {
    // The verbatim slide (text + inline figures/videos) is the fixed prefix;
    // the lecture and chat replies render as markdown after it.
    if (crRenderTimer) { clearTimeout(crRenderTimer); crRenderTimer = null; crRenderPending = null; }
    const html = (cr.prefixHTML || '') + formatLecture(text || '');
    crEls.board.innerHTML = html + (streaming ? '<span class="cr-cursor">▋</span>' : '');
    crEls.board.scrollTop = crEls.board.scrollHeight;
}

// Coalesce streaming token renders to ~16fps. Re-running formatLecture over the
// whole growing lecture on EVERY token is O(n²) and makes the writing lag; this
// renders at most once per frame-ish instead.
function crRenderBoardStreaming(text) {
    crRenderPending = text;
    if (crRenderTimer) return;
    crRenderTimer = setTimeout(() => {
        crRenderTimer = null;
        if (crRenderPending == null) return;
        const t = crRenderPending; crRenderPending = null;
        const b = crEls.board;
        const prevTop = b.scrollTop;
        const wasNearBottom = b.scrollHeight - prevTop - b.clientHeight < 60;
        b.innerHTML = (cr.prefixHTML || '') + formatLecture(t) + '<span class="cr-cursor">▋</span>';
        // follow the writing, but don't yank the user back if they scrolled up to read
        b.scrollTop = wasNearBottom ? b.scrollHeight : prevTop;
    }, 60);
}

function crSetStatus(t) { if (crEls.status) crEls.status.textContent = t; }

function crThinkingHTML() {
    return '<div class="cr-thinking"><span class="cr-think-dots"><i></i><i></i><i></i></span> Lunar is thinking…</div>';
}
function crShowThinking(prefixRaw) {
    crEls.board.innerHTML = (cr.prefixHTML || '') +
        (prefixRaw ? formatLecture(prefixRaw) : '') + crThinkingHTML();
    crEls.board.scrollTop = crEls.board.scrollHeight;
}

// ---- verbatim board: figures, videos & links extracted from the slide ----
function crAttr(s) { return String(s == null ? '' : s).replace(/"/g, '&quot;'); }

function crMediaHTML(b) {
    if (!b || !b.url) return '';
    if (b.type === 'image') {
        const cap = (b.alt || '').trim();
        return `<figure class="cr-figure"><img src="${crAttr(b.url)}" alt="${crAttr(cap)}" loading="lazy">` +
            (cap ? `<figcaption>${escapeHtml(cap)}</figcaption>` : '') + `</figure>`;
    }
    if (b.type === 'video') {
        return `<figure class="cr-figure"><video src="${crAttr(b.url)}" controls preload="metadata" class="cr-video"></video></figure>`;
    }
    return '';
}

function crLinksHTML(links) {
    const ls = (links || []).filter(l => l && l.url);
    if (!ls.length) return '';
    return '<div class="cr-links"><span class="cr-links-label">Links</span>' +
        ls.map(l => `<a href="${crAttr(l.url)}" target="_blank" rel="noopener">${escapeHtml(l.text || l.url)}</a>`).join('') +
        '</div>';
}

// Type one verbatim text segment into the board (chalk-writing effect).
async function crTypeInto(full, gen) {
    full = full || '';
    const tick = 16, maxMs = 3000;
    const ticks = Math.max(1, Math.min(full.length, Math.floor(maxMs / tick)));
    const step = Math.max(1, Math.ceil(full.length / ticks));
    for (let i = 0; i < full.length; i += step) {
        if (!cr.active || gen !== cr.typeGen) return;
        crEls.board.innerHTML = cr.prefixHTML + formatLecture(full.slice(0, i + step)) +
            '<span class="cr-cursor">▋</span>';
        crEls.board.scrollTop = crEls.board.scrollHeight;
        await delay(tick);
    }
}

// Preload an image URL; resolve(the Image) on load, resolve(null) on error.
function crLoadImage(url) {
    return new Promise((resolve) => {
        const im = new Image();
        im.onload = () => resolve(im);
        im.onerror = () => resolve(null);
        im.src = url;
    });
}

// Overlay an invisible, selectable text layer on the chalk slide (PDF.js / WPS
// style): one span per word, each MEASURED and stretched horizontally (scaleX) to
// sit exactly over its real word. That alignment is what makes selection precise —
// dragging grabs only the words under the cursor, never the surrounding text.
// The measured transforms are baked into the HTML string so they survive the
// streaming re-renders (and stay correct on resize, since every value is a ratio).
async function crLoadSlideTextLayer(idx, ar, gen) {
    try {
        const res = await fetch(`${API_BASE}/api/classroom/slide_text/${state.sessionId}/${idx}`);
        if (!res.ok) return;
        const data = await res.json();
        if (gen !== cr.typeGen || !cr.slideFigureHTML || cr.slideHasLayer) return;
        const words = (data && data.words) || [];
        if (!words.length) return;
        const liveFig = crEls.board.querySelector('.cr-slide');
        if (!liveFig) return;
        const a = ar || 1;

        // 1) Build the layer with each word positioned + sized to its box height,
        //    then attach it live so we can measure each word's natural width.
        const layer = document.createElement('div');
        layer.className = 'cr-textlayer';
        const els = words.map(w => {
            const s = document.createElement('span');
            s.textContent = w.t;
            s.style.left = (w.x * 100).toFixed(3) + '%';
            s.style.top = (w.y * 100).toFixed(3) + '%';
            s.style.fontSize = (w.h * 100 / a).toFixed(3) + 'cqw';
            layer.appendChild(s);
            return s;
        });
        liveFig.appendChild(layer);
        const layerW = layer.clientWidth || liveFig.clientWidth || 0;

        // 2) Stretch each word to exactly cover its box (synchronous — no await, so a
        //    streaming repaint can't wipe the layer mid-measure).
        if (layerW > 10) {
            for (let i = 0; i < words.length; i++) {
                const natural = els[i].offsetWidth || 1;
                const sx = Math.max(0.02, (words[i].w * layerW) / natural);
                els[i].style.transform = 'scaleX(' + sx.toFixed(4) + ')';
                els[i].textContent = words[i].t + ' ';   // space → clean selection text
            }
        }

        // 3) Bake the measured layer into prefixHTML and drop the live probe.
        const layerHTML = layer.outerHTML;
        layer.remove();
        cr.slideFigureHTML = cr.slideFigureHTML.replace('</figure>', layerHTML + '</figure>');
        cr.slideHasLayer = true;
        cr.prefixHTML = cr.slideFigureHTML + (cr.slideLinksHTML || '');
        if (cr.state !== 'teaching' && cr.state !== 'responding') {
            crRenderBoard(cr.boardRaw || '', false);
        }
    } catch (e) { /* selection just won't be available on this slide */ }
}

// Warm the next slide's render so navigation feels instant (cached server-side +
// in the browser). Harmless for non-board slides.
function crPrefetchSlide(idx) {
    if (idx < 0 || idx >= cr.slideCount) return;
    try {
        const im = new Image();
        im.onerror = () => {};
        im.src = `${API_BASE}/api/classroom/slide_image/${state.sessionId}/${idx}`;
    } catch (e) { /* ignore */ }
}

// Write the slide verbatim: type each text block, reveal each figure/video in
// slide order, then list any links. Builds cr.prefixHTML as it goes.
async function crTypeSlidePayload(payload, gen) {
    cr.prefixHTML = '';
    cr.curIsBoard = false;
    // Blank original page — tell the user instead of showing an empty board.
    if (payload && payload.blank) {
        cr.prefixHTML = '<div class="cr-empty">This page is blank in the original document. ' +
            'Hit <b>Next slide</b> to continue.</div>';
        crEls.board.innerHTML = cr.prefixHTML;
        crEls.board.scrollTop = 0;
        return;
    }
    // PDF / image slides: the real page, recolored to chalk, opens on the board.
    if (payload && payload.image) {
        cr.curIsBoard = true;
        // Show a loading state and preload the image so the board is never just
        // blank while the server renders the page.
        crEls.board.innerHTML = '<div class="cr-rendering"><span class="cr-spin"></span>Opening slide…</div>';
        crEls.board.scrollTop = 0;
        const img = await crLoadImage(payload.image);
        if (gen !== cr.typeGen) return;     // a newer slide started
        cr.slideLinksHTML = crLinksHTML(payload.links);
        cr.slideHasLayer = false;
        if (img) {
            cr.slideFigureHTML = `<figure class="cr-slide"><img class="cr-slide-img" src="${crAttr(payload.image)}" alt="slide" draggable="false"></figure>`;
            cr.prefixHTML = cr.slideFigureHTML + cr.slideLinksHTML;
            // Overlay an invisible, selectable text layer so the real slide can be
            // highlighted like normal text (fetched async; updates prefixHTML when ready).
            const ar = (img.naturalWidth && img.naturalHeight) ? (img.naturalWidth / img.naturalHeight) : 1;
            crLoadSlideTextLayer(cr.slideIndex, ar, gen);
        } else {
            cr.slideFigureHTML = '';
            cr.prefixHTML = '<div class="cr-empty">Couldn’t open this slide. ' +
                'Hit <b>Next slide</b> to continue.</div>' + cr.slideLinksHTML;
        }
        crEls.board.innerHTML = cr.prefixHTML;
        crEls.board.scrollTop = 0;
        return;
    }
    const blocks = (payload && payload.blocks) || [];
    if (!blocks.length) {
        cr.prefixHTML = '<div class="cr-empty">This slide has no teachable content ' +
            '(it looks like a title, names, or references). Hit Next to continue.</div>';
        crEls.board.innerHTML = cr.prefixHTML;
        return;
    }
    for (const b of blocks) {
        if (!cr.active || gen !== cr.typeGen) return;
        if (b.type === 'text') {
            await crTypeInto(b.text, gen);
            if (gen !== cr.typeGen) return;
            cr.prefixHTML += formatLecture(b.text);
        } else if (b.type === 'image' || b.type === 'video') {
            cr.prefixHTML += crMediaHTML(b);
            crEls.board.innerHTML = cr.prefixHTML + '<span class="cr-cursor">▋</span>';
            crEls.board.scrollTop = crEls.board.scrollHeight;
            await delay(240);
        }
    }
    cr.prefixHTML += crLinksHTML(payload.links);
    crEls.board.innerHTML = cr.prefixHTML;
    crEls.board.scrollTop = crEls.board.scrollHeight;
}

function crUpdateProgress() {
    crEls.slideLabel.textContent = `Slide ${cr.slideIndex + 1} of ${cr.slideCount}`;
    if (cr.progressFill) {
        const pct = cr.slideCount > 1 ? ((cr.slideIndex + 1) / cr.slideCount) * 100 : 100;
        cr.progressFill.style.width = pct + '%';
    } else {
        [...crEls.dots.children].forEach((d, i) => {
            d.className = 'cr-dot' + (i < cr.slideIndex ? ' done' : i === cr.slideIndex ? ' active' : '');
        });
    }
    const busy = CR_BUSY.includes(cr.state);
    crEls.nextBtn.disabled = busy;
    if (crEls.prevBtn) crEls.prevBtn.disabled = busy || cr.slideIndex <= 0;
    // Show the Stop button only while Lunar is actively generating.
    if (crEls.stopBtn) crEls.stopBtn.style.display = busy ? 'inline-flex' : 'none';
    if (crEls.sendBtn) crEls.sendBtn.style.display = busy ? 'none' : 'inline-flex';
    // "Find anything" stays disabled while Lunar is writing — searching then
    // would fight the lecture LLM for the CPU and crawl.
    if (crEls.searchInput) {
        crEls.searchInput.disabled = busy;
        crEls.searchInput.placeholder = busy ? 'Available after the lecture…' : 'Find anything…';
        if (busy) crCloseSearch();
    }
}

function crAddBubble(role, text) {
    const b = document.createElement('div');
    b.className = `cr-bubble ${role}`;
    b.textContent = text;
    crEls.bubbles.appendChild(b);
    crEls.bubbles.scrollTop = crEls.bubbles.scrollHeight;
    return b;
}

// Show the classroom shell with a "reading your slides" state while the upload
// is being parsed/OCR'd (so the user knows it's working).
function crEnterReading(filename) {
    if (!crEls.root) crInit();
    cr.active = true;
    cr.history = [];
    cr.slideCount = 0;
    cr.state = 'reading';
    document.getElementById('main-content').style.display = 'none';
    const topbar = document.querySelector('.topbar'); if (topbar) topbar.classList.add('hidden');
    crEls.root.style.display = 'flex';
    crFitRoom();
    crEls.filename.textContent = filename || '';
    crEls.bubbles.innerHTML = '';
    crEls.dots.innerHTML = '';
    crEls.slideLabel.textContent = '';
    crSetStatus('Reading your slides…');
    crEls.board.innerHTML =
        '<div class="cr-thinking"><span class="cr-think-dots"><i></i><i></i><i></i></span> Lunar is reading your slides…</div>';
}

async function enterClassroom(filename) {
    if (!crEls.root) crInit();
    cr.active = true;
    cr.history = [];
    document.getElementById('main-content').style.display = 'none';
    const topbar = document.querySelector('.topbar'); if (topbar) topbar.classList.add('hidden');
    crEls.root.style.display = 'flex';
    crEls.filename.textContent = filename || '';
    crEls.bubbles.innerHTML = '';
    crEls.board.innerHTML =
        '<div class="cr-thinking"><span class="cr-think-dots"><i></i><i></i><i></i></span> Lunar is opening your class…</div>';
    crSetStatus('Opening your class…');

    try {
        const res = await fetch(`${API_BASE}/api/classroom/start`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ session_id: state.sessionId }) });
        const data = await res.json();
        cr.slideCount = data.count || 1;
    } catch (e) { cr.slideCount = 1; }

    crBuildProgress();
    crTeachSlide(0);
}

// Dots for small decks; a slim progress bar for big ones (so 97 slides don't
// overflow the topbar and shove the Voice/Exit buttons off-screen).
function crBuildProgress() {
    crEls.dots.innerHTML = '';
    if (cr.slideCount > 24) {
        const bar = document.createElement('div'); bar.className = 'cr-bar';
        const fill = document.createElement('div'); fill.className = 'cr-bar-fill';
        bar.appendChild(fill); crEls.dots.appendChild(bar);
        cr.progressFill = fill;
    } else {
        cr.progressFill = null;
        for (let i = 0; i < cr.slideCount; i++) {
            const d = document.createElement('div'); d.className = 'cr-dot'; crEls.dots.appendChild(d);
        }
    }
}

function crExit() {
    if (cr.teachAbort) { try { cr.teachAbort.abort(); } catch (e) {} }
    crCloseSearch();
    cr.active = false;
    crEls.root.style.display = 'none';
    document.getElementById('main-content').style.display = '';
    const topbar = document.querySelector('.topbar'); if (topbar) topbar.classList.remove('hidden');
    // Offer a way back into the lesson.
    const ret = document.getElementById('return-classroom-btn');
    if (ret && cr.slideCount > 0) ret.style.display = 'inline-flex';
}

// Re-enter the classroom right where you left off (no re-teaching).
function resumeClassroom() {
    if (!crEls.root) crInit();
    if (!cr.slideCount) return;
    cr.active = true;
    document.getElementById('main-content').style.display = 'none';
    const topbar = document.querySelector('.topbar'); if (topbar) topbar.classList.add('hidden');
    crEls.root.style.display = 'flex';
}

async function crTeachSlide(index) {
    if (index < 0 || index >= cr.slideCount) return;
    crHideSelTools();
    // Cancel the previous slide's note generation so it stops hogging the CPU
    // (LLM inference pins all cores and would starve this slide's render).
    if (cr.teachAbort) { try { cr.teachAbort.abort(); } catch (e) {} }
    cr.teachAbort = new AbortController();
    cr.activeAbort = cr.teachAbort;    // so the Stop button can cancel the lecture
    cr.stopReq = false;
    const teachSignal = cr.teachAbort.signal;
    const gen = ++cr.typeGen;          // abort any typing from the previous slide
    cr.slideIndex = index;
    cr.state = 'teaching';
    cr.last = (index >= cr.slideCount - 1);
    cr.boardRaw = '';
    cr.prefixHTML = '';
    cr.noteBuf = '';
    cr.verbatimDone = false;
    cr.slideExaminable = true;
    crUpdateProgress();
    crSetStatus('Lunar is reading the slide…');
    crShowThinking('');

    // The backend first sends the verbatim slide (text + inline media), then
    // streams a short note. We type the slide out (chalk effect) while buffering
    // the note, then reveal the note, so nothing appears instantly.
    let typingPromise = Promise.resolve();
    let gotPayload = false;
    try {
        await streamNDJSON('/api/classroom/teach_stream',
            { session_id: state.sessionId, slide_index: index }, (msg) => {  // teachSignal below
                if (msg.error) throw new Error(msg.error);
                if (msg.slide) {
                    gotPayload = true;
                    cr.slideExaminable = !!msg.slide.examinable;
                    typingPromise = crTypeSlidePayload(msg.slide, gen).then(() => {
                        if (gen !== cr.typeGen) return;
                        cr.verbatimDone = true;
                        if (cr.noteBuf) {
                            cr.boardRaw += cr.noteBuf;
                            cr.noteBuf = '';
                            crRenderBoard(cr.boardRaw, true);
                        } else if (cr.slideExaminable) {
                            // Slide is up but qwen is still warming up — show
                            // "Lunar is thinking…" under it so it never feels dead.
                            crShowThinking('');
                        }
                    });
                } else if (msg.token) {
                    if (cr.verbatimDone) { cr.boardRaw += msg.token; crRenderBoardStreaming(cr.boardRaw); }
                    else { cr.noteBuf += msg.token; }
                }
                if (msg.done) cr.last = !!msg.last;
            }, teachSignal);
    } catch (e) {
        // A slide-navigation abort drops silently; a manual Stop falls through so we
        // keep whatever streamed and finalize the board below.
        if (e && e.name === 'AbortError' && !cr.stopReq) return;
        if (!(e && e.name === 'AbortError') && !gotPayload) {
            cr.prefixHTML = '';
            cr.boardRaw = "Hmm, I lost my chalk for a second. Use Previous/Next to try this slide again.";
        }
    }
    if (gen !== cr.typeGen) return;     // a newer slide started — abandon this one
    await typingPromise;
    if (gen !== cr.typeGen) return;     // a newer slide started — abandon this one
    if (cr.curIsBoard) crPrefetchSlide(index + 1);   // warm the next page render
    cr.verbatimDone = true;
    if (cr.noteBuf) { cr.boardRaw += cr.noteBuf; cr.noteBuf = ''; }
    // Tell the student about highlight → Explain / Solve.
    if (cr.slideExaminable) {
        cr.boardRaw += "\n\n_Highlight any part of the slide or this lesson, then tap " +
            "**Explain** for a closer look — or **Solve** if it's a question._";
    }
    crRenderBoard(cr.boardRaw, false);
    cr.history.push({ role: 'assistant', content: crStripMd(cr.boardRaw || '').slice(0, 400) });

    // Lecture done — the student can ask about the slide or move on.
    cr.state = 'awaiting';
    crSetStatus(cr.last ? 'Class complete — highlight, ask, or review'
        : 'Highlight to Explain/Solve, ask, or hit Next');
    crUpdateProgress();
}

const CR_BUSY = ['reading', 'teaching', 'responding'];

async function crPrevSlide() {
    if (CR_BUSY.includes(cr.state)) return;
    if (cr.slideIndex <= 0) return;
    crTeachSlide(cr.slideIndex - 1);
}

async function crNextSlide() {
    if (CR_BUSY.includes(cr.state)) return;
    if (cr.slideIndex >= cr.slideCount - 1) {
        crAppendBoard("\n\n## That's a wrap!\nYou've finished every slide. Great work — ask me anything to review.");
        cr.last = true;
        crSetStatus('Class complete — ask me anything to review');
        return;
    }
    crTeachSlide(cr.slideIndex + 1);
}

function crAppendBoard(md) {
    cr.boardRaw = (cr.boardRaw || '') + md;
    crRenderBoard(cr.boardRaw, false);
}

function crSubmitInput() {
    const text = (crEls.input.value || '').trim();
    if (!text) return;
    if (CR_BUSY.includes(cr.state)) return;  // wait for Lunar to finish
    crEls.input.value = '';
    crHandleMessage(text);
}

// Stop whatever Lunar is generating right now (lecture, explanation, solution, or
// chat reply). Aborts the in-flight stream; each stream's handler keeps whatever was
// written so far and drops the classroom back to 'awaiting'.
function crStopGeneration() {
    if (!CR_BUSY.includes(cr.state)) return;
    cr.stopReq = true;
    try { if (cr.activeAbort) cr.activeAbort.abort(); } catch (e) {}
    crSetStatus('Stopped.');
}

async function crHandleMessage(text) {
    // The student's message is sent to Lunar but never shown on screen.
    cr.history.push({ role: 'user', content: text });

    cr.state = 'responding';
    crSetStatus('Lunar is thinking…');
    crUpdateProgress();
    crAppendBoard('\n\n');
    let buf = '';
    const startLen = cr.boardRaw.length;
    crShowThinking(cr.boardRaw.slice(0, startLen));
    cr.stopReq = false;
    cr.activeAbort = new AbortController();
    try {
        await streamNDJSON('/api/classroom/chat_stream', {
            session_id: state.sessionId,
            slide_index: cr.slideIndex,
            message: text,
            history: cr.history.slice(-6)
        }, (msg) => {
            if (msg.error) throw new Error(msg.error);
            if (msg.token) { buf += msg.token; crRenderBoardStreaming(cr.boardRaw.slice(0, startLen) + buf); }
        }, cr.activeAbort.signal);
    } catch (e) {
        if (cr.stopReq && buf.trim()) { /* user stopped — keep what we have */ }
        else if (buf.trim().length < 12) buf = "Sorry, I didn't catch that — could you say it again?";
    }
    cr.boardRaw = cr.boardRaw.slice(0, startLen) + buf;
    crRenderBoard(cr.boardRaw, false);
    cr.history.push({ role: 'assistant', content: crStripMd(buf).slice(0, 400) });

    cr.state = 'awaiting';
    crSetStatus(cr.last ? 'Last slide — ask me anything' : 'Ask about this slide, or hit Next');
    crUpdateProgress();
}

document.addEventListener('DOMContentLoaded', crInit);
