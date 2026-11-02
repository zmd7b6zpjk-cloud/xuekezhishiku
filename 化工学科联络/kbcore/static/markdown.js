/* 轻量 Markdown 渲染器：支持化工笔记常用的语法子集
 * 标题 / 列表 / 引用 / 代码块 / 表格 / 图片 / 加粗斜体 / 删除线
 * [[双链]] / #标签 / $行内公式$ / $$块公式$$ / 裸链接
 * 公式在检测到 KaTeX 时渲染，否则保留可读的原始文本。
 */
(function (global) {
  'use strict';

  var ESC_MAP = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
  var CJK = /[\u2e80-\u9fff\uf900-\ufaff\uff00-\uffef]/;
  var PH_CODE = '\u0001';
  var PH_MATH = '\u0002';

  function esc(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function (ch) {
      return ESC_MAP[ch];
    });
  }

  function isCjk(ch) { return !!ch && CJK.test(ch); }

  function joinSoft(lines) {
    var out = '';
    for (var i = 0; i < lines.length; i++) {
      var line = lines[i].replace(/\s+$/, '');
      if (!out) { out = line; continue; }
      out += (isCjk(out.charAt(out.length - 1)) && isCjk(line.charAt(0))) ? '' : ' ';
      out += line;
    }
    return out;
  }

  function render(src) {
    var text = String(src == null ? '' : src).replace(/\r\n?/g, '\n');
    return blocks(text.split('\n'));
  }

  function isBlockStart(line, next) {
    return /^(#{1,6})\s+/.test(line) ||
      /^```/.test(line) ||
      /^>\s?/.test(line) ||
      /^\s*([-*+]|\d+[.)])\s+/.test(line) ||
      /^\s*([-*_])(\s*\1){2,}\s*$/.test(line) ||
      /^\s*\$\$/.test(line) ||
      (line.indexOf('|') !== -1 && next !== undefined && /^\s*\|?\s*:?-{2,}/.test(next));
  }

  function blocks(lines) {
    var out = [];
    var i = 0;
    while (i < lines.length) {
      var line = lines[i];
      if (!line.trim()) { i++; continue; }

      var fence = line.match(/^```(\S*)\s*$/);
      if (fence) {
        var code = [];
        i++;
        while (i < lines.length && !/^```\s*$/.test(lines[i])) { code.push(lines[i]); i++; }
        i++;
        out.push('<pre class="code-block"><code>' + esc(code.join('\n')) + '</code></pre>');
        continue;
      }

      var heading = line.match(/^(#{1,6})\s+(.*)$/);
      if (heading) {
        var level = heading[1].length;
        out.push('<h' + level + '>' + inline(heading[2]) + '</h' + level + '>');
        i++;
        continue;
      }

      if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) {
        out.push('<hr>');
        i++;
        continue;
      }

      if (/^>\s?/.test(line)) {
        var quoted = [];
        while (i < lines.length && /^>\s?/.test(lines[i])) {
          quoted.push(lines[i].replace(/^>\s?/, ''));
          i++;
        }
        out.push('<blockquote>' + blocks(quoted) + '</blockquote>');
        continue;
      }

      if (line.indexOf('|') !== -1 && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1])) {
        i = renderTable(lines, i, out);
        continue;
      }

      if (/^\s*([-*+]|\d+[.)])\s+/.test(line)) {
        var list = renderList(lines, i);
        out.push(list.html);
        i = list.next;
        continue;
      }

      if (/^\s*\$\$/.test(line)) {
        var math = [line.replace(/^\s*\$\$/, '')];
        var closed = /\$\$\s*$/.test(math[0]);
        math[0] = math[0].replace(/\$\$\s*$/, '');
        i++;
        while (!closed && i < lines.length) {
          var current = lines[i];
          if (/\$\$\s*$/.test(current)) {
            math.push(current.replace(/\$\$\s*$/, ''));
            closed = true;
          } else {
            math.push(current);
          }
          i++;
        }
        out.push('<div class="math-block" data-tex="' + esc(math.join('\n')) + '"></div>');
        continue;
      }

      var paragraph = [];
      while (i < lines.length && lines[i].trim() &&
        !isBlockStart(lines[i], lines[i + 1])) {
        paragraph.push(lines[i]);
        i++;
      }
      if (!paragraph.length) {
        paragraph.push(lines[i]);
        i++;
      }
      out.push('<p>' + inline(joinSoft(paragraph)) + '</p>');
    }
    return out.join('\n');
  }

  function renderTable(lines, start, out) {
    function split(row) {
      return row.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(function (cell) {
        return cell.trim();
      });
    }
    var head = split(lines[start]);
    var aligns = split(lines[start + 1]).map(function (cell) {
      var left = cell.charAt(0) === ':';
      var right = cell.charAt(cell.length - 1) === ':';
      return left && right ? 'center' : right ? 'right' : left ? 'left' : '';
    });
    var i = start + 2;
    var rows = [];
    while (i < lines.length && lines[i].trim() && lines[i].indexOf('|') !== -1) {
      rows.push(split(lines[i]));
      i++;
    }
    function alignAttr(index) {
      return aligns[index] ? ' style="text-align:' + aligns[index] + '"' : '';
    }
    var headHtml = head.map(function (cell, index) {
      return '<th' + alignAttr(index) + '>' + inline(cell) + '</th>';
    }).join('');
    var bodyHtml = rows.map(function (row) {
      return '<tr>' + head.map(function (_, index) {
        return '<td' + alignAttr(index) + '>' + inline(row[index] || '') + '</td>';
      }).join('') + '</tr>';
    }).join('');
    out.push('<div class="table-wrap"><table><thead><tr>' + headHtml + '</tr></thead><tbody>' + bodyHtml + '</tbody></table></div>');
    return i;
  }

  function renderList(lines, start) {
    var ordered = /^\s*\d+[.)]\s+/.test(lines[start]);
    var itemRe = ordered ? /^(\s*)\d+[.)]\s+(.*)$/ : /^(\s*)[-*+]\s+(.*)$/;
    var anyRe = /^(\s*)([-*+]|\d+[.)])\s+/;
    var items = [];
    var i = start;
    while (i < lines.length) {
      var match = lines[i].match(itemRe);
      if (!match) { break; }
      var baseIndent = match[1].length;
      var text = match[2];
      var nested = '';
      i++;
      while (i < lines.length) {
        if (!lines[i].trim()) {
          var j = i;
          while (j < lines.length && !lines[j].trim()) { j++; }
          if (j < lines.length && itemRe.test(lines[j])) { i = j; break; }
          if (j < lines.length && /^\s+/.test(lines[j]) && anyRe.test(lines[j])) { i = j; continue; }
          break;
        }
        var sub = lines[i].match(anyRe);
        if (sub) {
          if (sub[1].length > baseIndent) {
            var child = renderList(lines, i);
            nested += child.html;
            i = child.next;
            continue;
          }
          break;
        }
        if (/^\s{2,}\S/.test(lines[i])) {
          text += ' ' + lines[i].trim();
          i++;
          continue;
        }
        break;
      }
      items.push('<li>' + inline(text) + nested + '</li>');
      if (i >= lines.length) { break; }
      if (!lines[i].trim()) { break; }
      if (!anyRe.test(lines[i])) { break; }
    }
    var tag = ordered ? 'ol' : 'ul';
    return { html: '<' + tag + '>' + items.join('') + '</' + tag + '>', next: i };
  }

  function inline(text) {
    var codes = [];
    var maths = [];
    var value = String(text == null ? '' : text);

    value = value.replace(/`([^`]+)`/g, function (_, code) {
      codes.push(code);
      return PH_CODE + (codes.length - 1) + PH_CODE;
    });
    value = value.replace(/\$\$([^$]+?)\$\$/g, function (_, tex) {
      maths.push({ tex: tex, display: true });
      return PH_MATH + (maths.length - 1) + PH_MATH;
    });
    value = value.replace(/\$(?!\s)([^$\n]+?)(?<!\s)\$/g, function (_, tex) {
      maths.push({ tex: tex, display: false });
      return PH_MATH + (maths.length - 1) + PH_MATH;
    });

    value = esc(value);

    value = value.replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g, function (_, alt, src) {
      return '<img src="' + src + '" alt="' + alt + '" loading="lazy">';
    });
    value = value.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, function (_, label, href) {
      var external = /^https?:/i.test(href);
      var safe = /^(https?:|mailto:|\/|#)/i.test(href) ? href : '#';
      return '<a href="' + safe + '"' + (external ? ' target="_blank" rel="noopener"' : '') + '>' + label + '</a>';
    });
    value = value.replace(/\[\[([^\[\]|]+)(?:\|([^\]]+))?\]\]/g, function (_, target, label) {
      var title = target.split('#')[0].trim();
      var shown = (label || target).trim();
      return '<a href="#" class="wikilink" data-wikilink="' + title + '">' + shown + '</a>';
    });

    value = value.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
    value = value.replace(/__([^_\n]+)__/g, '<strong>$1</strong>');
    value = value.replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, '$1<em>$2</em>');
    value = value.replace(/(^|[^\w])_([^_\n]+)_(?!\w)/g, '$1<em>$2</em>');
    value = value.replace(/~~([^~\n]+)~~/g, '<del>$1</del>');

    value = value.replace(/(^|[\s（(，。；、：>])#([\u4e00-\u9fa5A-Za-z0-9_\-]{1,24})/g, function (_, pre, tag) {
      return pre + '<a href="#" class="taglink" data-tag="' + tag + '">#' + tag + '</a>';
    });
    value = value.replace(/(^|[\s(])(https?:\/\/[^\s<)）]+)/g, function (_, pre, url) {
      return pre + '<a href="' + url + '" target="_blank" rel="noopener">' + url + '</a>';
    });

    value = value.replace(new RegExp(PH_CODE + '(\\d+)' + PH_CODE, 'g'), function (_, index) {
      return '<code>' + esc(codes[Number(index)]) + '</code>';
    });
    value = value.replace(new RegExp(PH_MATH + '(\\d+)' + PH_MATH, 'g'), function (_, index) {
      var item = maths[Number(index)];
      return '<span class="math' + (item.display ? ' display' : '') + '" data-tex="' + esc(item.tex) + '"></span>';
    });

    return value;
  }

  function enhanceMath(root) {
    if (!root) { return; }
    root.querySelectorAll('.math[data-tex], .math-block[data-tex]').forEach(function (el) {
      if (el.dataset.rendered === '1') { return; }
      var tex = el.dataset.tex || '';
      if (global.katex && typeof global.katex.render === 'function') {
        try {
          global.katex.render(tex, el, {
            throwOnError: false,
            displayMode: el.classList.contains('math-block') || el.classList.contains('display'),
            output: 'html',
          });
          el.dataset.rendered = '1';
          return;
        } catch (err) {
          /* 渲染失败则退回原始文本 */
        }
      }
      if (!el.textContent) { el.textContent = tex; }
    });
  }

  global.md = { render: render, enhanceMath: enhanceMath, escape: esc };
})(typeof window !== 'undefined' ? window : globalThis);
