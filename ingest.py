"""ingest.py — 处理 inbox 里的 .txt/.md:DeepSeek 摘要+标签 → 交互式问理由 → 写入 notes/ → 原文件移 archive/。

用法:
    python ingest.py

重复运行安全:inbox 为空则直接退出;同一文件重投会覆盖对应笔记。
"""

import shutil

import common


def process_file(src, api_key):
    """处理单个文件。成功(含空文件直存)→ True;失败留 inbox → False。"""
    try:
        text = common.read_text_file(src)
    except ValueError as e:
        print("  跳过:无法读取 %s(%s),留在 inbox" % (src.name, e))
        return False

    print("\n===== %s =====" % src.name)
    if not text.strip():
        summary, tags = "(空文件)", []
        print("  文件为空,不调 API,直接入库")
    else:
        text_for_api = text[:common.API_MAX_CHARS]
        if len(text) > common.API_MAX_CHARS:
            print("  文件较长,仅用前 %d 字生成摘要" % common.API_MAX_CHARS)
        result = common.summarize(text_for_api, api_key)
        summary, tags = result["summary"], result["tags"]
        if not (common.TAG_MIN <= len(tags) <= common.TAG_MAX):
            print("  警告:标签数 %d 不在 2-4 个内,已保留" % len(tags))

    print("  摘要: %s" % summary)
    print("  标签: %s" % (", ".join(tags) if tags else "(无)"))

    try:
        reason = input("  为什么存它?(回车跳过): ").strip()
    except EOFError:
        reason = ""  # stdin 被管道耗尽(批量模式),按留空处理
    if not reason:
        reason = "(待补)"
        print("  理由留空,记为「(待补)」")

    meta = {
        "标题": src.name,
        "摘要": summary,
        "标签": ", ".join(tags),
        "理由": reason,
        "保存时间": common.now_str(),
        "上次回顾": "",
    }
    note = common.build_note(meta, text)

    # 幂等:notes 里已有同 stem 笔记且标题一致 → 覆盖;否则加时间戳后缀
    stem = src.stem
    existing = common.NOTES_DIR / (stem + ".md")
    note_path = existing
    if existing.exists():
        existing_meta = common.read_note(existing)["meta"]
        if existing_meta.get("标题") == src.name:
            print("  覆盖已有笔记 %s(同一文件重投)" % existing.name)
        else:
            note_path = common.unique_path(common.NOTES_DIR, stem, ".md")

    common.write_text_file(note_path, note)
    archive_path = common.unique_path(common.ARCHIVE_DIR, src.stem, src.suffix)
    shutil.move(str(src), str(archive_path))
    print("  已写入 %s,原文件移到 archive/%s" % (note_path.name, archive_path.name))
    return True


def main():
    common.setup_console()
    common.ensure_dirs()

    files = sorted({p for pattern in ("*.txt", "*.md")
                    for p in common.INBOX_DIR.glob(pattern)
                    if not p.name.startswith(".")})

    for p in sorted(common.INBOX_DIR.iterdir()):
        if (p.is_file() and not p.name.startswith(".")
                and p.suffix.lower() not in (".txt", ".md")):
            print("跳过(非文本): %s" % p.name)

    if not files:
        print("inbox 为空,没有需要处理的文件。")
        return

    api_key = common.load_api_key()  # 有文件才检查 key

    ok = 0
    failed = 0
    try:
        for src in files:
            try:
                if process_file(src, api_key):
                    ok += 1
                else:
                    failed += 1
            except common.DeepseekError as e:
                print("  处理失败:%s,留在 inbox" % e)
                failed += 1
            except (OSError, ValueError) as e:
                print("  处理失败:%s,留在 inbox" % e)
                failed += 1
    except KeyboardInterrupt:
        print("\n已中断:成功 %d 个,其余留在 inbox,重跑即可" % ok)
        return
    print("\n处理完成:成功 %d 个,失败 %d 个(失败的留在 inbox,重跑即可)" % (ok, failed))


if __name__ == "__main__":
    main()
