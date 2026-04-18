const TYPE_COLORS = {
  "BLE-Adv": "#00bcd4",
  "WiFi-Probe": "#2196f3",
  "WiFi-AP": "#64b5f6",
  "keyfob": "#ffeb3b",
  "tpms": "#ffeb3b",
  "ISM": "#ffeb3b",
  "ADS-B": "#4caf50",
  "PMR446": "#f44336",
  "dPMR": "#f44336",
  "70cm": "#f44336",
  "MarineVHF": "#f44336",
  "2m": "#f44336",
  "FRS": "#f44336",
  "FM_voice": "#f44336",
  "RemoteID": "#f44336",
  "DroneCtrl": "#f44336",
  "GSM-UPLINK-GSM-900": "#ccc",
  "GSM-UPLINK-GSM-850": "#ccc",
  "lora": "#ce93d8",
  "Meshtastic-Position": "#ab47bc",
  "Meshtastic-Telemetry": "#ab47bc",
  "Meshtastic-Node": "#9575cd",
  "pocsag": "#ccc"
};
function esc(s) {
  if (!s) return '';
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

// Central tooltip dictionary — human-readable explanations shown on hover
// for every short tag/badge in the UI. Lookups are case-insensitive and fall
// back to prefix matches so dynamic values (e.g. "LNA 24") resolve.
const TAG_TIPS = {
  // Device flags
  'rand':        'Device advertises with rotating random MAC addresses. Modern phones/watches/earbuds use this as a privacy feature to prevent tracking — the fingerprint groups all rotated MACs back into one device.',
  // Capture status
  'running':     'Capture source is running and producing samples.',
  'pending':     'Capture source has not started yet.',
  'degraded':    'Capture is running but the pipeline cannot keep up — samples are being dropped. Consider lowering sample rate or gain.',
  'failed':      'Capture source exited with an error. Check the status message or server logs for details.',
  // Bands
  '2.4 ghz':     'AP observed broadcasting on the 2.4 GHz band (channels 1-14).',
  '5 ghz':       'AP observed broadcasting on the 5 GHz band (channels 32+).',
  '6 ghz':       'AP observed broadcasting on the 6 GHz band (Wi-Fi 6E).',
  // Config/capture tags
  'transcribe':  'Audio is transcribed to text using Whisper (local model or OpenAI API).',
  'digital':     'Digital voice modes enabled (dPMR/DMR detection on PMR446).',
  'no audio':    'Audio recording is disabled — only detection events are logged.',
  // Crypto (shown as plain cell text but good to cover)
  'wpa2-psk':    'WPA2 Personal — pre-shared key authentication (standard home network).',
  'wpa3-sae':    'WPA3 Personal — SAE (Simultaneous Authentication of Equals), more secure than WPA2-PSK.',
  'wpa2-eap':    'WPA2 Enterprise — 802.1X authentication (corporate networks).',
  'owe':         'Opportunistic Wireless Encryption — encrypted but unauthenticated (open networks with WPA3 encryption).',
  'open':        'No encryption — plaintext network.',
  'wep':         'WEP — legacy, broken encryption. Treat as open.',
};
const TAG_TIP_PREFIXES = [
  ['lna ',     'HackRF LNA (Low-Noise Amplifier) gain in dB. Boosts RF signal at the front end; too high causes overload.'],
  ['vga ',     'HackRF VGA (Variable-Gain Amplifier) baseband gain in dB. Applied after downconversion.'],
  ['lang: ',   'Forced Whisper transcription language (ISO 639-1 code). Otherwise auto-detected.'],
  ['whisper: ','Whisper model used for transcription. Larger = more accurate but slower.'],
  ['ppm ',     'RTL-SDR / HackRF crystal frequency correction in parts-per-million. Corrects cheap SDR clock drift.'],
  ['probing: ','Network name(s) this client device is searching for. Clients reveal saved networks in their probe requests.'],
];

function tipFor(tag) {
  if (!tag) return '';
  const k = String(tag).toLowerCase().trim();
  if (TAG_TIPS[k]) return TAG_TIPS[k];
  for (const [prefix, tip] of TAG_TIP_PREFIXES) {
    if (k.startsWith(prefix)) return tip;
  }
  return '';
}

function tipAttr(tag) {
  const t = tipFor(tag);
  return t ? ' title="' + esc(t) + '"' : '';
}

// --- Generic per-table client-side sorting ---
// Every tab body that wants column sort registers through setTable(id,
// rows, renderFn). The Devices tab has its own bespoke sort state
// (_devSort) so we route based on data-sub vs data-tbl on the <th>.
const _tblData = {};     // tbody id → raw rows[]
const _tblRender = {};   // tbody id → renderFn(sortedRows)
const _tblSort = {};     // tbody id → {key, dir}

function _cmpRows(a, b, key, dir) {
  const av = a[key], bv = b[key];
  if (av == null && bv == null) return 0;
  if (av == null) return 1;   // nulls always sink to the bottom
  if (bv == null) return -1;
  if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * dir;
  return String(av).localeCompare(String(bv)) * dir;
}

function _sortRows(rows, key, dirStr) {
  const dir = dirStr === 'asc' ? 1 : -1;
  return rows.slice().sort((a, b) => _cmpRows(a, b, key, dir));
}

function _updateTblSortIndicators(id) {
  document.querySelectorAll('th.sortable[data-tbl="'+id+'"]').forEach(th => {
    th.classList.remove('sort-asc', 'sort-desc');
    const s = _tblSort[id];
    if (s && s.key === th.dataset.key) {
      th.classList.add(s.dir === 'asc' ? 'sort-asc' : 'sort-desc');
    }
  });
}

function setTable(id, rows, renderFn) {
  _tblData[id] = rows;
  _tblRender[id] = renderFn;
  const s = _tblSort[id];
  const out = s ? _sortRows(rows, s.key, s.dir) : rows;
  renderFn(out);
  _updateTblSortIndicators(id);
}

function tblSortBy(id, key) {
  const s = _tblSort[id];
  if (s && s.key === key) {
    if (s.dir === 'desc') _tblSort[id] = {key, dir: 'asc'};
    else delete _tblSort[id];    // third click clears → source order
  } else {
    _tblSort[id] = {key, dir: 'desc'};
  }
  const rows = _tblData[id] || [];
  const render = _tblRender[id];
  if (render) {
    const s2 = _tblSort[id];
    render(s2 ? _sortRows(rows, s2.key, s2.dir) : rows);
  }
  _updateTblSortIndicators(id);
}

// --- Config / Captures ---
async function loadConfig() {
  const capEl = document.getElementById('captures');
  try {
    const r = await fetch('/api/config');
    const cfg = await r.json();
    if (!cfg.captures || !cfg.captures.length) {
      capEl.innerHTML = '<div class="empty">no server_info.json found (server not running?)</div>';
      return;
    }
    const STATUS_COLORS = {
      running: '#4caf50',
      pending: '#888',
      degraded: '#ff9800',
      failed: '#f44336',
    };
    let html = '';
    cfg.captures.forEach(cap => {
      const t = cap.type;
      const status = cap.status || 'pending';
      const statusColor = STATUS_COLORS[status] || '#888';
      let line = '<div style="margin-bottom:8px;border-left:3px solid ' + statusColor + ';padding-left:8px">';
      line += '<div><span style="color:#4fc3f7;font-weight:600">' + esc(cap.name) + '</span>';
      line += ' <span' + tipAttr(status) + ' style="background:' + statusColor + ';color:#000;padding:1px 6px;border-radius:3px;font-size:10px;font-weight:600;margin-left:6px;cursor:help">' + esc(status.toUpperCase()) + '</span>';
      line += ' <span style="color:#888">' + esc(cap.device || '') + '</span></div>';
      if (cap.status_message) {
        line += '<div style="font-size:11px;color:' + statusColor + ';margin-left:12px">\u26a0 ' + esc(cap.status_message) + '</div>';
      }

      // Coverage line: frequency range + hopping/continuous/passive mode
      const modeIcon = {
        continuous: '\u25cf',   // filled dot — continuous
        hopping:    '\u{1F500}', // shuffle — hopping
        passive:    '\u{1F442}', // ear — passive listen
      };
      if (cap.coverage || cap.mode) {
        const icon = modeIcon[cap.mode] || '';
        line += '<div style="font-size:11px;color:#9ecbff;margin-left:12px;margin-top:2px">'
             + (icon ? icon + ' ' : '')
             + esc(cap.coverage || '')
             + (cap.mode ? ' <span style="color:#666">\u00b7 ' + esc(cap.mode) + '</span>' : '')
             + '</div>';
      }

      // --- Tag row: only orthogonal info, no duplication of the coverage line ---
      const tags = [];
      if (t === 'hackrf') {
        if (cap.lna_gain != null) tags.push('LNA ' + cap.lna_gain);
        if (cap.vga_gain != null) tags.push('VGA ' + cap.vga_gain);
        if (cap.transcribe) tags.push('\u2705 transcribe');
        if (cap.whisper_model && cap.whisper_model !== 'base') tags.push('whisper: ' + cap.whisper_model);
        if (cap.language) tags.push('lang: ' + cap.language);
      } else if (t === 'rtlsdr' || t === 'rtlsdr_sweep') {
        if (cap.parsers && cap.parsers.length) tags.push(cap.parsers.join(' \u00b7 '));
      } else if (t === 'ble') {
        if (cap.parsers && cap.parsers.length) tags.push(cap.parsers.join(' \u00b7 '));
      } else if (t === 'wifi') {
        if (cap.parsers && cap.parsers.length) tags.push(cap.parsers.join(' \u00b7 '));
      } else if (t === 'standalone') {
        if (cap.scanner_label || cap.scanner_type) {
          tags.push(cap.scanner_label || cap.scanner_type);
        }
        // Pretty-print common args (mirrors HackRF flag rendering)
        const args = cap.args || [];
        if (args.includes('--transcribe')) tags.push('\u2705 transcribe');
        if (args.includes('--digital')) tags.push('\u2705 digital');
        if (args.includes('--no-audio')) tags.push('no audio');
        const flagValue = (flag) => {
          const i = args.indexOf(flag);
          return (i >= 0 && i + 1 < args.length) ? args[i + 1] : null;
        };
        const lang = flagValue('--language');
        if (lang) tags.push('lang: ' + lang);
        const wm = flagValue('--whisper-model');
        if (wm && wm !== 'base') tags.push('whisper: ' + wm);
        const ppm = flagValue('--ppm');
        if (ppm) tags.push('ppm ' + ppm);
        // Anything else (positional band names, custom flags) — show as-is
        const known = new Set([
          '--transcribe', '--digital', '--no-audio',
          '--language', '--whisper-model', '--ppm',
        ]);
        const skipNext = new Set(['--language', '--whisper-model', '--ppm']);
        const extras = [];
        for (let i = 0; i < args.length; i++) {
          const a = args[i];
          if (known.has(a)) {
            if (skipNext.has(a)) i++;
            continue;
          }
          extras.push(a);
        }
        if (extras.length) tags.push(extras.join(' '));
      }
      if (tags.length) {
        line += '<div style="font-size:12px;color:#aaa;margin-left:12px">' + tags.map(t => {
          const tip = tipFor(t);
          const cur = tip ? ';cursor:help' : '';
          const attr = tip ? ' title="' + esc(tip) + '"' : '';
          return '<span' + attr + ' style="background:#0f3460;padding:1px 6px;border-radius:3px;margin-right:4px;display:inline-block;margin-top:2px' + cur + '">' + esc(t) + '</span>';
        }).join('') + '</div>';
      }

      // --- Sub-channel list (HackRF + WiFi use the same tree-style rendering) ---
      const fmtFreq = (mhz) => {
        if (mhz == null) return '';
        if (mhz >= 1000) return (mhz / 1000).toFixed(3) + ' GHz';
        return Number(mhz).toFixed(4).replace(/0+$/, '').replace(/\.$/, '') + ' MHz';
      };

      if (t === 'hackrf' && cap.channels && cap.channels.length) {
        cap.channels.forEach(ch => {
          const chTags = [];
          if (ch.band) chTags.push(ch.band);
          if (ch.name) chTags.push(ch.name);
          chTags.push(fmtFreq(ch.freq_mhz));
          if (ch.bandwidth_mhz) chTags.push(ch.bandwidth_mhz + ' MHz BW');
          if (ch.parsers && ch.parsers.length) chTags.push(ch.parsers.join(' \u00b7 '));
          if (ch.transcribe) chTags.push('\u2705 transcribe');
          line += '<div style="font-size:11px;color:#888;margin-left:24px;margin-top:2px">\u2514 ' + chTags.join(' \u00b7 ') + '</div>';
        });
      }

      if (t === 'wifi' && cap.channel_list && cap.channel_list.length) {
        const chList = cap.channel_list;
        // Compact form for long lists: show first 6 + count
        const shown = chList.length > 8 ? chList.slice(0, 6) : chList;
        shown.forEach(ch => {
          line += '<div style="font-size:11px;color:#888;margin-left:24px;margin-top:2px">'
               + '\u2514 CH' + esc(ch.name) + ' \u00b7 ' + esc(fmtFreq(ch.freq_mhz)) + '</div>';
        });
        if (chList.length > shown.length) {
          line += '<div style="font-size:11px;color:#666;margin-left:24px;margin-top:2px">'
               + '\u2514 \u2026 +' + (chList.length - shown.length) + ' more</div>';
        }
      }

      line += '</div>';
      html += line;
    });
    if (cfg.started) {
      html += '<div style="font-size:11px;color:#555;margin-top:4px">Started: ' + esc(cfg.started.replace('T', ' ').split('.')[0]) + '</div>';
    }
    capEl.innerHTML = html;
  } catch(e) {
    capEl.innerHTML = '<div class="empty">could not load config</div>';
  }
}

// --- Live Tab ---
function renderCategories(rows) {
  const tbody = document.getElementById('categories');
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="5" class="empty">waiting for detections...</td></tr>';
    return;
  }
  tbody.innerHTML = rows.map(c => {
    const typesStr = (c.types || []).map(t => {
      const col = TYPE_COLORS[t] || '#ccc';
      return '<span style="color:'+col+';margin-right:8px">'+esc(t)+'</span>';
    }).join('');
    return '<tr style="cursor:pointer" onclick="goToTab(\''+esc(c.id)+'\')">'
      + '<td style="font-weight:600;color:#e0e0e0">'+esc(c.label)+'</td>'
      + '<td class="num">'+c.count+'</td>'
      + '<td class="num">'+(c.uniques>0?c.uniques:'-')+'</td>'
      + '<td>'+(c.last_seen||'-')+'</td>'
      + '<td style="font-size:11px">'+typesStr+'</td>'
      + '</tr>';
  }).join('');
}

function updateOverview(state) {
  document.getElementById('h-time').textContent = state.time || '-';
  document.getElementById('h-uptime').textContent = state.uptime || '-';
  document.getElementById('h-count').textContent = state.detection_count || 0;
  document.getElementById('h-db').textContent = state.db || '-';

  const gps = state.gps;
  const gpsEl = document.getElementById('h-gps');
  if (gps && gps.lat != null) {
    gpsEl.textContent = gps.lat.toFixed(4) + ', ' + gps.lon.toFixed(4);
    gpsEl.style.color = '#4fc3f7';
  } else {
    gpsEl.textContent = 'no fix';
    gpsEl.style.color = '#888';
  }

  // System stats
  const sys = state.system || {};
  const cpuEl = document.getElementById('s-cpu');
  if (sys.cpu_pct != null) {
    cpuEl.textContent = sys.cpu_pct + '%';
    cpuEl.style.color = sys.cpu_pct > 80 ? '#f44336' : sys.cpu_pct > 50 ? '#ffeb3b' : '#4caf50';
  }
  const tempEl = document.getElementById('s-temp');
  if (sys.cpu_temp != null) {
    tempEl.textContent = sys.cpu_temp + '\u00b0C';
    tempEl.style.color = sys.cpu_temp > 75 ? '#f44336' : sys.cpu_temp > 60 ? '#ffeb3b' : '#4caf50';
  }
  const memEl = document.getElementById('s-mem');
  if (sys.mem_used_mb != null) {
    memEl.textContent = sys.mem_used_mb + ' / ' + sys.mem_total_mb + ' MB (' + sys.mem_pct + '%)';
    memEl.style.color = sys.mem_pct > 85 ? '#f44336' : sys.mem_pct > 70 ? '#ffeb3b' : '#e0e0e0';
  }
  const diskEl = document.getElementById('s-disk');
  if (sys.disk_used_gb != null) {
    diskEl.textContent = sys.disk_used_gb + ' / ' + sys.disk_total_gb + ' GB (' + sys.disk_pct + '%)';
    diskEl.style.color = sys.disk_pct > 90 ? '#f44336' : sys.disk_pct > 75 ? '#ffeb3b' : '#e0e0e0';
  }

  // (Config is in its own tab)

  // Categories table (Live tab overview)
  setTable('categories', state.categories || [], renderCategories);

  // Recent events
  const recEl = document.getElementById('recent');
  if (state.recent && state.recent.length) {
    recEl.innerHTML = state.recent.map(ev => {
      const color = TYPE_COLORS[ev.type] || '#ccc';
      const line = esc(ev.line);
      const typed = esc(ev.type);
      const colored = line.replace(typed,
        '<span style="color:'+color+';font-weight:600">'+typed+'</span>');
      return '<div class="event-line">' + colored + '</div>';
    }).join('');
  } else {
    recEl.innerHTML = '<div class="empty">...</div>';
  }

  // Populate filter dropdown
  populateFilter(state.signals);
}

// --- Log Tab ---
let detOffset = 0;
let detectionsLoaded = false;
let filterPopulated = false;
let _logRows = [];

function populateFilter(signals) {
  if (filterPopulated || !signals || !signals.length) return;
  const sel = document.getElementById('det-filter');
  signals.forEach(s => {
    const opt = document.createElement('option');
    opt.value = s.type;
    opt.textContent = s.type + ' (' + s.count + ')';
    sel.appendChild(opt);
  });
  filterPopulated = true;
}

function renderLogRows(rows) {
  const tbody = document.getElementById('det-body');
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="7" class="empty">no detections</td></tr>';
    return;
  }
  tbody.innerHTML = rows.map(d => {
    const ts = d.timestamp ? d.timestamp.split('T')[1].split('.')[0] : '-';
    const color = TYPE_COLORS[d.signal_type] || '#ccc';
    const hasTx = !!d.transcript;
    const detailText = hasTx ? '\u201c' + d.transcript + '\u201d' : (d.detail || '');
    const audioBtn = d.audio_file
      ? '<button class="play-btn" onclick="playAudio(this,\''+esc(d.audio_file)+'\')">&#9654;</button>'
      : '';
    const freq = (d.frequency_mhz != null) ? d.frequency_mhz.toFixed(3) : '-';
    return '<tr>'
      + '<td>'+ts+'</td>'
      + '<td class="sig-type" style="color:'+color+'">'+esc(d.signal_type)+'</td>'
      + '<td>'+esc(d.channel)+'</td>'
      + '<td>'+freq+'</td>'
      + '<td class="num">'+(d.snr_db!=null?d.snr_db+' dB':'-')+'</td>'
      + '<td class="detail'+(hasTx?' transcript':'')+'">'+esc(detailText)+'</td>'
      + '<td>'+audioBtn+'</td>'
      + '</tr>';
  }).join('');
}

async function loadDetections(append) {
  if (!append) { detOffset = 0; _logRows = []; }
  const filter = document.getElementById('det-filter').value;
  const url = '/api/detections?limit=50&offset=' + detOffset
    + (filter ? '&type=' + encodeURIComponent(filter) : '');
  try {
    const r = await fetch(url);
    const data = await r.json();
    _logRows = append ? _logRows.concat(data) : data.slice();
    setTable('det-body', _logRows, renderLogRows);
    detOffset += data.length;
    detectionsLoaded = true;
    document.getElementById('det-more').style.display = data.length < 50 ? 'none' : '';
  } catch(e) {}
}

document.getElementById('det-filter').addEventListener('change', () => loadDetections());

// --- Audio Playback ---
const audioEl = document.getElementById('audio-player');

function playAudio(btn, filename) {
  if (audioEl.dataset.file === filename && !audioEl.paused) {
    audioEl.pause();
    btn.innerHTML = '&#9654;';
    btn.classList.remove('playing');
    return;
  }
  document.querySelectorAll('.play-btn.playing').forEach(b => {
    b.innerHTML = '&#9654;'; b.classList.remove('playing');
  });
  audioEl.src = '/audio/' + encodeURIComponent(filename);
  audioEl.dataset.file = filename;
  audioEl.play();
  btn.innerHTML = '&#9724;';
  btn.classList.add('playing');
  audioEl.onended = () => {
    btn.innerHTML = '&#9654;'; btn.classList.remove('playing');
  };
}

// --- Devices Tab ---
let _devCache = { wifi_aps: [], wifi_clients: [], ble: [], summary: {} };
let _devSubtab = 'wifi_aps';
let _devExpanded = { wifi_aps: new Set(), wifi_clients: new Set(), ble: new Set() };
// null = server-default sort; otherwise {key, dir: 'asc'|'desc'}
let _devSort = { wifi_aps: null, wifi_clients: null, ble: null };

function _devSortValue(row, key) {
  if (key === 'channel') {
    const chs = row.channels || [];
    return chs.length ? chs[0] : 0;
  }
  const v = row[key];
  // RSSI: idle devices have null last_rssi. Treat null as very weak so
  // DESC sort (strongest first) puts them at the bottom instead of
  // interleaving them randomly via string comparison.
  if (key === 'last_rssi' && v == null) return -999;
  if (v == null) return '';
  return v;
}

function _devApplySort(sub, rows) {
  const s = _devSort[sub];
  if (!s) return rows;
  const dir = s.dir === 'asc' ? 1 : -1;
  const out = rows.slice();
  out.sort((a, b) => {
    const av = _devSortValue(a, s.key);
    const bv = _devSortValue(b, s.key);
    if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * dir;
    return String(av).localeCompare(String(bv)) * dir;
  });
  return out;
}

function _devUpdateSortIndicators() {
  document.querySelectorAll('th.sortable').forEach(th => {
    th.classList.remove('sort-asc', 'sort-desc');
    const sub = th.dataset.sub;
    const s = _devSort[sub];
    if (s && s.key === th.dataset.key) {
      th.classList.add(s.dir === 'asc' ? 'sort-asc' : 'sort-desc');
    }
  });
}

function devSortBy(sub, key) {
  const s = _devSort[sub];
  if (s && s.key === key) {
    if (s.dir === 'desc') _devSort[sub] = { key, dir: 'asc' };
    else _devSort[sub] = null;  // third click clears → server default
  } else {
    _devSort[sub] = { key, dir: 'desc' };
  }
  _devUpdateSortIndicators();
  renderDevices();
}

async function loadDevices() {
  try {
    const r = await fetch('/api/devices');
    _devCache = await r.json();
    renderDevices();
  } catch(e) {}
}

function fmtTs(ts) {
  if (!ts) return '-';
  const parts = ts.split('T');
  if (parts.length < 2) return ts;
  return parts[0].slice(5) + ' ' + parts[1].split('.')[0];
}

function activeDot(active) {
  return active
    ? '<span class="status-dot" title="Active now"></span>'
    : '<span class="status-dot off" style="opacity:0.2"></span>';
}

function renderDevices() {
  const activeOnly = document.getElementById('dev-active-only').checked;
  const s = _devCache.summary || {};

  const cardStyle = 'background:#16213e;border:1px solid #0f3460;border-radius:6px;padding:8px 14px;font-size:12px;text-align:center;min-width:80px';
  document.getElementById('dev-stats').innerHTML =
    '<div style="'+cardStyle+'"><div style="font-size:20px;font-weight:600;color:#2196f3">'+(s.wifi_aps||0)+'</div>WiFi APs</div>'
    + '<div style="'+cardStyle+'"><div style="font-size:20px;font-weight:600;color:#64b5f6">'+(s.wifi_clients||0)+'</div>WiFi Clients</div>'
    + '<div style="'+cardStyle+'"><div style="font-size:20px;font-weight:600;color:#00bcd4">'+(s.ble||0)+'</div>BLE</div>'
    + '<div style="'+cardStyle+'"><div style="font-size:20px;font-weight:600;color:#4caf50">'+(s.active||0)+'</div>Active</div>';

  renderWifiAps(activeOnly);
  renderWifiClients(activeOnly);
  renderBle(activeOnly);
}

function renderWifiAps(activeOnly) {
  const aps = _devApplySort('wifi_aps',
    (_devCache.wifi_aps || []).filter(a => !activeOnly || a.active));
  const tbody = document.getElementById('ap-body');
  if (!aps.length) {
    tbody.innerHTML = '<tr><td colspan="9" class="empty">no APs found — run sdr.py server to collect beacon data</td></tr>';
    return;
  }
  const rows = [];
  aps.forEach((a, i) => {
    const key = a.group_key || i;
    const isExp = _devExpanded.wifi_aps.has(String(key));
    const label = a.hidden ? '<span style="color:#888">(hidden)</span>' : esc(a.label || '');
    const bssidCell = a.bssid_count > 1
      ? '<span style="color:#4fc3f7">'+a.bssid_count+' radios</span>'
      : (a.bssids[0] ? esc(a.bssids[0].bssid) : '-');
    const bands = (a.bands || []).map(b => '<span title="'+esc(tipFor(b+' GHz'))+'" style="background:#0f3460;color:#9ecbff;padding:0 5px;border-radius:3px;font-size:10px;margin-right:2px;cursor:help">'+b+' GHz</span>').join('');
    const chs = (a.channels || []).join(',');
    const rssi = (a.last_rssi != null) ? a.last_rssi.toFixed(0)+' dBm' : '-';
    const borderStyle = a.active ? 'border-left:3px solid #4caf50' : '';
    const clientCount = a.client_count || 0;
    const noClientsTip = 'No associated clients observed yet. Client detection requires capturing data/mgmt frames while tuned to the AP channel — with channel hopping this can be slow. Dwelling longer on a channel surfaces more clients.';
    const clientCell = clientCount > 0
      ? '<span style="color:#4fc3f7;cursor:help" title="'+esc((a.clients||[]).join('\n'))+'">'+clientCount+'</span>'
      : '<span style="color:#555;cursor:help" title="'+esc(noClientsTip)+'">\u2014</span>';
    rows.push(
      '<tr style="cursor:pointer;'+borderStyle+'" onclick="toggleDevRow(\'wifi_aps\',\''+encodeURIComponent(String(key))+'\')">'
      + '<td>'+activeDot(a.active)+'</td>'
      + '<td>'+label+'</td>'
      + '<td style="font-family:monospace;font-size:11px">'+bssidCell+'</td>'
      + '<td>'+bands+' <span style="color:#888;font-size:11px">'+esc(chs)+'</span></td>'
      + '<td'+tipAttr(a.crypto)+' style="font-size:11px'+(tipFor(a.crypto)?';cursor:help':'')+'">'+esc(a.crypto||'')+'</td>'
      + '<td style="color:#888;font-size:11px">'+esc(a.manufacturer||'')+'</td>'
      + '<td class="num">'+rssi+'</td>'
      + '<td class="num">'+clientCell+'</td>'
      + '<td style="font-size:11px;white-space:nowrap">'+fmtTs(a.first_seen)+'</td>'
      + '<td style="font-size:11px;white-space:nowrap">'+fmtTs(a.last_seen)+'</td>'
      + '</tr>'
    );
    if (isExp) {
      let detail = '<div style="padding:8px 12px;background:#0a1020;font-size:11px">';
      detail += '<div style="color:#888;margin-bottom:4px">SSIDs: ' + (a.ssids||[]).map(esc).join(', ') + '</div>';
      detail += '<table style="width:100%;margin-top:4px"><thead><tr>'
        + '<th>BSSID</th><th>SSID</th><th class="num">Ch</th><th>Crypto</th><th>Vendor</th>'
        + '<th class="num">RSSI</th><th class="num">Clients</th><th class="num">Beacons</th><th>Last Seen</th>'
        + '</tr></thead><tbody>';
      (a.bssids||[]).forEach(b => {
        detail += '<tr><td style="font-family:monospace">'+esc(b.bssid)+'</td>'
          + '<td>'+esc((b.ssids||[]).join(',')||'(hidden)')+'</td>'
          + '<td class="num">'+esc((b.channels||[]).join(','))+'</td>'
          + '<td>'+esc(b.crypto||'')+'</td>'
          + '<td style="color:#888">'+esc(b.manufacturer||'')+'</td>'
          + '<td class="num">'+(b.last_rssi!=null?b.last_rssi.toFixed(0):'-')+'</td>'
          + '<td class="num">'+((b.client_count||0) > 0 ? b.client_count : '<span style="color:#555">\u2014</span>')+'</td>'
          + '<td class="num">'+(b.total_beacons||0)+'</td>'
          + '<td style="font-size:11px">'+fmtTs(b.last_seen)+'</td></tr>';
      });
      detail += '</tbody></table>';
      if ((a.clients||[]).length) {
        detail += '<div style="margin-top:8px"><div style="color:#4fc3f7;margin-bottom:2px">Associated clients ('+a.client_count+')</div>'
          + '<div style="font-family:monospace;color:#ccc;column-count:3">'
          + a.clients.map(esc).join('<br>')
          + '</div></div>';
      }
      detail += '</div>';
      rows.push('<tr><td colspan="10" style="padding:0">'+detail+'</td></tr>');
    }
  });
  tbody.innerHTML = rows.join('');
}

function _fmtRssi(v) {
  if (v == null) return '<span style="color:#555">\u2014</span>';
  // Stronger = higher (less negative). Color-code: near/far visual bucket.
  const n = Math.round(v);
  const color = n >= -55 ? '#4caf50'
              : n >= -70 ? '#ffeb3b'
              : n >= -85 ? '#ffb74d'
              : '#f44336';
  return '<span style="color:'+color+'">'+n+' dBm</span>';
}

function renderWifiClients(activeOnly) {
  const items = _devApplySort('wifi_clients',
    (_devCache.wifi_clients || []).filter(c => !activeOnly || c.active));
  const tbody = document.getElementById('wc-body');
  if (!items.length) {
    tbody.innerHTML = '<tr><td colspan="9" class="empty">no clients found</td></tr>';
    return;
  }
  const rows = [];
  items.forEach((c, i) => {
    const key = c.persona_key || c.dev_sig || String(i);
    const isExp = _devExpanded.wifi_clients.has(key);
    const sessColor = c.sessions >= 20 ? '#f44336' : c.sessions >= 5 ? '#ffeb3b' : '#e0e0e0';
    const borderStyle = c.active ? 'border-left:3px solid #4caf50' : '';
    const rowStyle = c.sessions <= 1 ? 'opacity:0.5' : '';

    let labelHtml = '<span style="color:#e0e0e0">' + esc(c.label || 'unknown') + '</span>';
    if (c.randomized) labelHtml += ' <span title="'+esc(tipFor('rand'))+'" style="background:#333;color:#888;padding:0 5px;border-radius:3px;font-size:10px;cursor:help">rand</span>';
    if (c.ssids && c.ssids.length) {
      labelHtml += ' <span style="background:#1a1a2e;color:#9ecbff;padding:0 5px;border-radius:3px;font-size:10px;cursor:help" title="'+esc(tipFor('probing: x'))+'\n\n'+esc(c.ssids.join(', '))+'">probing: '+esc(c.ssids[0])+(c.ssids.length>1?' +'+(c.ssids.length-1):'')+'</span>';
    }

    rows.push(
      '<tr style="cursor:pointer;'+rowStyle+';'+borderStyle+'" onclick="toggleDevRow(\'wifi_clients\',\''+encodeURIComponent(key)+'\')">'
      + '<td>'+activeDot(c.active)+'</td>'
      + '<td>'+labelHtml+'</td>'
      + '<td style="color:#888;font-size:12px">'+esc(c.manufacturer||'')+'</td>'
      + '<td class="num">'+_fmtRssi(c.last_rssi)+'</td>'
      + '<td class="num">'+c.mac_count+'</td>'
      + '<td class="num">'+c.ssid_count+'</td>'
      + '<td class="num" style="color:'+sessColor+'">'+c.sessions+'</td>'
      + '<td class="num">'+(c.total_probes||0).toLocaleString()+'</td>'
      + '<td style="font-size:11px;white-space:nowrap">'+fmtTs(c.last_session)+'</td>'
      + '</tr>'
    );
    if (isExp) {
      let detail = '<div style="padding:8px 12px;background:#0a1020;font-size:11px;display:flex;gap:24px;flex-wrap:wrap">';
      detail += '<div><div style="color:#4fc3f7;margin-bottom:2px">MACs ('+c.mac_count+')</div><div style="font-family:monospace;color:#ccc">'+(c.macs||[]).map(esc).join('<br>')+'</div></div>';
      detail += '<div><div style="color:#4fc3f7;margin-bottom:2px">Probed SSIDs ('+c.ssid_count+')</div><div style="color:#9ecbff">'+(c.ssids||[]).map(esc).join('<br>')+'</div></div>';
      detail += '<div><div style="color:#4fc3f7;margin-bottom:2px">Fingerprint</div><div style="font-family:monospace;color:#888">'+esc(c.dev_sig||'')+'</div></div>';
      detail += '</div>';
      rows.push('<tr><td colspan="9" style="padding:0">'+detail+'</td></tr>');
    }
  });
  tbody.innerHTML = rows.join('');
}

function renderBle(activeOnly) {
  const items = _devApplySort('ble',
    (_devCache.ble || []).filter(d => !activeOnly || d.active));
  const tbody = document.getElementById('ble-body');
  if (!items.length) {
    tbody.innerHTML = '<tr><td colspan="9" class="empty">no BLE devices found</td></tr>';
    return;
  }
  const rows = [];
  items.forEach((d, i) => {
    const key = d.persona_key || d.dev_sig || String(i);
    const isExp = _devExpanded.ble.has(key);
    const sessColor = d.sessions >= 20 ? '#f44336' : d.sessions >= 5 ? '#ffeb3b' : '#e0e0e0';
    const borderStyle = d.active ? 'border-left:3px solid #4caf50' : '';
    const rowStyle = d.sessions <= 1 ? 'opacity:0.5' : '';

    let labelHtml = '<span style="color:#e0e0e0">' + esc(d.label || 'unknown') + '</span>';
    if (d.randomized) labelHtml += ' <span title="'+esc(tipFor('rand'))+'" style="background:#333;color:#888;padding:0 5px;border-radius:3px;font-size:10px;cursor:help">rand</span>';

    rows.push(
      '<tr style="cursor:pointer;'+rowStyle+';'+borderStyle+'" onclick="toggleDevRow(\'ble\',\''+encodeURIComponent(key)+'\')">'
      + '<td>'+activeDot(d.active)+'</td>'
      + '<td>'+labelHtml+'</td>'
      + '<td style="color:#888;font-size:12px">'+esc(d.manufacturer||'')+'</td>'
      + '<td style="color:#aaa;font-size:11px">'+esc(d.apple_device||'')+'</td>'
      + '<td class="num">'+_fmtRssi(d.last_rssi)+'</td>'
      + '<td class="num">'+d.mac_count+'</td>'
      + '<td class="num" style="color:'+sessColor+'">'+d.sessions+'</td>'
      + '<td class="num">'+(d.total_probes||0).toLocaleString()+'</td>'
      + '<td style="font-size:11px;white-space:nowrap">'+fmtTs(d.last_session)+'</td>'
      + '</tr>'
    );
    if (isExp) {
      let detail = '<div style="padding:8px 12px;background:#0a1020;font-size:11px;display:flex;gap:24px;flex-wrap:wrap">';
      detail += '<div><div style="color:#4fc3f7;margin-bottom:2px">MACs ('+d.mac_count+')</div><div style="font-family:monospace;color:#ccc">'+(d.macs||[]).map(esc).join('<br>')+'</div></div>';
      if (d.names && d.names.length) {
        detail += '<div><div style="color:#4fc3f7;margin-bottom:2px">Names</div><div style="color:#9ecbff">'+(d.names||[]).map(esc).join('<br>')+'</div></div>';
      }
      detail += '<div><div style="color:#4fc3f7;margin-bottom:2px">Fingerprint</div><div style="font-family:monospace;color:#888">'+esc(d.dev_sig||'')+'</div></div>';
      detail += '</div>';
      rows.push('<tr><td colspan="9" style="padding:0">'+detail+'</td></tr>');
    }
  });
  tbody.innerHTML = rows.join('');
}

function toggleDevRow(sub, encKey) {
  const key = decodeURIComponent(encKey);
  const s = _devExpanded[sub];
  if (s.has(key)) s.delete(key); else s.add(key);
  renderDevices();
}

function switchDevSubtab(name) {
  _devSubtab = name;
  document.querySelectorAll('.dev-subtab-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.sub === name);
  });
  document.querySelectorAll('.dev-subpane').forEach(p => {
    p.style.display = p.dataset.sub === name ? 'block' : 'none';
  });
}

document.querySelectorAll('.dev-subtab-btn').forEach(btn => {
  btn.addEventListener('click', () => switchDevSubtab(btn.dataset.sub));
});
document.querySelectorAll('th.sortable').forEach(th => {
  th.addEventListener('click', () => {
    if (th.dataset.sub) devSortBy(th.dataset.sub, th.dataset.key);
    else if (th.dataset.tbl) tblSortBy(th.dataset.tbl, th.dataset.key);
  });
});
document.getElementById('dev-active-only').addEventListener('change', () => renderDevices());

// --- Session switcher (header dropdown) ---
// "" = LIVE (tailed current session). Non-empty = basename of a historical
// .db file. Only category tabs honor this; Live/Log/Timeline always show
// the active session.
let _selectedSession = "";

async function loadSessions() {
  try {
    const r = await fetch('/api/sessions');
    const data = await r.json();
    const sel = document.getElementById('session-select');
    if (!sel) return;
    // Remember current selection; reset options
    const prev = sel.value;
    sel.innerHTML = '<option value="">LIVE</option>';
    (data.sessions || []).forEach(s => {
      const opt = document.createElement('option');
      opt.value = s.name;
      const when = s.mtime_iso ? s.mtime_iso.replace('T', ' ') : '';
      const n = s.detection_count || 0;
      const live = s.live ? ' (live)' : '';
      opt.textContent = s.name + live + ' — ' + n + ' dets — ' + when;
      sel.appendChild(opt);
    });
    // Restore prior selection if it still exists
    if (prev && Array.from(sel.options).some(o => o.value === prev)) {
      sel.value = prev;
    }
  } catch(e) {}
}

function onSessionChange() {
  const sel = document.getElementById('session-select');
  _selectedSession = sel.value || "";
  const status = document.getElementById('session-status');
  if (_selectedSession) {
    status.textContent = 'BROWSING';
    status.style.color = '#ff9800';
  } else {
    status.textContent = 'LIVE';
    status.style.color = '#4caf50';
  }
  // Refresh the active category tab, if any
  const activeBtn = document.querySelector('.tab-btn.active');
  const tab = activeBtn ? activeBtn.dataset.tab : null;
  if (tab && ['voice','drones','aircraft','vessels','keyfobs','tpms','cellular','ism','lora','pagers'].includes(tab)) {
    loadCategory(tab);
  }
}

// --- Signals parent tab + sub-nav ---
// The seven category tabs (Voice/Drones/Aircraft/Vessels/Vehicles/Cellular/
// Other) used to be top-level tab buttons. They're now sub-panes under a
// single "Signals" tab, grouped with a sub-nav row that reuses the same
// styling as the Devices sub-tabs. Category names still uniquely
// identify each pane — nothing downstream changed.
let _sigSubtab = 'voice';

function switchSigSubtab(name) {
  _sigSubtab = name;
  document.querySelectorAll('.sig-subtab-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.sub === name);
  });
  document.querySelectorAll('.sig-subpane').forEach(p => {
    p.style.display = p.dataset.sub === name ? 'block' : 'none';
  });
  loadCategory(name);
}

document.querySelectorAll('.sig-subtab-btn').forEach(btn => {
  btn.addEventListener('click', () => switchSigSubtab(btn.dataset.sub));
});

// Category filter change events — re-render without refetch. Reset
// pagination to page 1 so the user isn't stranded on an offset that's
// past the filtered dataset's end.
function _onFilterChange(cat) {
  _categoryOffset[cat] = 0;
  _renderFiltered(cat);
}
['voice','drones','cellular','ism'].forEach(cat => {
  const typeSel = document.getElementById(cat + '-filter-type');
  if (typeSel) typeSel.addEventListener('change', () => _onFilterChange(cat));
  const chSel = document.getElementById(cat + '-filter-ch');
  if (chSel) chSel.addEventListener('change', () => _onFilterChange(cat));
  const audioChk = document.getElementById(cat + '-filter-audio');
  if (audioChk) audioChk.addEventListener('change', () => _onFilterChange(cat));
  const txChk = document.getElementById(cat + '-filter-transcript');
  if (txChk) txChk.addEventListener('change', () => _onFilterChange(cat));
});

// --- Category Tabs ---
const _CATEGORY_BODY_IDS = {
  voice:    'voice-body',
  drones:   'drones-body',
  aircraft: 'aircraft-body',
  vessels:  'vessels-body',
  keyfobs:  'keyfobs-body',
  tpms:     'tpms-body',
  cellular: 'cellular-body',
  ism:      'ism-body',
  lora:       'lora-body',
  meshtastic: 'meshtastic-body',
  pagers:     'pagers-body',
};

// Raw rows cache for client-side filtering
const _categoryRows = {};
// Per-category pagination offset (in rows, not pages)
const _categoryOffset = {};
const _CATEGORY_PAGE_SIZE = 50;

async function loadCategory(name) {
  try {
    let url = '/api/cat/' + encodeURIComponent(name);
    if (_selectedSession) {
      url += '?session=' + encodeURIComponent(_selectedSession);
    }
    const r = await fetch(url);
    const data = await r.json();
    const rows = data.rows || [];
    _categoryRows[name] = rows;
    _populateFilters(name, rows);
    _renderFiltered(name);
  } catch(e) {}
}

function _renderFiltered(name) {
  const rows = _categoryRows[name] || [];
  const filtered = _applyFilters(name, rows);
  const total = filtered.length;
  const limit = _CATEGORY_PAGE_SIZE;
  // Clamp the saved offset after filters shrink the dataset
  let offset = _categoryOffset[name] || 0;
  if (offset >= total) offset = Math.max(0, total - limit);
  _categoryOffset[name] = offset;
  const page = filtered.slice(offset, offset + limit);
  const fn = _CATEGORY_RENDERERS[name];
  const bodyId = _CATEGORY_BODY_IDS[name];
  if (fn && bodyId) setTable(bodyId, page, fn);
  _renderPager(name + '-pager', {
    total, offset, limit,
    onChange: (newOffset) => {
      _categoryOffset[name] = Math.max(0, Math.min(newOffset, Math.max(0, total - 1)));
      _renderFiltered(name);
    },
  });
}

function _populateFilters(name, rows) {
  // Populate type dropdown
  const typeSel = document.getElementById(name + '-filter-type');
  if (typeSel) {
    const prev = typeSel.value;
    const types = [...new Set(rows.map(r => r.signal_type || r.technology || r.kind || '').filter(Boolean))].sort();
    typeSel.innerHTML = '<option value="">All Types</option>' +
      types.map(t => '<option value="'+esc(t)+'">'+esc(t)+'</option>').join('');
    typeSel.value = prev;
  }
  // Populate channel dropdown (voice)
  const chSel = document.getElementById(name + '-filter-ch');
  if (chSel) {
    const prev = chSel.value;
    const chs = [...new Set(rows.map(r => r.channel || '').filter(Boolean))].sort();
    chSel.innerHTML = '<option value="">All Channels</option>' +
      chs.map(c => '<option value="'+esc(c)+'">'+esc(c)+'</option>').join('');
    chSel.value = prev;
  }
}

function _applyFilters(name, rows) {
  let out = rows;
  // Type filter
  const typeSel = document.getElementById(name + '-filter-type');
  if (typeSel && typeSel.value) {
    const v = typeSel.value;
    out = out.filter(r => (r.signal_type || r.technology || r.kind || '') === v);
  }
  // Channel filter (voice)
  const chSel = document.getElementById(name + '-filter-ch');
  if (chSel && chSel.value) {
    const v = chSel.value;
    out = out.filter(r => r.channel === v);
  }
  // Audio only (voice)
  const audioChk = document.getElementById(name + '-filter-audio');
  if (audioChk && audioChk.checked) {
    out = out.filter(r => r.audio_file);
  }
  // With transcript (voice)
  const txChk = document.getElementById(name + '-filter-transcript');
  if (txChk && txChk.checked) {
    out = out.filter(r => r.transcript);
  }
  return out;
}

function _emptyRow(bodyId, cols, msg) {
  const tbody = document.getElementById(bodyId);
  if (tbody) tbody.innerHTML = '<tr><td colspan="'+cols+'" class="empty">'+esc(msg)+'</td></tr>';
}

function _fmtCoord(lat, lon) {
  if (lat == null || lon == null) return '-';
  return lat.toFixed(4) + ', ' + lon.toFixed(4);
}

function renderVoice(rows) {
  const tbody = document.getElementById('voice-body');
  if (!rows.length) { _emptyRow('voice-body', 8, 'no voice transmissions yet'); return; }
  tbody.innerHTML = rows.map(r => {
    const ts = r.timestamp ? r.timestamp.split('T')[1].split('.')[0] : '-';
    const color = TYPE_COLORS[r.signal_type] || '#ccc';
    const dur = r.duration_s != null ? (+r.duration_s).toFixed(1)+'s' : '-';
    const tx = r.transcript || '';
    const audio = r.audio_file
      ? '<button class="play-btn" onclick="playAudio(this,\''+esc(r.audio_file)+'\')">&#9654;</button>'
      : '';
    return '<tr>'
      + '<td>'+ts+'</td>'
      + '<td class="sig-type" style="color:'+color+'">'+esc(r.signal_type)+'</td>'
      + '<td>'+esc(r.channel||'-')+'</td>'
      + '<td class="num">'+(r.frequency_mhz ? r.frequency_mhz.toFixed(3) : '-')+'</td>'
      + '<td class="num">'+dur+'</td>'
      + '<td class="num">'+(r.snr_db != null ? r.snr_db+' dB' : '-')+'</td>'
      + '<td class="detail'+(tx?' transcript':'')+'">'+esc(tx?('\u201c'+tx+'\u201d'):'')+'</td>'
      + '<td>'+audio+'</td>'
      + '</tr>';
  }).join('');
}

function renderDrones(rows) {
  const tbody = document.getElementById('drones-body');
  if (!rows.length) { _emptyRow('drones-body', 9, 'no drones detected — RemoteID / DroneCtrl / DroneVideo not seen yet'); return; }
  tbody.innerHTML = rows.map(r => {
    const color = TYPE_COLORS[r.signal_type] || '#ccc';
    const pos = _fmtCoord(r.last_lat, r.last_lon);
    const alt = r.altitude_m != null ? r.altitude_m.toFixed(0)+' m' : '-';
    const spd = r.speed_ms != null ? r.speed_ms.toFixed(1)+' m/s' : '-';
    const op  = _fmtCoord(r.op_lat, r.op_lon);
    return '<tr>'
      + '<td class="sig-type" style="color:'+color+'">'+esc(r.signal_type)+'</td>'
      + '<td style="font-family:monospace">'+esc(r.serial||r.key||'-')+'</td>'
      + '<td>'+esc(r.ua_type||'')+'</td>'
      + '<td>'+esc(r.protocol||'')+'</td>'
      + '<td style="font-size:11px">'+pos+'</td>'
      + '<td class="num">'+alt+'</td>'
      + '<td class="num">'+spd+'</td>'
      + '<td style="font-size:11px">'+op+'</td>'
      + '<td style="font-size:11px">'+(r.last_seen||'-')+'</td>'
      + '</tr>';
  }).join('');
}

function renderAircraft(rows) {
  const tbody = document.getElementById('aircraft-body');
  if (!rows.length) { _emptyRow('aircraft-body', 11, 'no aircraft detected — ADS-B capture not running'); return; }
  tbody.innerHTML = rows.map(r => {
    const alt = r.altitude_ft != null ? r.altitude_ft+' ft' : '-';
    const spd = r.speed_kt != null ? r.speed_kt.toFixed(0)+' kt' : '-';
    const hdg = r.heading != null ? r.heading.toFixed(0)+'\u00b0' : '-';
    const vr = r.vertical_rate != null ? (r.vertical_rate >= 0 ? '+' : '') + r.vertical_rate + ' fpm' : '-';
    const pos = _fmtCoord(r.latitude, r.longitude);
    const squawk = r.squawk || '-';
    const sqStyle = r.emergency ? 'color:#f44336;font-weight:600' : '';
    const sqLabel = r.emergency ? esc(squawk) + ' <span style="color:#f44336;font-size:10px">' + esc(r.emergency) + '</span>' : esc(squawk);
    const cat = r.category || '-';
    const ground = r.on_ground ? '<span style="color:#ff9800;font-size:10px;margin-left:4px">GND</span>' : '';
    return '<tr>'
      + '<td style="font-family:monospace">'+esc(r.icao)+'</td>'
      + '<td style="font-weight:600">'+esc(r.callsign||'-')+'</td>'
      + '<td>'+esc(cat)+ground+'</td>'
      + '<td class="num">'+alt+'</td>'
      + '<td class="num">'+spd+'</td>'
      + '<td class="num">'+hdg+'</td>'
      + '<td class="num">'+vr+'</td>'
      + '<td style="'+sqStyle+'">'+sqLabel+'</td>'
      + '<td style="font-size:11px">'+pos+'</td>'
      + '<td class="num">'+r.count+'</td>'
      + '<td style="font-size:11px">'+(r.last_seen||'-')+'</td>'
      + '</tr>';
  }).join('');
}

function renderVessels(rows) {
  const tbody = document.getElementById('vessels-body');
  if (!rows.length) { _emptyRow('vessels-body', 13, 'no vessels detected — AIS capture not running'); return; }
  tbody.innerHTML = rows.map(r => {
    const spd = r.speed_kn != null ? r.speed_kn.toFixed(1)+' kn' : '-';
    const crs = r.course != null ? r.course.toFixed(0)+'\u00b0' : '-';
    const hdg = r.heading != null && r.heading < 511 ? r.heading+'\u00b0' : '-';
    const dft = r.draught != null && r.draught > 0 ? r.draught.toFixed(1)+' m' : '-';
    const pos = _fmtCoord(r.latitude, r.longitude);
    return '<tr>'
      + '<td style="font-family:monospace">'+esc(r.mmsi)+'</td>'
      + '<td style="font-weight:600">'+esc(r.name||'-')+'</td>'
      + '<td>'+esc(r.callsign||'-')+'</td>'
      + '<td>'+esc(r.ship_type||'')+'</td>'
      + '<td>'+esc(r.nav_status||'')+'</td>'
      + '<td>'+esc(r.destination||'-')+'</td>'
      + '<td class="num">'+spd+'</td>'
      + '<td class="num">'+crs+'</td>'
      + '<td class="num">'+hdg+'</td>'
      + '<td class="num">'+dft+'</td>'
      + '<td style="font-size:11px">'+pos+'</td>'
      + '<td class="num">'+r.count+'</td>'
      + '<td style="font-size:11px">'+(r.last_seen||'-')+'</td>'
      + '</tr>';
  }).join('');
}

function renderKeyfobs(rows) {
  const tbody = document.getElementById('keyfobs-body');
  if (!rows.length) { _emptyRow('keyfobs-body', 6, 'no keyfob detections yet'); return; }
  tbody.innerHTML = rows.map(r => {
    return '<tr>'
      + '<td style="font-family:monospace">'+esc(r.id)+'</td>'
      + '<td>'+esc(r.protocol||'')+'</td>'
      + '<td class="num">'+(r.frequency_mhz ? r.frequency_mhz.toFixed(3) : '-')+'</td>'
      + '<td class="num">'+(r.snr_db != null ? r.snr_db+' dB' : '-')+'</td>'
      + '<td class="num">'+r.count+'</td>'
      + '<td style="font-size:11px">'+(r.last_seen||'-')+'</td>'
      + '</tr>';
  }).join('');
}

function renderTpms(rows) {
  const tbody = document.getElementById('tpms-body');
  if (!rows.length) { _emptyRow('tpms-body', 7, 'no TPMS detections yet'); return; }
  tbody.innerHTML = rows.map(r => {
    const pressure = r.pressure_kpa != null ? r.pressure_kpa.toFixed(0)+' kPa' : '-';
    const temp     = r.temperature_c != null ? r.temperature_c.toFixed(0)+' \u00b0C' : '-';
    return '<tr>'
      + '<td style="font-family:monospace">'+esc(r.id)+'</td>'
      + '<td>'+esc(r.protocol||'')+'</td>'
      + '<td class="num">'+(r.frequency_mhz ? r.frequency_mhz.toFixed(3) : '-')+'</td>'
      + '<td class="num">'+pressure+'</td>'
      + '<td class="num">'+temp+'</td>'
      + '<td class="num">'+r.count+'</td>'
      + '<td style="font-size:11px">'+(r.last_seen||'-')+'</td>'
      + '</tr>';
  }).join('');
}

function renderCellular(rows) {
  const tbody = document.getElementById('cellular-body');
  if (!rows.length) { _emptyRow('cellular-body', 7, 'no cellular uplink activity detected'); return; }
  tbody.innerHTML = rows.map(r => {
    return '<tr>'
      + '<td style="font-weight:600;color:#ff7043">'+esc(r.technology)+'</td>'
      + '<td style="font-size:11px">'+esc(r.band)+'</td>'
      + '<td>'+esc(r.channel||'-')+'</td>'
      + '<td class="num">'+(r.frequency_mhz ? r.frequency_mhz.toFixed(3) : '-')+'</td>'
      + '<td class="num">'+r.count+'</td>'
      + '<td class="num">'+(r.last_snr != null ? r.last_snr+' dB' : '-')+'</td>'
      + '<td style="font-size:11px">'+(r.last_seen||'-')+'</td>'
      + '</tr>';
  }).join('');
}

function _renderSignalRows(tbodyId, rows, emptyMsg) {
  const tbody = document.getElementById(tbodyId);
  if (!rows.length) { _emptyRow(tbodyId, 7, emptyMsg); return; }
  tbody.innerHTML = rows.map(r => {
    const ts = r.timestamp ? r.timestamp.split('T')[1].split('.')[0] : '-';
    const color = TYPE_COLORS[r.signal_type] || '#ccc';
    const info = [r.model, r.protocol].filter(Boolean).join(' / ');
    return '<tr>'
      + '<td>'+ts+'</td>'
      + '<td class="sig-type" style="color:'+color+'">'+esc(r.signal_type)+'</td>'
      + '<td>'+esc(r.channel||'-')+'</td>'
      + '<td class="num">'+(r.frequency_mhz ? r.frequency_mhz.toFixed(3) : '-')+'</td>'
      + '<td class="num">'+(r.snr_db != null ? r.snr_db+' dB' : '-')+'</td>'
      + '<td>'+esc(info)+'</td>'
      + '<td class="detail">'+esc(r.detail||'')+'</td>'
      + '</tr>';
  }).join('');
}

function renderIsm(rows)    { _renderSignalRows('ism-body', rows, 'no ISM detections yet'); }
function renderLora(rows)   { _renderSignalRows('lora-body', rows, 'no LoRa detections yet'); }

function renderMeshtastic(rows) {
  const tbody = document.getElementById('meshtastic-body');
  if (!rows.length) { _emptyRow('meshtastic-body', 8, 'no Meshtastic traffic yet \u2014 connect a Meshtastic device via sdr.py mesh'); return; }
  tbody.innerHTML = rows.map(r => {
    const snr = r.snr != null ? r.snr.toFixed(1) : '-';
    const hops = r.hops != null ? r.hops : '-';
    const pos = _fmtCoord(r.latitude, r.longitude);
    const typeColors = {Position:'#4caf50', Telemetry:'#ff9800', Node:'#9e9e9e'};
    const color = typeColors[r.subtype] || '#ccc';
    return '<tr>'
      + '<td style="font-size:11px">'+(r.timestamp||'-')+'</td>'
      + '<td><span style="color:'+color+';font-weight:600">'+esc(r.subtype||'')+'</span></td>'
      + '<td style="font-weight:600">'+esc(r.node_name||'-')+'</td>'
      + '<td style="font-family:monospace;font-size:11px">'+esc(r.node_id||'')+'</td>'
      + '<td>'+esc(r.detail||'')+'</td>'
      + '<td class="num">'+snr+'</td>'
      + '<td class="num">'+hops+'</td>'
      + '<td style="font-size:11px">'+pos+'</td>'
      + '</tr>';
  }).join('');
}

function renderPagers(rows) { _renderSignalRows('pagers-body', rows, 'no pager messages yet'); }

const _CATEGORY_RENDERERS = {
  voice:    renderVoice,
  drones:   renderDrones,
  aircraft: renderAircraft,
  vessels:  renderVessels,
  keyfobs:  renderKeyfobs,
  tpms:     renderTpms,
  cellular: renderCellular,
  ism:      renderIsm,
  lora:       renderLora,
  meshtastic: renderMeshtastic,
  pagers:     renderPagers,
};

// --- FPV Video Feed ---
let _fpvStreaming = false;
let _fpvPollTimer = null;

function fpvCheckFrame() {
  // Probe if fpv_latest.png exists, show/hide section accordingly
  const section = document.getElementById('fpv-section');
  if (!section) return;
  const img = document.getElementById('fpv-frame');
  const empty = document.getElementById('fpv-empty');
  if (_fpvStreaming) return;
  // Load frame directly — if it succeeds, show the section
  const test = new Image();
  test.onload = () => {
    section.style.display = '';
    img.src = test.src;
    img.style.display = '';
    empty.style.display = 'none';
  };
  test.src = '/api/fpv/frame?t=' + Date.now();
}

function fpvLoadFrame() {
  const img = document.getElementById('fpv-frame');
  const empty = document.getElementById('fpv-empty');
  img.src = '/api/fpv/frame?t=' + Date.now();
  img.onload = () => { img.style.display = ''; empty.style.display = 'none'; };
  img.onerror = () => { img.style.display = 'none'; empty.style.display = ''; };
}

function fpvToggleStream() {
  const img = document.getElementById('fpv-frame');
  const empty = document.getElementById('fpv-empty');
  _fpvStreaming = !_fpvStreaming;
  if (_fpvStreaming) {
    img.src = '/api/fpv/stream';
    img.style.display = '';
    empty.style.display = 'none';
    document.getElementById('fpv-info').textContent = 'STREAMING';
  } else {
    img.src = '';
    img.style.display = 'none';
    document.getElementById('fpv-info').textContent = '';
    fpvLoadFrame();
  }
}

// Check for FPV frames when drones tab is active
setInterval(() => {
  const activeBtn = document.querySelector('.sig-subtab-btn.active');
  if (activeBtn && activeBtn.dataset.sub === 'drones') fpvCheckFrame();
}, 3000);

// --- Activity Tab ---
async function loadActivity() {
  try {
    const r = await fetch('/api/activity?minutes=60');
    const data = await r.json();

    const allTypes = new Set();
    data.forEach(m => Object.keys(m.counts).forEach(t => allTypes.add(t)));
    const types = Array.from(allTypes);

    const maxTotal = Math.max(1, ...data.map(m => m.total));

    const W = 800, H = 200, PAD = 40;
    const barW = Math.max(1, (W - PAD * 2) / data.length);

    let svg = '<svg viewBox="0 0 '+W+' '+(H+30)+'" style="width:100%;height:auto">';

    // Gridlines
    for (let g = 0; g <= 4; g++) {
      const gy = PAD + (H - PAD) * (1 - g/4);
      svg += '<line x1="'+PAD+'" y1="'+gy+'" x2="'+(W-10)+'" y2="'+gy+'" stroke="#0f3460" stroke-width="0.5"/>';
      svg += '<text x="'+(PAD-4)+'" y="'+(gy+3)+'" fill="#888" font-size="9" text-anchor="end" font-family="monospace">'+Math.round(maxTotal*g/4)+'</text>';
    }

    data.forEach((m, i) => {
      const x = PAD + i * barW;
      let y = H;
      types.forEach(t => {
        const count = m.counts[t] || 0;
        if (!count) return;
        const barH = (count / maxTotal) * (H - PAD);
        y -= barH;
        const color = TYPE_COLORS[t] || '#ccc';
        svg += '<rect x="'+x+'" y="'+y+'" width="'+Math.max(1,barW-1)+'" height="'+barH+'" fill="'+color+'" opacity="0.8">'
             + '<title>'+m.minute.slice(11)+' '+t+': '+count+'</title></rect>';
      });
      if (i % 10 === 0) {
        svg += '<text x="'+(x+barW/2)+'" y="'+(H+15)+'" fill="#888" font-size="9" text-anchor="middle" font-family="monospace">'+m.minute.slice(11)+'</text>';
      }
    });

    svg += '</svg>';
    document.getElementById('activity-chart').innerHTML = svg;

    // Summary
    const totals = {};
    data.forEach(m => Object.entries(m.counts).forEach(([t,c]) => totals[t]=(totals[t]||0)+c));
    document.getElementById('activity-summary').innerHTML = Object.entries(totals)
      .sort((a,b) => b[1]-a[1])
      .map(([t,c]) => '<span style="color:'+(TYPE_COLORS[t]||'#ccc')+'">'+esc(t)+'</span>: '+c)
      .join('&nbsp;&nbsp;&nbsp;');
  } catch(e) {}
}

// --- Tab Navigation ---
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => {
      c.classList.remove('active'); c.style.display = 'none';
    });
    btn.classList.add('active');
    const panel = document.getElementById('tab-' + btn.dataset.tab);
    panel.classList.add('active');
    panel.style.display = 'block';
    // replaceState instead of location.hash — the latter triggers a
    // jump-to-anchor if any element on the page happens to share the id
    // (e.g. the Leaflet map container is <div id="map">, which makes
    // clicking the Map tab scroll the page down to it).
    history.replaceState(null, '', '#' + btn.dataset.tab);
    if (btn.dataset.tab === 'log') loadDetections();
    if (btn.dataset.tab === 'devices') loadDevices();
    if (btn.dataset.tab === 'config') loadConfig();
    if (btn.dataset.tab === 'timeline') loadActivity();
    if (btn.dataset.tab === 'map') {
      initMap();
      loadMap();
    }
    if (btn.dataset.tab === 'correlations') loadCorrelations();
    if (btn.dataset.tab === 'agents') fetchAgents();
    if (btn.dataset.tab === 'signals') loadCategory(_sigSubtab);
  });
});

// Category names resolve into the Signals parent + a sub-tab switch.
// Everything else is a plain top-tab click.
const _SIGNAL_CATEGORIES = ['voice','drones','aircraft','vessels','keyfobs','tpms','cellular','ism','lora','meshtastic','pagers'];

function goToTab(name) {
  if (_SIGNAL_CATEGORIES.includes(name)) {
    const btn = document.querySelector('.tab-btn[data-tab="signals"]');
    if (btn) btn.click();
    switchSigSubtab(name);
    return;
  }
  const btn = document.querySelector('.tab-btn[data-tab="'+name+'"]');
  if (btn) btn.click();
}

// Auto-refresh Config tab every 3s so status badges stay live
setInterval(() => {
  const cfgTab = document.getElementById('tab-config');
  if (cfgTab && cfgTab.classList.contains('active')) loadConfig();
}, 3000);

// Auto-refresh the active signals sub-pane every 3s. Skips when a
// historical session is selected from the dropdown (that data never
// changes) and skips when the document is hidden (background tab).
setInterval(() => {
  if (_selectedSession) return;
  if (document.hidden) return;
  const activeBtn = document.querySelector('.tab-btn.active');
  if (activeBtn && activeBtn.dataset.tab === 'signals') {
    loadCategory(_sigSubtab);
  }
}, 3000);

// --- Device Correlations tab ---
// Reads output/correlations.json, which the server's live
// DeviceCorrelator writes every 30s from the real-time _on_detection
// hook. Pairs and clusters both shown; no filtering yet.
async function loadCorrelations() {
  try {
    const r = await fetch('/api/correlations');
    const data = await r.json();
    renderCorrelations(data);
  } catch (e) {}
}

let _corrEmptyNote = '';

function renderCorrPairs(pairs) {
  const tbody = document.getElementById('corr-body');
  if (!pairs.length) {
    tbody.innerHTML = '<tr><td colspan="7" class="empty">'
      + esc(_corrEmptyNote || 'no correlated pairs yet — run the server for a few minutes to accumulate co-occurrences')
      + '</td></tr>';
    return;
  }
  tbody.innerHTML = pairs.map(p => {
    const ratioColor = p.ratio >= 0.9 ? '#4caf50' : p.ratio >= 0.7 ? '#ffeb3b' : '#e0e0e0';
    const xBadge = p.cross_transport
      ? '<span style="background:#0f3460;color:#9ecbff;padding:0 5px;border-radius:3px;font-size:10px" title="Correlated across different signal types (e.g. WiFi + BLE)">cross</span>'
      : '';
    return '<tr>'
      + '<td style="font-family:monospace;font-size:11px">' + esc(p.device_a) + '</td>'
      + '<td style="font-family:monospace;font-size:11px">' + esc(p.device_b) + '</td>'
      + '<td class="num">' + p.co_occurrences + '</td>'
      + '<td class="num">' + p.total_a + '</td>'
      + '<td class="num">' + p.total_b + '</td>'
      + '<td class="num" style="color:' + ratioColor + '">' + (p.ratio * 100).toFixed(0) + '%</td>'
      + '<td>' + xBadge + '</td>'
      + '</tr>';
  }).join('');
}

function renderCorrelations(data) {
  const pairs = data.correlated_pairs || [];
  const clusters = data.clusters || [];
  const total = data.total_devices || 0;
  const ts = data.timestamp ? data.timestamp.replace('T', ' ').split('.')[0] : '—';

  const summary = document.getElementById('corr-summary');
  if (summary) {
    summary.textContent = `${pairs.length} pair${pairs.length === 1 ? '' : 's'} · `
      + `${clusters.length} cluster${clusters.length === 1 ? '' : 's'} · `
      + `${total} device${total === 1 ? '' : 's'} · last ${ts}`;
  }

  _corrEmptyNote = data.note || '';
  setTable('corr-body', pairs, renderCorrPairs);

  const clustEl = document.getElementById('corr-clusters');
  if (!clusters.length) {
    clustEl.innerHTML = '<div class="empty">no clusters yet — a cluster is 2+ devices that all correlate transitively</div>';
  } else {
    clustEl.innerHTML = clusters.map((c, i) =>
      '<div style="padding:6px 0;border-bottom:1px solid #0f3460">'
      + '<div style="color:#4fc3f7;font-weight:600;font-size:11px;margin-bottom:4px">Cluster ' + (i + 1) + ' (' + c.length + ' devices)</div>'
      + '<div style="font-family:monospace;font-size:11px;color:#ccc">'
      + c.map(esc).join('<br>')
      + '</div></div>'
    ).join('');
  }
}

// Auto-refresh Correlations tab every 10s while active (the server
// publishes every 30s so any faster is wasted work).
setInterval(() => {
  if (_selectedSession) return;
  if (document.hidden) return;
  const activeBtn = document.querySelector('.tab-btn.active');
  if (activeBtn && activeBtn.dataset.tab === 'correlations') loadCorrelations();
}, 10000);

// --- Situational Awareness Map (Leaflet) ---
// Lazy-initialized on first Map tab activation. Markers are grouped by
// layer (aircraft/vessels/drones/operators); each layer is toggleable
// via the checkbox row. Auto-refreshes every 3s when the Map tab is
// visible; historical session freezes the map like other category tabs.
let _map = null;
const _mapLayers = {
  aircraft:    null,
  vessels:     null,
  drones:      null,
  operators:   null,
  meshtastic:  null,
};
const _MAP_COLORS = {
  aircraft:    '#2196f3',
  vessels:     '#4caf50',
  drones:      '#f44336',
  operators:   '#ff9800',
  meshtastic:  '#ab47bc',
};

// Source-based layers: one per detection source (server + each agent).
// { id -> {color, position, detections, enabled, markerLayer, ringsLayer} }
const _mapSources = {};
// Stable colour assignment per source id.
const _SOURCE_PALETTE = [
  '#ffd54f', '#4dd0e1', '#f06292', '#81c784', '#ba68c8',
  '#ff8a65', '#9fa8da', '#a1887f', '#dce775',
];
const _SERVER_COLOR = '#29b6f6';
function _sourceColor(id, idx) {
  if (id === 'server') return _SERVER_COLOR;
  return _SOURCE_PALETTE[idx % _SOURCE_PALETTE.length];
}

// Per-signal-type path-loss parameters for the uncalibrated distance
// estimate rendered as rings around each source. n is the path-loss
// exponent; snr_ref_db is a rough SNR-at-1m baseline. Values borrowed
// from docs/triangulation.md, adapted to SNR (rather than dBm RSSI,
// which we can't trust without calibration).
const _PATH_LOSS = {
  'PMR446':   {n: 2.2, snr_1m: 40},
  'dPMR':     {n: 2.2, snr_1m: 40},
  '70cm':     {n: 2.2, snr_1m: 40},
  '2m':       {n: 2.2, snr_1m: 40},
  'FRS':      {n: 2.2, snr_1m: 40},
  'MarineVHF':{n: 2.2, snr_1m: 40},
  'FM_voice': {n: 2.2, snr_1m: 40},
  'keyfob':   {n: 2.7, snr_1m: 35},
  'tpms':     {n: 2.5, snr_1m: 30},
  'GSM':      {n: 3.0, snr_1m: 40},
  'LTE':      {n: 3.0, snr_1m: 40},
  'BLE-Adv':  {n: 2.5, snr_1m: 40},
  'WiFi-Probe':{n: 2.7, snr_1m: 40},
  'WiFi-AP':  {n: 2.7, snr_1m: 40},
  'lora':     {n: 2.3, snr_1m: 35},
  '_default': {n: 2.5, snr_1m: 40},
};
function _distanceFromSnr(signal_type, snr_db) {
  if (snr_db == null) return null;
  const pl = _PATH_LOSS[signal_type] || _PATH_LOSS._default;
  // distance = 10^((snr_1m - snr) / (10 * n))
  const d = Math.pow(10, (pl.snr_1m - snr_db) / (10 * pl.n));
  // clamp to something sane so a stray low-SNR hit doesn't paint a
  // 50 km circle that dominates the map
  return Math.max(1, Math.min(d, 5000));
}

function initMap() {
  if (_map || typeof L === 'undefined') return;
  _map = L.map('map', {
    center: [0, 0],
    zoom: 2,
    worldCopyJump: true,
  });
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap contributors',
  }).addTo(_map);
  for (const k of Object.keys(_mapLayers)) {
    _mapLayers[k] = L.layerGroup().addTo(_map);
  }
  // Re-sync layer visibility when checkboxes change
  for (const k of Object.keys(_mapLayers)) {
    const cb = document.getElementById('map-show-' + k);
    if (cb) cb.addEventListener('change', () => {
      if (cb.checked) _map.addLayer(_mapLayers[k]);
      else _map.removeLayer(_mapLayers[k]);
    });
  }
  // Age filter: refetch on change.
  const ageSel = document.getElementById('map-age-limit');
  if (ageSel) ageSel.addEventListener('change', () => loadMap());
  // Force Leaflet to recompute its size once the container is visible
  setTimeout(() => { if (_map) _map.invalidateSize(); }, 100);
}

function _mapMarker(lat, lon, color, popup) {
  return L.circleMarker([lat, lon], {
    radius: 6,
    color: color,
    fillColor: color,
    fillOpacity: 0.8,
    weight: 2,
  }).bindPopup(popup);
}

function _planeMarker(lat, lon, color, heading, popup) {
  const svg = '<svg width="24" height="24" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
    + '<g transform="rotate(' + (heading || 0) + ' 12 12)">'
    + '<path d="M12 2 L14 9 L20 12 L14 13 L15 20 L12 18 L9 20 L10 13 L4 12 L10 9 Z" '
    + 'fill="' + color + '" stroke="#000" stroke-width="0.8"/>'
    + '</g></svg>';
  return L.marker([lat, lon], {
    icon: L.divIcon({
      html: svg,
      className: '',
      iconSize: [24, 24],
      iconAnchor: [12, 12],
    }),
  }).bindPopup(popup);
}

function _mapAgeWindowHours() {
  const sel = document.getElementById('map-age-limit');
  if (!sel || sel.value === '') return null;
  const h = parseFloat(sel.value);
  return Number.isFinite(h) && h > 0 ? h : null;
}

async function loadMap() {
  if (!_map) return;
  const windowHours = _mapAgeWindowHours();
  const params = [];
  if (_selectedSession) params.push('session=' + encodeURIComponent(_selectedSession));
  if (windowHours != null) params.push('window=' + windowHours);
  const qs = params.length ? '?' + params.join('&') : '';
  const tabs = ['aircraft', 'vessels', 'drones', 'meshtastic'];
  try {
    const results = await Promise.all(tabs.map(t =>
      fetch('/api/cat/' + t + qs).then(r => r.json()).catch(() => ({rows: []}))
    ));
    const [aircraft, vessels, drones, meshtastic] = results.map(d => d.rows || []);
    // Sources are session-independent — always union across all DBs.
    // The window filter applies to their detections, not to their node
    // positions (we want nodes pinned even if their last hit is stale).
    let sources = [];
    try {
      const srcQs = windowHours != null
        ? '?limit=100&window=' + windowHours : '?limit=100';
      const s = await fetch('/api/map/sources' + srcQs).then(r => r.json());
      sources = s.sources || [];
    } catch (e) {}
    _renderMap({aircraft, vessels, drones, meshtastic, sources});
  } catch (e) {}
}

function _syncSourcesState(sources) {
  // Preserve the `enabled` flag across refreshes; default new sources to on.
  const seen = new Set();
  sources.forEach((s, idx) => {
    seen.add(s.id);
    let state = _mapSources[s.id];
    if (!state) {
      state = {
        color: _sourceColor(s.id, idx),
        enabled: true,
        markerLayer: L.layerGroup(),
        ringsLayer: L.layerGroup(),
      };
      state.markerLayer.addTo(_map);
      state.ringsLayer.addTo(_map);
      _mapSources[s.id] = state;
    }
    state.position = s.position;
    state.detections = s.detections || [];
    state.label = s.label || s.id;
  });
  // Drop sources that vanished from the API response.
  Object.keys(_mapSources).forEach(id => {
    if (!seen.has(id)) {
      const st = _mapSources[id];
      if (st.markerLayer) _map.removeLayer(st.markerLayer);
      if (st.ringsLayer) _map.removeLayer(st.ringsLayer);
      delete _mapSources[id];
    }
  });
}

function _renderSourcesPanel() {
  const el = document.getElementById('map-sources-body');
  if (!el) return;
  const ids = Object.keys(_mapSources).sort((a, b) =>
    (a === 'server' ? -1 : b === 'server' ? 1 : a.localeCompare(b)));
  if (!ids.length) {
    el.innerHTML = '<div class="empty">no sources yet</div>';
    return;
  }
  el.innerHTML = ids.map(id => {
    const s = _mapSources[id];
    const hasPos = s.position && s.position.lat != null;
    const latest = (s.detections && s.detections[0]) || null;
    const latestTxt = latest
      ? esc(latest.signal_type) + ' · SNR '
        + (latest.snr_db != null ? latest.snr_db.toFixed(0) + ' dB' : '?')
      : '<span style="color:#666">no detections</span>';
    const posTxt = hasPos
      ? s.position.lat.toFixed(4) + ', ' + s.position.lon.toFixed(4)
      : '<span style="color:#666">no position</span>';
    return `<label style="display:flex; align-items:flex-start; gap:6px; padding:4px; cursor:pointer;">
      <input type="checkbox" data-src="${esc(id)}" ${s.enabled ? 'checked' : ''} style="margin-top:2px;">
      <span style="display:inline-block; width:10px; height:10px; border-radius:50%; background:${s.color}; margin-top:4px; flex-shrink:0;"></span>
      <span style="flex:1; min-width:0;">
        <div style="font-weight:600">${esc(s.label)}</div>
        <div style="color:#888; font-size:11px">${latestTxt}</div>
        <div style="color:#666; font-size:10px; font-family:monospace">${posTxt}</div>
        <div style="color:#666; font-size:10px">${(s.detections || []).length} recent</div>
      </span>
    </label>`;
  }).join('');
  el.querySelectorAll('input[type="checkbox"][data-src]').forEach(cb => {
    cb.addEventListener('change', () => {
      const id = cb.dataset.src;
      if (_mapSources[id]) {
        _mapSources[id].enabled = cb.checked;
        _drawSources();
      }
    });
  });
}

function _drawSources() {
  const bounds = [];
  Object.keys(_mapSources).forEach(id => {
    const s = _mapSources[id];
    s.markerLayer.clearLayers();
    s.ringsLayer.clearLayers();
    if (!s.enabled || !s.position || s.position.lat == null) return;
    const lat = s.position.lat, lon = s.position.lon;
    bounds.push([lat, lon]);
    // Node marker (bigger, permanent tooltip with the source id).
    L.circleMarker([lat, lon], {
      radius: 9, color: s.color, fillColor: s.color, fillOpacity: 0.9, weight: 3,
    })
      .bindPopup(`<b>${esc(s.label)}</b><br>${(s.detections || []).length} recent detections`)
      .bindTooltip(s.label, {permanent: true, direction: 'top', offset: [0, -10]})
      .addTo(s.markerLayer);
    // One uncertainty ring per recent detection with an SNR value.
    (s.detections || []).forEach(d => {
      const r = _distanceFromSnr(d.signal_type, d.snr_db);
      if (r == null) return;
      const popup = `<b>${esc(s.label)} · ${esc(d.signal_type || '')}</b><br>`
        + (d.channel ? esc(d.channel) + '<br>' : '')
        + (d.freq_mhz ? d.freq_mhz.toFixed(4) + ' MHz<br>' : '')
        + 'SNR ' + (d.snr_db != null ? d.snr_db.toFixed(1) + ' dB' : '?') + '<br>'
        + '~' + r.toFixed(0) + ' m (uncalibrated estimate)<br>'
        + '<span style="color:#888; font-size:10px">' + esc(d.timestamp || '') + '</span>';
      L.circle([lat, lon], {
        radius: r, color: s.color, fillColor: s.color, fillOpacity: 0.05, weight: 1,
      }).bindPopup(popup).addTo(s.ringsLayer);
    });
  });
  return bounds;
}

function _renderMap(data) {
  for (const k of Object.keys(_mapLayers)) {
    if (_mapLayers[k]) _mapLayers[k].clearLayers();
  }
  let positioned = 0;
  const bounds = [];

  (data.aircraft || []).forEach(a => {
    if (a.latitude == null || a.longitude == null) return;
    const popup = '<b>' + esc(a.callsign || a.icao) + '</b><br>'
      + esc(a.icao) + (a.category ? ' &middot; ' + esc(a.category) : '') + '<br>'
      + (a.altitude_ft != null ? a.altitude_ft + ' ft' : '-') + '<br>'
      + (a.speed_kt != null ? a.speed_kt.toFixed(0) + ' kt' : '') + ' '
      + (a.heading != null ? a.heading.toFixed(0) + '&deg;' : '')
      + (a.vertical_rate != null ? '<br>' + (a.vertical_rate >= 0 ? '+' : '') + a.vertical_rate + ' fpm' : '')
      + (a.squawk ? '<br>Squawk ' + esc(a.squawk) : '')
      + (a.emergency ? '<br><b style="color:#f44336">' + esc(a.emergency) + '</b>' : '')
      + (a.on_ground ? '<br><span style="color:#ff9800">On ground</span>' : '');
    _planeMarker(a.latitude, a.longitude, _MAP_COLORS.aircraft, a.heading, popup)
      .addTo(_mapLayers.aircraft);
    bounds.push([a.latitude, a.longitude]);
    positioned++;
  });

  (data.vessels || []).forEach(v => {
    if (v.latitude == null || v.longitude == null) return;
    const popup = '<b>' + esc(v.name || v.mmsi) + '</b>'
      + (v.callsign ? ' (' + esc(v.callsign) + ')' : '') + '<br>'
      + 'MMSI ' + esc(v.mmsi) + (v.imo ? ' &middot; IMO ' + esc(v.imo) : '') + '<br>'
      + (v.ship_type ? esc(v.ship_type) : '') + (v.nav_status ? ' &middot; ' + esc(v.nav_status) : '') + '<br>'
      + (v.speed_kn != null ? v.speed_kn.toFixed(1) + ' kn' : '-') + ' '
      + (v.course != null ? v.course.toFixed(0) + '&deg;' : '')
      + (v.destination ? '<br>Dest: ' + esc(v.destination) : '')
      + (v.draught != null && v.draught > 0 ? '<br>Draught: ' + v.draught.toFixed(1) + ' m' : '');
    _mapMarker(v.latitude, v.longitude, _MAP_COLORS.vessels, popup)
      .addTo(_mapLayers.vessels);
    bounds.push([v.latitude, v.longitude]);
    positioned++;
  });

  (data.drones || []).forEach(d => {
    if (d.last_lat != null && d.last_lon != null) {
      const popup = '<b>' + esc(d.serial || d.key) + '</b><br>'
        + esc(d.ua_type || d.signal_type) + '<br>'
        + (d.altitude_m != null ? d.altitude_m.toFixed(0) + ' m' : '-') + '<br>'
        + (d.speed_ms != null ? d.speed_ms.toFixed(1) + ' m/s' : '');
      _mapMarker(d.last_lat, d.last_lon, _MAP_COLORS.drones, popup)
        .addTo(_mapLayers.drones);
      bounds.push([d.last_lat, d.last_lon]);
      positioned++;
    }
    if (d.op_lat != null && d.op_lon != null) {
      const popup = '<b>Operator</b><br>' + esc(d.serial || d.key);
      _mapMarker(d.op_lat, d.op_lon, _MAP_COLORS.operators, popup)
        .addTo(_mapLayers.operators);
      bounds.push([d.op_lat, d.op_lon]);
      positioned++;
    }
  });

  // Meshtastic nodes — deduplicate by node_id, keep latest position
  const meshNodes = {};
  (data.meshtastic || []).forEach(m => {
    if (m.latitude == null || m.longitude == null) return;
    const id = m.node_id || m.detail;
    if (!id) return;
    const prev = meshNodes[id];
    if (!prev || m.timestamp > prev.timestamp) meshNodes[id] = m;
  });
  Object.values(meshNodes).forEach(m => {
    const popup = '<b>' + esc(m.node_name || m.node_id) + '</b><br>'
      + '<span style="font-family:monospace;font-size:11px">' + esc(m.node_id || '') + '</span><br>'
      + esc(m.subtype || '') + '<br>'
      + (m.snr != null ? 'SNR ' + m.snr.toFixed(1) + ' dB' : '')
      + (m.hops != null ? ' · ' + m.hops + ' hop(s)' : '')
      + (m.detail ? '<br>' + esc(m.detail) : '');
    _mapMarker(m.latitude, m.longitude, _MAP_COLORS.meshtastic, popup)
      .addTo(_mapLayers.meshtastic);
    bounds.push([m.latitude, m.longitude]);
    positioned++;
  });
  const meshCount = Object.keys(meshNodes).length;

  // Sources (server + agents): side panel + node markers + uncertainty rings
  _syncSourcesState(data.sources || []);
  _renderSourcesPanel();
  const sourceBounds = _drawSources();
  sourceBounds.forEach(b => bounds.push(b));
  const sourceCount = Object.values(_mapSources).filter(s => s.enabled && s.position).length;

  // Summary line
  const el = document.getElementById('map-summary');
  if (el) {
    el.textContent = positioned + sourceCount > 0
      ? positioned + ' position(s) on map (' + (data.aircraft.length) + ' aircraft, '
          + (data.vessels.length) + ' vessels, ' + (data.drones.length) + ' drones'
          + (meshCount > 0 ? ', ' + meshCount + ' mesh nodes' : '')
          + (sourceCount > 0 ? ', ' + sourceCount + ' source(s)' : '')
          + ')'
      : 'no GPS positions in the current session — run a capture with GPS, or wait for RemoteID / ADS-B / AIS';
  }

  // On first load, fit to data if we have any
  if (!_map._hasFit && bounds.length) {
    _map.fitBounds(bounds, {padding: [40, 40], maxZoom: 12});
    _map._hasFit = true;
  }
}

function mapFitAll() {
  if (!_map) return;
  const bounds = [];
  for (const g of Object.values(_mapLayers)) {
    if (!g) continue;
    g.eachLayer(m => {
      const ll = m.getLatLng();
      bounds.push([ll.lat, ll.lng]);
    });
  }
  if (bounds.length) _map.fitBounds(bounds, {padding: [40, 40], maxZoom: 14});
}

// Auto-refresh the Map tab on the same cadence as category tabs
setInterval(() => {
  if (_selectedSession) return;
  if (document.hidden) return;
  const activeBtn = document.querySelector('.tab-btn.active');
  if (activeBtn && activeBtn.dataset.tab === 'map') loadMap();
}, 3000);

// Session dropdown: initial load + change handler + periodic refresh so
// new sessions on disk show up without a full page reload.
loadSessions();
setInterval(loadSessions, 15000);
document.getElementById('session-select').addEventListener('change', onSessionChange);

if (location.hash) {
  goToTab(location.hash.slice(1));
}

// --- SSE Connection ---
let errorCount = 0;
let polling = false;

function connectSSE() {
  const dot = document.getElementById('status-dot');
  const txt = document.getElementById('status-text');
  const es = new EventSource('/api/events');

  es.onopen = () => {
    errorCount = 0;
    dot.className = 'status-dot';
    txt.textContent = 'live';
  };

  es.onmessage = (ev) => {
    try {
      const state = JSON.parse(ev.data);
      updateOverview(state);
      // Auto-refresh the Log tab when new state arrives (2s SSE cadence)
      const logTab = document.getElementById('tab-log');
      if (logTab && logTab.classList.contains('active') && !_selectedSession) {
        loadDetections();
      }
    } catch(e) {}
  };

  es.onerror = () => {
    es.close();
    errorCount++;
    dot.className = 'status-dot off';
    txt.textContent = 'reconnecting...';
    if (errorCount >= 3 && !polling) {
      polling = true;
      txt.textContent = 'polling';
      startPolling();
    } else if (!polling) {
      setTimeout(connectSSE, 2000);
    }
  };
}

function startPolling() {
  const dot = document.getElementById('status-dot');
  const txt = document.getElementById('status-text');
  setInterval(async () => {
    try {
      const r = await fetch('/api/state');
      const state = await r.json();
      updateOverview(state);
      dot.className = 'status-dot';
      txt.textContent = 'polling';
    } catch(e) {
      dot.className = 'status-dot off';
      txt.textContent = 'disconnected';
    }
  }, 3000);
}

// Refresh activity chart every 60s if active
setInterval(() => {
  const el = document.getElementById('tab-timeline');
  if (el && el.classList.contains('active')) loadActivity();
}, 60000);

// --- Generic pager helper ---
// Renders First/Prev/Next/Last controls + "n-m of TOTAL (page X/Y)"
// label into `containerId`. Calls `onChange(newOffset)` when the user
// clicks a control. Safe to call with total <= limit (renders just the
// count, no navigation).
function _renderPager(containerId, opts) {
  const el = document.getElementById(containerId);
  if (!el) return;
  const total = opts.total || 0;
  const limit = opts.limit || 50;
  const offset = Math.max(0, Math.min(opts.offset || 0, Math.max(0, total - 1)));
  const visible = Math.min(limit, Math.max(0, total - offset));
  if (total <= limit) {
    el.innerHTML = total
      ? `<span style="color:#888">${total} row${total === 1 ? '' : 's'}</span>`
      : '';
    return;
  }
  const pageCount = Math.ceil(total / limit);
  const currentPage = Math.floor(offset / limit) + 1;
  const first = offset + 1;
  const last = offset + visible;
  const prev = offset <= 0 ? 'disabled' : '';
  const next = last >= total ? 'disabled' : '';
  // Expose a stable global so inline onclick can call back. Each call
  // overrides the previous binding for this container.
  const slot = '__pager_' + containerId.replace(/-/g, '_');
  window[slot] = opts.onChange;
  el.innerHTML =
    `<button ${prev} onclick="window['${slot}'](0)">« First</button>` +
    `<button ${prev} onclick="window['${slot}'](${offset - limit})">‹ Prev</button>` +
    `<span style="padding: 0 8px; color:#888">${first}–${last} of ${total} (page ${currentPage}/${pageCount})</span>` +
    `<button ${next} onclick="window['${slot}'](${offset + limit})">Next ›</button>` +
    `<button ${next} onclick="window['${slot}'](${(pageCount - 1) * limit})">Last »</button>`;
}


// --- Agents tab ---
let _agentDetPage = 0;
const _AGENT_DET_PAGE_SIZE = 50;

async function fetchAgents() {
  try {
    const res = await fetch('/api/agents');
    const data = await res.json();
    renderPendingAgents(data.pending || {});
    renderApprovedAgents(data.approved || {}, data.info || {});
  } catch (e) {
    // leave existing rows in place on error
  }
  await loadAgentDetectionsPage(_agentDetPage);
}

async function loadAgentDetectionsPage(page) {
  _agentDetPage = Math.max(0, page);
  const offset = _agentDetPage * _AGENT_DET_PAGE_SIZE;
  try {
    const res = await fetch('/api/agents/detections?limit='
      + _AGENT_DET_PAGE_SIZE + '&offset=' + offset);
    const data = await res.json();
    renderAgentDetections(data);
  } catch (e) {
    // leave existing rows in place on error
  }
}

function renderAgentDetections(data) {
  const tbody = document.getElementById('agents-detections');
  if (!tbody) return;
  const rows = data.detections || [];
  const total = data.total || 0;
  const limit = data.limit || _AGENT_DET_PAGE_SIZE;
  const offset = data.offset || 0;
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="8" class="empty">no detections from agents yet</td></tr>';
  } else {
    tbody.innerHTML = rows.map(r => {
      const ts = r.timestamp ? (r.timestamp.split('T')[1]?.split('.')[0] || r.timestamp) : '';
      const geo = (r.latitude != null && r.longitude != null)
        ? `${r.latitude.toFixed(4)}, ${r.longitude.toFixed(4)}` : '';
      const rssi = (r.power_db != null) ? r.power_db.toFixed(1) : '';
      const snr = (r.snr_db != null) ? r.snr_db.toFixed(1) : '';
      return `<tr>
        <td>${esc(ts)}</td>
        <td>${esc(r.agent_id || '')}</td>
        <td>${esc(r.signal_type || '')}</td>
        <td>${esc(r.channel || '')}</td>
        <td>${r.freq_mhz ? r.freq_mhz.toFixed(4) : ''}</td>
        <td>${esc(rssi)}</td>
        <td>${esc(snr)}</td>
        <td>${esc(geo)}</td>
      </tr>`;
    }).join('');
  }
  _renderPager('agents-detections-pager', {
    total, offset, limit,
    onChange: (newOffset) => loadAgentDetectionsPage(Math.floor(newOffset / limit)),
  });
}

function renderPendingAgents(pending) {
  const tbody = document.getElementById('agents-pending');
  const ids = Object.keys(pending).sort();
  if (!ids.length) {
    tbody.innerHTML = '<tr><td colspan="5" class="empty">no pending agents</td></tr>';
    return;
  }
  tbody.innerHTML = ids.map(id => {
    const p = pending[id] || {};
    const seen = p.first_seen_at ? new Date(p.first_seen_at * 1000).toLocaleTimeString() : '';
    return `<tr>
      <td>${esc(id)}</td><td>${esc(p.hw || '')}</td><td>${esc(p.version || '')}</td>
      <td>${seen}</td>
      <td><button onclick="approveAgent('${esc(id)}')">Approve</button></td>
    </tr>`;
  }).join('');
}

function _fmtUptime(s) {
  if (s == null || s <= 0) return '';
  if (s < 60) return s + 's';
  if (s < 3600) return Math.floor(s / 60) + 'm';
  if (s < 86400) return Math.floor(s / 3600) + 'h ' + Math.floor((s % 3600) / 60) + 'm';
  return Math.floor(s / 86400) + 'd ' + Math.floor((s % 86400) / 3600) + 'h';
}

// Per-agent expand state — preserved across re-renders
const _agentExpanded = {};

function _toggleAgentRow(id) {
  _agentExpanded[id] = !_agentExpanded[id];
  fetchAgents();  // re-render
}

function _renderAgentConfig(id, info) {
  const cfg = (info || {}).config;
  if (!cfg) {
    return `<div style="padding: 8px 16px; color:#888; font-size:11px">
      no config received yet — waiting for the agent's CFGINFO snapshot
    </div>`;
  }
  const ageS = cfg.received_at ? Math.max(0, (Date.now() / 1000) - cfg.received_at) : null;
  const ageTxt = ageS != null ? _fmtUptime(Math.floor(ageS)) + ' ago' : '';
  return `<div style="padding: 8px 16px; font-size:11px; font-family:monospace; line-height:1.6">
    <div><span style="color:#888">version:</span> ${esc(cfg.version || '')} (${esc(cfg.hw || '')})</div>
    <div><span style="color:#888">meshtastic_port:</span> ${esc(cfg.meshtastic_port || '')}</div>
    <div><span style="color:#888">mesh_channel_index:</span> ${esc(cfg.mesh_channel_index)}</div>
    <div><span style="color:#888">gps_port:</span> ${esc(cfg.gps_port || '(none)')}</div>
    <div><span style="color:#888">state_dir:</span> ${esc(cfg.state_dir || '')}</div>
    <div style="color:#666; margin-top:4px">snapshot received ${ageTxt}</div>
  </div>`;
}

function renderApprovedAgents(approved, info) {
  const tbody = document.getElementById('agents-approved');
  const ids = Object.keys(approved).sort();
  if (!ids.length) {
    tbody.innerHTML = '<tr><td colspan="9" class="empty">no approved agents</td></tr>';
    return;
  }
  tbody.innerHTML = ids.map(id => {
    const a = approved[id] || {};
    const i = info[id] || {};
    const lastSeen = a.last_seen_at ? new Date(a.last_seen_at * 1000).toLocaleTimeString() : '';
    let gpsLat = i.lat, gpsLon = i.lon;
    if ((gpsLat == null || gpsLon == null) && i.last_position) {
      gpsLat = i.last_position.lat;
      gpsLon = i.last_position.lon;
    }
    const gps = (gpsLat != null && gpsLon != null)
      ? `${gpsLat.toFixed(4)},${gpsLon.toFixed(4)}` : '';
    const sats = (i.sats != null && i.sats > 0) ? i.sats : '';
    const cpu = (i.cpu != null && i.cpu > 0) ? i.cpu + '%' : '';
    const uptime = _fmtUptime(i.uptime_sec);
    const expanded = !!_agentExpanded[id];
    const arrow = expanded ? '▾' : '▸';
    let html = `<tr>
      <td><a href="#" onclick="event.preventDefault(); _toggleAgentRow('${esc(id)}')" style="text-decoration:none; color:inherit">${arrow} ${esc(id)}</a></td>
      <td>${esc(i.scanner || '')}</td><td>${esc(i.state || '')}</td>
      <td>${esc(gps)}</td><td>${esc(sats)}</td><td>${esc(cpu)}</td>
      <td>${esc(uptime)}</td><td>${lastSeen}</td>
      <td>
        <button onclick="sendAgentCmd('${esc(id)}','STOP',[])">Stop</button>
        <button onclick="promptAgentStart('${esc(id)}')">Start...</button>
      </td>
    </tr>`;
    if (expanded) {
      html += `<tr><td colspan="9" style="background:#0e1420; padding:0">${_renderAgentConfig(id, i)}</td></tr>`;
    }
    return html;
  }).join('');
}

async function approveAgent(id) {
  await fetch('/api/agents/approve', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({agent_id: id}),
  });
  fetchAgents();
}

async function sendAgentCmd(id, verb, args) {
  await fetch('/api/agents/cmd', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({agent_id: id, verb: verb, args: args}),
  });
}

function promptAgentStart(id) {
  const scanner = prompt(`Scanner to start on ${id} (e.g. pmr, ism, wifi):`);
  if (!scanner) return;
  const extra = prompt('Extra args (space-separated, optional):', '') || '';
  const args = [scanner].concat(extra.trim().split(/\s+/).filter(Boolean));
  sendAgentCmd(id, 'START', args);
}

// Poll agents tab when it's active
setInterval(() => {
  const tab = document.querySelector('.tab-btn.active');
  if (tab && tab.dataset.tab === 'agents') fetchAgents();
}, 3000);

// Trigger initial load when the Agents tab is selected
document.querySelectorAll('.tab-btn[data-tab="agents"]').forEach(btn =>
  btn.addEventListener('click', fetchAgents));

connectSSE();
