const sessionId = Math.random().toString(36).substring(2, 15);
let currentPhase = 1; 

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

btnDecline.addEventListener('click', invokeCallEndSim);

btnAccept.addEventListener('click', () => {
    callControls.classList.add('hidden');
    callActiveUI.classList.remove('hidden');
    
    let seconds = 0;
    const timer = document.querySelector('.timer');
    window.callInterval = setInterval(() => {
        seconds++;
        const mins = Math.floor(seconds / 60).toString().padStart(2, '0');
        const secs = (seconds % 60).toString().padStart(2, '0');
        timer.innerText = `${mins}:${secs}`;
    }, 1000);
});

btnEnd.addEventListener('click', () => {
    clearInterval(window.callInterval);
    invokeCallEndSim();
});

async function invokeCallEndSim() {
    voiceUI.classList.add('hidden');
    chatUI.style.filter = "none";
    chatUI.style.opacity = "1";
    
    appendSystemMessage("Voice Call Ended."); 
    appendSystemMessage("Agent 3 (Final Notice) is joining the chat...");
    showTyping();

    // Notify backend
    await fetch('/api/simulate-call-end', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ session_id: sessionId, message: "", phase: 2 })
    });

    // Wait and trigger agent 3 response organically
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
