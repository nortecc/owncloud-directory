#!/usr/bin/env python3
"""
Web-Frontend für den OwnCloud Dateiverzeichnis-Generator.
Start: python3 app.py
Dann im Browser öffnen: http://localhost:5000
"""

import os
import sys
import io
import threading
import time
import json
from datetime import datetime
from flask import Flask, render_template_string, request, jsonify, send_file, Response

# Funktionen aus dem Haupt-Script importieren
# (Script muss im gleichen Ordner liegen)
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, script_dir)

try:
    from owncloud_verzeichnis import parse_share_id, fetch_recursive, build_pdf
    SCRIPT_AVAILABLE = True
except ImportError as e:
    SCRIPT_AVAILABLE = False
    IMPORT_ERROR = str(e)

app = Flask(__name__)

# ──────────────────────────────────────────────
# Fortschritt-Tracking (thread-safe)
# ──────────────────────────────────────────────
progress_store = {}
progress_lock = threading.Lock()

def set_progress(job_id, data):
    with progress_lock:
        progress_store[job_id] = data

def get_progress(job_id):
    with progress_lock:
        return progress_store.get(job_id, {})

# ──────────────────────────────────────────────
# HTML Template
# ──────────────────────────────────────────────
HTML = r"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Dateiverzeichnis Generator – nesseler bau</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap');

  :root {
    --ng-green: #43B02A;
    --ng-green-light: #e8f9d9;
    --ng-green-mid: #c5f080;
    --ng-blue: #2D4B9B;
    --bg: #f5f6f7;
    --surface: #ffffff;
    --surface2: #f0f1f3;
    --border: #e2e4e8;
    --border-focus: #4dc300;
    --text: #1a1c20;
    --muted: #6b7280;
    --hint: #9ca3af;
    --mono: 'JetBrains Mono', 'Courier New', monospace;
    --sans: 'Inter', system-ui, sans-serif;
    --radius: 10px;
    --shadow: 0 1px 3px rgba(0,0,0,0.08), 0 1px 2px rgba(0,0,0,0.04);
    --shadow-md: 0 4px 12px rgba(0,0,0,0.08), 0 2px 4px rgba(0,0,0,0.04);
  }

  * { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    font-family: var(--sans);
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
    font-size: 14px;
    line-height: 1.5;
  }

  /* ── Header ── */
  header {
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    padding: 0 2rem;
    height: 60px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    position: sticky;
    top: 0;
    z-index: 100;
    box-shadow: var(--shadow);
  }

  .logo-area { display: flex; align-items: center; gap: 12px; }

  .logo-box {
    width: 60px; height: 60px;
    background: var(--ng-green);
    border-radius: 8px;
    display: flex; align-items: center; justify-content: center;
    font-family: var(--mono);
    font-size: 20px; font-weight: 500;
    color: #fff;
    flex-shrink: 0;
  }

  .logo-label { line-height: 1.2; }
  .logo-label strong { display: block; font-size: 14px; font-weight: 600; color: var(--text); }
  .logo-label span { font-size: 11px; color: var(--muted); }

  .header-chip {
    font-family: var(--mono);
    font-size: 11px;
    color: var(--ng-green);
    background: var(--ng-green-light);
    border: 1px solid var(--ng-green-mid);
    padding: 3px 10px;
    border-radius: 20px;
    font-weight: 500;
  }

  /* ── Layout ── */
  main {
    max-width: 820px;
    margin: 0 auto;
    padding: 2.5rem 1.5rem;
  }

  .page-title {
    margin-bottom: 2rem;
  }
  .page-title h1 {
    font-size: 22px;
    font-weight: 600;
    color: var(--text);
    margin-bottom: 4px;
  }
  .page-title p {
    font-size: 13px;
    color: var(--muted);
    max-width: 500px;
    line-height: 1.6;
  }

  /* ── Card ── */
  .card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 1.5rem;
    margin-bottom: 1.25rem;
    box-shadow: var(--shadow);
  }

  .card-header {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 1.25rem;
    padding-bottom: 0.75rem;
    border-bottom: 1px solid var(--border);
  }

  .card-header-dot {
    width: 8px; height: 8px;
    background: var(--ng-green);
    border-radius: 50%;
    flex-shrink: 0;
  }

  .card-header-title {
    font-size: 12px;
    font-weight: 600;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }

  /* ── Form ── */
  .field { margin-bottom: 1rem; }

  label {
    display: block;
    font-size: 13px;
    font-weight: 500;
    color: var(--text);
    margin-bottom: 5px;
  }

  .label-opt {
    font-weight: 400;
    color: var(--hint);
    font-size: 12px;
    margin-left: 4px;
  }

  input[type="text"],
  input[type="password"] {
    width: 100%;
    background: var(--surface);
    border: 1.5px solid var(--border);
    color: var(--text);
    font-family: var(--sans);
    font-size: 14px;
    padding: 9px 12px;
    border-radius: 8px;
    outline: none;
    transition: border-color 0.15s, box-shadow 0.15s;
  }

  input:hover { border-color: #c5c8ce; }

  input:focus {
    border-color: var(--border-focus);
    box-shadow: 0 0 0 3px rgba(77,195,0,0.12);
  }

  input::placeholder { color: var(--hint); }

  .field-hint {
    font-size: 11px;
    color: var(--hint);
    margin-top: 4px;
  }

  .row {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1rem;
  }

  /* ── Buttons ── */
  .btn-primary {
    width: 100%;
    padding: 11px 16px;
    background: var(--ng-green);
    color: #fff;
    border: none;
    border-radius: 8px;
    font-family: var(--sans);
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.15s;
    margin-top: 0.5rem;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    box-shadow: 0 1px 3px rgba(77,195,0,0.3);
  }

  .btn-primary:hover { background: #44b000; box-shadow: 0 2px 6px rgba(77,195,0,0.35); }
  .btn-primary:active { transform: scale(0.99); }
  .btn-primary:disabled { opacity: 0.5; cursor: not-allowed; transform: none; box-shadow: none; }

  .btn-outline {
    flex: 1;
    padding: 10px 16px;
    background: transparent;
    color: var(--text);
    border: 1.5px solid var(--border);
    border-radius: 8px;
    font-family: var(--sans);
    font-size: 14px;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.15s;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
    text-decoration: none;
  }

  .btn-outline:hover { background: var(--surface2); border-color: #c5c8ce; }

  .btn-outline.green {
    color: var(--ng-green);
    border-color: var(--ng-green-mid);
    background: var(--ng-green-light);
  }
  .btn-outline.green:hover { background: #daf5c0; }

  /* ── Progress ── */
  #progress-area { display: none; }

  .progress-track {
    background: var(--surface2);
    border-radius: 6px;
    height: 6px;
    margin: 1rem 0;
    overflow: hidden;
  }

  .progress-fill {
    height: 100%;
    background: linear-gradient(90deg, var(--ng-green), #7ee000);
    border-radius: 6px;
    width: 0%;
    transition: width 0.4s ease;
  }

  .log-area {
    background: #f8faf6;
    border: 1px solid #dcefd0;
    border-radius: 8px;
    padding: 0.75rem 1rem;
    font-family: var(--mono);
    font-size: 12px;
    color: var(--muted);
    max-height: 130px;
    overflow-y: auto;
    line-height: 1.9;
  }

  .log-area .ok { color: #2a8a00; }
  .log-area .err { color: #c0392b; }
  .log-area .info { color: var(--ng-blue); }

  /* ── Results ── */
  #result-area { display: none; }

  .stat-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 0.75rem;
    margin-bottom: 1.25rem;
  }

  .stat {
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 0.875rem 1rem;
    text-align: center;
  }

  .stat-val {
    font-family: var(--mono);
    font-size: 24px;
    font-weight: 500;
    color: var(--ng-green);
    display: block;
    line-height: 1.2;
  }

  .stat-label {
    font-size: 11px;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-top: 3px;
    display: block;
  }

  /* ── File tree ── */
  .file-tree {
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 4px;
    max-height: 300px;
    overflow-y: auto;
    margin-bottom: 1.25rem;
  }

  .tree-item {
    display: flex;
    align-items: center;
    gap: 7px;
    padding: 5px 10px;
    border-radius: 6px;
    font-size: 12.5px;
    transition: background 0.1s;
    cursor: default;
  }

  .tree-item:hover { background: rgba(77,195,0,0.06); }

  .tree-item.is-dir {
    color: var(--ng-blue);
    font-weight: 600;
  }

  .tree-item.is-file { color: var(--text); }

  .tree-icon { font-size: 13px; flex-shrink: 0; }
  .tree-name { flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .tree-meta { font-size: 11px; color: var(--hint); white-space: nowrap; font-family: var(--mono); }

  .download-row { display: flex; gap: 0.75rem; }

  /* ── Error ── */
  .alert-error {
    background: #fff5f5;
    border: 1px solid #fcc;
    border-radius: 8px;
    padding: 0.75rem 1rem;
    font-size: 13px;
    color: #c0392b;
    display: none;
    margin-top: 0.75rem;
  }

  /* ── Scrollbar ── */
  ::-webkit-scrollbar { width: 5px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: #d1d5db; border-radius: 3px; }
  ::-webkit-scrollbar-thumb:hover { background: #9ca3af; }

  /* ── Spinner ── */
  @keyframes spin { to { transform: rotate(360deg); } }
  .spinner {
    width: 14px; height: 14px;
    border: 2px solid rgba(255,255,255,0.4);
    border-top-color: #fff;
    border-radius: 50%;
    animation: spin 0.7s linear infinite;
    display: none;
  }

  @media (max-width: 560px) {
    .row { grid-template-columns: 1fr; }
    .download-row { flex-direction: column; }
    main { padding: 1.5rem 1rem; }
  }
</style>
</head>
<body>

<header>
  <div class="logo-area">
    <img src="data:image/jpeg;base64,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" alt="nesseler Logo" style="height:40px;width:40px;object-fit:cover;border-radius:8px;flex-shrink:0;" />
    <div class="logo-label">
      <strong>nesseler bau</strong>
      <span>Dateiverzeichnis Generator</span>
    </div>
  </div>
  <div class="header-chip">v2.0</div>
</header>

<main>
  <div class="page-title">
    <h1>OwnCloud Dateiverzeichnis als PDF</h1>
    <p>Share-Link und Projektbezeichnung eingeben – das Tool liest das Verzeichnis rekursiv aus und erstellt ein druckfertiges PDF.</p>
  </div>

  <!-- Form -->
  <div class="card">
    <div class="card-header">
      <div class="card-header-dot"></div>
      <span class="card-header-title">Konfiguration</span>
    </div>

    <div class="field">
      <label>OwnCloud Share-Link</label>
      <input type="text" id="oc-url"
             placeholder="https://cloud.nesseler.de/owncloud/index.php/s/TOKEN"
             value="{{ prefill_url }}" />
      <div class="field-hint">Öffentlicher Share-Link im Format .../s/TOKEN</div>
    </div>

    <div class="field">
      <label>Share-Passwort <span class="label-opt">(optional)</span></label>
      <input type="password" id="oc-pass" placeholder="Leer lassen, wenn kein Passwort" />
    </div>

    <div class="row">
      <div class="field">
        <label>Projektbezeichnung</label>
        <input type="text" id="projekt" placeholder="z.B. Neubau EFH Aachen" />
      </div>
      <div class="field">
        <label>Ausgabedateiname <span class="label-opt">(optional)</span></label>
        <input type="text" id="filename" placeholder="dateiverzeichnis.pdf" />
      </div>
    </div>

    <button class="btn-primary" id="btn-start" onclick="startGeneration()">
      <div class="spinner" id="spinner"></div>
      <span id="btn-label">PDF erstellen</span>
    </button>

    <div class="alert-error" id="error-box"></div>
  </div>

  <!-- Progress -->
  <div class="card" id="progress-area">
    <div class="card-header">
      <div class="card-header-dot"></div>
      <span class="card-header-title">Fortschritt</span>
    </div>
    <div class="progress-track">
      <div class="progress-fill" id="progress-fill"></div>
    </div>
    <div class="log-area" id="log-area"></div>
  </div>

  <!-- Results -->
  <div class="card" id="result-area">
    <div class="card-header">
      <div class="card-header-dot"></div>
      <span class="card-header-title">Ergebnis</span>
    </div>

    <div class="stat-grid">
      <div class="stat">
        <span class="stat-val" id="stat-files">–</span>
        <span class="stat-label">Dateien</span>
      </div>
      <div class="stat">
        <span class="stat-val" id="stat-dirs">–</span>
        <span class="stat-label">Ordner</span>
      </div>
      <div class="stat">
        <span class="stat-val" id="stat-size">–</span>
        <span class="stat-label">Gesamt</span>
      </div>
    </div>

    <div class="file-tree" id="file-tree"></div>

    <div class="download-row">
      <a class="btn-outline green" id="btn-download" href="#" download>
        ↓ PDF herunterladen
      </a>
      <button class="btn-outline" onclick="resetForm()">
        ↺ Neu starten
      </button>
    </div>
  </div>

</main>

<script>
let currentJobId = null;
let pollInterval = null;

function log(msg, cls) {
  const area = document.getElementById('log-area');
  const line = document.createElement('div');
  line.className = cls || '';
  line.textContent = msg;
  area.appendChild(line);
  area.scrollTop = area.scrollHeight;
}

function setProgress(pct) {
  document.getElementById('progress-fill').style.width = pct + '%';
}

function showError(msg) {
  const box = document.getElementById('error-box');
  box.textContent = msg;
  box.style.display = 'block';
  setBusy(false);
}

function setBusy(busy) {
  const btn = document.getElementById('btn-start');
  const spinner = document.getElementById('spinner');
  const label = document.getElementById('btn-label');
  btn.disabled = busy;
  spinner.style.display = busy ? 'inline-block' : 'none';
  label.textContent = busy ? 'Wird erstellt...' : 'PDF erstellen';
}

function formatSize(bytes) {
  if (!bytes) return '–';
  const units = ['B','KB','MB','GB'];
  let i = 0;
  while (bytes >= 1024 && i < units.length - 1) { bytes /= 1024; i++; }
  return bytes.toFixed(1) + '\u00a0' + units[i];
}

function renderTree(entries) {
  const tree = document.getElementById('file-tree');
  tree.innerHTML = '';
  entries.forEach(e => {
    const div = document.createElement('div');
    div.className = 'tree-item ' + (e.is_dir ? 'is-dir' : 'is-file');
    div.style.paddingLeft = (10 + (e.depth || 0) * 18) + 'px';
    const icon = e.is_dir ? '📁' : getIcon(e.name);
    const meta = e.is_dir ? '' : formatSize(e.size);
    div.innerHTML = `<span class="tree-icon">${icon}</span><span class="tree-name">${e.name}</span><span class="tree-meta">${meta}</span>`;
    tree.appendChild(div);
  });
}

function getIcon(name) {
  const ext = (name.split('.').pop() || '').toLowerCase();
  const map = {pdf:'📄',doc:'📝',docx:'📝',xls:'📊',xlsx:'📊',
    ppt:'📋',pptx:'📋',jpg:'🖼',jpeg:'🖼',png:'🖼',
    mp4:'🎬',zip:'🗜',rar:'🗜',txt:'📄',csv:'📊',
    dwg:'📐',dxf:'📐',ifc:'🏗'};
  return map[ext] || '📄';
}

async function startGeneration() {
  document.getElementById('error-box').style.display = 'none';
  document.getElementById('result-area').style.display = 'none';
  document.getElementById('log-area').innerHTML = '';

  const url = document.getElementById('oc-url').value.trim();
  const pass = document.getElementById('oc-pass').value;
  const projekt = document.getElementById('projekt').value.trim();
  let filename = document.getElementById('filename').value.trim() || 'dateiverzeichnis.pdf';
  if (!filename.endsWith('.pdf')) filename += '.pdf';

  if (!url) { showError('Bitte OwnCloud-Link eingeben.'); return; }
  if (!projekt) { showError('Bitte Projektbezeichnung eingeben.'); return; }

  setBusy(true);
  document.getElementById('progress-area').style.display = 'block';
  setProgress(5);
  log('Verbinde mit OwnCloud...', 'info');

  try {
    const resp = await fetch('/api/generate', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({url, password: pass, projekt, filename})
    });
    const data = await resp.json();
    if (!resp.ok || data.error) { showError(data.error || 'Unbekannter Fehler'); return; }
    currentJobId = data.job_id;
    pollProgress();
  } catch(e) {
    showError('Verbindungsfehler: ' + e.message);
  }
}

function pollProgress() {
  pollInterval = setInterval(async () => {
    try {
      const resp = await fetch('/api/progress/' + currentJobId);
      const data = await resp.json();
      if (data.log) {
        document.getElementById('log-area').innerHTML = '';
        data.log.forEach(l => log(l.msg, l.cls));
      }
      setProgress(data.progress || 0);
      if (data.status === 'done') {
        clearInterval(pollInterval);
        setProgress(100);
        setBusy(false);
        showResults(data);
      } else if (data.status === 'error') {
        clearInterval(pollInterval);
        showError(data.error || 'Fehler bei der Verarbeitung');
      }
    } catch(e) {
      clearInterval(pollInterval);
      showError('Polling-Fehler: ' + e.message);
    }
  }, 800);
}

function showResults(data) {
  document.getElementById('stat-files').textContent = data.file_count || 0;
  document.getElementById('stat-dirs').textContent = data.dir_count || 0;
  document.getElementById('stat-size').textContent = formatSize(data.total_size || 0);
  if (data.entries) renderTree(data.entries);
  const dlBtn = document.getElementById('btn-download');
  dlBtn.href = '/api/download/' + currentJobId;
  dlBtn.download = data.filename || 'dateiverzeichnis.pdf';
  document.getElementById('result-area').style.display = 'block';
  document.getElementById('result-area').scrollIntoView({behavior: 'smooth', block: 'start'});
}

function resetForm() {
  document.getElementById('result-area').style.display = 'none';
  document.getElementById('progress-area').style.display = 'none';
  document.getElementById('log-area').innerHTML = '';
  document.getElementById('error-box').style.display = 'none';
  setBusy(false);
  setProgress(0);
  currentJobId = null;
  window.scrollTo({top: 0, behavior: 'smooth'});
}
</script>
</body>
</html>
"""

# ──────────────────────────────────────────────
# API Routes
# ──────────────────────────────────────────────

@app.route("/")
def index():
    return render_template_string(HTML, prefill_url="")


@app.route("/api/generate", methods=["POST"])
def api_generate():
    if not SCRIPT_AVAILABLE:
        return jsonify({"error": f"owncloud_verzeichnis.py nicht gefunden: {IMPORT_ERROR}"}), 500

    data = request.json
    url = data.get("url", "").strip()
    password = data.get("password", "").strip()
    projekt = data.get("projekt", "").strip()
    filename = data.get("filename", "dateiverzeichnis.pdf").strip()

    if not url or not projekt:
        return jsonify({"error": "URL und Projektbezeichnung erforderlich"}), 400

    job_id = f"job_{int(time.time()*1000)}"
    set_progress(job_id, {"status": "running", "progress": 5, "log": [
        {"msg": f"Job gestartet: {job_id}", "cls": "info"}
    ]})

    # Hintergrund-Thread
    def run_job():
        logs = []
        def add_log(msg, cls=""):
            logs.append({"msg": msg, "cls": cls})
            set_progress(job_id, {**get_progress(job_id), "log": logs.copy()})

        try:
            add_log(f"Parse Share-Link ...", "info")
            base_url, token = parse_share_id(url)
            add_log(f"Token: {token[:8]}...", "ok")

            set_progress(job_id, {**get_progress(job_id), "progress": 15})
            add_log("Lade Verzeichnisstruktur (rekursiv) ...", "info")

            # Passwort-Unterstützung: patch webdav_propfind temporär
            import owncloud_verzeichnis as ov
            original_propfind = ov.webdav_propfind

            if password:
                def propfind_with_pass(base, tok, path="/", depth=1):
                    import requests
                    webdav_url = f"{base}/public.php/webdav{path}"
                    body = """<?xml version="1.0" encoding="UTF-8"?><d:propfind xmlns:d="DAV:"><d:prop><d:displayname/><d:getcontentlength/><d:getlastmodified/><d:resourcetype/><d:getcontenttype/></d:prop></d:propfind>"""
                    headers = {"Depth": str(depth), "Content-Type": "application/xml"}
                    resp = requests.request("PROPFIND", webdav_url, headers=headers,
                                          data=body, auth=(tok, password), timeout=30)
                    if resp.status_code not in (207, 200):
                        raise ConnectionError(f"WebDAV-Fehler {resp.status_code}")
                    return resp.text
                ov.webdav_propfind = propfind_with_pass

            entries = fetch_recursive(base_url, token)

            if password:
                ov.webdav_propfind = original_propfind

            file_count = sum(1 for e in entries if not e["is_dir"])
            dir_count = sum(1 for e in entries if e["is_dir"])
            total_size = sum(e["size"] for e in entries if not e["is_dir"])

            add_log(f"{len(entries)} Einträge geladen ({file_count} Dateien, {dir_count} Ordner)", "ok")
            set_progress(job_id, {**get_progress(job_id), "progress": 60})

            # Logo suchen
            logo_candidates = [
                os.path.join(script_dir, "NG_Logo_2021_Bau_4c.jpg"),
                os.path.join(script_dir, "logo.jpg"),
                os.path.join(script_dir, "logo.png"),
            ]
            logo_path = next((p for p in logo_candidates if os.path.exists(p)), None)
            if logo_path:
                add_log(f"Logo gefunden: {os.path.basename(logo_path)}", "ok")
            else:
                add_log("Logo nicht gefunden – PDF ohne Logo", "")

            add_log("Erstelle PDF ...", "info")
            output_path = os.path.join(script_dir, f"output_{job_id}.pdf")
            build_pdf(entries, projekt, url, logo_path, output_path)

            set_progress(job_id, {
                "status": "done",
                "progress": 100,
                "log": logs,
                "file_count": file_count,
                "dir_count": dir_count,
                "total_size": total_size,
                "entries": entries[:200],  # max 200 für Preview
                "output_path": output_path,
                "filename": filename,
            })

        except Exception as e:
            add_log(f"Fehler: {e}", "err")
            set_progress(job_id, {**get_progress(job_id), "status": "error", "error": str(e)})

    threading.Thread(target=run_job, daemon=True).start()
    return jsonify({"job_id": job_id})


@app.route("/api/progress/<job_id>")
def api_progress(job_id):
    data = get_progress(job_id)
    if not data:
        return jsonify({"status": "unknown"}), 404
    # output_path nicht an Client senden
    safe = {k: v for k, v in data.items() if k != "output_path"}
    return jsonify(safe)


@app.route("/api/download/<job_id>")
def api_download(job_id):
    data = get_progress(job_id)
    if not data or data.get("status") != "done":
        return "Job nicht fertig oder nicht gefunden", 404
    output_path = data.get("output_path")
    if not output_path or not os.path.exists(output_path):
        return "Datei nicht gefunden", 404
    filename = data.get("filename", "dateiverzeichnis.pdf")
    return send_file(output_path, as_attachment=True, download_name=filename,
                     mimetype="application/pdf")


# ──────────────────────────────────────────────
# Start
# ──────────────────────────────────────────────
if __name__ == "__main__":
    if not SCRIPT_AVAILABLE:
        print(f"FEHLER: owncloud_verzeichnis.py nicht gefunden ({IMPORT_ERROR})")
        print("Bitte beide Dateien im selben Ordner ablegen.")
        sys.exit(1)

    print("=" * 50)
    print("  nesseler bau – Dateiverzeichnis Web-App")
    print("=" * 50)
    print("  Öffne im Browser: http://localhost:8000")
    print("  Stoppen: Ctrl+C")
    print("=" * 50)
    app.run(host="0.0.0.0", port=8000, debug=False)