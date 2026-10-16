// NFLE.Table: the one table component for client-rendered tabs. Same behavior as the Rankings table (INSIGHTS
// section 7): drawn full length (only the page scrolls), pinned name column, sticky header (a copy rides under the
// nav once the real one scrolls away when the table has to scroll sideways on phones), sortable headers (first click
// = the column's natural direction, blanks always last), edge shadow + first-name fold while scrolled sideways.
// Data in, HTML out: sorting reorders the row data and redraws the body.
//
//   const t = NFLE.Table(mountEl, {
//     columns: [{ key, label, headHtml? (header HTML instead of the label), title?, num?, stick?, first? ('asc' | 'desc'), sort? (false = not sortable), cls?, w? (px),
//                 value?: row => sortable value, html?: row => cell HTML (escape it yourself) }],
//     rows, sort: { key, dir }, rowAttrs?: row => 'data-open-pid="..."', rowClass?: row => 'teamrow', cls?: 'tiles',
//     onSort?: sort => {} (after a header click)
//   });
//   t.update(rows); t.setColumns(columns); t.setSort({ key, dir });
(() => {
  const NFLE = window.NFLE = window.NFLE || {};
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  NFLE.esc = NFLE.esc || esc;
  const all = new Set();
  const navH = () => { const n = document.querySelector('nav.tabs'); return n ? n.getBoundingClientRect().bottom : 0; };

  NFLE.Table = (mount, opt) => {
    let cols = opt.columns, rows = opt.rows || [], sort = opt.sort || null;
    mount.classList.add('dt-wrap');
    mount.innerHTML = `<div class="fhead" aria-hidden="true"><div class="fhead-in"><table class="dt ${esc(opt.cls || '')}"></table></div></div>
      <div class="scroll"><table class="dt ${esc(opt.cls || '')}"><thead></thead><tbody></tbody></table></div>`;
    const strip = mount.querySelector('.fhead'), inner = strip.firstElementChild, copy = inner.firstElementChild;
    const sc = mount.querySelector('.scroll'), tbl = sc.firstElementChild;
    const val = (c, r) => {
      const v = c.value ? c.value(r) : r[c.key];
      return v === undefined || v === null || v === '' || (typeof v === 'number' && isNaN(v)) ? null : typeof v === 'string' ? v.toLowerCase() : v;
    };
    // Fixed column widths (every column has w): tables built from the same columns line up exactly (several tables
    // stacked, e.g. Standings), and the layout doesn't shift with the content.
    const sizes = () => {
      const fixed = cols.every(c => c.w);
      tbl.classList.toggle('dt-fixed', fixed);
      tbl.querySelector('colgroup')?.remove();
      if (fixed) {
        // + room for the number chips (shell.js NFLE.chips) in every column but the pinned name
        const wd = c => c.w + (c.stick ? 0 : 8);
        tbl.insertAdjacentHTML('afterbegin', `<colgroup>${cols.map(c => `<col style="width:${wd(c)}px">`).join('')}</colgroup>`);
        tbl.style.minWidth = `${cols.reduce((t, c) => t + wd(c), 0)}px`;
      } else tbl.style.minWidth = '';
    };
    const head = () => {
      sizes();
      tbl.tHead.innerHTML = `<tr>${cols.map(c => {
        const cls = [c.num ? 'num' : '', c.stick ? 'stick' : '', c.sort === false ? 'nosort' : 'can-sort', c.cls || '',
                     sort && sort.key === c.key ? `sorted-${sort.dir} sorted` : ''].filter(Boolean).join(' ');
        const lab = c.headHtml ? c.headHtml : c.title ? `<abbr title="${esc(c.title)}">${esc(c.label)}</abbr>` : esc(c.label);
        return `<th class="${cls}" data-key="${esc(c.key)}">${lab}</th>`;
      }).join('')}</tr>`;
    };
    let gen = 0;
    const BATCH = 40;
    const body = () => {
      let rs = rows;
      if (sort) {
        const c = cols.find(x => x.key === sort.key);
        if (c) {
          const m = sort.dir === 'asc' ? 1 : -1;
          rs = rows.map((r, i) => [val(c, r), i, r]).sort((a, b) => {
            if (a[0] === null || b[0] === null) return a[0] === b[0] ? a[1] - b[1] : a[0] === null ? 1 : -1;
            return (a[0] > b[0] ? 1 : a[0] < b[0] ? -1 : a[1] - b[1]) * (a[0] === b[0] ? 1 : m);
          }).map(x => x[2]);
        }
      }
      const rowHtml = r => `<tr${opt.rowClass ? ` class="${esc(opt.rowClass(r))}"` : ''}${opt.rowAttrs ? ' ' + opt.rowAttrs(r) : ''}>${cols.map(c => {
        // the sorted column's numbers keep their chip (owner 2026-10-16: chips only on key / sorted columns)
        const cls = [c.num ? 'num' : '', c.stick ? 'stick' : '', c.cls || '', sort && sort.key === c.key && !c.stick ? 'sorted' : ''].filter(Boolean).join(' ');
        return `<td${cls ? ` class="${cls}"` : ''}>${c.html ? c.html(r) : esc(r[c.key] ?? '')}</td>`;
      }).join('')}</tr>`;
      // The rows that fill the screen first, the rest in batches after it paints (owner 2026-10-16: "lazy load so the
      // important stuff gets drawn more quickly"; the landing QB table drew 31 rows of ~70 elements for 5 in view).
      // A newer draw (sort, filter, new data) cancels the batches of an older one.
      const my = ++gen, tb = tbl.tBodies[0], first = Math.max(12, Math.ceil(innerHeight / 45));
      tb.innerHTML = rs.slice(0, first).map(rowHtml).join('');
      if (rs.length <= first) return;
      let i = first;
      const more = () => {
        if (my !== gen) return;
        tb.insertAdjacentHTML('beforeend', rs.slice(i, i + BATCH).map(rowHtml).join(''));
        i += BATCH;
        if (i < rs.length) setTimeout(more, 0); else layout();
      };
      requestAnimationFrame(() => setTimeout(more, 0));  // after the first paint
    };
    tbl.tHead.addEventListener('click', e => {
      if (e.target.closest('select, input, button')) return;  // controls inside a header (custom-column pickers)
      const th = e.target.closest('th'); if (!th || th.classList.contains('nosort')) return;
      const c = cols.find(x => x.key === th.dataset.key);
      sort = { key: c.key, dir: sort && sort.key === c.key ? (sort.dir === 'asc' ? 'desc' : 'asc') : (c.first || (c.num ? 'desc' : 'asc')) };
      head(); body(); layout();
      if (opt.onSort) opt.onSort(sort);
    });
    // Header copy for tables that scroll sideways (phones): a zero-height sticky strip under the nav.
    const buildCopy = () => {
      copy.innerHTML = tbl.tHead.outerHTML;
      const src = [...tbl.tHead.rows[0].cells], dst = [...copy.tHead.rows[0].cells];
      let total = 0;
      dst.forEach((c, i) => {
        const w = src[i].getBoundingClientRect().width; total += w;
        c.style.width = c.style.minWidth = c.style.maxWidth = w + 'px';
        c.onclick = () => src[i].click();
      });
      copy.style.width = total + 'px'; inner.style.width = sc.clientWidth + 'px'; inner.scrollLeft = sc.scrollLeft;
    };
    let built = false;
    const place = () => {
      const top = navH(), r = tbl.getBoundingClientRect(), th = tbl.tHead.getBoundingClientRect();
      const show = !sc.classList.contains('fits') && r.width > 0 && th.top < top && r.bottom - th.height > top + 40;
      if (show && !built) { buildCopy(); built = true; }
      strip.classList.toggle('show', show);
    };
    const layout = () => {
      const nv = document.querySelector('nav.tabs');
      document.documentElement.style.setProperty('--navh', `${nv ? nv.offsetHeight : 0}px`);  // 0 when phones hide the top bar
      sc.classList.remove('fits');
      sc.classList.toggle('fits', tbl.offsetWidth > 0 && tbl.scrollWidth <= sc.clientWidth + 1);
      edge();
      built = false; measured = false; place();
    };
    // More columns off the right edge: a soft fade on the wrapper says "scroll sideways" (owner 2026-10-16).
    const edge = () => { const w = sc.closest('.dt-wrap') || sc.parentElement;
      if (w) w.classList.toggle('more', sc.scrollLeft + sc.clientWidth < sc.scrollWidth - 4); };
    // Sideways scroll: header copy follows, pinned-column edge shadow, first names fold (--sx; .fn-rest --w).
    let measured = false, frame = 0;
    sc.addEventListener('scroll', () => {
      inner.scrollLeft = sc.scrollLeft;
      if (frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        if (!measured) { sc.querySelectorAll('.fn-rest').forEach(s => s.style.setProperty('--w', `${s.scrollWidth}px`)); measured = true; }
        sc.style.setProperty('--sx', `${Math.min(sc.scrollLeft, 120)}px`);
        sc.classList.toggle('scrolled', sc.scrollLeft > 2);
        edge();
      });
    }, { passive: true });
    const api = {
      update(r) { rows = r || []; body(); layout(); },
      setColumns(c) { cols = c; if (sort && !cols.some(x => x.key === sort.key)) sort = null; head(); body(); layout(); },
      setSort(x) { sort = x; head(); body(); layout(); },
      getSort: () => sort,
      layout, place,
    };
    head(); body();
    all.add(api);
    requestAnimationFrame(layout);
    return api;
  };
  window.addEventListener('scroll', () => all.forEach(t => t.place()), { passive: true });
  window.addEventListener('resize', () => all.forEach(t => t.layout()));
  document.addEventListener('nfle-route', () => requestAnimationFrame(() => all.forEach(t => t.layout())));
})();
