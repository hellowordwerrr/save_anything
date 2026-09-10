"""search.py — 在 notes/ 的标题/摘要/标签/理由中检索关键词(不搜正文)。

用法:
    python search.py 关键词 [关键词...]

多个关键词为 AND 关系,大小写不敏感;结果按保存时间倒序;无匹配打印「没找到」。
"""

import sys

import common


def main():
    common.setup_console()
    if len(sys.argv) < 2:
        print("用法: python search.py 关键词 [关键词...]")
        sys.exit(1)

    keywords = [k.lower() for k in sys.argv[1:]]
    matches = []
    for n in common.list_notes():
        meta = n["meta"]
        hit = " ".join(str(meta.get(f, "")) for f in ("标题", "摘要", "标签", "理由")).lower()
        if all(k in hit for k in keywords):
            matches.append(n)

    if not matches:
        print("没找到")
        return

    matches.sort(key=lambda n: n["meta"].get("保存时间", ""), reverse=True)
    for i, n in enumerate(matches):
        if i:
            print()
        rel = n["path"].relative_to(common.BASE_DIR).as_posix()
        print(rel)
        meta = n["meta"]
        for f in ("摘要", "标签", "理由"):
            print("  %s: %s" % (f, meta.get(f, "") or "(无)"))


if __name__ == "__main__":
    main()
