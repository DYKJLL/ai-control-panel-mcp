let ws = null;
let currentLoginAccountId = null;
let loginPollTimer = null;

function connectWebSocket() {
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
  ws = new WebSocket(protocol + '//' + location.host + '/ws');
  ws.onopen = () => addLog('info', 'WebSocket 已连接');
  ws.onmessage = e => { try { handleMsg(JSON.parse(e.data)); } catch(ex) {} };
  ws.onclose = () => { addLog('error', 'WebSocket 断开，5秒后重连...'); setTimeout(connectWebSocket, 5000); };
  ws.onerror = () => {};
}

function handleMsg(msg) {
  if (msg.type === 'state_change') updateDashboard(msg.data);
  else if (msg.type === 'login_complete') { addLog('success', '登录完成: ' + msg.data.service); loadAccounts(); }
}

function addLog(level, text) {
  const list = document.getElementById('logList');
  const item = document.createElement('div');
  item.className = 'log-item ' + level;
  item.textContent = '[' + new Date().toLocaleTimeString() + '] ' + text;
  list.prepend(item);
  list.querySelector('.empty')?.remove();
  while (list.children.length > 200) list.removeChild(list.lastChild);
}

async function api(path, opts) {
  const r = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...opts });
  return r.json();
}

async function loadAccounts() {
  const data = await api('/api/call/list_accounts');
  const list = document.getElementById('accountList');
  if (!data.success || !data.result || !data.result.length) {
    list.innerHTML = '<div class="empty">暂无账号</div>';
    return;
  }
  list.innerHTML = data.result.map(a => {
    const statusMap = { active:'在线', inactive:'离线', logging_in:'登录中' };
    const svc = (a.service || '').toLowerCase();
    let iconClass = 'custom';
    let iconText = svc.charAt(0).toUpperCase();
    if (svc.includes('doubao') || svc.includes('豆包')) { iconClass = 'doubao'; iconText = '豆'; }
    else if (svc.includes('qianwen') || svc.includes('千问')) { iconClass = 'qianwen'; iconText = '千'; }
    return '<div class="account-item">'
      + '<div class="icon ' + iconClass + '">' + iconText + '</div>'
      + '<div class="info"><div class="name">' + esc(a.label) + '</div>'
      + '<div class="meta">' + (a.service || '') + ' · ' + (a.has_cookies ? '已登录' : '未登录') + '</div></div>'
      + '<span class="account-status ' + a.status + '">' + statusMap[a.status] + '</span>'
      + '<div class="account-actions">'
      + '<button class="btn-sm" onclick="openAcc(\'' + a.id + '\')">详情</button>'
      + '<button class="btn-sm" style="border-color:var(--red);color:var(--red)" onclick="delAcc(\'' + a.id + '\')">删除</button>'
      + '</div>'
      + '</div>';
  }).join('');
}

function esc(s) { return String(s).replace(/[&<>"]/g, function(m) { return { '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;' }[m]; }); }

async function loadQueueStatus() {
  const data = await api('/api/queue/status');
  if (data.total === undefined) return;
  document.getElementById('totalTasks').textContent = data.total;
  document.getElementById('pendingTasks').textContent = data.pending || 0;
  document.getElementById('runningTasks').textContent = data.running || 0;
  document.getElementById('completedTasks').textContent = data.completed || 0;
  document.getElementById('failedTasks').textContent = data.failed || 0;
  document.getElementById('queueStatus').textContent = (data.running || 0) + ' / ' + (data.total || 0);
}

async function loadProxyStatus() {
  const data = await api('/api/call/get_proxy_status');
  const info = document.getElementById('proxyInfo');
  if (data.success && data.result) {
    const p = data.result;
    info.innerHTML = '<div style="margin-bottom:4px">模式: <strong>' + (p.current || '未设置') + '</strong></div>'
      + '<div>状态: ' + (p.providers ? Object.values(p.providers).map(v => v.alive ? '<span style="color:#3fb950">\u25CF</span> 在线' : '<span style="color:#f85149">\u25CF</span> 离线').join(' ') : '检测中...') + '</div>';
    document.getElementById('proxyStatus').textContent = p.current || '未设置';
  }
}

async function switchProxy() {
  const mode = document.getElementById('proxyModeSelect').value;
  await api('/api/call/switch_proxy', { method: 'POST', body: JSON.stringify({ mode }) });
  addLog('info', '切换代理: ' + mode);
  loadProxyStatus();
}

async function callFunction() {
  const sel = document.getElementById('fnSelect');
  const paramsText = document.getElementById('fnParams').value;
  const name = sel.value;
  if (!name) { addLog('error', '请选择函数'); return; }
  let params = {};
  if (paramsText.trim()) { try { params = JSON.parse(paramsText); } catch(e) { addLog('error', '参数 JSON 格式错误'); return; } }
  sendWS({ action: 'call', name, params });
  const result = await api('/api/call/' + name, { method: 'POST', body: JSON.stringify(params) });
  document.getElementById('fnResult').textContent = JSON.stringify(result, null, 2);
}

function sendWS(data) { if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(data)); }

function updateDashboard(state) {
  if (!state.queue) return;
  document.getElementById('totalTasks').textContent = state.queue.total || 0;
  document.getElementById('pendingTasks').textContent = state.queue.pending || 0;
  document.getElementById('runningTasks').textContent = state.queue.running || 0;
  document.getElementById('completedTasks').textContent = state.queue.completed || 0;
  document.getElementById('failedTasks').textContent = state.queue.failed || 0;
}

async function startLogin() {
  const service = document.getElementById('accService').value.trim() || 'custom';
  const label = document.getElementById('accLabel').value.trim() || service;
  const url = document.getElementById('accUrl').value.trim();
  if (!url) { addLog('error', '请输入网址'); return; }
  const btn = document.getElementById('btnStartLogin');
  btn.disabled = true; btn.textContent = '打开中...';
  const result = await api('/api/account/start-login', { method: 'POST', body: JSON.stringify({ service, label, url }) });
  btn.disabled = false; btn.textContent = '打开浏览器并登录';
  if (result.success) {
    currentLoginAccountId = result.account_id;
    document.getElementById('loginProgress').style.display = 'block';
    document.getElementById('loginStatus').textContent = '浏览器已打开，请在浏览器中完成登录...';
    addLog('info', '浏览器已打开: ' + url);
    startLoginPolling();
  } else {
    addLog('error', '打开浏览器失败: ' + (result.error || ''));
  }
}

function startLoginPolling() {
  if (loginPollTimer) clearInterval(loginPollTimer);
  loginPollTimer = setInterval(async () => {
    if (!currentLoginAccountId) { clearInterval(loginPollTimer); return; }
    const data = await api('/api/account/login-status/' + currentLoginAccountId);
    if (data.status === 'active') {
      clearInterval(loginPollTimer);
      document.getElementById('loginProgress').style.display = 'none';
      currentLoginAccountId = null;
      addLog('success', '登录信息已捕获保存');
      loadAccounts();
    }
  }, 2000);
}

async function confirmLogin() {
  if (!currentLoginAccountId) { addLog('error', '没有进行中的登录'); return; }
  addLog('info', '正在捕获登录信息...');
  const result = await api('/api/account/capture-login', { method: 'POST', body: JSON.stringify({ account_id: currentLoginAccountId }) });
  if (result.success) {
    document.getElementById('loginProgress').style.display = 'none';
    if (loginPollTimer) clearInterval(loginPollTimer);
    addLog('success', '登录信息已保存');
    currentLoginAccountId = null;
    loadAccounts();
  } else {
    addLog('error', '捕获失败: ' + (result.error || ''));
  }
}

async function cancelLogin() {
  if (!currentLoginAccountId) return;
  await api('/api/account/cancel-login', { method: 'POST', body: JSON.stringify({ account_id: currentLoginAccountId }) });
  document.getElementById('loginProgress').style.display = 'none';
  if (loginPollTimer) clearInterval(loginPollTimer);
  currentLoginAccountId = null;
  addLog('info', '登录已取消');
  loadAccounts();
}

async function openAcc(id) {
  const r = await api('/api/account/open-browser', { method: 'POST', body: JSON.stringify({ account_id: id }) });
  if (!r.success) { addLog('error', '打开失败: ' + (r.error || '')); return; }
  addLog('success', '已打开账号页面');
  // 自动点击"新对话"进入聊天页
  setTimeout(async () => {
    const r2 = await api('/api/call/browser_click', { method: 'POST', body: JSON.stringify({ text: '新对话' }) });
    if (r2.success) addLog('info', '已进入新对话');
  }, 4000);
}

async function delAcc(id) {
  if (!confirm('确认删除此账号？')) return;
  const r = await api('/api/account/delete', { method: 'POST', body: JSON.stringify({ account_id: id }) });
  if (r.success) { addLog('info', '账号已删除'); loadAccounts(); }
  else addLog('error', '删除失败: ' + (r.error || ''));
}

async function loadFunctions() {
  const data = await api('/api/functions');
  const sel = document.getElementById('fnSelect');
  sel.innerHTML = '<option value="">选择函数...</option>';
  (data.functions || []).forEach(function(fn) {
    var opt = document.createElement('option');
    opt.value = fn.name;
    opt.textContent = fn.name + (fn.description ? ' - ' + fn.description : '');
    sel.appendChild(opt);
  });
  addLog('info', '加载了 ' + (data.functions || []).length + ' 个函数');
}

connectWebSocket();
loadFunctions();
loadQueueStatus();
loadProxyStatus();
loadAccounts();
setInterval(loadQueueStatus, 3000);
setInterval(loadProxyStatus, 10000);
