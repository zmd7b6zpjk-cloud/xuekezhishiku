/* 联络图谱：纯 Canvas 力导向布局，无第三方依赖 */
(function (global) {
  'use strict';

  var PALETTE = [
    '#5fa8c9', '#d98d5f', '#7fb98a', '#b79ad4', '#d9b45f',
    '#8fa9d0', '#d47f95', '#a9bd6a', '#c9a37a', '#9aa7bd'
  ];
  var MISSING_COLOR = '#7d776b';

  function clamp(value, low, high) {
    return Math.max(low, Math.min(high, value));
  }

  function GraphView(canvas, data, options) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.options = options || {};
    this.onOpen = this.options.onOpen || function () {};
    this.onHover = this.options.onHover || function () {};
    this.onLeave = this.options.onLeave || function () {};

    this.theme = this.options.theme || {
      background: '#14130f',
      label: '#ece5d8',
      muted: 'rgba(236,229,216,0.45)',
      edge: 'rgba(220,210,190,0.18)',
      edgeActive: 'rgba(217,180,95,0.65)'
    };

    this.colors = new Map();
    this.nodes = [];
    this.links = [];
    this.byTitle = new Map();
    this.scale = 1;
    this.ox = 0;
    this.oy = 0;
    this.alpha = 1;
    this.width = 1;
    this.height = 1;
    this.dpr = 1;
    this.hover = null;
    this.drag = null;
    this.pan = null;
    this.moved = false;
    this.startX = 0;
    this.startY = 0;
    this.lastX = 0;
    this.lastY = 0;
    this._destroyed = false;

    this._bind();
    this.setData(data || { nodes: [], edges: [] });
    this.resize();
    this._loop = this._loop.bind(this);
    this._raf = requestAnimationFrame(this._loop);
  }

  GraphView.prototype.colorFor = function (discipline) {
    return this.colors.get(discipline) || MISSING_COLOR;
  };

  GraphView.prototype.setData = function (data) {
    var self = this;
    var disciplines = [];
    (data.nodes || []).forEach(function (node) {
      if (disciplines.indexOf(node.discipline) === -1) { disciplines.push(node.discipline); }
    });
    disciplines.sort();
    this.colors = new Map();
    disciplines.forEach(function (discipline, index) {
      self.colors.set(discipline, discipline === '待创建' ? MISSING_COLOR : PALETTE[index % PALETTE.length]);
    });

    this.nodes = (data.nodes || []).map(function (node) {
      return {
        title: node.title,
        discipline: node.discipline,
        tags: node.tags || [],
        degree: node.degree || 0,
        missing: !!node.missing,
        x: 0,
        y: 0,
        vx: 0,
        vy: 0,
        r: node.missing ? 5.5 : 6.5 + Math.min(15, Math.sqrt((node.degree || 0) + 1) * 4.2)
      };
    });
    this.byTitle = new Map();
    this.nodes.forEach(function (node) { self.byTitle.set(node.title, node); });
    this.links = (data.edges || []).filter(function (edge) {
      return self.byTitle.has(edge.source) && self.byTitle.has(edge.target);
    }).map(function (edge) {
      return { source: edge.source, target: edge.target };
    });
    this.alpha = 1;
    this.initPositions();
  };

  GraphView.prototype.initPositions = function () {
    var groups = new Map();
    this.nodes.forEach(function (node) {
      if (!groups.has(node.discipline)) { groups.set(node.discipline, []); }
      groups.get(node.discipline).push(node);
    });
    var cx = this.width / 2;
    var cy = this.height / 2;
    var radius = Math.max(90, Math.min(this.width, this.height) * 0.34);
    var names = Array.from(groups.keys());
    names.forEach(function (name, gi) {
      var group = groups.get(name);
      var angle = (gi / Math.max(1, names.length)) * Math.PI * 2 - Math.PI / 2;
      var gx = cx + Math.cos(angle) * radius;
      var gy = cy + Math.sin(angle) * radius;
      group.forEach(function (node, ni) {
        var spread = 26 + 26 * Math.sqrt(ni + 1);
        var a = angle + (ni / Math.max(1, group.length)) * Math.PI * 1.6;
        node.x = gx + Math.cos(a) * spread;
        node.y = gy + Math.sin(a) * spread;
        node.vx = 0;
        node.vy = 0;
      });
    });
  };

  GraphView.prototype.resize = function () {
    var rect = this.canvas.getBoundingClientRect();
    this.width = Math.max(1, rect.width || this.canvas.clientWidth || 800);
    this.height = Math.max(1, rect.height || this.canvas.clientHeight || 600);
    this.dpr = Math.min(global.devicePixelRatio || 1, 2);
    this.canvas.width = Math.round(this.width * this.dpr);
    this.canvas.height = Math.round(this.height * this.dpr);
    if (!this.nodes.length) { return; }
    if (!this._positioned) {
      this.initPositions();
      this._positioned = true;
    }
    var w = this.width;
    var h = this.height;
    this.nodes.forEach(function (node) {
      node.x = clamp(node.x, 40, w - 40);
      node.y = clamp(node.y, 40, h - 40);
    });
  };

  GraphView.prototype.reset = function () {
    this.scale = 1;
    this.ox = 0;
    this.oy = 0;
    this.alpha = 1;
    this.initPositions();
  };

  GraphView.prototype.setTheme = function (theme) {
    this.theme = Object.assign({}, this.theme, theme || {});
  };

  GraphView.prototype.destroy = function () {
    this._destroyed = true;
    if (this._raf) { cancelAnimationFrame(this._raf); }
    this._unbind();
    if (this._observer) { this._observer.disconnect(); }
  };

  GraphView.prototype._bind = function () {
    var self = this;
    this._onPointerDown = function (event) { self.pointerDown(event); };
    this._onPointerMove = function (event) { self.pointerMove(event); };
    this._onPointerUp = function (event) { self.pointerUp(event); };
    this._onWheel = function (event) { self.wheel(event); };
    this._onLeave = function () { self.hover = null; self.onLeave(); };
    this.canvas.addEventListener('pointerdown', this._onPointerDown);
    this.canvas.addEventListener('pointermove', this._onPointerMove);
    this.canvas.addEventListener('pointerup', this._onPointerUp);
    this.canvas.addEventListener('pointercancel', this._onPointerUp);
    this.canvas.addEventListener('pointerleave', this._onLeave);
    this.canvas.addEventListener('wheel', this._onWheel, { passive: false });
    if (global.ResizeObserver) {
      this._observer = new ResizeObserver(function () { self.resize(); });
      this._observer.observe(this.canvas);
    }
  };

  GraphView.prototype._unbind = function () {
    this.canvas.removeEventListener('pointerdown', this._onPointerDown);
    this.canvas.removeEventListener('pointermove', this._onPointerMove);
    this.canvas.removeEventListener('pointerup', this._onPointerUp);
    this.canvas.removeEventListener('pointercancel', this._onPointerUp);
    this.canvas.removeEventListener('pointerleave', this._onLeave);
    this.canvas.removeEventListener('wheel', this._onWheel);
  };

  GraphView.prototype.toWorld = function (event) {
    var rect = this.canvas.getBoundingClientRect();
    return {
      x: (event.clientX - rect.left - this.ox) / this.scale,
      y: (event.clientY - rect.top - this.oy) / this.scale
    };
  };

  GraphView.prototype.hitTest = function (x, y) {
    var best = null;
    var bestDistance = Infinity;
    for (var i = 0; i < this.nodes.length; i++) {
      var node = this.nodes[i];
      var dx = node.x - x;
      var dy = node.y - y;
      var distance = Math.sqrt(dx * dx + dy * dy);
      if (distance < node.r + 8 && distance < bestDistance) {
        best = node;
        bestDistance = distance;
      }
    }
    return best;
  };

  GraphView.prototype.pointerDown = function (event) {
    this.canvas.setPointerCapture && this.canvas.setPointerCapture(event.pointerId);
    var point = this.toWorld(event);
    var node = this.hitTest(point.x, point.y);
    this.moved = false;
    this.startX = event.clientX;
    this.startY = event.clientY;
    this.lastX = event.clientX;
    this.lastY = event.clientY;
    if (node) {
      this.drag = { node: node, dx: node.x - point.x, dy: node.y - point.y };
      this.alpha = Math.max(this.alpha, 0.25);
    } else {
      this.pan = { x: event.clientX, y: event.clientY, ox: this.ox, oy: this.oy };
    }
  };

  GraphView.prototype.pointerMove = function (event) {
    this.lastX = event.clientX;
    this.lastY = event.clientY;
    if (Math.abs(event.clientX - this.startX) + Math.abs(event.clientY - this.startY) > 4) {
      this.moved = true;
    }
    var point = this.toWorld(event);
    if (this.drag) {
      this.drag.node.x = point.x + this.drag.dx;
      this.drag.node.y = point.y + this.drag.dy;
      this.drag.node.vx = 0;
      this.drag.node.vy = 0;
      return;
    }
    if (this.pan) {
      this.ox = this.pan.ox + (event.clientX - this.pan.x);
      this.oy = this.pan.oy + (event.clientY - this.pan.y);
      return;
    }
    var node = this.hitTest(point.x, point.y);
    if (node !== this.hover) {
      this.hover = node;
      if (node) { this.onHover(node, event.clientX, event.clientY); } else { this.onLeave(); }
    } else if (node) {
      this.onHover(node, event.clientX, event.clientY);
    }
  };

  GraphView.prototype.pointerUp = function () {
    var node = this.drag ? this.drag.node : null;
    if (node && !this.moved) { this.onOpen(node.title, node); }
    this.drag = null;
    this.pan = null;
  };

  GraphView.prototype.wheel = function (event) {
    event.preventDefault();
    var rect = this.canvas.getBoundingClientRect();
    var mx = event.clientX - rect.left;
    var my = event.clientY - rect.top;
    var factor = event.deltaY < 0 ? 1.12 : 1 / 1.12;
    var next = clamp(this.scale * factor, 0.25, 3.2);
    this.ox = mx - (mx - this.ox) * (next / this.scale);
    this.oy = my - (my - this.oy) * (next / this.scale);
    this.scale = next;
  };

  GraphView.prototype._loop = function () {
    if (this._destroyed) { return; }
    this.step();
    this.draw();
    this._raf = requestAnimationFrame(this._loop);
  };

  GraphView.prototype.step = function () {
    var nodes = this.nodes;
    var count = nodes.length;
    if (!count) { return; }
    var alpha = Math.max(0.015, this.alpha);
    var cx = this.width / 2;
    var cy = this.height / 2;
    var i;
    var j;

    for (i = 0; i < count; i++) {
      var node = nodes[i];
      node.vx *= 0.84;
      node.vy *= 0.84;
      node.vx += (cx - node.x) * 0.0016 * alpha;
      node.vy += (cy - node.y) * 0.0016 * alpha;
    }

    if (count <= 280) {
      for (i = 0; i < count; i++) {
        var a = nodes[i];
        for (j = i + 1; j < count; j++) {
          var b = nodes[j];
          var dx = a.x - b.x;
          var dy = a.y - b.y;
          var distance2 = dx * dx + dy * dy;
          if (distance2 > 160000) { continue; }
          if (distance2 < 1) { distance2 = 1; }
          var distance = Math.sqrt(distance2);
          var force = (2600 * alpha) / distance2;
          var fx = (dx / distance) * force;
          var fy = (dy / distance) * force;
          a.vx += fx; a.vy += fy;
          b.vx -= fx; b.vy -= fy;
        }
      }
    }

    for (i = 0; i < this.links.length; i++) {
      var link = this.links[i];
      var source = this.byTitle.get(link.source);
      var target = this.byTitle.get(link.target);
      if (!source || !target) { continue; }
      var lx = target.x - source.x;
      var ly = target.y - source.y;
      var length = Math.sqrt(lx * lx + ly * ly) || 1;
      var rest = 105 + (source.r + target.r) * 1.6;
      var pull = (length - rest) * 0.006 * alpha;
      lx = (lx / length) * pull;
      ly = (ly / length) * pull;
      source.vx += lx; source.vy += ly;
      target.vx -= lx; target.vy -= ly;
    }

    var boundX = this.width - 34;
    var boundY = this.height - 34;
    for (i = 0; i < count; i++) {
      var current = nodes[i];
      if (this.drag && this.drag.node === current) { continue; }
      current.x += clamp(current.vx, -18, 18);
      current.y += clamp(current.vy, -18, 18);
      current.x = clamp(current.x, 34, boundX);
      current.y = clamp(current.y, 34, boundY);
    }
    this.alpha *= 0.988;
    if (this.alpha < 0.02) { this.alpha = 0.02; }
  };

  GraphView.prototype.draw = function () {
    var ctx = this.ctx;
    var theme = this.theme;
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    ctx.clearRect(0, 0, this.width, this.height);
    ctx.fillStyle = theme.background;
    ctx.fillRect(0, 0, this.width, this.height);

    ctx.save();
    ctx.translate(this.ox, this.oy);
    ctx.scale(this.scale, this.scale);

    var hovered = this.hover;
    var neighbors = null;
    if (hovered) {
      neighbors = new Set([hovered.title]);
      this.links.forEach(function (link) {
        if (link.source === hovered.title) { neighbors.add(link.target); }
        if (link.target === hovered.title) { neighbors.add(link.source); }
      });
    }

    ctx.lineWidth = 1 / this.scale;
    for (var i = 0; i < this.links.length; i++) {
      var link = this.links[i];
      var source = this.byTitle.get(link.source);
      var target = this.byTitle.get(link.target);
      if (!source || !target) { continue; }
      var active = hovered && (link.source === hovered.title || link.target === hovered.title);
      ctx.strokeStyle = active ? theme.edgeActive : theme.edge;
      ctx.lineWidth = (active ? 1.7 : 1) / this.scale;
      ctx.beginPath();
      ctx.moveTo(source.x, source.y);
      ctx.lineTo(target.x, target.y);
      ctx.stroke();
    }

    for (i = 0; i < this.nodes.length; i++) {
      var node = this.nodes[i];
      var color = this.colorFor(node.discipline);
      var dim = neighbors && !neighbors.has(node.title);
      ctx.globalAlpha = dim ? 0.28 : 1;

      ctx.beginPath();
      ctx.arc(node.x, node.y, node.r, 0, Math.PI * 2);
      if (node.missing) {
        ctx.setLineDash([3, 3]);
        ctx.strokeStyle = MISSING_COLOR;
        ctx.lineWidth = 1.4 / this.scale;
        ctx.stroke();
        ctx.setLineDash([]);
      } else {
        ctx.fillStyle = color;
        ctx.fill();
        ctx.strokeStyle = 'rgba(0,0,0,0.35)';
        ctx.lineWidth = 1 / this.scale;
        ctx.stroke();
      }

      if (node === hovered) {
        ctx.beginPath();
        ctx.arc(node.x, node.y, node.r + 6 / this.scale, 0, Math.PI * 2);
        ctx.strokeStyle = 'rgba(255,255,255,0.65)';
        ctx.lineWidth = 1.4 / this.scale;
        ctx.stroke();
      }
      ctx.globalAlpha = 1;
    }

    ctx.restore();

    var showLabels = this.scale > 0.48;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    for (i = 0; i < this.nodes.length; i++) {
      var item = this.nodes[i];
      var isHover = item === hovered;
      if (!showLabels && !isHover) { continue; }
      var sx = item.x * this.scale + this.ox;
      var sy = (item.y + item.r) * this.scale + this.oy + 7;
      var label = item.title.length > 14 ? item.title.slice(0, 14) + '…' : item.title;
      ctx.font = (isHover ? '600 ' : '500 ') + (isHover ? 13 : 12) + 'px "Segoe UI", "Microsoft YaHei", system-ui, sans-serif';
      ctx.fillStyle = item.missing ? theme.muted : theme.label;
      ctx.shadowColor = 'rgba(0,0,0,0.75)';
      ctx.shadowBlur = 4;
      ctx.fillText(label, sx, sy);
      ctx.shadowBlur = 0;
    }
  };

  global.GraphView = GraphView;
})(typeof window !== 'undefined' ? window : globalThis);
