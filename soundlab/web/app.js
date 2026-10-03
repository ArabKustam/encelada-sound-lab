'use strict';
// Encelada Sound Lab — фронтенд без сборки. Источник правды — рецепт (JSON); сервер рендерит его в звук.

const $ = (id) => document.getElementById(id);
const S = { catalog: null, sounds: [], cur: null, sel: 0, cursor: 0, evOffset: 0, pending: new Set(), actx: null };

async function api(path, body, raw) {
  const opt = body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
  const r = await fetch(path, opt);
  if (raw) { if (!r.ok) throw new Error((await r.json()).error); return r.arrayBuffer(); }
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}
const status = (t, bad) => { $('status').textContent = t; $('status').style.color = bad ? 'var(--bad)' : ''; };
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];
const midiName = (m) => NOTE_NAMES[((m % 12) + 12) % 12] + (Math.floor(m / 12) - 1);
function toMidi(n) {
  if (typeof n === 'number') return n;
  const m = /^([A-Ga-g])([#b]?)(-?\d+)$/.exec(String(n).trim());
  if (!m) return 60;
  const base = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 }[m[1].toUpperCase()];
  return base + (m[2] === '#' ? 1 : m[2] === 'b' ? -1 : 0) + 12 * (parseInt(m[3]) + 1);
}

// ------------------------------------------------------------------ библиотека
async function loadLibrary() {
  S.sounds = await api('/api/sounds');
  const q = $('filter').value.toLowerCase();
  $('lib').innerHTML = '';
  for (const s of S.sounds) {
    const text = (s.name + ' ' + (s.tags || []).join(' ')).toLowerCase();
    if (q && !text.includes(q)) continue;
    const li = document.createElement('li');
    li.className = S.cur && S.cur.id === s.id ? 'sel' : '';
    li.innerHTML = `<button class="play" title="Слушать">▶</button><div class="t"><div>${esc(s.name)}</div>
      <div class="tags">${s.seconds ?? '?'} с · ${esc((s.tags || []).join(', '))}</div></div>`;
    li.onclick = () => select(s.id);
    li.querySelector('.play').onclick = (e) => { e.stopPropagation(); new Audio(`/api/file/${s.id}/audio.ogg?${s.updated}`).play(); };
    $('lib').appendChild(li);
  }
}

async function select(id) {
  const data = await api('/api/sound/' + id);
  S.cur = data;
  S.sel = 0;
  S.cursor = 0;
  $('empty').hidden = true;
  $('sound').hidden = false;
  showSound();
  loadLibrary();
}

function showSound(onlyMedia) {
  const { id, recipe, meta } = S.cur;
  const v = meta.updated || Date.now();
  if (id) {
    $('audio').src = `/api/file/${id}/audio.ogg?${v}`;
    $('wave').src = `/api/file/${id}/waveform.png?${v}`;
    $('spec').src = `/api/file/${id}/spectrogram.png?${v}`;
    $('dlOgg').href = `/api/file/${id}/audio.ogg`; $('dlOgg').download = id + '.ogg';
    $('dlWav').href = `/api/file/${id}/audio.wav`; $('dlWav').download = id + '.wav';
  } else {
    $('audio').removeAttribute('src'); $('wave').removeAttribute('src'); $('spec').removeAttribute('src');
  }
  $('wave').style.visibility = $('spec').style.visibility = id ? 'visible' : 'hidden';
  const last = (meta.history || []).slice(-1)[0];
  $('seconds').textContent = meta.seconds ? meta.seconds + ' с' : 'ещё не отрендерено';
  $('author').textContent = last ? (last.author === 'claude' ? 'последняя правка: Claude' : 'последняя правка: вы') : '';
  if (onlyMedia) return;
  $('name').value = recipe.name || id || '';
  $('desc').value = recipe.description || '';
  $('tempo').value = recipe.tempo || 90;
  $('channels').value = String(recipe.channels || 2);
  renderTracks();
  renderMaster();
  $('json').value = JSON.stringify(recipe, null, 1);
  $('history').innerHTML = (S.cur.versions || []).map((n) =>
    `<li>версия ${n} <button data-v="${n}">вернуть</button></li>`).join('') +
    (meta.history || []).slice().reverse().map((h) =>
      `<li class="muted">${new Date(h.t * 1000).toLocaleString()} — ${h.author === 'claude' ? 'Claude' : 'вы'} ${esc(h.note || '')} (${h.seconds} с)</li>`).join('');
  $('history').querySelectorAll('button[data-v]').forEach((b) => b.onclick = async () => {
    await api('/api/revert', { id: S.cur.id, version: +b.dataset.v });
    S.pending.add(S.cur.id); status('возврат к версии ' + b.dataset.v + '…');
  });
}

// ------------------------------------------------------------------ дорожки
function instValue(inst) {
  if (!inst) return 'str:piano';
  if (typeof inst === 'string' || typeof inst === 'number') return 'str:' + inst;
  if (inst.kit) return 'kit:' + (typeof inst.kit === 'string' ? inst.kit : 'synth');
  if (inst.sample) return 'sample:' + inst.sample;
  if (inst.gm_drums) return 'gmdrums';
  if (inst.gm !== undefined) return 'gm:' + inst.gm;
  if (inst.drum) return 'drum:' + inst.drum;
  return 'synth:' + (inst.synth || 'piano');
}
function instOptions(selected) {
  const c = S.catalog;
  let h = '';
  if (c.real && Object.keys(c.real.presets).length) h += '<optgroup label="Живые инструменты (записи оркестра)">' +
    Object.keys(c.real.presets).map((k) => `<option value="str:${k}">${k}</option>`).join('') + '</optgroup>';
  h += '<optgroup label="Пение нейросетью (слоги в lyrics)">' + ['певица', 'мужской голос', 'певицы', 'хор певиц', 'ангельские голоса', 'мужской хор']
    .map((k) => `<option value="str:${k}">${k}</option>`).join('') + '</optgroup>';
  h += '<optgroup label="Синтезаторы">' + Object.entries(c.synths).map(([k, d]) =>
    `<option value="synth:${k}" title="${esc(d)}">${k} — ${esc(d)}</option>`).join('') + '</optgroup>';
  h += '<optgroup label="Наборы ударных (для сеток drums)">' + Object.keys(c.drums.kits).map((k) => `<option value="kit:${k}">набор ${k}</option>`).join('') + '</optgroup>';
  h += '<optgroup label="Нотные блоки Minecraft">' + Object.keys(c.noteblock).map((k) => `<option value="sample:mc:note_block/${k}">нотный блок ${k}</option>`).join('') + '</optgroup>';
  h += '<optgroup label="Ударные (синтез, один звук)">' + c.drums.synth_drums.map((d) => `<option value="drum:${d}">${d}</option>`).join('') + '</optgroup>';
  h += `<optgroup label="Настоящие инструменты General MIDI (${esc(c.soundfont || 'нет SoundFont')})">` +
    c.gm.map((n, i) => `<option value="gm:${i}">${i} ${esc(n)}</option>`).join('') + '<option value="gmdrums">GM ударные</option></optgroup>';
  if (!h.includes(`value="${selected}"`)) h = `<option value="${esc(selected)}">${esc(selected.replace(/^(str|sample):/, ''))}</option>` + h;
  return h.replace(`value="${selected}"`, `value="${selected}" selected`);
}
function parseInst(v, old) {
  const params = old && old.params ? { params: old.params } : {};
  if (v === 'gmdrums') return { gm_drums: true };
  const k = v.split(':')[0], x = v.slice(k.length + 1);
  if (k === 'str') return x;
  if (k === 'kit') return { kit: x };
  if (k === 'sample') return { sample: x };
  if (k === 'gm') return { gm: +x };
  if (k === 'drum') return { drum: x };
  return { synth: x, ...params };
}
const COMPACT_KEYS = ['lyrics', 'notes', 'melody', 'chords', 'drums', 'parts', 'sections', 'loop', 'kit', 'style', 'octave', 'chord_octave',
  'chord_length', 'arp_step', 'pulse', 'strum', 'bass', 'gate', 'step', 'swing', 'humanize', 'velocity', 'length', 'key', 'transpose'];
function isCompact(tr) {
  return typeof tr.notes === 'string' || ['lyrics', 'melody', 'chords', 'drums', 'parts', 'sections', 'kit', 'transpose'].some((k) => tr[k] !== undefined)
    || (tr.loop && (tr.type || 'notes') === 'notes');
}
async function refreshExpanded() {
  if (!S.cur || !(S.cur.recipe.tracks || []).some(isCompact)) { S.expanded = null; return; }
  try { S.expanded = (await api('/api/expand', { recipe: S.cur.recipe })).recipe; }
  catch (err) { S.expanded = null; status('нотация: ' + err.message, true); }
  document.querySelectorAll('canvas.roll').forEach((c) => c._draw && c._draw());
}
function num(v) { const n = parseFloat(v); return Number.isFinite(n) ? n : v; }

function fxEditor(list, host, onChange) {
  host.innerHTML = '';
  (list || []).forEach((fx, i) => {
    const def = S.catalog.effects[fx.type] || { defaults: {} };
    const div = document.createElement('div');
    div.className = 'fx';
    div.innerHTML = `<b title="${esc(def.description)}">${esc(fx.type)}</b>` + Object.keys(def.defaults).map((k) =>
      `<label>${k} <input data-k="${k}" value="${esc(fx[k] ?? def.defaults[k])}" size="6"></label>`).join('') +
      '<button class="del" title="Убрать">✕</button>';
    div.querySelectorAll('input').forEach((inp) => inp.onchange = () => {
      const d = def.defaults[inp.dataset.k];
      fx[inp.dataset.k] = typeof d === 'boolean' ? inp.value === 'true' : typeof d === 'number' ? num(inp.value) : inp.value;
      onChange();
    });
    div.querySelector('.del').onclick = () => { list.splice(i, 1); onChange(true); };
    host.appendChild(div);
  });
  const add = document.createElement('select');
  add.innerHTML = '<option value="">＋ эффект…</option>' + Object.entries(S.catalog.effects).map(([k, d]) =>
    `<option value="${k}">${k} — ${esc(d.description)}</option>`).join('');
  add.onchange = () => { if (!add.value) return; list.push({ type: add.value, ...S.catalog.effects[add.value].defaults }); onChange(true); };
  host.appendChild(add);
}

function renderTracks() {
  const r = S.cur.recipe;
  const host = $('tracks');
  host.innerHTML = '';
  (r.tracks || []).forEach((tr, i) => {
    const type = tr.type || 'notes';
    const card = document.createElement('div');
    card.className = 'track' + (tr.mute ? ' muted' : '') + (i === S.sel ? ' sel' : '');
    card.style.borderColor = i === S.sel ? 'var(--acc)' : '';
    card.innerHTML = `<div class="trackHead"><span class="badge">${type === 'notes' ? 'ноты' : type === 'sfx' ? 'эффект' : 'аудио'}</span>
      <input class="tname" value="${esc(tr.name || '')}">
      <label><input type="checkbox" class="mute" ${tr.mute ? 'checked' : ''}> выкл</label>
      <label>громк. <input type="range" class="gain" min="0" max="1.5" step="0.01" value="${tr.gain ?? 0.8}"></label>
      <label>панорама <input type="range" class="pan" min="-1" max="1" step="0.05" value="${tr.pan ?? 0}"></label>
      <button class="up" title="Выше">↑</button><button class="dup" title="Копия">⧉</button><button class="del danger" title="Удалить">✕</button></div>
      <div class="row body"></div><div class="fxs"></div>
      <details><summary class="muted small">Автоматизация (кривые по долям)</summary>
      <textarea class="auto" rows="3" style="width:100%">${esc(JSON.stringify(tr.automation || {}))}</textarea>
      <div class="muted small">Например: {"gain": [[0,1],[32,0]], "lowpass": [[24,12000],[32,400]], "detune": [[24,0],[32,-100]], "pan": [[0,-1],[16,1]]}</div></details>`;
    card.onclick = (e) => { if (S.sel !== i && !['INPUT', 'SELECT', 'BUTTON', 'TEXTAREA', 'CANVAS'].includes(e.target.tagName)) { S.sel = i; renderTracks(); } };
    card.querySelector('.tname').onchange = (e) => { tr.name = e.target.value; syncJson(); };
    card.querySelector('.mute').onchange = (e) => { tr.mute = e.target.checked; renderTracks(); };
    card.querySelector('.gain').oninput = (e) => { tr.gain = +e.target.value; syncJson(); };
    card.querySelector('.pan').oninput = (e) => { tr.pan = +e.target.value; syncJson(); };
    card.querySelector('.del').onclick = () => { r.tracks.splice(i, 1); S.sel = 0; renderTracks(); };
    card.querySelector('.dup').onclick = () => { r.tracks.splice(i + 1, 0, JSON.parse(JSON.stringify(tr))); renderTracks(); };
    card.querySelector('.up').onclick = () => { if (i > 0) { [r.tracks[i - 1], r.tracks[i]] = [r.tracks[i], r.tracks[i - 1]]; renderTracks(); } };
    card.querySelector('.auto').onchange = (e) => {
      try { tr.automation = JSON.parse(e.target.value || '{}'); syncJson(); status('автоматизация обновлена'); }
      catch (err) { status('ошибка в JSON автоматизации: ' + err.message, true); }
    };
    const body = card.querySelector('.body');
    if (type === 'notes' && isCompact(tr)) {
      const fields = {};
      COMPACT_KEYS.forEach((k) => { if (tr[k] !== undefined) fields[k] = tr[k]; });
      const text = JSON.stringify(fields, null, 1);
      body.innerHTML = `<label>инструмент <select class="inst">${instOptions(tr.instrument === undefined && tr.kit ? 'kit:' + tr.kit : instValue(tr.instrument))}</select></label>
        <button class="hear">прослушать инструмент</button>
        <button class="explode" title="Превратить нотацию в обычные ноты (можно править мышкой)">развернуть в ноты</button>
        <div class="muted small" style="width:100%">Нотация дорожки (правьте текст; синтаксис — GUIDE.md). Пиано-ролл ниже — только просмотр.</div>
        <textarea class="notation" rows="${Math.min(12, 2 + text.split('\n').length)}" style="width:100%" spellcheck="false">${esc(text)}</textarea>`;
      body.querySelector('.inst').onchange = (e) => {
        if (e.target.value.startsWith('kit:') && tr.drums !== undefined || tr.kit !== undefined && e.target.value.startsWith('kit:')) { tr.kit = e.target.value.slice(4); delete tr.instrument; }
        else { tr.instrument = parseInst(e.target.value, tr.instrument); delete tr.kit; }
        syncJson(); renderTracks();
      };
      body.querySelector('.hear').onclick = () => audition(tr.kit || (tr.instrument && tr.instrument.kit)
        ? { instrument: { kit: tr.kit || tr.instrument.kit }, note: 'kick', length: 0.3 } : { instrument: tr.instrument, note: 'C4' });
      body.querySelector('.notation').onchange = (e) => {
        try {
          const f = JSON.parse(e.target.value || '{}');
          COMPACT_KEYS.forEach((k) => delete tr[k]);
          Object.assign(tr, f); syncJson(); refreshExpanded(); status('нотация обновлена');
        } catch (err) { status('ошибка в JSON нотации: ' + err.message, true); }
      };
      body.querySelector('.explode').onclick = async () => {
        try {
          const { tracks } = await api('/api/expand_track', { recipe: S.cur.recipe, index: i });
          r.tracks.splice(i, 1, ...tracks); renderTracks(); status('дорожка развёрнута в ноты');
        } catch (err) { status(err.message, true); }
      };
      const canvas = document.createElement('canvas');
      canvas.className = 'roll';
      body.after(canvas);
      pianoRoll(canvas, tr, () => 0.5, i, true);
    } else if (type === 'notes') {
      body.innerHTML = `<label>инструмент <select class="inst">${instOptions(instValue(tr.instrument))}</select></label>
        <label>длина новой ноты <select class="len"><option>0.25</option><option selected>0.5</option><option>1</option><option>2</option><option>4</option></select></label>
        <button class="hear">прослушать инструмент</button>
        <span class="muted small">ЛКМ — добавить/убрать ноту, ПКМ — курсор записи</span>`;
      body.querySelector('.inst').onchange = (e) => { tr.instrument = parseInst(e.target.value, tr.instrument); syncJson(); };
      body.querySelector('.hear').onclick = () => audition({ instrument: tr.instrument, note: 'C4' });
      const canvas = document.createElement('canvas');
      canvas.className = 'roll';
      body.after(canvas);
      pianoRoll(canvas, tr, () => +body.querySelector('.len').value, i);
    } else if (type === 'sfx') {
      const def = S.catalog.sfx[tr.sfx] || { defaults: {} };
      body.innerHTML = `<label>генератор <select class="sfx">${Object.entries(S.catalog.sfx).map(([k, d]) =>
        `<option value="${k}" ${k === tr.sfx ? 'selected' : ''}>${k} — ${esc(d.description)}</option>`).join('')}</select></label>
        <label>с доли <input type="number" class="at" step="0.25" value="${tr.at ?? 0}"></label>
        <label>повтор каждые <input type="number" class="every" step="0.5" value="${(tr.repeat || {}).every ?? 0}"></label>
        <label>раз <input type="number" class="count" min="1" value="${(tr.repeat || {}).count ?? 1}"></label>
        <button class="hear">прослушать</button>` + Object.keys(def.defaults).map((k) =>
        `<label>${k} <input class="p" data-k="${k}" value="${esc((tr.params || {})[k] ?? def.defaults[k])}" size="7"></label>`).join('');
      body.querySelector('.sfx').onchange = (e) => { tr.sfx = e.target.value; tr.params = {}; renderTracks(); };
      body.querySelector('.at').onchange = (e) => { tr.at = +e.target.value; syncJson(); };
      body.querySelector('.every').onchange = (e) => { tr.repeat = { ...(tr.repeat || {}), every: +e.target.value }; syncJson(); };
      body.querySelector('.count').onchange = (e) => { tr.repeat = { ...(tr.repeat || {}), count: +e.target.value }; syncJson(); };
      body.querySelectorAll('.p').forEach((inp) => inp.onchange = () => {
        tr.params = tr.params || {};
        const d = def.defaults[inp.dataset.k];
        tr.params[inp.dataset.k] = typeof d === 'number' ? num(inp.value) : inp.value; syncJson();
      });
      body.querySelector('.hear').onclick = () => audition({ sfx: tr.sfx, params: tr.params || {}, effects: tr.effects || [] });
    } else {
      body.innerHTML = `<label>источник <input class="src" list="srcList" size="34" value="${esc(tr.source || '')}" placeholder="library:id, mc:entity.zombie.ambient, samples:x.wav"></label>
        <datalist id="srcList">${S.sounds.map((s) => `<option value="library:${s.id}">${esc(s.name)}</option>`).join('')}</datalist>
        <label>с доли <input type="number" class="at" step="0.25" value="${tr.at ?? 0}"></label>
        <label>повторить <input type="number" class="loop" min="1" value="${tr.loop ?? 1}"></label>`;
      body.querySelector('.src').onchange = (e) => { tr.source = e.target.value; syncJson(); };
      body.querySelector('.at').onchange = (e) => { tr.at = +e.target.value; syncJson(); };
      body.querySelector('.loop').onchange = (e) => { tr.loop = +e.target.value; syncJson(); };
    }
    tr.effects = tr.effects || [];
    fxEditor(tr.effects, card.querySelector('.fxs'), (rerender) => { syncJson(); if (rerender) renderTracks(); });
    host.appendChild(card);
  });
  syncJson();
  refreshExpanded();
}

function renderMaster() {
  const r = S.cur.recipe;
  r.master = r.master || {};
  const m = r.master;
  $('master').innerHTML = `<div class="row"><label>нормализация, дБ <input type="number" id="mNorm" step="0.5" value="${m.normalize ?? -1}"></label>
    <label>затухание в конце, с <input type="number" id="mFade" step="0.5" value="${m.fade_out ?? 0}"></label>
    <label>обрезать до доли <input type="number" id="mLen" step="1" value="${m.length_beats ?? ''}"></label></div><div id="mFx"></div>`;
  $('mNorm').onchange = (e) => { m.normalize = +e.target.value; syncJson(); };
  $('mFade').onchange = (e) => { m.fade_out = +e.target.value; syncJson(); };
  $('mLen').onchange = (e) => { if (e.target.value) m.length_beats = +e.target.value; else delete m.length_beats; syncJson(); };
  m.effects = m.effects || [];
  fxEditor(m.effects, $('mFx'), (re) => { syncJson(); if (re) renderMaster(); });
}

function syncJson() {
  const r = S.cur.recipe;
  r.name = $('name').value || r.name;
  r.description = $('desc').value;
  r.tempo = +$('tempo').value || 90;
  r.channels = +$('channels').value;
  $('json').value = JSON.stringify(r, null, 1);
}

// ------------------------------------------------------------------ пиано-ролл
function pianoRoll(canvas, tr, lenFn, index, readOnly) {
  let notes = readOnly ? [] : (tr.notes = tr.notes || []);
  const draw = () => {
    if (readOnly) {
      const et = S.expanded && S.expanded.tracks.find((t) => t.name === tr.name);
      const rows = {};
      notes = ((et && et.notes) || []).map((n) => {
        if (typeof n[2] === 'string' && !/^[A-Ga-g][#b]?-?\d$/.test(n[2])) {
          if (rows[n[2]] === undefined) rows[n[2]] = 48 + 2 * Object.keys(rows).length;
          return [n[0], n[1], rows[n[2]], n[3]];
        }
        return n;
      });
    }
    const W = canvas.width = canvas.clientWidth * devicePixelRatio;
    const H = canvas.height = canvas.clientHeight * devicePixelRatio;
    const g = canvas.getContext('2d');
    const pitches = notes.map((n) => toMidi(n[2]));
    let lo = Math.min(...pitches, 60) - 3, hi = Math.max(...pitches, 72) + 3;
    if (hi - lo < 24) hi = lo + 24;
    const beats = Math.max(16, Math.ceil(Math.max(0, ...notes.map((n) => n[0] + n[1])) / 4) * 4 + 4);
    canvas._geo = { lo, hi, beats, W, H };
    const bx = W / beats, ry = H / (hi - lo + 1);
    g.fillStyle = '#0c0e14'; g.fillRect(0, 0, W, H);
    for (let p = lo; p <= hi; p++) if ([1, 3, 6, 8, 10].includes(((p % 12) + 12) % 12)) { g.fillStyle = '#10131b'; g.fillRect(0, (hi - p) * ry, W, ry); }
    for (let b = 0; b <= beats; b++) { g.fillStyle = b % 4 ? '#1a1f2c' : '#2c3450'; g.fillRect(b * bx, 0, 1, H); }
    g.font = `${10 * devicePixelRatio}px sans-serif`;
    for (let p = lo; p <= hi; p++) if (p % 12 === 0) { g.fillStyle = '#56607a'; g.fillText(midiName(p), 2, (hi - p + 0.85) * ry); }
    for (const n of notes) {
      const v = n[3] ?? 0.8;
      g.fillStyle = `hsl(${200 + v * 80}, 80%, ${40 + v * 25}%)`;
      g.fillRect(n[0] * bx + 1, (hi - toMidi(n[2])) * ry + 1, Math.max(3, n[1] * bx - 2), Math.max(2, ry - 2));
    }
    if (index === S.sel) { g.fillStyle = '#ffc56b'; g.fillRect(S.cursor * bx, 0, 2, H); }
  };
  canvas._draw = draw;
  requestAnimationFrame(draw);
  const pos = (e) => {
    const { lo, hi, beats, W, H } = canvas._geo;
    const rect = canvas.getBoundingClientRect();
    const x = (e.clientX - rect.left) / rect.width * W, y = (e.clientY - rect.top) / rect.height * H;
    return { beat: Math.floor(x / (W / beats) * 4) / 4, pitch: hi - Math.floor(y / (H / (hi - lo + 1))) };
  };
  canvas.oncontextmenu = (e) => { e.preventDefault(); S.sel = index; S.cursor = pos(e).beat; renderTracks(); };
  canvas.onclick = (e) => {
    if (readOnly) return status('дорожка записана нотацией — правьте текст выше или нажмите «развернуть в ноты»');
    const { beat, pitch } = pos(e);
    const hit = notes.findIndex((n) => toMidi(n[2]) === pitch && beat >= n[0] && beat < n[0] + n[1]);
    if (hit >= 0) notes.splice(hit, 1);
    else { notes.push([beat, lenFn(), midiName(pitch), 0.75]); audition({ instrument: tr.instrument, note: midiName(pitch), length: 0.4 }); }
    notes.sort((a, b) => a[0] - b[0]);
    draw(); syncJson();
  };
}

// ------------------------------------------------------------------ звук: прослушивание и клавиатура
async function audition(body) {
  try {
    S.actx = S.actx || new AudioContext();
    const buf = await api('/api/audition', body, true);
    const audio = await S.actx.decodeAudioData(buf);
    const src = S.actx.createBufferSource();
    src.buffer = audio; src.connect(S.actx.destination); src.start();
  } catch (err) { status('прослушивание: ' + err.message, true); }
}

function buildKeyboard() {
  const kbd = $('kbd');
  const whites = [0, 2, 4, 5, 7, 9, 11, 12, 14, 16, 17, 19, 21, 23];
  const blacks = [[1, 0], [3, 1], [6, 3], [8, 4], [10, 5], [13, 7], [15, 8], [18, 10], [20, 11], [22, 12]];
  const press = (semi, el) => {
    const note = midiName(12 * (+$('octave').value + 1) + semi);
    el.classList.add('down'); setTimeout(() => el.classList.remove('down'), 200);
    audition({ instrument: parseInst($('kbdInst').value), note, length: 0.8 });
    if ($('rec').checked && S.cur) {
      const tr = S.cur.recipe.tracks[S.sel];
      if (tr && (tr.type || 'notes') === 'notes') {
        const step = +$('recStep').value;
        tr.notes = tr.notes || [];
        tr.notes.push([S.cursor, step, note, 0.75]);
        S.cursor += step;
        renderTracks();
      } else status('для записи выберите дорожку нот', true);
    }
  };
  whites.forEach((s) => { const d = document.createElement('div'); d.className = 'w'; d.onmousedown = () => press(s, d); d.dataset.s = s; kbd.appendChild(d); });
  blacks.forEach(([s, after]) => {
    const d = document.createElement('div'); d.className = 'b'; d.dataset.s = s;
    d.style.left = `calc(${(after + 1) / whites.length * 100}% - 2.5%)`; d.onmousedown = () => press(s, d); kbd.appendChild(d);
  });
  const map = 'awsedftgyhujk';
  document.addEventListener('keydown', (e) => {
    if (['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName) || e.repeat) return;
    const i = map.indexOf(e.key.toLowerCase());
    if (i < 0) return;
    const el = kbd.querySelector(`[data-s="${i}"]`);
    if (el) press(i, el);
  });
  $('kbdInst').innerHTML = instOptions('synth:musicbox');
}

// ------------------------------------------------------------------ сэмплы: звуки Minecraft, samples/, библиотека
async function searchSamples() {
  const q = $('sampleQ').value.trim();
  const { results, stats } = await api('/api/samples?q=' + encodeURIComponent(q));
  $('sampleStats').textContent = `Minecraft: ${stats.mc_files} файлов, ${stats.mc_events} событий; своих сэмплов: ${stats.user_samples}`;
  $('samples').innerHTML = '';
  for (const r of results.slice(0, 60)) {
    const li = document.createElement('li');
    li.innerHTML = `<button class="play" title="Слушать">▶</button><span class="t" title="${esc(r.ref)}">${esc(r.ref)}</span><button class="add" title="Добавить дорожкой в текущий звук">＋</button>`;
    li.querySelector('.play').onclick = () => new Audio('/api/sample?ref=' + encodeURIComponent(r.ref)).play();
    li.querySelector('.add').onclick = () => {
      if (!S.cur) return status('сначала откройте или создайте звук', true);
      S.cur.recipe.tracks.push({ name: r.ref.split(/[:/.]/).pop(), type: 'audio', source: r.ref, at: S.cursor || 0, gain: 0.8, effects: [] });
      renderTracks(); status('добавлено: ' + r.ref);
    };
    $('samples').appendChild(li);
  }
}

// ------------------------------------------------------------------ лента событий: смотреть, как создаётся звук
async function pollEvents() {
  try {
    const { events, offset } = await api('/api/events?offset=' + S.evOffset);
    const first = S.evOffset === 0;
    S.evOffset = offset;
    const log = $('log');
    for (const e of events) {
      const div = document.createElement('div');
      div.className = 'e ' + (e.level || '') + (e.author === 'claude' ? ' claude' : '');
      const t = new Date(e.t * 1000).toLocaleTimeString();
      div.textContent = `${t} [${e.id}] ${e.msg}`;
      log.appendChild(div);
      if (!first && e.level === 'done' && e.id === '_preview') {
        if (S.waitPreview) { S.waitPreview = false; new Audio('/api/file/_preview/audio.ogg?' + Date.now()).play(); status('играет предпросмотр'); }
        continue;
      }
      if (!first && e.level === 'done') {
        await loadLibrary();
        if (S.cur && S.cur.id === e.id) {
          const fresh = await api('/api/sound/' + e.id);
          S.cur.meta = fresh.meta; S.cur.versions = fresh.versions;
          if (e.author === 'claude') { S.cur.recipe = fresh.recipe; showSound(); } else showSound(true);
          status('готово');
        } else if (e.author === 'claude' && !S.cur) select(e.id);
      }
      if (!first && e.level === 'start' && e.author === 'claude') status('Claude создаёт «' + e.id + '»…');
      if (e.level === 'error' && !first) status(e.msg, true);
    }
    while (log.children.length > 500) log.firstChild.remove();
    if (events.length) log.scrollTop = log.scrollHeight;
  } catch (err) { status('нет связи с сервером', true); }
  setTimeout(pollEvents, 700);
}

// ------------------------------------------------------------------ кнопки
function newRecipe(recipe) {
  S.cur = { id: null, recipe, meta: { history: [] }, versions: [] };
  S.sel = 0; S.cursor = 0;
  $('empty').hidden = true; $('sound').hidden = false;
  showSound();
}

async function doRender(asNew) {
  if (!S.cur) return;
  syncJson();
  const recipe = S.cur.recipe;
  try {
    const res = await api('/api/render', { id: asNew ? null : S.cur.id, recipe, author: 'user' });
    S.cur.id = res.id;
    status('рендер «' + res.id + '»…');
  } catch (err) { status(err.message, true); }
}

async function compose(kind) {
  let params = {};
  if (kind === 'song') {
    const st = prompt('Песня: abyss (как «Сделано в Бездне»), takopi (нежная аниме), jumping (прыгающие голоса), angelic (ангельский гимн). Можно добавить тональность: «takopi D major»', 'abyss');
    if (st === null) return;
    const [style, ...k] = st.trim().split(/\s+/);
    params = { style: style || 'abyss', seed: Math.floor(Math.random() * 1e6) };
    if (k.length) params.key = k.join(' ');
  } else if (kind === 'beat') {
    const st = prompt('Стиль бита: lofi, trap, house, rock, chiptune, noteblock (нотные блоки Minecraft). Можно добавить тональность: «lofi D minor»', 'lofi');
    if (st === null) return;
    const [style, ...k] = st.trim().split(/\s+/);
    params = { style: style || 'lofi', seed: Math.floor(Math.random() * 1e6) };
    if (k.length) params.key = k.join(' ');
  } else if (kind === 'calm') {
    const key = prompt('Тональность (C, D, F, G…) и лад через пробел (major, lydian, dorian):', 'F lydian');
    if (key === null) return;
    const [k, sc] = key.split(/\s+/);
    params = { key: k || 'F', scale: sc || 'lydian', bars: 8, seed: Math.floor(Math.random() * 1e6), name: 'calm_' + (k || 'F').toLowerCase() };
  } else if (kind === 'horror') {
    const inten = prompt('Интенсивность 0…1:', '0.7');
    if (inten === null) return;
    params = { intensity: +inten || 0.7, bars: 8, seed: Math.floor(Math.random() * 1e6), name: 'dread' };
  } else {
    const at = prompt('На какой доле хорошее превращается в жуть? И стиль (melt / cut / fade):', '24 melt');
    if (at === null) return;
    const [b, style] = at.split(/\s+/);
    params = { at_beat: +b || 24, style: style || 'melt', calm: { bars: Math.ceil((+b || 24) / 4) + 1, seed: Math.floor(Math.random() * 1e6) },
      horror: { bars: 6, seed: Math.floor(Math.random() * 1e6) } };
  }
  const { recipe } = await api('/api/compose', { kind, params });
  newRecipe(recipe);
  status('сочинено — нажмите «Рендер», чтобы услышать');
}

async function init() {
  S.catalog = await api('/api/catalog');
  buildKeyboard();
  await loadLibrary();
  pollEvents();
  $('filter').oninput = loadLibrary;
  ['name', 'desc', 'tempo', 'channels'].forEach((id) => $(id).onchange = syncJson);
  $('btnRender').onclick = () => doRender(false);
  $('btnSaveNew').onclick = () => doRender(true);
  $('btnNew').onclick = () => newRecipe({ name: 'новый звук', tempo: 90, tracks: [
    { name: 'мелодия', type: 'notes', instrument: { synth: 'musicbox' }, notes: [], gain: 0.8, effects: [{ type: 'reverb', size: 0.6, mix: 0.3 }] }],
    master: { normalize: -1 } });
  $('btnCalm').onclick = () => compose('calm');
  $('btnBeat').onclick = () => compose('beat');
  $('btnAiSong').onclick = async () => {
    const caption = prompt('Нейро-песня (ACE-Step). Стиль по-английски:', 'gentle emotional anime ending, j-pop ballad, soft female vocal, piano, strings');
    if (!caption) return;
    const lyrics = prompt('Текст с секциями [verse] [chorus] (можно по-японски; пусто — без слов):', '');
    if (lyrics === null) return;
    const language = prompt('Язык текста (ja, en, ru, zh…):', 'ja') || 'en';
    const duration = +prompt('Длительность, с:', '60') || 60;
    await api('/api/ai_song', { caption, lyrics: lyrics.replace(/\\n/g, '\n'), language, duration, instrumental: !lyrics });
    status('ACE-Step генерирует — смотрите ленту справа');
  };
  $('btnAiSfx').onclick = async () => {
    const p = prompt('Нейро-SFX (Woosh). Описание по-английски:', 'long sharp claws scraping along a rough stone wall');
    if (!p) return;
    const r = await api('/api/ai_sfx', { prompt: p, duration: +prompt('Длительность, с:', '5') || 5, variants: 3 });
    status('генерирую 3 варианта: ' + r.id);
  };
  $('btnSong').onclick = () => compose('song');
  $('btnPreview').onclick = async () => {
    if (!S.cur) return;
    syncJson();
    const span = prompt('Какие доли прослушать? «от до» (пусто — всё):', '0 16');
    if (span === null) return;
    const [a, b] = span.trim().split(/\s+/).map(Number);
    try { await api('/api/preview', { recipe: S.cur.recipe, from: a || 0, to: b || 0 }); S.waitPreview = true; status('предпросмотр…'); }
    catch (err) { status(err.message, true); }
  };
  $('sampleQ').onchange = searchSamples;
  $('btnHorror').onclick = () => compose('horror');
  $('btnMorph').onclick = () => compose('morph');
  $('addNotes').onclick = () => { S.cur.recipe.tracks.push({ name: 'ноты', type: 'notes', instrument: 'piano', notes: [], gain: 0.8, effects: [] }); renderTracks(); };
  $('addSfx').onclick = () => { S.cur.recipe.tracks.push({ name: 'эффект', type: 'sfx', sfx: 'whisper', at: 0, params: {}, gain: 0.7, effects: [] }); renderTracks(); };
  $('addAudio').onclick = () => { S.cur.recipe.tracks.push({ name: 'аудио', type: 'audio', source: '', at: 0, gain: 0.8, effects: [] }); renderTracks(); };
  $('applyJson').onclick = () => {
    try { S.cur.recipe = JSON.parse($('json').value); showSound(); status('JSON применён'); }
    catch (err) { status('ошибка JSON: ' + err.message, true); }
  };
  $('btnDelete').onclick = async () => {
    if (!S.cur?.id || !confirm('Переместить «' + S.cur.id + '» в корзину?')) return;
    await api('/api/delete', { id: S.cur.id }); S.cur = null; $('sound').hidden = true; $('empty').hidden = false; loadLibrary();
  };
  $('btnExport').onclick = async () => {
    if (!S.cur?.id) return status('сначала отрендерите', true);
    const key = prompt('Ключ звука в Minecraft (namespace:имя):', 'drugs:halluc.' + S.cur.id);
    if (!key) return;
    const dir = prompt('Папка ресурспака (пусто — soundlab/exports):', '');
    const long = (S.cur.meta.seconds || 0) > 12;
    const res = await api('/api/export', { id: S.cur.id, key, pack_dir: dir, mono: confirm('Моно? (нужно для звуков «в мире» с позицией; для музыки можно «Отмена»)'), stream: long });
    status('экспортировано: ' + res.event + ' → ' + res.file);
  };
  $('upload').onchange = async (e) => {
    const f = e.target.files[0];
    if (!f) return;
    const r = await fetch('/api/upload?name=' + encodeURIComponent(f.name), { method: 'POST', body: f });
    const j = await r.json();
    if (!r.ok) return status(j.error, true);
    status('загружено: ' + j.id + ' — добавьте эффекты и нажмите «Рендер»');
    setTimeout(() => select(j.id), 1500);
  };
  document.querySelectorAll('.tabs button').forEach((b) => b.onclick = () => {
    document.querySelectorAll('.tabs button').forEach((x) => x.classList.toggle('on', x === b));
    ['tracks', 'json', 'history'].forEach((t) => $('tab-' + t).hidden = t !== b.dataset.tab);
    if (b.dataset.tab === 'json') syncJson();
  });
  const tick = () => {
    const a = $('audio');
    if (a.duration) $('playhead').style.left = (a.currentTime / a.duration * 100) + '%';
    requestAnimationFrame(tick);
  };
  tick();
}
init().catch((err) => status('ошибка запуска: ' + err.message, true));
