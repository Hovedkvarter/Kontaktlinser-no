/* Kontaktlinser.no search v2. Pure matching + shared homepage/header UI.
 * Search spelling only: product identity, hrefs, prices and offers are not changed.
 * No network/API/AI dependency beyond the existing /data/search-index.json.
 */
(function (root, factory) {
  'use strict';
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root && root.document) {
    root.KLSearch = api;
    if (root.document.readyState === 'loading') {
      root.document.addEventListener('DOMContentLoaded', function () { api.init(root); });
    } else {
      api.init(root);
    }
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  var PROTECTED = new Set(['max', 'xr', 'toric', 'multifocal']);
  var IGNORE = new Set(['for', 'with', 'linse', 'linser', 'kontaktlinse', 'kontaktlinser']);
  var WORDS = {
    pk: 'pack', pakke: 'pack', pakker: 'pack', pakning: 'pack', pakninger: 'pack',
    packs: 'pack', stk: 'pack', pcs: 'pack',
    torisk: 'toric', toriske: 'toric', astigmatism: 'toric', astigmatisme: 'toric',
    multifokal: 'multifocal', multifokale: 'multifocal'
  };

  function tokens(value) {
    var text = String(value || '').toLowerCase().replace(/[\u00ae\u2122]/g, '')
      .replace(/æ/g, 'ae').replace(/ø/g, 'o').normalize('NFKD')
      .replace(/[\u0300-\u036f]/g, '');
    // Explicit spelling variants, not new private-label/product equivalences.
    text = text.replace(/\bone\s*day\b/g, '1 day').replace(/\bmy\s+day\b/g, 'myday')
      .replace(/\bi\s+wear\b/g, 'iwear').replace(/\beye\s+q\b/g, 'eyeq')
      .replace(/\beasy\s+vision\b/g, 'easyvision').replace(/\btrue\s+lens\b/g, 'truelens')
      .replace(/\bair\s*optix\b/g, 'air optix').replace(/\bopti\s*free\b/g, 'opti free')
      .replace(/\baqua\s+comfort\b/g, 'aquacomfort')
      .replace(/\bhydra\s+luxe\b/g, 'hydraluxe').replace(/\bhydra\s+glyde\b/g, 'hydraglyde')
      .replace(/(\d+)\s+linser\b/g, '$1 pack');
    // Letter/digit boundaries make 1-day / 1 day / 1day and Total1 / Total 1 equal.
    // Numeric tokens stay whole: 6 never matches 16, and 30 never matches 90.
    return (text.match(/[a-z]+|\d+(?:[.,]\d+)?/g) || []).map(function (t) {
      t = t.replace(',', '.');
      return Object.prototype.hasOwnProperty.call(WORDS, t) ? WORDS[t] : t;
    }).filter(function (t) { return !IGNORE.has(t); });
  }

  function normalize(value) { return tokens(value).join(' '); }
  function numeric(t) { return /^\d/.test(t); }
  function internalHref(href) {
    return typeof href === 'string' && /^\/(?!\/)/.test(href) && !/[\\\u0000-\u0020]/.test(href);
  }

  function createIndex(items) {
    if (!Array.isArray(items)) throw new TypeError('Invalid search index');
    var seen = new Set();
    return items.filter(function (item) {
      if (!item || typeof item.name !== 'string' || !internalHref(item.href) || seen.has(item.href)) return false;
      seen.add(item.href);
      return true;
    }).map(function (item, order) {
      var name = tokens(item.name);
      return { item: item, name: name, phrase: name.join(' '),
        terms: tokens(item.search || item.name), order: order };
    });
  }

  function oneEdit(a, b) {
    // One missing/extra/wrong letter OR one adjacent transposition. Bounded work.
    if (Math.abs(a.length - b.length) > 1) return false;
    if (a === b) return true;
    var i = 0;
    while (i < a.length && a[i] === b[i]) i++;
    if (a.length === b.length) {
      return a.slice(i + 1) === b.slice(i + 1) ||
        (a[i] === b[i + 1] && a[i + 1] === b[i] && a.slice(i + 2) === b.slice(i + 2));
    }
    return a.length > b.length ? a.slice(i + 1) === b.slice(i) : a.slice(i) === b.slice(i + 1);
  }

  function identityMatches(entry, query) {
    var counts = Object.create(null);
    entry.name.forEach(function (t) { if (numeric(t)) counts[t] = (counts[t] || 0) + 1; });
    for (var i = 0; i < query.length; i++) {
      var t = query[i];
      // A number or an explicit variant cannot be supplied by metadata/series counts.
      if (numeric(t)) {
        if (!counts[t]) return false;
        counts[t]--;
        if (/^(pack|ml|g)$/.test(query[i + 1] || '') &&
            (' ' + entry.phrase + ' ').indexOf(' ' + t + ' ' + query[i + 1] + ' ') === -1) return false;
      }
      if (PROTECTED.has(t) && entry.name.indexOf(t) === -1) return false;
    }
    return true;
  }

  function scoreEntry(entry, query, fuzzy) {
    if (!identityMatches(entry, query)) return null;
    var score = 0, edits = 0, allName = true;
    for (var i = 0; i < query.length; i++) {
      var t = query[i], exact = entry.name.indexOf(t) !== -1;
      var prefix = function (word) { return !numeric(t) && word.indexOf(t) === 0; };
      if (exact) { score += 100; continue; }
      if (entry.name.some(prefix)) { score += 70; continue; }
      allName = false;
      if (entry.terms.indexOf(t) !== -1) { score += 40; continue; }
      if (entry.terms.some(prefix)) { score += 20; continue; }
      // Fuzzy fallback only for ONE word >=4 letters, never numbers/short variant codes.
      if (fuzzy && edits === 0 && t.length >= 4 && !numeric(t) && !PROTECTED.has(t) &&
          entry.name.some(function (word) { return !numeric(word) && word.length >= 4 && oneEdit(t, word); })) {
        edits++; score += 5; continue;
      }
      return null;
    }
    var phrase = query.join(' '), exactName = entry.phrase === phrase;
    if (exactName) score += 10000;
    else if (entry.phrase.indexOf(phrase + ' ') === 0) score += 500;
    else if ((' ' + entry.phrase + ' ').indexOf(' ' + phrase + ' ') !== -1) score += 250;
    if (allName) score += 300;
    score -= Math.max(0, entry.name.length - query.length);
    return { item: entry.item, score: score, approximate: edits > 0, exactName: exactName, order: entry.order };
  }

  function search(index, value) {
    var query = tokens(value);
    if (String(value || '').length > 160 || query.length > 20) {
      return { results: [], approximate: false, tooLong: true };
    }
    if (!query.length) return { results: [], approximate: false, tooLong: false };
    var results = index.map(function (e) { return scoreEntry(e, query, false); }).filter(Boolean);
    if (!results.length && query.some(function (t) { return t.length >= 4 && !numeric(t); })) {
      results = index.map(function (e) { return scoreEntry(e, query, true); }).filter(Boolean);
    }
    results.sort(function (a, b) { return b.score - a.score || a.order - b.order; });
    return { results: results, approximate: results.some(function (r) { return r.approximate; }), tooLong: false };
  }

  function directMatch(result) {
    if (result.approximate) return null; // Spelling suggestions always require a choice.
    var exact = result.results.filter(function (r) { return r.exactName; });
    if (exact.length === 1) return exact[0];
    return result.results.length === 1 ? result.results[0] : null;
  }

  function esc(value) {
    return String(value || '').replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function init(win) {
    var doc = win.document, rows = doc.querySelectorAll('.search-row'), dataPromise = null;
    if (!rows.length) return;
    if (!doc.getElementById('kl-search-v2-style')) {
      var style = doc.createElement('style');
      style.id = 'kl-search-v2-style';
      style.textContent = '.search-suggestions{max-height:min(420px,60vh);overflow-y:auto;overscroll-behavior:contain}' +
        '.search-suggestion[aria-selected="true"]{background:var(--blue-tint);outline:2px solid var(--blue);outline-offset:-2px}' +
        '.search-result-note{padding:10px 14px;font-size:.8rem;line-height:1.4;color:var(--muted);border-bottom:1px solid var(--border)}' +
        '.search-more,.search-retry{display:block;width:100%;padding:12px 14px;background:transparent;border:0;border-top:1px solid var(--border);color:var(--blue);font:inherit;font-size:.85rem;cursor:pointer;text-align:left;min-height:44px}' +
        '.search-more:focus-visible,.search-retry:focus-visible{outline:2px solid var(--blue);outline-offset:-2px}' +
        '.search-no-match a{color:var(--blue);text-decoration:underline}' +
        '.search-live-status{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}' +
        '.search-suggestion>div:last-child{min-width:0}.search-suggestion-name{overflow-wrap:anywhere}';
      doc.head.appendChild(style);
    }

    function loadData() {
      if (dataPromise) return dataPromise;
      dataPromise = Promise.resolve().then(function () {
        var products = doc.getElementById('product-search-data');
        if (products) {
          var labels = doc.getElementById('private-label-search-data');
          var data = JSON.parse(products.textContent);
          if (!Array.isArray(data)) throw new TypeError('Invalid inline search data');
          if (labels) {
            var labelData = JSON.parse(labels.textContent);
            if (!Array.isArray(labelData)) throw new TypeError('Invalid label search data');
            data = data.concat(labelData);
          }
          return data;
        }
        return win.fetch('/data/search-index.json').then(function (response) {
          if (!response.ok) throw new Error('Search index HTTP ' + response.status);
          return response.json();
        });
      }).then(createIndex).catch(function (error) {
        dataPromise = null; // A later focus/retry can recover; never cache a failed request as []!
        throw error;
      });
      return dataPromise;
    }

    function track(row, name, source) {
      var guide = row.getAttribute('data-guide');
      if (!guide) return;
      win.__klTrack && win.__klTrack({ event: 'guide_search_click', guide: guide, product: name, source: source });
    }

    rows.forEach(function (row, rowIndex) {
      if (row.dataset.klSearchReady) return;
      var input = row.querySelector('.search-input'), suggestions = row.querySelector('.search-suggestions');
      var button = row.querySelector('.search-btn');
      if (!input || !suggestions || !button) return;
      row.dataset.klSearchReady = '2';
      var listId = 'kl-search-list-' + rowIndex, active = -1, visible = [], limit = 8;
      var revision = 0, current = null, currentValue = '';
      var live = doc.createElement('div');
      live.className = 'search-live-status'; live.setAttribute('role', 'status');
      live.setAttribute('aria-live', 'polite'); live.setAttribute('aria-atomic', 'true');
      row.appendChild(live);
      var emptyList = '<div id="' + listId + '" role="listbox" aria-label="Søkeforslag"></div>';
      suggestions.innerHTML = emptyList;
      input.setAttribute('role', 'combobox'); input.setAttribute('aria-autocomplete', 'list');
      input.setAttribute('aria-expanded', 'false'); input.setAttribute('aria-controls', listId);
      input.setAttribute('enterkeyhint', 'search');
      if (!input.labels || !input.labels.length) input.setAttribute('aria-label', 'Søk etter linse eller merke');

      function hide() {
        revision++; active = -1; current = null; visible = [];
        input.setAttribute('aria-expanded', 'false'); input.removeAttribute('aria-activedescendant');
        suggestions.style.display = 'none'; suggestions.innerHTML = emptyList; live.textContent = '';
      }
      function open() { suggestions.style.display = 'block'; input.setAttribute('aria-expanded', 'true'); }
      function choose(match, source) {
        if (!match || !internalHref(match.item.href)) return;
        track(row, match.item.name, source);
        win.location.href = match.item.href;
      }
      function render(result, choosing) {
        current = result; active = -1;
        input.removeAttribute('aria-activedescendant');
        visible = result.results.slice(0, limit);
        if (!visible.length) {
          var text = result.tooLong ? 'Prøv et kortere produktnavn.' : 'Ingen treff. Prøv merkenavnet eller en kortere del av produktnavnet.';
          suggestions.innerHTML = '<div class="search-no-match">' + text + ' <a href="/#merker">Se alle merker</a></div>' + emptyList;
          live.textContent = text; open(); return;
        }
        var note = result.approximate ? 'Mente du disse? Forslag med lignende skrivemåte.' :
          (choosing ? 'Velg riktig variant og pakning.' : result.results.length + (result.results.length === 1 ? ' treff' : ' treff'));
        var html = '<div class="search-result-note">' + esc(note) + '</div><div id="' + listId + '" role="listbox" aria-label="Søkeforslag">';
        html += visible.map(function (match, i) {
          var item = match.item;
          var image = typeof item.image === 'string' && /^(https?:\/\/|\/(?!\/))/.test(item.image) ? item.image : '';
          var thumb = image ? '<div class="product-thumb"><img src="' + esc(image) + '" alt="" loading="lazy"></div>' :
            '<div class="product-thumb">' + esc(String(item.badge || item.meta || item.name).slice(0, 2).toUpperCase()) + '</div>';
          return '<a class="search-suggestion" id="' + listId + '-' + i + '" role="option" aria-selected="false" tabindex="-1" href="' + esc(item.href) + '" data-name="' + esc(item.name) + '">' + thumb +
            '<div><div class="search-suggestion-name">' + esc(item.name) + '</div><div class="search-suggestion-meta">' + esc(item.meta) + '</div></div></a>';
        }).join('');
        html += '</div>';
        if (result.results.length > limit) html += '<button type="button" class="search-more">Vis alle ' + result.results.length + ' treff</button>';
        suggestions.innerHTML = html;
        live.textContent = result.results.length + ' treff.' + (result.approximate ? ' Forslag med lignende skrivemåte.' : ' Bruk piltastene for å velge.');
        open();
      }
      function update(choosing) {
        var value = input.value, ticket = ++revision;
        if (!value.trim()) { hide(); return Promise.resolve(null); }
        if (currentValue !== value) { limit = 8; currentValue = value; }
        return loadData().then(function (index) {
          if (ticket !== revision || input.value !== value) return null;
          var result = search(index, value); render(result, choosing); return result;
        }).catch(function () {
          if (ticket !== revision || input.value !== value) return null;
          current = null; visible = []; active = -1; input.removeAttribute('aria-activedescendant');
          suggestions.innerHTML = '<div class="search-no-match">Søket kunne ikke lastes. <a href="/#merker">Bla i merkene</a></div><button type="button" class="search-retry">Prøv søket igjen</button>' + emptyList;
          live.textContent = 'Søket kunne ikke lastes. Prøv igjen.'; open(); return null;
        });
      }
      function select(delta) {
        if (!visible.length) return;
        active = active < 0 ? (delta > 0 ? 0 : visible.length - 1) : (active + delta + visible.length) % visible.length;
        suggestions.querySelectorAll('.search-suggestion').forEach(function (link, i) {
          link.setAttribute('aria-selected', i === active ? 'true' : 'false');
        });
        var option = doc.getElementById(listId + '-' + active);
        input.setAttribute('aria-activedescendant', option.id);
        option.scrollIntoView({ block: 'nearest' });
      }
      function submit() {
        if (currentValue === input.value && active >= 0 && visible[active]) { choose(visible[active], 'button'); return; }
        update(true).then(function (result) {
          if (!result) return;
          var match = directMatch(result);
          if (match) choose(match, 'button');
          else input.focus();
        });
      }
      input.addEventListener('input', function () { current = null; active = -1; update(false); });
      input.addEventListener('focus', function () {
        if (current && currentValue === input.value && input.getAttribute('aria-expanded') === 'true') return;
        // A focus-only preload must not generate an unhandled rejection.
        if (input.value.trim()) update(false); else loadData().catch(function () {});
      });
      input.addEventListener('keydown', function (event) {
        if (event.isComposing) return;
        if (event.key === 'Escape') { event.preventDefault(); hide(); return; }
        if (event.key === 'Enter') { event.preventDefault(); submit(); return; }
        if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
        event.preventDefault();
        var delta = event.key === 'ArrowDown' ? 1 : -1;
        if (current && currentValue === input.value && input.getAttribute('aria-expanded') === 'true') select(delta);
        else update(false).then(function (result) { if (result) select(delta); });
      });
      button.addEventListener('click', submit);
      suggestions.addEventListener('click', function (event) {
        var more = event.target.closest('.search-more');
        if (more && current) { event.stopPropagation(); limit = current.results.length; render(current, false); input.focus(); return; }
        if (event.target.closest('.search-retry')) { event.stopPropagation(); update(false); return; }
        var link = event.target.closest('.search-suggestion');
        if (link) track(row, link.getAttribute('data-name'), 'suggestion');
      });
      doc.addEventListener('click', function (event) { if (!row.contains(event.target)) hide(); });
      doc.addEventListener('focusin', function (event) { if (!row.contains(event.target)) hide(); });
    });
  }

  return { normalize: normalize, tokens: tokens, createIndex: createIndex, search: search, directMatch: directMatch, init: init };
});
