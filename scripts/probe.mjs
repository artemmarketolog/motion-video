// Frame fingerprints for the incremental cache. Runs inside the hf.py sandbox:
//   hf.py /ABS/VIDEO probe <out.json relative to the video folder>
// Seeks the registered GSAP timeline to every frame and hashes what is visible
// (inline styles, SVG attributes, geometry, text, CSS-rule styles, asset bytes).
// No screenshots, so a whole video takes seconds. Equal hash => equal pixels as
// long as the composition follows the determinism contract.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {createRequire} from 'node:module';

const VERSION = 'probe-v2';
const out = process.argv[2];
if (!out) throw new Error('usage: probe.mjs <output.json>');
const root = '/project';
const require = createRequire('/runtime/node_modules/hyperframes/package.json');
const puppeteer = require('puppeteer-core');
const sha = (x) => crypto.createHash('sha1').update(x).digest('hex');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const attr = (name) => (html.match(new RegExp('data-composition-id[^>]*?' + name + '="([^"]+)"')) ||
  html.match(new RegExp(name + '="([^"]+)"[^>]*data-composition-id')) || [])[1];
const fps = Number(attr('data-fps') || 30);
const width = Number(attr('data-width'));
const height = Number(attr('data-height'));
const duration = Number(attr('data-duration'));
const compId = (html.match(/data-composition-id="([^"]+)"/) || [])[1];
if (!width || !height || !duration || !compId) throw new Error('root composition attributes missing');
const frames = Math.round(duration * fps);
const started = Date.now();

const fileHash = new Map();
function assetHash(url) {
  if (!url.startsWith('file:///project/')) return 'external:' + url;
  const p = decodeURIComponent(url.slice('file://'.length).split(/[?#]/)[0]);
  if (!fileHash.has(p)) fileHash.set(p, fs.existsSync(p) ? sha(fs.readFileSync(p)) : 'missing');
  return fileHash.get(p);
}

const browser = await puppeteer.launch({
  executablePath: '/opt/chrome/chrome', headless: true,
  args: ['--no-sandbox', '--disable-gpu', '--allow-file-access-from-files', '--font-render-hinting=none',
         '--hide-scrollbars', '--mute-audio'],
});
try {
  const page = await browser.newPage();
  await page.setViewport({width, height});
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.goto('file:///project/index.html', {waitUntil: 'load', timeout: 60000});
  await page.evaluate(async (id) => {
    await document.fonts.ready;
    for (let i = 0; i < 100 && !(window.__timelines && window.__timelines[id]); i++) await new Promise((r) => setTimeout(r, 50));
    if (!(window.__timelines && window.__timelines[id])) throw new Error('timeline not registered: ' + id);
  }, compId);

  // Static pass: CSS-rule-derived style per element (inline styles removed), text, attributes.
  const statics = await page.evaluate(() => {
    const els = Array.from(document.body.querySelectorAll('*')).filter((e) => e.tagName !== 'SCRIPT');
    const saved = els.map((e) => e.getAttribute('style'));
    els.forEach((e) => e.removeAttribute('style'));
    const urls = new Set();
    const grab = (value) => { for (const m of value.matchAll(/url\("?([^")]+)"?\)/g)) urls.add(m[1]); };
    const res = els.map((e) => {
      const cs = getComputedStyle(e);
      let css = '';
      for (let i = 0; i < cs.length; i++) { const k = cs[i]; const v = cs.getPropertyValue(k); css += k + ':' + v + ';'; if (v.includes('url(')) grab(v); }
      let pseudo = '';
      for (const p of ['::before', '::after']) {
        const ps = getComputedStyle(e, p);
        if (ps.content && ps.content !== 'none' && ps.content !== 'normal') {
          for (let i = 0; i < ps.length; i++) pseudo += ps[i] + ':' + ps.getPropertyValue(ps[i]) + ';';
        }
      }
      // Timing attributes are handled by the frame pass (visibility window, media time); keeping them
      // here would mark every frame dirty when only the total length changed.
      const attrs = Array.from(e.attributes).filter((a) => !['style', 'data-start', 'data-duration', 'data-track-index', 'data-media-start'].includes(a.name)).map((a) => a.name + '=' + a.value).join('\u0001');
      const text = Array.from(e.childNodes).filter((n) => n.nodeType === 3).map((n) => n.nodeValue).join('\u0002');
      const src = e.currentSrc || e.src || (e.getAttribute && (e.getAttribute('href') || e.getAttribute('xlink:href'))) || '';
      if (src && typeof src === 'string') urls.add(new URL(src, location.href).href);
      return {tag: e.tagName, attrs, text, css, pseudo, src: src ? new URL(String(src), location.href).href : ''};
    });
    els.forEach((e, i) => { if (saved[i] !== null) e.setAttribute('style', saved[i]); });
    const fonts = [];
    for (const sheet of Array.from(document.styleSheets)) {
      let rules = [];
      try { rules = Array.from(sheet.cssRules); } catch (_) { rules = []; }
      for (const r of rules) if (r.type === CSSRule.FONT_FACE_RULE) fonts.push(r.cssText);
    }
    return {items: res, urls: Array.from(urls), fonts};
  });
  for (const f of statics.fonts) for (const m of f.matchAll(/url\("?([^")]+)"?\)/g)) statics.urls.push(new URL(m[1], 'file:///project/index.html').href);
  const urlHashes = Object.fromEntries(statics.urls.map((u) => [u, assetHash(u)]));
  const staticHashes = statics.items.map((s) => {
    let deps = s.src ? urlHashes[s.src] || assetHash(s.src) : '';
    for (const m of (s.css + s.pseudo).matchAll(/url\("?([^")]+)"?\)/g)) deps += '|' + (urlHashes[m[1]] || m[1]);
    return sha(JSON.stringify([s.tag, s.attrs, s.text, s.css, s.pseudo, deps])).slice(0, 16);
  });
  const global = sha(JSON.stringify([VERSION, width, height, fps, statics.fonts,
    statics.fonts.map((f) => Array.from(f.matchAll(/url\("?([^")]+)"?\)/g)).map((m) => assetHash(new URL(m[1], 'file:///project/index.html').href)))]));

  // Frame pass.
  const result = await page.evaluate((id, fps, frames, W, H, staticHashes) => {
    const tl = window.__timelines[id];
    const els = Array.from(document.body.querySelectorAll('*')).filter((e) => e.tagName !== 'SCRIPT');
    const index = new Map(els.map((e, i) => [e, i]));
    const rootEl = document.querySelector('[data-composition-id]');
    const timed = els.map((e) => e === rootEl || !e.hasAttribute('data-start') ? null :
      [Number(e.getAttribute('data-start')), e.hasAttribute('data-duration') ? Number(e.getAttribute('data-duration')) : Infinity]);
    const M = 400;
    // 53-bit string hash (cyrb53), fast and good enough for change detection.
    const h53 = (str, seed = 0) => {
      let h1 = 0xdeadbeef ^ seed, h2 = 0x41c6ce57 ^ seed;
      for (let i = 0; i < str.length; i++) { const c = str.charCodeAt(i); h1 = Math.imul(h1 ^ c, 2654435761); h2 = Math.imul(h2 ^ c, 1597334677); }
      h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909);
      h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909);
      return (4294967296 * (2097151 & h2) + (h1 >>> 0)).toString(36);
    };
    const hashes = [];
    let volatile = 0;
    for (let f = 0; f < frames; f++) {
      const t = f / fps;
      tl.totalTime(t, false);
      let acc = '';
      const walk = (e) => {
        const i = index.get(e);
        if (i === undefined) return;
        const w = timed[i];
        if (w && (t < w[0] - 1e-9 || t >= w[0] + w[1] - 1e-9)) return;
        const cs = getComputedStyle(e);
        if (cs.display === 'none' || cs.opacity === '0') return;
        const r = e.getBoundingClientRect();
        const leaf = e.children.length === 0;
        const onScreen = r.right >= -M && r.bottom >= -M && r.left <= W + M && r.top <= H + M;
        if (!leaf || onScreen) {
          let dyn = staticHashes[i] + '|' + (e.getAttribute('style') || '') + '|' + r.x.toFixed(2) + ',' + r.y.toFixed(2) + ',' + r.width.toFixed(2) + ',' + r.height.toFixed(2) + '|' + cs.visibility;
          if (e.namespaceURI === 'http://www.w3.org/2000/svg') dyn += '|' + Array.from(e.attributes).map((a) => a.name + '=' + a.value).join(';');
          if (e.tagName === 'VIDEO' && w) dyn += '|v' + Math.round((Number(e.getAttribute('data-media-start') || 0) + (t - w[0]) * Number(e.getAttribute('data-playback-rate') || 1)) * fps);
          if (e.tagName === 'CANVAS') {
            if (e.hasAttribute('data-mv-volatile')) { dyn += '|volatile' + f; volatile++; }
            else { try { dyn += '|c' + h53(e.toDataURL()); } catch (_) { dyn += '|volatile' + f; volatile++; } }
          }
          const text = Array.from(e.childNodes).filter((n) => n.nodeType === 3).map((n) => n.nodeValue).join('');
          if (text) dyn += '|t' + text;
          acc += h53(dyn) + ';';
        }
        for (const c of e.children) walk(c);
      };
      for (const c of document.body.children) walk(c);
      hashes.push(h53(acc, 7) + h53(acc, 13));
    }
    return {hashes, volatile, elements: els.length};
  }, compId, fps, frames, width, height, staticHashes);
  const report = {version: VERSION, composition: compId, fps, width, height, duration, frames,
    global, hashes: result.hashes, elements: result.elements, volatile_canvas_frames: result.volatile,
    page_errors: errors, elapsed_s: (Date.now() - started) / 1000};
  const target = path.resolve(root, out);
  if (!target.startsWith(root + '/')) throw new Error('output must stay inside the video folder');
  fs.mkdirSync(path.dirname(target), {recursive: true});
  fs.writeFileSync(target, JSON.stringify(report));
  console.log(JSON.stringify({frames, elements: result.elements, elapsed_s: report.elapsed_s, page_errors: errors.length, out: target}));
} finally {
  await browser.close();
}
