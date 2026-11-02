# -*- coding: utf-8 -*-
"""知识库核心与 HTTP 接口测试。

运行：python -m unittest discover -s tests -v
"""
from __future__ import annotations

import http.cookiejar
import json
import shutil
import sys
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kbcore import frontmatter as fm  # noqa: E402
from kbcore import server as kbserver  # noqa: E402
from kbcore.store import KBError, Store  # noqa: E402

TMP_ROOT = ROOT / ".tmp"
TMP_ROOT.mkdir(exist_ok=True)


def make_root() -> Path:
    # 不用 tempfile.mkdtemp：它用 0o700 建目录，在本机受限令牌下会不可访问。
    root = TMP_ROOT / ("kbtest-" + uuid.uuid4().hex[:8])
    root.mkdir()
    return root


class FrontmatterTest(unittest.TestCase):
    def test_roundtrip_keeps_unicode_tags_and_unknown_keys(self):
        meta = {
            "title": "精馏塔：McCabe-Thiele 图解法",
            "discipline": "化学工程",
            "tags": ["分离工程", "相平衡"],
            "created": "2026-10-01 08:00",
            "updated": "2026-10-02 09:30",
            "aliases": ["McCabe-Thiele", "M-T 图"],
            "pinned": True,
        }
        body = "正文第一段。\n\n[[化工热力学：逸度、活度与相平衡]] 与 #热力学"
        text = fm.serialize(meta, body)
        parsed, parsed_body = fm.parse(text)
        self.assertEqual(parsed["title"], meta["title"])
        self.assertEqual(parsed["tags"], meta["tags"])
        self.assertEqual(parsed["aliases"], meta["aliases"])
        self.assertTrue(parsed["pinned"])
        self.assertEqual(parsed["created"], "2026-10-01 08:00")
        self.assertIn("[[化工热力学", parsed_body)

    def test_block_list_and_no_frontmatter(self):
        parsed, body = fm.parse("---\ntitle: 测试\ntags:\n  - 甲\n  - 乙\n---\n\n正文\n")
        self.assertEqual(parsed["tags"], ["甲", "乙"])
        self.assertEqual(body.strip(), "正文")
        meta, body = fm.parse("没有 frontmatter 的正文\n第二行")
        self.assertEqual(meta, {})
        self.assertTrue(body.startswith("没有"))


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.root = make_root()
        self.store = Store(self.root)

    def tearDown(self):
        try:
            self.store.close()
        except Exception:
            pass
        shutil.rmtree(self.root, ignore_errors=True)

    def test_create_get_and_cjk_search(self):
        self.store.create(
            "反应动力学：从微分方程到反应器设计",
            body="速率方程 $r=kC$，与 [[常微分方程数值解]] 相关。",
            discipline="化学工程",
            tags=["反应工程", "微分方程"],
        )
        entry = self.store.get("反应动力学：从微分方程到反应器设计")
        self.assertEqual(entry["discipline"], "化学工程")
        self.assertIn("反应工程", entry["tags"])
        self.assertEqual(entry["links"], ["常微分方程数值解"])

        for query in ("反应器", "动力", "kC"):
            result = self.store.query(query)
            self.assertEqual(result["total"], 1, query)
            self.assertEqual(result["items"][0]["title"], "反应动力学：从微分方程到反应器设计")

        self.assertEqual(self.store.query("", tag="微分方程")["total"], 1)
        self.assertEqual(self.store.query("", discipline="物理")["total"], 0)
        self.assertEqual(self.store.query("不存在的词")["total"], 0)

    def test_update_rename_rewrites_backlinks(self):
        self.store.create("旧名字", body="内容", discipline="数学")
        self.store.create("引用者", body="见 [[旧名字]] 与 [[旧名字|别名]]", discipline="数学")
        updated = self.store.update("旧名字", title="新名字", body="新内容")
        self.assertEqual(updated["title"], "新名字")
        self.assertIn("[[新名字]]", self.store.get("引用者")["body"])
        self.assertIn("[[新名字|别名]]", self.store.get("引用者")["body"])
        self.assertEqual(self.store.get("新名字")["backlinks"], ["引用者"])
        with self.assertRaises(KBError):
            self.store.create("引用者", body="重复")

    def test_delete_moves_file_to_trash(self):
        self.store.create("待删除", body="x", discipline="未分类")
        result = self.store.delete("待删除")
        self.assertTrue((self.root / result["trash"]).exists())
        with self.assertRaises(KBError):
            self.store.get("待删除")
        self.assertEqual(self.store.stats()["cards"], 0)

    def test_update_preserves_custom_frontmatter(self):
        self.store.create("自定义字段", body="原正文", discipline="数学")
        path = self.store.vault / "数学" / "自定义字段.md"
        text = path.read_text(encoding="utf-8").replace(
            "updated:", "aliases: [另一个名字]\nupdated:"
        )
        path.write_text(text, encoding="utf-8")
        self.store.sync(force=True)
        self.store.update("自定义字段", body="新正文")
        meta, body = fm.parse(path.read_text(encoding="utf-8"))
        self.assertEqual(meta["aliases"], ["另一个名字"])
        self.assertIn("新正文", body)

    def test_external_edit_is_indexed(self):
        self.store.create("外部编辑", body="原文", discipline="物理")
        path = self.store.vault / "物理" / "外部编辑.md"
        text = path.read_text(encoding="utf-8").replace("原文", "被 VSCode 改过的内容")
        path.write_text(text, encoding="utf-8")
        self.store.sync(force=True)
        entry = self.store.get("外部编辑")
        self.assertIn("VSCode", entry["body"])
        self.assertEqual(self.store.query("VSCode")["total"], 1)

    def test_inbox_ingest(self):
        inbox = self.root / "inbox"
        (inbox / "2026-10-01-酶与载体.md").write_text(
            "---\ntitle: 酶与载体\ntags: [酶动力学]\n---\n\n# 固定化酶\n\n扩散限制见 [[催化剂与多孔材料]] #传质\n",
            encoding="utf-8",
        )
        (inbox / "随手笔记.txt").write_text("# 随手一条\n\n今天想到：热量衡算与焓。\n", encoding="utf-8")
        (inbox / "README.md").write_text("说明", encoding="utf-8")
        result = self.store.ingest_inbox()
        self.assertEqual(len(result["added"]), 2)
        self.assertEqual(result["remaining"], 0)
        self.assertEqual(self.store.query("", tag="酶动力学")["total"], 1)
        titles = [item["title"] for item in self.store.query(limit=10)["items"]]
        self.assertIn("酶与载体", titles)
        self.assertIn("随手一条", titles)

    def test_graph_and_doctor(self):
        self.store.create("甲", body="看向 [[乙]] 与 [[不存在]]", discipline="数学", tags=["a"])
        self.store.create("乙", body="看向 [[甲]]", discipline="物理", tags=["b"])
        graph = self.store.graph()
        self.assertEqual(graph["total_cards"], 2)
        self.assertEqual(len(graph["edges"]), 3)
        missing = [node for node in graph["nodes"] if node.get("missing")]
        self.assertEqual([node["title"] for node in missing], ["不存在"])
        report = self.store.doctor()
        self.assertFalse(report["ok"])
        self.assertEqual(report["dangling"], [{"from": "甲", "to": "不存在"}])


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.root = make_root()
        self.store = Store(self.root)
        self.server = kbserver.make_server(self.store, "127.0.0.1", 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = "http://127.0.0.1:%d" % self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        try:
            self.store.close()
        except Exception:
            pass
        shutil.rmtree(self.root, ignore_errors=True)

    def call(self, method, path, payload=None, headers=None):
        data = None
        headers = dict(headers or {})
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        with urllib.request.urlopen(request) as response:
            body = response.read()
            content_type = response.headers.get("Content-Type", "")
            if "application/json" in content_type:
                return response.status, json.loads(body.decode("utf-8"))
            return response.status, body

    def test_index_and_static_are_served(self):
        status, body = self.call("GET", "/")
        self.assertEqual(status, 200)
        html = body.decode("utf-8")
        self.assertIn("化工学科联络", html)
        status, js = self.call("GET", "/static/app.js")
        self.assertEqual(status, 200)
        self.assertIn(b"function", js)

    def test_crud_and_search_api(self):
        status, data = self.call("POST", "/api/entries", {
            "title": "相平衡",
            "discipline": "化学工程",
            "tags": ["热力学"],
            "body": "逸度相等，参考 [[化学平衡]]",
        })
        self.assertEqual(status, 201)
        title = data["entry"]["title"]

        status, listing = self.call("GET", "/api/entries?q=%E9%80%B8%E5%BA%A6")
        self.assertEqual(status, 200)
        self.assertEqual(listing["total"], 1)

        status, data = self.call("PUT", "/api/entries/" + urllib.parse.quote(title), {
            "title": "相平衡与逸度",
            "body": "更新后的正文",
        })
        self.assertEqual(status, 200)
        self.assertEqual(data["entry"]["title"], "相平衡与逸度")

        status, data = self.call("DELETE", "/api/entries/" + urllib.parse.quote("相平衡与逸度"))
        self.assertEqual(status, 200)
        self.assertEqual(data["deleted"]["title"], "相平衡与逸度")

        with self.assertRaises(urllib.error.HTTPError) as context:
            self.call("GET", "/api/entries/" + urllib.parse.quote("相平衡与逸度"))
        self.assertEqual(context.exception.code, 404)

    def test_upload_quick_graph_export_and_stats(self):
        raw = b"\x89PNG\r\n\x1a\nfake-image-bytes"
        request = urllib.request.Request(
            self.base + "/api/upload?name=paste.png",
            data=raw,
            method="POST",
            headers={"Content-Type": "image/png"},
        )
        with urllib.request.urlopen(request) as response:
            uploaded = json.loads(response.read().decode("utf-8"))
        self.assertTrue(uploaded["url"].startswith("/attachments/"))
        self.assertTrue((self.store.attachments / uploaded["name"]).exists())

        status, data = self.call("POST", "/api/quick", {"text": "速记：Arrhenius 的斜率是 -Ea/R #动力学", "discipline": "化学工程"})
        self.assertEqual(status, 201)
        self.assertIn("动力学", data["entry"]["tags"])

        status, graph = self.call("GET", "/api/graph")
        self.assertEqual(status, 200)
        self.assertGreaterEqual(len(graph["nodes"]), 1)

        status, stats = self.call("GET", "/api/stats")
        self.assertEqual(stats["cards"], 1)

        request = urllib.request.Request(self.base + "/api/export")
        with urllib.request.urlopen(request) as response:
            self.assertEqual(response.headers.get("Content-Type"), "application/zip")
            self.assertGreater(len(response.read()), 100)

    def test_token_guard(self):
        server = kbserver.make_server(self.store, "127.0.0.1", 0, token="secret-token")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = "http://127.0.0.1:%d" % server.server_address[1]
        try:
            with self.assertRaises(urllib.error.HTTPError) as context:
                urllib.request.urlopen(base + "/api/stats")
            self.assertEqual(context.exception.code, 401)
            request = urllib.request.Request(base + "/api/stats", headers={"X-KB-Token": "secret-token"})
            with urllib.request.urlopen(request) as response:
                self.assertEqual(response.status, 200)

            jar = http.cookiejar.CookieJar()
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
            with opener.open(base + "/?token=secret-token") as response:
                self.assertEqual(response.status, 200)
            self.assertIn("kb_token", {cookie.name for cookie in jar})
            with opener.open(base + "/api/stats") as response:
                self.assertEqual(response.status, 200)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
