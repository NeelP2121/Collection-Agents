const sessionId = Math.random().toString(36).substring(2, 15);
let currentPhase = 1;
let vapiInstance = null;
let vapiConfigured = false;
let callInterval = null;

const chatInput = document.getElementById('chat-input');
const sendBtn = document.getElementById('send-button');
const messagesContainer = document.getElementById('messages-container');
const chatUI = document.getElementById('chat-ui');
const voiceUI = document.getElementById('voice-ui');

const btnAccept = document.getElementById('btn-call-accept');
const btnDecline = document.getElementById('btn-call-decline');
const btnEnd = document.getElementById('btn-call-end');
const callControls = document.querySelector('.call-controls');
const callActiveUI = document.getElementById('call-active-ui');

// Auto-scroll logic
function scrollToBottom() {
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

// Typing Indicator
function showTyping() {
    const typingMsg = document.createElement('div');
    typingMsg.className = 'message agent-msg typing-indicator';
    typingMsg.id = 'typing-indicator';
    typingMsg.innerHTML = '<div class="typing-dot"></div><div class="typing-dot"></div><div class="typing-dot"></div>';
    messagesContainer.appendChild(typingMsg);
    scrollToBottom();
}

function hideTyping() {
    const el = document.getElementById('typing-indicator');
    if (el) el.remove();
}

// Formatting text messages manually
function appendMessage(text, role) {
    const msg = document.createElement('div');
    msg.className = `message ${role}-msg`;
    msg.innerText = text;
    messagesContainer.appendChild(msg);
    scrollToBottom();
}

function appendSystemMessage(text) {
    const msg = document.createElement('div');
    msg.className = 'message system-message';
    msg.innerText = text;
    messagesContainer.appendChild(msg);
    scrollToBottom();
}

// Bridge API Calls
async function sendMessage() {
    const text = chatInput.value.trim();
    if (!text) return;

    appendMessage(text, 'user');
    chatInput.value = '';
    
    showTyping();

    try {
        const res = await fetch('/api/chat', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                session_id: sessionId,
                message: text,
                phase: currentPhase
            })
        });
        
        const data = await res.json();
        
        hideTyping();
        appendMessage(data.reply, 'agent');
        
        // Handle trigger: transition to voice phase
        if (data.trigger_call && currentPhase === 1) {
            triggerVoiceHandoff();
        }
        
    } catch (err) {
        hideTyping();
        appendMessage("Network error. Could not connect to agent.", 'agent');
    }
}

sendBtn.addEventListener('click', sendMessage);
chatInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') sendMessage();
});

// Voice UI Handlers
function triggerVoiceHandoff() {
    appendSystemMessage("Transferring to Voice Resolution Agent...");
    
    setTimeout(() => {
        chatUI.style.filter = "blur(10px)";
        chatUI.style.opacity = "0.5";
        voiceUI.classList.remove('hidden');
        currentPhase = 2;
    }, 1500);
}

const voiceStatusText = document.getElementById('voice-status-text');
const callActivityLabel = document.getElementById('call-activity-label');

btnDecline.addEventListener('click', () => {
    stopVapiCall();
    invokeCallEndSim();
});

btnAccept.addEventListener('click', async () => {
    // Unlock browser AudioContext immediately inside the user gesture
    // so VAPI's WebRTC audio output is allowed to play
    try {
        const AudioCtx = window.AudioContext || window.webkitAudioContext;
        if (AudioCtx) { const ctx = new AudioCtx(); await ctx.resume(); }
    } catch (_) {}

    callControls.classList.add('hidden');
    callActiveUI.classList.remove('hidden');
    startCallTimer();
    await startVapiCall();
});

btnEnd.addEventListener('click', () => {
    stopVapiCall();
    invokeCallEndSim();
});

// --- Timer helpers ---
function startCallTimer() {
    let seconds = 0;
    const timer = document.querySelector('.timer');
    callInterval = setInterval(() => {
        seconds++;
        const mins = Math.floor(seconds / 60).toString().padStart(2, '0');
        const secs = (seconds % 60).toString().padStart(2, '0');
        timer.innerText = `${mins}:${secs}`;
    }, 1000);
}

// Wait for the ESM module to set window.Vapi (fires 'vapi-ready' event)
function waitForVapiSDK(timeoutMs = 8000) {
    if (typeof window.Vapi === 'function') return Promise.resolve(true);
    return new Promise((resolve) => {
        const onReady = () => { window.removeEventListener('vapi-ready', onReady); resolve(true); };
        window.addEventListener('vapi-ready', onReady);
        setTimeout(() => { window.removeEventListener('vapi-ready', onReady); resolve(false); }, timeoutMs);
    });
}

// --- VAPI web call ---
async function startVapiCall() {
    try {
        const [configRes, sdkReady] = await Promise.all([
            fetch(`/api/vapi-config?session_id=${sessionId}`),
            waitForVapiSDK()
        ]);
        const config = await configRes.json();

        if (!config.configured || !config.public_key) {
            if (callActivityLabel) callActivityLabel.innerText = 'VAPI key not configured — demo mode.';
            console.warn('[VAPI] public key not set on server — running demo mode');
            setTimeout(() => invokeCallEndSim(), 5000);
            return;
        }

        if (!sdkReady || typeof window.Vapi !== 'function') {
            if (callActivityLabel) callActivityLabel.innerText = 'VAPI SDK failed to load — check network.';
            console.error('[VAPI] window.Vapi is not available after waiting');
            setTimeout(() => invokeCallEndSim(), 3000);
            return;
        }

        if (callActivityLabel) callActivityLabel.innerText = 'Requesting microphone...';
        vapiConfigured = true;
        vapiInstance = new window.Vapi(config.public_key);
        console.log('[VAPI] initialised with public key', config.public_key.slice(0, 8) + '...');

        vapiInstance.on('call-start', () => {
            if (callActivityLabel) callActivityLabel.innerText = 'Connected. Speak clearly.';
        });

        vapiInstance.on('speech-start', () => {
            if (callActivityLabel) callActivityLabel.innerText = 'Agent speaking...';
        });

        vapiInstance.on('speech-end', () => {
            if (callActivityLabel) callActivityLabel.innerText = 'Your turn to speak.';
        });

        vapiInstance.on('call-end', () => {
            clearInterval(callInterval);
            invokeCallEndSim();
        });

        vapiInstance.on('error', (err) => {
            console.error('VAPI error:', err);
            if (callActivityLabel) callActivityLabel.innerText = 'Call error — ending session.';
            clearInterval(callInterval);
            setTimeout(() => invokeCallEndSim(), 2000);
        });

        if (callActivityLabel) callActivityLabel.innerText = 'Connecting to VAPI...';
        // Prefer a pre-built assistant ID (more reliable); fall back to inline config
        const startArg = config.assistant_id || config.assistant;
        console.log('[VAPI] calling start() with', config.assistant_id ? `assistant_id: ${config.assistant_id}` : 'inline config', config.assistant);
        const timeout = new Promise((_, reject) =>
            setTimeout(() => reject(new Error('VAPI connection timed out after 15s')), 15000)
        );
        await Promise.race([vapiInstance.start(startArg), timeout]);
        console.log('[VAPI] start() resolved');

    } catch (err) {
        console.error('[VAPI] Failed to start call:', err);
        if (callActivityLabel) callActivityLabel.innerText = 'Could not connect — ending session.';
        clearInterval(callInterval);
        setTimeout(() => invokeCallEndSim(), 2000);
    }
}

function stopVapiCall() {
    clearInterval(callInterval);
    if (vapiInstance && vapiConfigured) {
        try { vapiInstance.stop(); } catch (_) {}
    }
}

async function invokeCallEndSim() {
    voiceUI.classList.add('hidden');
    chatUI.style.filter = "none";
    chatUI.style.opacity = "1";

    appendSystemMessage("Voice Call Ended.");
    appendSystemMessage("Agent 3 (Final Notice) is joining the chat...");
    showTyping();

    await fetch('/api/simulate-call-end', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ session_id: sessionId, message: "", phase: 2 })
    });

    setTimeout(() => {
        sendBackendInitAgent3();
    }, 2000);
}

async function sendBackendInitAgent3() {
    try {
        currentPhase = 3;
        const res = await fetch('/api/chat', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            // Trigger Agent 3 to read handoff and respond immediately
            body: JSON.stringify({ session_id: sessionId, message: "Hello? Are you still there?", phase: 3 })
        });
        
        const data = await res.json();
        hideTyping();
        appendMessage(data.reply, 'agent');
    } catch(err) {
        hideTyping();
        appendMessage("Network error during handover.", "agent");
    }
}
