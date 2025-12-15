"""
Hyperdrive Dashboard - Local control panel for VPS management
"""

import os
import json
import httpx
from datetime import datetime
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

from vps_manager import VPSManager

load_dotenv()

app = FastAPI(title="Hyperdrive Dashboard")
vps = VPSManager()

VPS_API_URL = os.getenv("VPS_API_URL", "http://localhost:3000")


# ==================== API ENDPOINTS ====================

@app.get("/api/health")
async def health():
    """Dashboard health check."""
    return {"status": "ok", "vps_host": vps.host}


@app.get("/api/containers")
async def list_containers():
    """List all containers on VPS."""
    try:
        containers = vps.get_all_containers()
        return {"containers": containers}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/workers")
async def list_workers():
    """List worker containers and their VPN status."""
    try:
        workers = vps.list_workers()
        # Enrich with VPN status
        for w in workers:
            worker_num = w["name"].replace("worker-", "")
            w["vpn"] = vps.get_worker_vpn_status(worker_num)
        return {"workers": workers}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/workers/{worker_id}/restart")
async def restart_worker(worker_id: str):
    """Restart a worker."""
    try:
        success, msg = vps.restart_worker(worker_id)
        return {"success": success, "message": msg}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/workers/{worker_id}/stop")
async def stop_worker(worker_id: str):
    """Stop a worker."""
    try:
        success, msg = vps.stop_worker(worker_id)
        return {"success": success, "message": msg}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/workers/{worker_id}/logs")
async def get_worker_logs(worker_id: str, lines: int = 100):
    """Get worker logs."""
    try:
        logs = vps.get_worker_logs(worker_id, lines)
        return {"logs": logs}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/workers/new")
async def spin_up_new_worker(worker_num: int):
    """Spin up a new worker with Nitter and Redis."""
    try:
        success, msg = vps.spin_up_worker(worker_num)
        return {"success": success, "message": msg}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/nitters")
async def list_nitters():
    """List Nitter containers."""
    try:
        nitters = vps.list_nitters()
        return {"nitters": nitters}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/nitters/{nitter_id}/restart")
async def restart_nitter(nitter_id: str):
    """Restart a Nitter instance."""
    try:
        success, msg = vps.restart_nitter(nitter_id)
        return {"success": success, "message": msg}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/nitters/{nitter_id}/flush")
async def flush_nitter_cache(nitter_id: str):
    """Flush Nitter's Redis cache."""
    try:
        success, msg = vps.flush_nitter_cache(nitter_id)
        return {"success": success, "message": msg}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/sessions")
async def get_sessions():
    """Get current session cookies."""
    try:
        sessions = vps.get_sessions()
        return {"sessions": sessions}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/sessions")
async def update_sessions(sessions: str = Form(...)):
    """Update session cookies."""
    try:
        success, msg = vps.update_sessions(sessions)
        return {"success": success, "message": msg}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/jobs")
async def get_jobs():
    """Get jobs from VPS API."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{VPS_API_URL}/api/jobs", timeout=10)
            return resp.json()
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    """Get specific job details."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{VPS_API_URL}/api/jobs/{job_id}", timeout=10)
            return resp.json()
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/queue")
async def get_queue_stats():
    """Get queue statistics."""
    try:
        stats = vps.get_redis_queue_stats()
        return stats
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/system")
async def get_system_stats():
    """Get VPS system stats."""
    try:
        return {
            "disk": vps.get_disk_usage(),
            "memory": vps.get_memory_usage()
        }
    except Exception as e:
        raise HTTPException(500, str(e))


# ==================== HTML DASHBOARD ====================

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Hyperdrive Dashboard</title>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-dark: #0a0a0f;
            --bg-panel: #12121a;
            --border: #2a2a3a;
            --text: #e0e0e0;
            --text-dim: #888;
            --accent: #00d4aa;
            --accent-dim: rgba(0, 212, 170, 0.1);
            --danger: #ff4757;
            --warning: #ffa502;
            --success: #2ed573;
        }
        
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        body {
            font-family: 'Inter', sans-serif;
            background: var(--bg-dark);
            color: var(--text);
            min-height: 100vh;
        }
        
        .header {
            background: var(--bg-panel);
            border-bottom: 1px solid var(--border);
            padding: 1rem 2rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .logo {
            font-family: 'JetBrains Mono', monospace;
            font-size: 1.5rem;
            font-weight: 700;
            color: var(--accent);
        }
        
        .status-bar {
            display: flex;
            gap: 2rem;
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.8rem;
        }
        
        .status-item {
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }
        
        .status-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: var(--success);
        }
        
        .status-dot.warning { background: var(--warning); }
        .status-dot.danger { background: var(--danger); }
        
        .main {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 1.5rem;
            padding: 1.5rem;
            max-width: 1600px;
            margin: 0 auto;
        }
        
        .panel {
            background: var(--bg-panel);
            border: 1px solid var(--border);
            border-radius: 8px;
            overflow: hidden;
        }
        
        .panel-header {
            padding: 1rem;
            border-bottom: 1px solid var(--border);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .panel-title {
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.9rem;
            text-transform: uppercase;
            letter-spacing: 0.1em;
            color: var(--accent);
        }
        
        .panel-body {
            padding: 1rem;
            max-height: 400px;
            overflow-y: auto;
        }
        
        .item-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 0.75rem;
            border-bottom: 1px solid var(--border);
        }
        
        .item-row:last-child { border-bottom: none; }
        
        .item-name {
            font-family: 'JetBrains Mono', monospace;
            font-weight: 600;
        }
        
        .item-status {
            font-size: 0.8rem;
            color: var(--text-dim);
        }
        
        .item-actions {
            display: flex;
            gap: 0.5rem;
        }
        
        .btn {
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.7rem;
            padding: 0.4rem 0.8rem;
            border: 1px solid var(--border);
            background: transparent;
            color: var(--text);
            cursor: pointer;
            border-radius: 4px;
            transition: all 0.2s;
        }
        
        .btn:hover {
            background: var(--accent-dim);
            border-color: var(--accent);
            color: var(--accent);
        }
        
        .btn.danger:hover {
            background: rgba(255, 71, 87, 0.1);
            border-color: var(--danger);
            color: var(--danger);
        }
        
        .btn.primary {
            background: var(--accent);
            color: var(--bg-dark);
            border-color: var(--accent);
        }
        
        .btn.primary:hover {
            background: #00b894;
        }
        
        .tag {
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.7rem;
            padding: 0.2rem 0.5rem;
            border-radius: 3px;
            text-transform: uppercase;
        }
        
        .tag.healthy { background: rgba(46, 213, 115, 0.2); color: var(--success); }
        .tag.unhealthy { background: rgba(255, 71, 87, 0.2); color: var(--danger); }
        .tag.running { background: rgba(0, 212, 170, 0.2); color: var(--accent); }
        .tag.idle { background: rgba(136, 136, 136, 0.2); color: var(--text-dim); }
        .tag.busy { background: rgba(255, 165, 2, 0.2); color: var(--warning); }
        
        .logs-panel {
            grid-column: span 2;
        }
        
        .logs-content {
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.75rem;
            background: #000;
            padding: 1rem;
            max-height: 300px;
            overflow-y: auto;
            white-space: pre-wrap;
            color: #0f0;
        }
        
        .job-card {
            padding: 0.75rem;
            border: 1px solid var(--border);
            border-radius: 4px;
            margin-bottom: 0.5rem;
        }
        
        .job-header {
            display: flex;
            justify-content: space-between;
            margin-bottom: 0.5rem;
        }
        
        .job-user {
            font-family: 'JetBrains Mono', monospace;
            font-weight: 600;
        }
        
        .job-progress {
            height: 4px;
            background: var(--border);
            border-radius: 2px;
            overflow: hidden;
        }
        
        .job-progress-fill {
            height: 100%;
            background: var(--accent);
            transition: width 0.3s;
        }
        
        .modal {
            display: none;
            position: fixed;
            top: 0; left: 0;
            width: 100%; height: 100%;
            background: rgba(0,0,0,0.8);
            z-index: 1000;
            justify-content: center;
            align-items: center;
        }
        
        .modal.active { display: flex; }
        
        .modal-content {
            background: var(--bg-panel);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 2rem;
            max-width: 600px;
            width: 90%;
        }
        
        .modal-title {
            font-family: 'JetBrains Mono', monospace;
            margin-bottom: 1rem;
            color: var(--accent);
        }
        
        textarea {
            width: 100%;
            min-height: 200px;
            background: #000;
            border: 1px solid var(--border);
            color: var(--text);
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.8rem;
            padding: 1rem;
            margin-bottom: 1rem;
        }
        
        .modal-actions {
            display: flex;
            gap: 1rem;
            justify-content: flex-end;
        }
        
        .refresh-btn {
            background: none;
            border: none;
            color: var(--text-dim);
            cursor: pointer;
            font-size: 1.2rem;
        }
        
        .refresh-btn:hover { color: var(--accent); }
        
        @keyframes spin {
            to { transform: rotate(360deg); }
        }
        
        .spinning { animation: spin 1s linear infinite; }
    </style>
</head>
<body>
    <header class="header">
        <div class="logo">⚡ HYPERDRIVE</div>
        <div class="status-bar">
            <div class="status-item">
                <div class="status-dot" id="vpsStatus"></div>
                <span id="vpsHost">Connecting...</span>
            </div>
            <div class="status-item">
                <span>Disk: <span id="diskUsage">--</span></span>
            </div>
            <div class="status-item">
                <span>Memory: <span id="memUsage">--</span></span>
            </div>
        </div>
    </header>
    
    <main class="main">
        <!-- Workers Panel -->
        <div class="panel">
            <div class="panel-header">
                <span class="panel-title">Workers</span>
                <div>
                    <button class="btn primary" onclick="showNewWorkerModal()">+ New Worker</button>
                    <button class="refresh-btn" onclick="refreshWorkers()">🔄</button>
                </div>
            </div>
            <div class="panel-body" id="workersList">
                <div class="item-row"><span class="item-status">Loading...</span></div>
            </div>
        </div>
        
        <!-- Nitter Panel -->
        <div class="panel">
            <div class="panel-header">
                <span class="panel-title">Nitter Instances</span>
                <button class="refresh-btn" onclick="refreshNitters()">🔄</button>
            </div>
            <div class="panel-body" id="nittersList">
                <div class="item-row"><span class="item-status">Loading...</span></div>
            </div>
        </div>
        
        <!-- Jobs Panel -->
        <div class="panel">
            <div class="panel-header">
                <span class="panel-title">Jobs</span>
                <div>
                    <span id="queueStats" style="font-size:0.8rem;color:var(--text-dim);margin-right:1rem;"></span>
                    <button class="refresh-btn" onclick="refreshJobs()">🔄</button>
                </div>
            </div>
            <div class="panel-body" id="jobsList">
                <div class="item-row"><span class="item-status">Loading...</span></div>
            </div>
        </div>
        
        <!-- Sessions Panel -->
        <div class="panel">
            <div class="panel-header">
                <span class="panel-title">Session Cookies</span>
                <button class="btn" onclick="showSessionsModal()">Edit Sessions</button>
            </div>
            <div class="panel-body" id="sessionsList">
                <div class="item-row"><span class="item-status">Click "Edit Sessions" to view/update</span></div>
            </div>
        </div>
        
        <!-- Logs Panel -->
        <div class="panel logs-panel">
            <div class="panel-header">
                <span class="panel-title">Worker Logs</span>
                <select id="logWorkerSelect" onchange="refreshLogs()" style="background:var(--bg-dark);color:var(--text);border:1px solid var(--border);padding:0.3rem;">
                    <option value="">Select worker...</option>
                </select>
            </div>
            <div class="logs-content" id="logsContent">Select a worker to view logs...</div>
        </div>
    </main>
    
    <!-- New Worker Modal -->
    <div class="modal" id="newWorkerModal">
        <div class="modal-content">
            <h3 class="modal-title">Spin Up New Worker</h3>
            <p style="margin-bottom:1rem;color:var(--text-dim);">This will create a new worker with its own Nitter and Redis instances.</p>
            <div style="margin-bottom:1rem;">
                <label style="display:block;margin-bottom:0.5rem;">Worker Number:</label>
                <input type="number" id="newWorkerNum" min="1" max="10" value="3" style="background:var(--bg-dark);border:1px solid var(--border);color:var(--text);padding:0.5rem;width:100px;">
            </div>
            <div class="modal-actions">
                <button class="btn" onclick="closeModal('newWorkerModal')">Cancel</button>
                <button class="btn primary" onclick="spinUpWorker()">Create Worker</button>
            </div>
        </div>
    </div>
    
    <!-- Sessions Modal -->
    <div class="modal" id="sessionsModal">
        <div class="modal-content">
            <h3 class="modal-title">Edit Session Cookies</h3>
            <textarea id="sessionsTextarea" placeholder="Loading sessions..."></textarea>
            <div class="modal-actions">
                <button class="btn" onclick="closeModal('sessionsModal')">Cancel</button>
                <button class="btn primary" onclick="saveSessions()">Save & Restart Nitters</button>
            </div>
        </div>
    </div>

    <script>
        // API calls
        async function api(endpoint, method = 'GET', body = null) {
            const opts = { method, headers: {} };
            if (body) {
                if (body instanceof FormData) {
                    opts.body = body;
                } else {
                    opts.headers['Content-Type'] = 'application/json';
                    opts.body = JSON.stringify(body);
                }
            }
            const resp = await fetch(endpoint, opts);
            return resp.json();
        }
        
        // Refresh functions
        async function refreshWorkers() {
            try {
                const data = await api('/api/workers');
                const container = document.getElementById('workersList');
                if (!data.workers || data.workers.length === 0) {
                    container.innerHTML = '<div class="item-row"><span class="item-status">No workers running</span></div>';
                    return;
                }
                container.innerHTML = data.workers.map(w => {
                    const vpnStatus = w.vpn?.connected ? 
                        `<span class="tag running">VPN: ${w.vpn.location || 'Connected'}</span>` : 
                        '<span class="tag unhealthy">VPN: Disconnected</span>';
                    return `
                        <div class="item-row">
                            <div>
                                <div class="item-name">${w.name}</div>
                                <div class="item-status">${w.status}</div>
                            </div>
                            <div style="display:flex;gap:0.5rem;align-items:center;">
                                ${vpnStatus}
                                <button class="btn" onclick="restartWorker('${w.name.replace('worker-', '')}')">Restart</button>
                                <button class="btn danger" onclick="stopWorker('${w.name.replace('worker-', '')}')">Stop</button>
                            </div>
                        </div>
                    `;
                }).join('');
                
                // Update log selector
                const select = document.getElementById('logWorkerSelect');
                const current = select.value;
                select.innerHTML = '<option value="">Select worker...</option>' + 
                    data.workers.map(w => `<option value="${w.name.replace('worker-', '')}">${w.name}</option>`).join('');
                select.value = current;
            } catch (e) {
                console.error('Failed to refresh workers:', e);
            }
        }
        
        async function refreshNitters() {
            try {
                const data = await api('/api/nitters');
                const container = document.getElementById('nittersList');
                if (!data.nitters || data.nitters.length === 0) {
                    container.innerHTML = '<div class="item-row"><span class="item-status">No Nitter instances</span></div>';
                    return;
                }
                container.innerHTML = data.nitters.map(n => {
                    const healthy = n.status.includes('healthy') && !n.status.includes('unhealthy');
                    return `
                        <div class="item-row">
                            <div>
                                <div class="item-name">${n.name}</div>
                                <div class="item-status">${n.ports || 'No ports'}</div>
                            </div>
                            <div style="display:flex;gap:0.5rem;align-items:center;">
                                <span class="tag ${healthy ? 'healthy' : 'unhealthy'}">${healthy ? 'Healthy' : 'Unhealthy'}</span>
                                <button class="btn" onclick="restartNitter('${n.name.replace('nitter-', '')}')">Restart</button>
                                <button class="btn" onclick="flushNitter('${n.name.replace('nitter-', '')}')">Flush Cache</button>
                            </div>
                        </div>
                    `;
                }).join('');
            } catch (e) {
                console.error('Failed to refresh nitters:', e);
            }
        }
        
        async function refreshJobs() {
            try {
                const data = await api('/api/jobs');
                const container = document.getElementById('jobsList');
                
                // Queue stats
                const queue = await api('/api/queue');
                document.getElementById('queueStats').textContent = 
                    `Pending: ${queue.pending_jobs || 0} | Total: ${queue.total_jobs || 0}`;
                
                if (!data.jobs || data.jobs.length === 0) {
                    container.innerHTML = '<div class="item-row"><span class="item-status">No jobs</span></div>';
                    return;
                }
                container.innerHTML = data.jobs.slice(0, 10).map(j => {
                    const statusClass = j.status === 'completed' ? 'healthy' : 
                                       j.status === 'running' ? 'busy' : 
                                       j.status === 'failed' ? 'unhealthy' : 'idle';
                    return `
                        <div class="job-card">
                            <div class="job-header">
                                <span class="job-user">@${j.username}</span>
                                <span class="tag ${statusClass}">${j.status}</span>
                            </div>
                            <div class="item-status">${j.current_step || j.status}</div>
                            <div class="job-progress">
                                <div class="job-progress-fill" style="width: ${j.progress || 0}%"></div>
                            </div>
                        </div>
                    `;
                }).join('');
            } catch (e) {
                console.error('Failed to refresh jobs:', e);
            }
        }
        
        async function refreshLogs() {
            const workerId = document.getElementById('logWorkerSelect').value;
            if (!workerId) return;
            try {
                const data = await api(`/api/workers/${workerId}/logs?lines=100`);
                document.getElementById('logsContent').textContent = data.logs || 'No logs available';
            } catch (e) {
                document.getElementById('logsContent').textContent = 'Error loading logs: ' + e.message;
            }
        }
        
        async function refreshSystem() {
            try {
                const data = await api('/api/system');
                document.getElementById('diskUsage').textContent = data.disk?.split(/\\s+/)[4] || '--';
                document.getElementById('memUsage').textContent = data.memory?.split(/\\s+/)[2] || '--';
                document.getElementById('vpsHost').textContent = 'VPS Connected';
                document.getElementById('vpsStatus').classList.remove('danger');
            } catch (e) {
                document.getElementById('vpsHost').textContent = 'VPS Disconnected';
                document.getElementById('vpsStatus').classList.add('danger');
            }
        }
        
        // Actions
        async function restartWorker(id) {
            if (!confirm(`Restart worker-${id}?`)) return;
            await api(`/api/workers/${id}/restart`, 'POST');
            setTimeout(refreshWorkers, 2000);
        }
        
        async function stopWorker(id) {
            if (!confirm(`Stop worker-${id}?`)) return;
            await api(`/api/workers/${id}/stop`, 'POST');
            setTimeout(refreshWorkers, 2000);
        }
        
        async function restartNitter(id) {
            if (!confirm(`Restart nitter-${id}?`)) return;
            await api(`/api/nitters/${id}/restart`, 'POST');
            setTimeout(refreshNitters, 2000);
        }
        
        async function flushNitter(id) {
            if (!confirm(`Flush cache for nitter-${id}?`)) return;
            await api(`/api/nitters/${id}/flush`, 'POST');
            alert('Cache flushed');
        }
        
        async function spinUpWorker() {
            const num = document.getElementById('newWorkerNum').value;
            if (!confirm(`Create worker-${num} with Nitter and Redis?`)) return;
            closeModal('newWorkerModal');
            const result = await api(`/api/workers/new?worker_num=${num}`, 'POST');
            alert(result.success ? 'Worker created!' : 'Error: ' + result.message);
            refreshWorkers();
            refreshNitters();
        }
        
        async function showSessionsModal() {
            document.getElementById('sessionsModal').classList.add('active');
            const data = await api('/api/sessions');
            document.getElementById('sessionsTextarea').value = data.sessions || '';
        }
        
        async function saveSessions() {
            const sessions = document.getElementById('sessionsTextarea').value;
            const formData = new FormData();
            formData.append('sessions', sessions);
            const result = await api('/api/sessions', 'POST', formData);
            alert(result.message);
            closeModal('sessionsModal');
        }
        
        function showNewWorkerModal() {
            document.getElementById('newWorkerModal').classList.add('active');
        }
        
        function closeModal(id) {
            document.getElementById(id).classList.remove('active');
        }
        
        // Initial load
        refreshWorkers();
        refreshNitters();
        refreshJobs();
        refreshSystem();
        
        // Auto refresh
        setInterval(refreshWorkers, 30000);
        setInterval(refreshJobs, 10000);
        setInterval(refreshSystem, 60000);
    </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Serve the dashboard UI."""
    return DASHBOARD_HTML


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8888)

