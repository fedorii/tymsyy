'use strict';

/* ── State ─────────────────────────────────────────── */
let currentChatId = null;
let ws = null;
const isMobile = () => window.innerWidth <= 640;

/* ── DOM refs ──────────────────────────────────────── */
const sidebar      = document.getElementById('sidebar');
const chatList     = document.getElementById('chatList');
const chatPlaceholder = document.getElementById('chatPlaceholder');
const chatView     = document.getElementById('chatView');
const messagesEl   = document.getElementById('messages');
const topbarName   = document.getElementById('topbarName');
const topbarSub    = document.getElementById('topbarSub');
const msgInput     = document.getElementById('msgInput');
const sendBtn      = document.getElementById('sendBtn');
const backBtn      = document.getElementById('backBtn');

/* ── Chat list click ───────────────────────────────── */
chatList.addEventListener('click', e => {
  const item = e.target.closest('.chat-item');
  if (!item) return;
  const id = Number(item.dataset.id);
  openChat(id);
  document.querySelectorAll('.chat-item').forEach(el => el.classList.remove('active'));
  item.classList.add('active');
});

/* ── Open chat ─────────────────────────────────────── */
async function openChat(chatId) {
  if (currentChatId === chatId) return;
  currentChatId = chatId;

  // mobile: show chat area
  if (isMobile()) {
    sidebar.classList.add('hidden-mobile');
  }

  chatPlaceholder.classList.add('hidden');
  chatView.classList.remove('hidden');
  messagesEl.innerHTML = '';
  topbarSub.textContent = '';

  // fetch info
  const info = await apiFetch(`/api/chats/${chatId}/info`);
  if (!info) return;
  topbarName.textContent = info.title;
  if (info.is_group) {
    topbarSub.textContent = info.members.map(m => m.username).join(', ');
  }

  // fetch history
  const msgs = await apiFetch(`/api/chats/${chatId}/messages`);
  if (msgs) msgs.forEach(appendMessage);
  scrollBottom();

  // WebSocket
  if (ws) ws.close();
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws/${chatId}/${TOKEN}`);
  ws.onmessage = e => {
    const msg = JSON.parse(e.data);
    // avoid duplicates from history
    if (!document.querySelector(`[data-msg-id="${msg.id}"]`)) {
      appendMessage(msg);
      scrollBottom();
      refreshChatList();
    }
  };
  ws.onerror = () => console.warn('WS error');
}

/* ── Append message ────────────────────────────────── */
function appendMessage(msg) {
  const mine = msg.sender_id === CURRENT_USER_ID;
  const div = document.createElement('div');
  div.className = `msg ${mine ? 'mine' : 'theirs'}`;
  div.dataset.msgId = msg.id;

  const time = new Date(msg.created_at).toLocaleTimeString('ru', {hour:'2-digit', minute:'2-digit'});
  const meta = mine ? time : `${msg.sender} · ${time}`;

  div.innerHTML = `
    <div class="msg-meta">${meta}</div>
    <div class="msg-bubble">${escapeHtml(msg.text)}</div>
  `;
  messagesEl.appendChild(div);
}

function scrollBottom() {
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

/* ── Send ──────────────────────────────────────────── */
function sendMessage() {
  const text = msgInput.value.trim();
  if (!text || !ws || ws.readyState !== WebSocket.OPEN) return;
  ws.send(JSON.stringify({text}));
  msgInput.value = '';
  msgInput.style.height = 'auto';
}

sendBtn.addEventListener('click', sendMessage);

msgInput.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});

// auto-resize textarea
msgInput.addEventListener('input', () => {
  msgInput.style.height = 'auto';
  msgInput.style.height = Math.min(msgInput.scrollHeight, 120) + 'px';
});

/* ── Back button (mobile) ──────────────────────────── */
backBtn.addEventListener('click', () => {
  sidebar.classList.remove('hidden-mobile');
  chatView.classList.add('hidden');
  chatPlaceholder.classList.remove('hidden');
  if (ws) { ws.close(); ws = null; }
  currentChatId = null;
  document.querySelectorAll('.chat-item').forEach(el => el.classList.remove('active'));
});

/* ── Modals ────────────────────────────────────────── */
document.getElementById('btnNewPrivate').addEventListener('click', () => {
  showModal('modalPrivate');
});

document.getElementById('btnNewGroup').addEventListener('click', () => {
  showModal('modalGroup');
});

document.querySelectorAll('.modal-close').forEach(btn => {
  btn.addEventListener('click', () => hideModal(btn.dataset.modal));
});

document.querySelectorAll('.modal-overlay').forEach(overlay => {
  overlay.addEventListener('click', e => {
    if (e.target === overlay) hideModal(overlay.id);
  });
});

function showModal(id) { document.getElementById(id).classList.remove('hidden'); }
function hideModal(id) { document.getElementById(id).classList.add('hidden'); }

/* ── Search users filter ───────────────────────────── */
document.getElementById('searchUser').addEventListener('input', e => {
  const q = e.target.value.toLowerCase();
  document.querySelectorAll('#userList .user-item').forEach(li => {
    li.style.display = li.textContent.toLowerCase().includes(q) ? '' : 'none';
  });
});

/* ── Private chat: click user ──────────────────────── */
document.getElementById('userList').addEventListener('click', async e => {
  const item = e.target.closest('.user-item');
  if (!item) return;
  hideModal('modalPrivate');
  const userId = Number(item.dataset.id);
  const res = await apiFetch(`/api/chats/private/${userId}`, {method:'POST'});
  if (res) {
    await refreshChatList();
    openChatById(res.chat_id);
  }
});

/* ── Group chat: select members ────────────────────── */
document.getElementById('groupUserList').addEventListener('click', e => {
  const item = e.target.closest('.user-item.selectable');
  if (!item) return;
  item.classList.toggle('selected');
});

document.getElementById('createGroupBtn').addEventListener('click', async () => {
  const name = document.getElementById('groupName').value.trim();
  if (!name) { alert('Укажите название группы'); return; }
  const selected = [...document.querySelectorAll('#groupUserList .user-item.selected')];
  const members = selected.map(el => Number(el.dataset.id));
  const res = await apiFetch('/api/chats/group', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({name, members}),
  });
  if (res) {
    hideModal('modalGroup');
    document.getElementById('groupName').value = '';
    document.querySelectorAll('#groupUserList .user-item').forEach(el => el.classList.remove('selected'));
    await refreshChatList();
    openChatById(res.chat_id);
  }
});

/* ── Helpers ───────────────────────────────────────── */
async function apiFetch(url, opts = {}) {
  try {
    const r = await fetch(url, opts);
    if (!r.ok) return null;
    return await r.json();
  } catch { return null; }
}

function escapeHtml(str) {
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
            .replace(/"/g,'&quot;').replace(/'/g,'&#039;').replace(/\n/g,'<br>');
}

async function refreshChatList() {
  // reload page to refresh sidebar list
  const r = await fetch('/chats');
  const html = await r.text();
  const parser = new DOMParser();
  const doc = parser.parseFromString(html, 'text/html');
  const newList = doc.getElementById('chatList');
  if (newList) {
    chatList.innerHTML = newList.innerHTML;
    // rebind is automatic because we use event delegation
  }
}

function openChatById(chatId) {
  const item = chatList.querySelector(`.chat-item[data-id="${chatId}"]`);
  if (item) {
    document.querySelectorAll('.chat-item').forEach(el => el.classList.remove('active'));
    item.classList.add('active');
  }
  openChat(chatId);
}

/* ── Auto-open first chat on desktop ───────────────── */
if (!isMobile()) {
  const first = chatList.querySelector('.chat-item');
  if (first) openChat(Number(first.dataset.id));
}