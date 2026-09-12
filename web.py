# -*- coding: utf-8 -*-
"""web.py — 「拾遗」前端:浏览 + 搜索 + 回顾。零第三方依赖的单页应用。

用法:
    python web.py [--port 8000]

只监听本机 127.0.0.1。API(全部 JSON,charset=utf-8):
    GET  /api/notes?q=关键词   笔记列表(标题/摘要/标签/理由/保存时间/路径)
    GET  /api/note?path=...    单条全文(含正文),路径必须落在 notes/ 内
    GET  /api/review           下一条待回顾笔记(规则同 resurface.py)
    POST /api/review           {"path": ..., "answer": ...} 记回笔记
    GET  /api/trash            回收站列表(先清理过期条目)
    POST /api/delete           {"path": ...}  笔记移入回收站
    POST /api/restore          {"name": ...}  从回收站恢复
    POST /api/purge            {"name": ...}  彻底删除回收站条目
"""

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import common

BASE = Path(__file__).resolve().parent
INDEX_FILE = BASE / "web" / "index.html"

PAGE = None  # 启动时读入内存


class Handler(BaseHTTPRequestHandler):
    def _send(self, data, ctype, status=200):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, obj, status=200):
        self._send(json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8", status)

    @staticmethod
    def _note_path(rel):
        """校验笔记路径:resolve 后必须仍在 notes/ 内且是 .md,防目录穿越。"""
        p = (BASE / rel).resolve()
        notes = common.NOTES_DIR.resolve()
        if notes not in p.parents or p.suffix.lower() != ".md" or not p.is_file():
            return None
        return p

    @staticmethod
    def _note_dict(path, parsed):
        return {"path": path.relative_to(common.BASE_DIR).as_posix(),
                "meta": parsed["meta"], "body": parsed["body"]}

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)
        try:
            if path == "/":
                self._send(PAGE, "text/html; charset=utf-8")
            elif path == "/api/notes":
                q = " ".join(qs.get("q", [""])).strip()
                keywords = q.split() if q else []
                out = [self._note_dict(n["path"], n)
                       for n in common.search_notes(common.list_notes(), keywords)]
                self._send_json({"notes": out})
            elif path == "/api/note":
                p = self._note_path(qs.get("path", [""])[0])
                if p is None:
                    self._send_json({"error": "笔记不存在"}, 404)
                else:
                    self._send_json(self._note_dict(p, common.read_note(p)))
            elif path == "/api/review":
                notes = common.list_notes()
                if not notes:
                    self._send_json({"note": None})
                else:
                    pick = common.pick_review_note(notes)
                    self._send_json({"note": self._note_dict(pick["path"], pick)})
            elif path == "/api/trash":
                common.purge_trash()
                self._send_json({"trash": common.trash_list()})
            else:
                self._send_json({"error": "not found"}, 404)
        except (OSError, ValueError) as e:
            self._send_json({"error": str(e)}, 500)

    def do_POST(self):
        path = urlparse(self.path).path
        if path not in ("/api/review", "/api/delete", "/api/restore", "/api/purge"):
            self._send_json({"error": "not found"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict):
                payload = {}
        except (ValueError, TypeError, OSError) as e:
            self._send_json({"error": str(e)}, 400)
            return
        try:
            if path == "/api/review":
                p = self._note_path(str(payload.get("path", "")))
                if p is None:
                    self._send_json({"error": "笔记不存在"}, 404)
                    return
                answer = str(payload.get("answer", "")).strip() or "(无回应)"
                updated = common.record_review(p, answer)
                self._send_json({"note": self._note_dict(p, updated)})
            elif path == "/api/delete":
                p = self._note_path(str(payload.get("path", "")))
                if p is None:
                    self._send_json({"error": "笔记不存在"}, 404)
                    return
                common.move_to_trash(p)
                self._send_json({"ok": True})
            elif path == "/api/restore":
                dest = common.restore_from_trash(str(payload.get("name", "")))
                if dest is None:
                    self._send_json({"error": "回收站里没有这条笔记"}, 404)
                else:
                    self._send_json({"ok": True, "path": dest})
            else:  # /api/purge
                if not common.remove_from_trash(str(payload.get("name", ""))):
                    self._send_json({"error": "回收站里没有这条笔记"}, 404)
                else:
                    self._send_json({"ok": True})
        except (OSError, ValueError) as e:
            self._send_json({"error": str(e)}, 500)

    def log_message(self, fmt, *args):
        pass  # 个人工具,终端保持安静


def main():
    common.setup_console()
    parser = argparse.ArgumentParser(description="拾遗前端(浏览+搜索+回顾+回收站)")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    common.ensure_dirs()
    removed = common.purge_trash()
    if removed:
        print("回收站清理:%d 条过期笔记已永久删除" % len(removed))

    global PAGE
    try:
        PAGE = INDEX_FILE.read_bytes()
    except OSError:
        sys.exit("找不到 %s,请确认文件存在" % INDEX_FILE)

    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    except OSError as e:
        sys.exit("端口 %d 起不来:%s" % (args.port, e))
    print("拾遗已启动: http://127.0.0.1:%d  (Ctrl+C 退出)" % args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出")


if __name__ == "__main__":
    main()
