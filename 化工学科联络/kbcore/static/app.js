/* 化工学科联络 · 前端交互 */
(function () {
  'use strict';

  var $ = function (selector, root) { return (root || document).querySelector(selector); };
  var $$ = function (selector, root) { return Array.prototype.slice.call((root || document).querySelectorAll(selector)); };
  var ESC_MAP = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
  function esc(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function (ch) { return ESC_MAP[ch]; });
  }

  var PALETTE = ['#2f6f8f', '#b1613a', '#4f7d5a', '#8a6aa8', '#b08a2e', '#5b7fa8', '#a34d63', '#6f7d3f', '#8c6b4f', '#56657a'];
  function disciplineColor(name) {
    var text = String(name || '');
    var hash = 0;
    for (var i = 0; i < text.length; i++) { hash = (hash * 31 + text.charCodeAt(i)) % 9973; }
    return PALETTE[hash % PALETTE.length];
  }

  var state = {
    q: '',
    discipline: '',
    tag: '',
    items: [],
    total: null,
    stats: null,
    current: null,
    editing: null,
    graphView: null,
    toastTimer: null,
  };

  // ---------------------------------------------------------------- 请求
  function api(path, options) {
    var opts = Object.assign({ headers: {} }, options || {});
    if (opts.json !== undefined) {
      opts.method = opts.method || 'POST';
      opts.body = JSON.stringify(opts.json);
      opts.headers['Content-Type'] = 'application/json';
      delete opts.json;
    }
    return fetch(path, opts).then(function (response) {
      var type = response.headers.get('Content-Type') || '';
      var parsing = type.indexOf('application/json') !== -1 ? response.json() : Promise.resolve(null);
      return parsing.then(function (data) {
        if (!response.ok) {
          var error = new Error((data && data.error) || ('请求失败（' + response.status + '）'));
          error.status = response.status;
          throw error;
        }
        return data;
      });
    });
  }

  function toast(message, kind) {
    var el = $('#toast');
    el.textContent = message;
    el.className = 'toast' + (kind === 'error' ? ' error' : '');
    el.hidden = false;
    clearTimeout(state.toastTimer);
    state.toastTimer = setTimeout(function () { el.hidden = true; }, 2600);
  }

  function formatDate(value) {
    if (!value) { return ''; }
    return value.length >= 10 ? value.slice(5) : value;
  }

  // ---------------------------------------------------------------- 启动
  document.addEventListener('DOMContentLoaded', init);

  function init() {
    applyTheme(localStorage.getItem('kb-theme') || 'light');
    bindEvents();
    refreshAll().then(function () {
      var title = titleFromHash();
      if (title) { openEntry(title, { push: false }); } else { renderEmpty(); }
    });
    window.addEventListener('load', function () {
      if (state.current) { window.md.enhanceMath($('#reader')); }
      if (state.graphView) { state.graphView.resize(); }
    });
  }

  function titleFromHash() {
    var hash = decodeURIComponent(location.hash.replace(/^#\/?/, ''));
    return hash || '';
  }

  function refreshAll() {
    return Promise.all([refreshStats(), loadEntries()]);
  }

  function refreshStats() {
    return api('/api/stats').then(function (stats) {
      state.stats = stats;
      renderSidebar();
    }).catch(function (error) {
      toast(error.message, 'error');
    });
  }

  function renderSidebar() {
    var stats = state.stats;
    if (!stats) { return; }

    var disciplines = $('#disciplines');
    var rows = stats.disciplines.map(function (item) {
      var active = state.discipline === item.name ? ' active' : '';
      return '<li><button class="nav-item' + active + '" data-discipline="' + esc(item.name) + '">' +
        '<span class="dot" style="--dot:' + disciplineColor(item.name) + '"></span>' +
        '<span class="name">' + esc(item.name) + '</span>' +
        '<span class="count">' + item.count + '</span></button></li>';
    }).join('');
    disciplines.innerHTML = rows || '<li class="hint" style="padding:6px 9px">还没有卡片</li>';

    var select = $('#quick-discipline');
    var previous = select.value;
    var options = ['<option value="未分类">未分类</option>'].concat(stats.disciplines.map(function (item) {
      return '<option value="' + esc(item.name) + '">' + esc(item.name) + '</option>';
    }));
    select.innerHTML = options.join('');
    if (previous && stats.disciplines.some(function (item) { return item.name === previous; })) {
      select.value = previous;
    } else if (stats.disciplines.some(function (item) { return item.name === '未分类'; })) {
      select.value = '未分类';
    }

    var datalist = $('#discipline-options');
    datalist.innerHTML = stats.disciplines.map(function (item) {
      return '<option value="' + esc(item.name) + '"></option>';
    }).join('');

    $('#tags').innerHTML = stats.tags.length ? stats.tags.map(function (item) {
      var active = state.tag === item.name ? ' active' : '';
      return '<button class="tag-chip' + active + '" data-tag="' + esc(item.name) + '">#' + esc(item.name) +
        '<span class="n">' + item.count + '</span></button>';
    }).join('') : '<span class="hint">暂无标签</span>';
    $('#tag-count').textContent = (stats.tag_total != null ? stats.tag_total : stats.tags.length) + ' 个';

    var inbox = $('#inbox-count');
    inbox.textContent = stats.inbox;
    inbox.className = 'badge' + (stats.inbox > 0 ? ' hot' : '');
    $('#inbox-count').title = stats.inbox ? '有文件等待导入' : '收件箱是空的';

    updateListHeading();

    $('#stat-line').textContent = stats.cards + ' 张卡片 · ' + (stats.words / 10000).toFixed(1) + ' 万字 · ' + stats.links + ' 条双链';
  }

  function updateListHeading(total) {
    if (total != null) { state.total = total; }
    var count = state.total != null ? state.total : (state.stats ? state.stats.cards : 0);
    $('#list-title').textContent = state.q ? '搜索：' + state.q : (state.discipline || '全部卡片');
    var bits = [count + ' 张'];
    if (state.discipline) { bits.push('学科：' + state.discipline); }
    if (state.tag) { bits.push('#' + state.tag); }
    $('#list-sub').innerHTML = bits.map(esc).join('<span class="dot"> · </span>');
    $('#btn-clear-filter').hidden = !(state.q || state.discipline || state.tag);
  }

  // ---------------------------------------------------------------- 列表
  function loadEntries() {
    var params = new URLSearchParams();
    params.set('limit', '500');
    if (state.q) { params.set('q', state.q); }
    if (state.discipline) { params.set('discipline', state.discipline); }
    if (state.tag) { params.set('tag', state.tag); }
    return api('/api/entries?' + params.toString()).then(function (data) {
      state.items = data.items;
      renderList(data);
      updateListHeading(data.total);
    }).catch(function (error) {
      $('#cards').innerHTML = '<li class="list-empty">加载失败：' + esc(error.message) + '</li>';
    });
  }

  function renderList(data) {
    var list = $('#cards');
    if (!data.items.length) {
      list.innerHTML = '<li class="list-empty">没有匹配的卡片。<br>换个关键词，或者新建一张。</li>';
      return;
    }
    var currentTitle = state.current ? state.current.title : '';
    list.innerHTML = data.items.map(function (item) {
      var active = item.title === currentTitle ? ' active' : '';
      var tags = item.tags.slice(0, 3).map(function (tag) {
        return '<span class="card-tag">#' + esc(tag) + '</span>';
      }).join('');
      return '<li class="card' + active + '" data-title="' + esc(item.title) + '">' +
        '<div class="card-top"><span class="card-title">' + esc(item.title) + '</span>' +
        '<time>' + esc(formatDate(item.updated)) + '</time></div>' +
        '<p class="card-excerpt">' + esc(item.excerpt || '（暂无正文）') + '</p>' +
        '<div class="card-foot"><span class="card-discipline"><i class="discipline-dot" style="background:' +
        disciplineColor(item.discipline) + '"></i>' + esc(item.discipline) + '</span>' + tags + '</div>' +
        '</li>';
    }).join('');
  }

  function markActive() {
    var title = state.current ? state.current.title : '';
    $$('#cards .card').forEach(function (card) {
      card.classList.toggle('active', card.dataset.title === title);
    });
  }

  // ---------------------------------------------------------------- 阅读
  function openEntry(title, options) {
    options = options || {};
    return api('/api/entries/' + encodeURIComponent(title)).then(function (data) {
      state.current = data.entry;
      renderReader();
      markActive();
      document.body.classList.add('reading');
      if (options.push !== false) {
        history.pushState({ title: title }, '', '#/' + encodeURIComponent(title));
      }
      $('#reader').scrollTop = 0;
    }).catch(function (error) {
      if (error.status === 404) {
        openEditor(null, title);
        toast('「' + title + '」还不存在，已为你打开新建卡片');
      } else {
        toast(error.message, 'error');
      }
    });
  }

  function renderReader() {
    var entry = state.current;
    var reader = $('#reader');
    if (!entry) { renderEmpty(); return; }

    var tags = entry.tags.map(function (tag) {
      return '<button class="chip tag" data-tag="' + esc(tag) + '">#' + esc(tag) + '</button>';
    }).join('');

    var linksSection = '';
    var resolved = entry.links_resolved || [];
    var dangling = entry.dangling || [];
    if (resolved.length || dangling.length) {
      linksSection =
        '<section class="section"><h3 class="section-title">指向的卡片 <span class="hint">' +
        (resolved.length + dangling.length) + '</span></h3><div class="chip-row">' +
        resolved.map(function (title) {
          return '<button class="chip" data-open="' + esc(title) + '">' + esc(title) + '</button>';
        }).join('') +
        dangling.map(function (title) {
          return '<button class="chip missing" data-new="' + esc(title) + '">' + esc(title) + ' ＋</button>';
        }).join('') + '</div></section>';
    } else {
      linksSection = '<section class="section"><h3 class="section-title">指向的卡片</h3>' +
        '<p class="hint">还没有建立联系。在正文里用 <code>[[卡片标题]]</code> 把它接到别的学科上。</p></section>';
    }

    var backlinks = (entry.backlinks || []).length ?
      '<section class="section"><h3 class="section-title">被这些卡片引用 <span class="hint">' +
      entry.backlinks.length + '</span></h3><div class="chip-row">' +
      entry.backlinks.map(function (title) {
        return '<button class="chip" data-open="' + esc(title) + '">' + esc(title) + '</button>';
      }).join('') + '</div></section>' : '';

    var related = (entry.related || []).length ?
      '<section class="section"><h3 class="section-title">相邻知识 <span class="hint">按标签与学科推荐</span></h3>' +
      '<div class="chip-row">' + entry.related.map(function (item) {
        return '<button class="related-item" data-open="' + esc(item.title) + '">' +
          '<strong>' + esc(item.title) + '</strong><span>' + esc(item.reason) + '</span></button>';
      }).join('') + '</div></section>' : '';

    var words = entry.words || 0;
    var minutes = Math.max(1, Math.round(words / 350));

    reader.innerHTML =
      '<div class="reader-inner">' +
      '<div class="reader-bar">' +
      '<button class="link tiny mobile-back" data-action="back">← 返回列表</button>' +
      '<span class="eyebrow">' + esc(entry.discipline) + '</span>' +
      '<div class="reader-actions">' +
      '<button class="btn ghost small" data-action="edit">编辑</button>' +
      '<button class="btn ghost small" data-action="copy">复制链接</button>' +
      '<button class="btn ghost small" data-action="delete">删除</button>' +
      '</div></div>' +
      '<h1 class="reader-title">' + esc(entry.title) + '</h1>' +
      '<div class="reader-meta">' +
      '<span>创建 ' + esc(entry.created) + '</span>' +
      '<span>更新 ' + esc(entry.updated) + '</span>' +
      '<span>' + words + ' 字 · 约 ' + minutes + ' 分钟</span>' +
      '<span class="path">' + esc(entry.path) + '</span>' +
      '</div>' +
      (tags ? '<div class="reader-tags">' + tags + '</div>' : '') +
      '<article class="markdown reader-body">' + window.md.render(entry.body) + '</article>' +
      linksSection + backlinks + related +
      '</div>';

    window.md.enhanceMath(reader);
  }

  function renderEmpty() {
    state.current = null;
    markActive();
    $('#reader').innerHTML =
      '<div class="empty-reader">' +
      '<div class="empty-glyph">⌬</div>' +
      '<h1>把学科连成一张网</h1>' +
      '<p>这里是你自己的本地知识库：化工、数学、物理、材料、生物、经济……<br>每张卡片都是一个节点，双链把节点连成网络。</p>' +
      '<div class="empty-tips">' +
      '<b>从三个入口开始：</b><br>' +
      '① 点右上角「新建卡片」，写下第一个概念；<br>' +
      '② 在正文里用 <code>[[另一张卡片]]</code> 建立联系；<br>' +
      '③ 把 Markdown 笔记丢进 <code>inbox/</code>，点侧栏「导入收件箱」。' +
      '</div>' +
      '<button class="btn primary" data-action="new">＋ 新建第一张卡片</button>' +
      '</div>';
    document.body.classList.remove('reading');
  }

  // ---------------------------------------------------------------- 编辑器
  function openEditor(entry, presetTitle) {
    state.editing = entry ? entry.title : null;
    $('#editor-heading').textContent = entry ? '编辑卡片' : '新建卡片';
    $('#editor-path').textContent = entry ? '保存到 ' + entry.path : '保存后写入 vault/ 目录，可用 Obsidian 直接编辑';
    $('#f-title').value = entry ? entry.title : (presetTitle || '');
    $('#f-discipline').value = entry ? entry.discipline : (state.discipline || '');
    $('#f-tags').value = entry ? entry.tags.join(', ') : '';
    $('#f-body').value = entry ? entry.body : '';
    $('#btn-delete').hidden = !entry;
    $('#editor-overlay').hidden = false;
    document.body.classList.add('no-scroll');
    updatePreview();
    setTimeout(function () { $('#f-title').focus(); }, 40);
  }

  function closeEditor() {
    $('#editor-overlay').hidden = true;
    document.body.classList.remove('no-scroll');
    state.editing = null;
  }

  function updatePreview() {
    $('#f-preview').innerHTML = window.md.render($('#f-body').value);
    window.md.enhanceMath($('#f-preview'));
  }

  function insertAtCursor(textarea, text) {
    var start = textarea.selectionStart || 0;
    var end = textarea.selectionEnd || 0;
    textarea.setRangeText(text, start, end, 'end');
    textarea.focus();
    updatePreview();
  }

  function uploadImage(file) {
    return fetch('/api/upload?name=' + encodeURIComponent(file.name || 'paste.png'), {
      method: 'POST',
      headers: { 'Content-Type': file.type || 'application/octet-stream' },
      body: file,
    }).then(function (response) {
      return response.json().then(function (data) {
        if (!response.ok) { throw new Error(data.error || '图片上传失败'); }
        return data;
      });
    });
  }

  function handlePaste(event) {
    var items = (event.clipboardData || window.clipboardData).items;
    if (!items) { return; }
    for (var i = 0; i < items.length; i++) {
      if (items[i].type && items[i].type.indexOf('image/') === 0) {
        var file = items[i].getAsFile();
        if (!file) { continue; }
        event.preventDefault();
        var textarea = $('#f-body');
        toast('正在上传图片…');
        uploadImage(file).then(function (data) {
          var snippet = '\n![](' + data.url + ')\n';
          insertAtCursor(textarea, snippet);
          toast('图片已插入');
        }).catch(function (error) { toast(error.message, 'error'); });
        return;
      }
    }
  }

  function submitEditor(event) {
    event.preventDefault();
    var title = $('#f-title').value.trim();
    if (!title) { toast('请填写标题', 'error'); return; }
    var payload = {
      title: title,
      discipline: $('#f-discipline').value.trim(),
      tags: $('#f-tags').value.trim(),
      body: $('#f-body').value,
    };
    var button = $('#btn-save');
    button.disabled = true;
    button.textContent = '保存中…';
    var request = state.editing
      ? api('/api/entries/' + encodeURIComponent(state.editing), { method: 'PUT', json: payload })
      : api('/api/entries', { json: payload });
    request.then(function (data) {
      return refreshAll().then(function () {
        closeEditor();
        history.replaceState({ title: data.entry.title }, '', '#/' + encodeURIComponent(data.entry.title));
        return openEntry(data.entry.title, { push: false });
      }).then(function () {
        toast('已保存：' + data.entry.title);
      });
    }).catch(function (error) {
      toast(error.message, 'error');
    }).finally(function () {
      button.disabled = false;
      button.textContent = '保存';
    });
  }

  function deleteCurrent(entry) {
    var target = entry || state.current;
    if (!target) { return; }
    if (!window.confirm('确定删除「' + target.title + '」？\n文件会移动到 data/trash/，仍可手动找回。')) { return; }
    api('/api/entries/' + encodeURIComponent(target.title), { method: 'DELETE' }).then(function () {
      closeEditor();
      history.replaceState(null, '', location.pathname);
      renderEmpty();
      return refreshAll().then(function () { toast('已删除，可在 data/trash/ 找回'); });
    }).catch(function (error) { toast(error.message, 'error'); });
  }

  // ---------------------------------------------------------------- 快速记录 / 收件箱
  function quickCapture() {
    var textarea = $('#quick');
    var text = textarea.value.trim();
    if (!text) { textarea.focus(); return; }
    var button = $('#btn-quick');
    button.disabled = true;
    api('/api/quick', { json: { text: text, discipline: $('#quick-discipline').value } }).then(function (data) {
      textarea.value = '';
      return refreshAll().then(function () {
        history.replaceState({ title: data.entry.title }, '', '#/' + encodeURIComponent(data.entry.title));
        return openEntry(data.entry.title, { push: false });
      }).then(function () { toast('已存入：' + data.entry.title); });
    }).catch(function (error) {
      toast(error.message, 'error');
    }).finally(function () { button.disabled = false; });
  }

  function ingestInbox() {
    var button = $('#btn-ingest');
    button.disabled = true;
    button.textContent = '导入中…';
    api('/api/ingest', { json: {} }).then(function (data) {
      var message = '导入 ' + data.added.length + ' 个文件';
      if (data.errors.length) { message += '，失败 ' + data.errors.length + ' 个'; }
      if (data.remaining) { message += '，还剩 ' + data.remaining + ' 个'; }
      toast(message, data.errors.length ? 'error' : '');
      return refreshAll();
    }).catch(function (error) {
      toast(error.message, 'error');
    }).finally(function () {
      button.disabled = false;
      button.textContent = '导入收件箱';
    });
  }

  // ---------------------------------------------------------------- 图谱
  function graphTheme() {
    var styles = getComputedStyle(document.documentElement);
    return {
      background: styles.getPropertyValue('--graph-bg').trim() || '#14130f',
      label: styles.getPropertyValue('--graph-ink').trim() || '#ece5d8',
      muted: 'rgba(236,229,216,0.42)',
      edge: 'rgba(220,210,190,0.16)',
      edgeActive: 'rgba(217,180,95,0.7)',
    };
  }

  function openGraph() {
    var overlay = $('#graph-overlay');
    overlay.hidden = false;
    document.body.classList.add('no-scroll');
    api('/api/graph').then(function (data) {
      if (overlay.hidden) { return; }
      var canvas = $('#graph-canvas');
      if (state.graphView) { state.graphView.destroy(); }
      state.graphView = new window.GraphView(canvas, data, {
        theme: graphTheme(),
        onOpen: function (title, node) {
          closeGraph();
          if (node && node.missing) {
            openEditor(null, title);
          } else {
            openEntry(title);
          }
        },
        onHover: function (node, x, y) { showGraphTip(node, x, y); },
        onLeave: function () { $('#graph-tip').hidden = true; },
      });
      var real = data.nodes.filter(function (node) { return !node.missing; }).length;
      $('#graph-sub').textContent = real + ' 张卡片 · ' + data.edges.length + ' 条联系';
      renderGraphLegend(data);
      setTimeout(function () { if (state.graphView) { state.graphView.resize(); } }, 30);
    }).catch(function (error) {
      overlay.hidden = true;
      document.body.classList.remove('no-scroll');
      toast(error.message, 'error');
    });
  }

  function closeGraph() {
    if (state.graphView) {
      state.graphView.destroy();
      state.graphView = null;
    }
    $('#graph-overlay').hidden = true;
    $('#graph-tip').hidden = true;
    document.body.classList.remove('no-scroll');
  }

  function renderGraphLegend(data) {
    var counts = new Map();
    data.nodes.forEach(function (node) { counts.set(node.discipline, (counts.get(node.discipline) || 0) + 1); });
    var html = Array.from(counts.entries()).map(function (pair) {
      var color = state.graphView ? state.graphView.colorFor(pair[0]) : '#888';
      return '<span class="legend-item"><i style="--c:' + color + '"></i>' + esc(pair[0]) + ' ' + pair[1] + '</span>';
    }).join('');
    $('#graph-legend').innerHTML = html;
  }

  function showGraphTip(node, clientX, clientY) {
    var tip = $('#graph-tip');
    var stage = $('#graph-stage').getBoundingClientRect();
    var meta = node.missing ? '待创建' : (node.discipline + ' · ' + node.degree + ' 条联系');
    tip.innerHTML = '<strong>' + esc(node.title) + '</strong><span>' + esc(meta) + '</span>';
    tip.hidden = false;
    var left = clientX - stage.left + 14;
    var top = clientY - stage.top + 14;
    left = Math.min(left, stage.width - tip.offsetWidth - 12);
    top = Math.min(top, stage.height - tip.offsetHeight - 12);
    tip.style.left = Math.max(8, left) + 'px';
    tip.style.top = Math.max(8, top) + 'px';
  }

  // ---------------------------------------------------------------- 主题 / 事件
  function applyTheme(theme) {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem('kb-theme', theme);
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) { meta.content = theme === 'dark' ? '#131210' : '#f2eee5'; }
    if (state.graphView) { state.graphView.setTheme(graphTheme()); }
  }

  function isTyping(target) {
    if (!target) { return false; }
    var tag = target.tagName;
    return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || target.isContentEditable;
  }

  function resetFilters() {
    state.q = '';
    state.discipline = '';
    state.tag = '';
    state.total = null;
    $('#search').value = '';
    refreshAll();
  }

  function bindEvents() {
    $('#btn-theme').addEventListener('click', function () {
      applyTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
    });

    $('#btn-menu').addEventListener('click', function () {
      document.body.classList.toggle('sidebar-open');
    });

    var searchTimer = null;
    $('#search').addEventListener('input', function (event) {
      var value = event.target.value.trim();
      clearTimeout(searchTimer);
      searchTimer = setTimeout(function () {
        state.q = value;
        loadEntries();
      }, 180);
    });
    $('#search').addEventListener('keydown', function (event) {
      if (event.key === 'Escape') {
        event.target.value = '';
        state.q = '';
        state.total = null;
        loadEntries();
        event.target.blur();
      }
    });

    $('#btn-new').addEventListener('click', function () { openEditor(null); });
    $('#btn-all').addEventListener('click', resetFilters);
    $('#btn-clear-filter').addEventListener('click', resetFilters);

    $('#disciplines').addEventListener('click', function (event) {
      var button = event.target.closest('[data-discipline]');
      if (!button) { return; }
      state.discipline = button.dataset.discipline;
      if (window.innerWidth <= 1020) { document.body.classList.remove('sidebar-open'); }
      refreshAll();
    });

    $('#tags').addEventListener('click', function (event) {
      var button = event.target.closest('[data-tag]');
      if (!button) { return; }
      state.tag = state.tag === button.dataset.tag ? '' : button.dataset.tag;
      refreshAll();
    });

    $('#cards').addEventListener('click', function (event) {
      var card = event.target.closest('.card');
      if (!card) { return; }
      document.body.classList.remove('sidebar-open');
      openEntry(card.dataset.title);
    });

    $('#btn-quick').addEventListener('click', quickCapture);
    $('#quick').addEventListener('keydown', function (event) {
      if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
        event.preventDefault();
        quickCapture();
      }
    });
    $('#btn-ingest').addEventListener('click', ingestInbox);
    $('#btn-export').addEventListener('click', function () { window.location.href = '/api/export'; });
    $('#btn-graph').addEventListener('click', openGraph);
    $('#btn-graph-close').addEventListener('click', closeGraph);
    $('#btn-graph-reset').addEventListener('click', function () {
      if (state.graphView) { state.graphView.reset(); }
    });

    $('#reader').addEventListener('click', function (event) {
      var action = event.target.closest('[data-action]');
      if (action) {
        var name = action.dataset.action;
        if (name === 'edit' && state.current) { openEditor(state.current); }
        if (name === 'delete' && state.current) { deleteCurrent(state.current); }
        if (name === 'copy' && state.current) {
          var url = location.href.split('#')[0] + '#/' + encodeURIComponent(state.current.title);
          if (navigator.clipboard) {
            navigator.clipboard.writeText(url).then(function () { toast('链接已复制'); },
              function () { toast(url); });
          } else {
            toast(url);
          }
        }
        if (name === 'back') {
          document.body.classList.remove('reading');
        }
        if (name === 'new') { openEditor(null); }
        return;
      }

      var tag = event.target.closest('[data-tag]');
      if (tag) {
        event.preventDefault();
        state.tag = state.tag === tag.dataset.tag ? '' : tag.dataset.tag;
        if (window.innerWidth <= 760) { document.body.classList.remove('reading'); }
        refreshAll();
        return;
      }

      var link = event.target.closest('.wikilink');
      if (link) {
        event.preventDefault();
        openEntry(link.dataset.wikilink);
        return;
      }

      var open = event.target.closest('[data-open]');
      if (open) {
        openEntry(open.dataset.open);
        return;
      }

      var create = event.target.closest('[data-new]');
      if (create) {
        openEditor(null, create.dataset.new);
      }
    });

    $('#editor').addEventListener('submit', submitEditor);
    $('#btn-cancel').addEventListener('click', closeEditor);
    $('#btn-delete').addEventListener('click', function () { deleteCurrent(); });
    $('#f-body').addEventListener('input', function () {
      clearTimeout(updatePreview._timer);
      updatePreview._timer = setTimeout(updatePreview, 120);
    });
    $('#f-body').addEventListener('paste', handlePaste);

    $('#editor-overlay').addEventListener('mousedown', function (event) {
      if (event.target === $('#editor-overlay')) { closeEditor(); }
    });
    $('#graph-overlay').addEventListener('mousedown', function (event) {
      if (event.target === $('#graph-overlay')) { closeGraph(); }
    });

    document.addEventListener('keydown', function (event) {
      var meta = event.ctrlKey || event.metaKey;
      if (meta && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        $('#search').focus();
        $('#search').select();
        return;
      }
      if (meta && event.key.toLowerCase() === 's' && !$('#editor-overlay').hidden) {
        event.preventDefault();
        $('#editor').requestSubmit();
        return;
      }
      if (event.key === 'Escape') {
        if (!$('#editor-overlay').hidden) { closeEditor(); return; }
        if (!$('#graph-overlay').hidden) { closeGraph(); return; }
        if (document.body.classList.contains('reading') && window.innerWidth <= 760) {
          document.body.classList.remove('reading');
          return;
        }
        if (!isTyping(event.target)) {
          state.tag = '';
          state.discipline = '';
          state.q = '';
          state.total = null;
          $('#search').value = '';
          refreshAll();
        }
        return;
      }
      if (!isTyping(event.target) && !event.altKey && !meta) {
        if (event.key === 'n') {
          event.preventDefault();
          openEditor(null);
        } else if (event.key === '/') {
          event.preventDefault();
          $('#search').focus();
        }
      }
    });

    window.addEventListener('popstate', function () {
      var title = titleFromHash();
      if (title) {
        openEntry(title, { push: false });
      } else {
        renderEmpty();
      }
    });
  }
})();
