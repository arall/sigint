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
  if (tab && ['voice','drones','aircraft','vessels','vehicles','cellular','other'].includes(tab)) {
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

// --- Category Tabs (Voice / Drones / Aircraft / Vessels / Vehicles / Cellular / Other) ---
const _CATEGORY_BODY_IDS = {
  voice:    'voice-body',
  drones:   'drones-body',
  aircraft: 'aircraft-body',
  vessels:  'vessels-body',
  vehicles: 'vehicles-body',
  cellular: 'cellular-body',
  other:    'other-body',
};

async function loadCategory(name) {
  try {
    let url = '/api/cat/' + encodeURIComponent(name);
    if (_selectedSession) {
      url += '?session=' + encodeURIComponent(_selectedSession);
    }
    const r = await fetch(url);
    const data = await r.json();
    const rows = data.rows || [];
    const fn = _CATEGORY_RENDERERS[name];
    const bodyId = _CATEGORY_BODY_IDS[name];
    if (fn && bodyId) setTable(bodyId, rows, fn);
  } catch(e) {}
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
  if (!rows.length) { _emptyRow('aircraft-body', 8, 'no aircraft detected — ADS-B capture not running'); return; }
  tbody.innerHTML = rows.map(r => {
    const alt = r.altitude_ft != null ? r.altitude_ft+' ft' : '-';
    const spd = r.speed_kt != null ? r.speed_kt.toFixed(0)+' kt' : '-';
    const hdg = r.heading != null ? r.heading.toFixed(0)+'\u00b0' : '-';
    const pos = _fmtCoord(r.latitude, r.longitude);
    return '<tr>'
      + '<td style="font-family:monospace">'+esc(r.icao)+'</td>'
      + '<td style="font-weight:600">'+esc(r.callsign||'-')+'</td>'
      + '<td class="num">'+alt+'</td>'
      + '<td class="num">'+spd+'</td>'
      + '<td class="num">'+hdg+'</td>'
      + '<td style="font-size:11px">'+pos+'</td>'
      + '<td class="num">'+r.count+'</td>'
      + '<td style="font-size:11px">'+(r.last_seen||'-')+'</td>'
      + '</tr>';
  }).join('');
}

function renderVessels(rows) {
  const tbody = document.getElementById('vessels-body');
  if (!rows.length) { _emptyRow('vessels-body', 9, 'no vessels detected — AIS capture not running'); return; }
  tbody.innerHTML = rows.map(r => {
    const spd = r.speed_kn != null ? r.speed_kn.toFixed(1)+' kn' : '-';
    const crs = r.course != null ? r.course.toFixed(0)+'\u00b0' : '-';
    const pos = _fmtCoord(r.latitude, r.longitude);
    return '<tr>'
      + '<td style="font-family:monospace">'+esc(r.mmsi)+'</td>'
      + '<td style="font-weight:600">'+esc(r.name||'-')+'</td>'
      + '<td>'+esc(r.ship_type||'')+'</td>'
      + '<td>'+esc(r.nav_status||'')+'</td>'
      + '<td class="num">'+spd+'</td>'
      + '<td class="num">'+crs+'</td>'
      + '<td style="font-size:11px">'+pos+'</td>'
      + '<td class="num">'+r.count+'</td>'
      + '<td style="font-size:11px">'+(r.last_seen||'-')+'</td>'
      + '</tr>';
  }).join('');
}

function renderVehicles(rows) {
  const tbody = document.getElementById('vehicles-body');
  if (!rows.length) { _emptyRow('vehicles-body', 8, 'no TPMS / keyfob detections yet'); return; }
  tbody.innerHTML = rows.map(r => {
    const pressure = r.pressure_kpa != null ? r.pressure_kpa.toFixed(0)+' kPa' : '-';
    const temp     = r.temperature_c != null ? r.temperature_c.toFixed(0)+' \u00b0C' : '-';
    const kindCol  = r.kind === 'TPMS' ? '#4fc3f7' : '#ffb74d';
    return '<tr>'
      + '<td style="color:'+kindCol+';font-weight:600">'+esc(r.kind)+'</td>'
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

function renderOther(rows) {
  const tbody = document.getElementById('other-body');
  if (!rows.length) { _emptyRow('other-body', 7, 'no other detections'); return; }
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

const _CATEGORY_RENDERERS = {
  voice:    renderVoice,
  drones:   renderDrones,
  aircraft: renderAircraft,
  vessels:  renderVessels,
  vehicles: renderVehicles,
  cellular: renderCellular,
  other:    renderOther,
};

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
    if (btn.dataset.tab === 'signals') loadCategory(_sigSubtab);
  });
});

// Category names resolve into the Signals parent + a sub-tab switch.
// Everything else is a plain top-tab click.
const _SIGNAL_CATEGORIES = ['voice','drones','aircraft','vessels','vehicles','cellular','other'];

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
  aircraft:  null,
  vessels:   null,
  drones:    null,
  operators: null,
};
const _MAP_COLORS = {
  aircraft:  '#4caf50',
  vessels:   '#2196f3',
  drones:    '#f44336',
  operators: '#ff9800',
};

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

async function loadMap() {
  if (!_map) return;
  const qs = _selectedSession ? ('?session=' + encodeURIComponent(_selectedSession)) : '';
  const tabs = ['aircraft', 'vessels', 'drones'];
  try {
    const results = await Promise.all(tabs.map(t =>
      fetch('/api/cat/' + t + qs).then(r => r.json()).catch(() => ({rows: []}))
    ));
    const [aircraft, vessels, drones] = results.map(d => d.rows || []);
    _renderMap({aircraft, vessels, drones});
  } catch (e) {}
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
      + esc(a.icao) + '<br>'
      + (a.altitude_ft != null ? a.altitude_ft + ' ft' : '-') + '<br>'
      + (a.speed_kt != null ? a.speed_kt.toFixed(0) + ' kt' : '') + ' '
      + (a.heading != null ? a.heading.toFixed(0) + '&deg;' : '');
    _mapMarker(a.latitude, a.longitude, _MAP_COLORS.aircraft, popup)
      .addTo(_mapLayers.aircraft);
    bounds.push([a.latitude, a.longitude]);
    positioned++;
  });

  (data.vessels || []).forEach(v => {
    if (v.latitude == null || v.longitude == null) return;
    const popup = '<b>' + esc(v.name || v.mmsi) + '</b><br>'
      + 'MMSI ' + esc(v.mmsi) + '<br>'
      + esc(v.ship_type || '') + '<br>'
      + (v.speed_kn != null ? v.speed_kn.toFixed(1) + ' kn' : '-') + ' '
      + (v.course != null ? v.course.toFixed(0) + '&deg;' : '');
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

  // Summary line
  const el = document.getElementById('map-summary');
  if (el) {
    el.textContent = positioned > 0
      ? positioned + ' position(s) on map (' + (data.aircraft.length) + ' aircraft, '
          + (data.vessels.length) + ' vessels, ' + (data.drones.length) + ' drones)'
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

connectSSE();
