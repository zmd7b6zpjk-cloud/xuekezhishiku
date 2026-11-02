# 化工学科联络 · 本地知识库

一个完全跑在自己电脑上的跨学科知识库。以化工为主干，把数学、物理、物理化学、材料、生物、控制、经济、计算机、安全与环境串成一张网。

- **纯本地**：只用 Python 标准库（`http.server` + `sqlite3`），不注册、不联网、数据不出电脑。
- **文件即知识**：每张卡片是 `vault/` 下的一个 Markdown 文件，可以用 Git 管理，也可以用 Obsidian / VS Code / 记事本直接编辑。
- **内置网页**：全文搜索、双向链接、学科联络图谱、图片粘贴、快速记录，开箱即用。
- **留好了存入端口**：网页编辑器、快速记录、命令行、收件箱文件夹、HTTP 接口、任意编辑器，六种方式随便挑。

---

## 30 秒开始

1. 双击 **`启动知识库.bat`**（首次会创建索引，随后自动打开浏览器）。
2. 看到 <http://127.0.0.1:8765/> 就成功了。
3. 点右上角 **＋ 新建卡片**，或者直接在左侧 **快速记录** 里写一句话。

> 需要 Python 3.9+。本机已在 Python 3.12 上验证通过。命令行启动：`python kb.py serve`

已经内置 18 张示例卡片，覆盖 11 个学科、70 条双链。它们既是跨学科写作的示范，也可以直接删改。

---

## 界面怎么用

| 区域 | 作用 |
| --- | --- |
| 左侧栏 | 快速记录、按学科筛选、按标签筛选、导入收件箱、导出备份 |
| 中间列表 | 搜索/筛选结果，点击卡片进入阅读 |
| 右侧阅读区 | 正文、公式、图片、标签、**指向 / 被引用 / 相邻知识** |
| 顶部 | 搜索框（`Ctrl+K`）、联络图谱、新建卡片、深浅色切换 |

快捷键：`Ctrl+K` 搜索，`n` 新建，`/` 聚焦搜索，`Ctrl+Enter` 快速记录，`Ctrl+S` 保存，`Esc` 关闭弹层。

---

## 六个「存入端口」

### 1. 网页编辑器（最常用）

新建卡片 → 填标题 / 学科 / 标签 → 写 Markdown。右侧实时预览，支持：

- `[[另一张卡片]]`：双向链接，自动出现在双方的「指向 / 被引用」里
- `#标签`：标签，可点击筛选
- `$E = mc^2$` 与 `$$...$$`：LaTeX 公式
- 直接 **粘贴截图**：自动上传到 `attachments/` 并插入 Markdown

### 2. 快速记录

左侧栏写一句话 → 选学科 → 存入。适合先记下来、之后整理。正文里的 `#标签` 会自动变成卡片标签。

### 3. 收件箱文件夹（批量导入）

把 `.md` 或 `.txt` 丢进项目里的 `inbox/`，然后点侧栏「导入收件箱」，或运行：

```powershell
python kb.py ingest
```

- 有 frontmatter 就用 `title` / `discipline` / `tags`；
- 没有就用第一个 `# 标题`，再退回到文件名；
- 导入后原文件会归档到 `data/ingested/`，不会丢。

也可以直接把任意位置的文件复制进来并导入：

```powershell
python kb.py import "D:\笔记\有机化学.md" "D:\笔记\化工安全.txt"
```

### 4. 命令行

```powershell
python kb.py add "催化剂表征" -d 材料 -t 催化,BET -b "BET 方程见 [[催化剂与多孔材料：BET 与孔结构]]"
python kb.py search 逸度
python kb.py list
python kb.py show "精馏塔与 McCabe-Thiele 图解法"
```

### 5. HTTP 接口（脚本 / 手机 / 浏览器书签）

知识库启动后就是一个本地 JSON API，任何脚本都能写进来：

```python
import json, urllib.request

payload = {
    "title": "今天读到的概念",
    "discipline": "化学工程",
    "tags": ["热力学"],
    "body": "逸度相等是相平衡判据，见 [[化工热力学：逸度、活度与相平衡]]",
}
request = urllib.request.Request(
    "http://127.0.0.1:8765/api/entries",
    data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)
print(urllib.request.urlopen(request).read().decode("utf-8"))
```

常用接口：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/entries?q=&discipline=&tag=` | 搜索 / 列表 |
| GET | `/api/entries/<标题>` | 单张卡片 |
| POST | `/api/entries` | 新建 |
| PUT | `/api/entries/<标题>` | 修改（可改标题） |
| DELETE | `/api/entries/<标题>` | 删除（移到 `data/trash/`） |
| POST | `/api/quick` | 快速记录 `{"text": "..."}` |
| POST | `/api/ingest` | 导入 `inbox/` |
| GET | `/api/graph` | 图谱节点与边 |
| GET | `/api/stats` | 统计 |
| POST | `/api/upload?name=a.png` | 原始二进制上传图片 |

### 6. 任意编辑器直接改 `vault/`

`vault/` 是知识的唯一事实来源。用 Obsidian 把 `vault/` 当仓库打开、用 VS Code 批量替换、甚至手写 Markdown 都行；网页会在 1 秒内自动同步（切换卡片或搜索时触发）。

---

## 手机 / 局域网访问

```powershell
python kb.py serve --lan
```

启动后会打印一个带令牌的地址，例如：

```
局域网 : http://192.168.1.23:8765/?token=xxxxxxxx
```

手机与电脑连同一个 Wi-Fi，浏览器打开该地址即可。默认只监听 `127.0.0.1`；`--lan` 会自动生成访问令牌，所有请求都要带令牌（首次访问后写入 Cookie）。

---

## 卡片格式

`vault/化学工程/反应动力学：从微分方程到反应器设计.md`：

```markdown
---
title: 反应动力学：从微分方程到反应器设计
discipline: 化学工程
tags: [反应工程, 动力学, 微分方程]
created: "2026-10-07 20:10"
updated: "2026-11-02 20:00"
---

动力学回答“多快”，热力学回答“到哪”。

速率 $-r_A = k(T)f(C)$，与 [[常微分方程数值解：从欧拉到龙格-库塔]] 相连。
```

- 标题就是文件名，也是双链的锚点；改标题时系统会自动改写其他卡片里指向它的 `[[双链]]`。
- `tags` 支持 `[a, b]` 或 YAML 块列表；其他自定义字段会原样保留。
- 图片放在 `attachments/`，网页里用 `/attachments/xxx.png` 引用。

---

## 学科联络图谱

点顶部「联络图谱」：

- 节点大小 = 连接数，颜色 = 学科；
- 拖动节点、滚轮缩放、点击打开；
- 虚线节点表示「待创建」的卡片——你在正文里写了 `[[某个还没写的概念]]`，它会先以虚影出现，提醒你以后补上。

---

## 搜索语法

搜索框支持组合：

```
相平衡                  # 标题、正文、标签全文匹配
#热力学                 # 按标签
@化学工程               # 按学科
#热力学 逸度            # 标签 + 关键词
```

中文按子串匹配（`动力` 能命中「反应动力学」），英文不区分大小写。

---

## 目录结构

```
化工学科联络/
├─ kb.py                     # 命令行入口（serve / add / search / ingest / doctor …）
├─ kbcore/                   # 后端：存储、frontmatter、HTTP 服务
│  └─ static/                # 前端：HTML / CSS / 三个 JS
├─ vault/                    # ★ 知识本体：按学科分文件夹的 Markdown
│  ├─ 化学工程/
│  ├─ 数学/
│  └─ …                      # 11 个学科，18 张示例卡片
├─ inbox/                    # 投递口：把 md/txt 丢进来
├─ attachments/              # 粘贴/上传的图片
├─ data/                     # 可删除、可重建：SQLite 索引、归档、回收站
├─ backups/                  # python kb.py backup 生成的 zip
├─ tests/                    # 13 个单元 / 接口测试
├─ 启动知识库.bat
└─ README.md
```

> `vault/`、`inbox/`、`attachments/` 是你的资产；`data/` 随时可以删掉重建。

---

## 命令一览

| 命令 | 作用 |
| --- | --- |
| `python kb.py` | 启动网页（等同 `serve`） |
| `python kb.py serve --lan --no-open` | 局域网启动、不自动开浏览器 |
| `python kb.py add 标题 -d 学科 -t 标签 -b 正文` | 命令行存卡片 |
| `python kb.py search 关键词` | 命令行搜索 |
| `python kb.py list` / `show 标题` | 浏览 |
| `python kb.py ingest` / `import 文件…` | 收件箱导入 |
| `python kb.py reindex` | 手动重建索引 |
| `python kb.py doctor` | 检查断链、孤立卡片、无标签卡片 |
| `python kb.py stats` | 统计 |
| `python kb.py backup` | 打包到 `backups/`（保留最近 10 份） |

---

## 备份与迁移

- 网页侧栏「导出备份」：下载包含 `vault/` 与 `attachments/` 的 zip；
- `python kb.py backup`：备份到 `backups/kb-时间.zip`；
- **恢复**：解压后把 `vault/` 覆盖回来，删掉 `data/kb.sqlite3`，重启即可重建索引；
- **换电脑**：复制整个项目目录即可，Python 环境不需要任何第三方包。

---

## 常见问题

**Q：双击 bat 没反应？**
先在项目目录运行 `python --version`。若提示找不到 Python，安装 Python 3.9+ 并勾选“Add to PATH”，或用 `py -3 kb.py serve`。

**Q：端口 8765 被占用？**
会自动尝试 8766–8774；也可以 `python kb.py serve --port 9000`。

**Q：公式显示不出来？**
公式默认尝试从 CDN 加载 KaTeX；完全离线时网页会退化为等宽字体的原始 LaTeX，仍然可读。若要彻底离线渲染，可把 KaTeX 的 `katex.min.css/js` 下载到 `kbcore/static/` 并改 `index.html` 的引用。

**Q：删除的卡片去哪了？**
移动到 `data/trash/`，手动拷回 `vault/` 对应学科目录即可复活。

**Q：能同时用 Obsidian 吗？**
可以。把 `vault/` 作为 Obsidian 仓库打开，双链语法兼容；网页与外部编辑会自动同步。外部编辑后如果网页还没刷新，切换一下卡片或按 `F5`。

**Q：局域网访问安全吗？**
`--lan` 会强制令牌；只在可信 Wi-Fi 下使用，不要把端口映射到公网。

**Q：索引坏了怎么办？**
删掉 `data/kb.sqlite3` 重启，系统会从 `vault/` 重建；知识本身不受影响。

---

## 设计与实现

- **文件是源，索引是缓存**：写操作先落盘 Markdown，再更新 SQLite；外部改动按 mtime/size 增量同步。
- **SQLite FTS5 trigram** 做中文子串检索；短查询自动退回 LIKE；结果按标题、标签、正文命中加权，再按更新时间排序。
- **路径安全**：所有标题、学科都做文件名清洗；静态资源与附件访问做目录穿越检查。
- **零依赖**：后端只用 Python 标准库，前端原生 JavaScript + Canvas，无构建步骤。
- **测试**：`python -m unittest discover -s tests -v`（13 个用例，覆盖解析、CRUD、双链重写、收件箱、图谱、API、令牌）。

---

## 下一步可以加什么

- 卡片之间的「关系类型」（因果 / 类比 / 冲突），而不只是链接；
- 每日回顾、间隔重复；
- 从网页一键剪藏（浏览器书签小工具调 `/api/entries`）；
- 导出静态站点发布到校园网；
- 给卡片加附件 PDF 与文献引用（DOI）。

---

*知识库的价值不在“存了多少”，而在“连了多少”。先写一张，再把它接到另一张上。*
