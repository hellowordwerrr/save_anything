"""resurface.py — 挑一条最久没看过的笔记,问「现在还有用吗?」并记回笔记。

用法:
    python resurface.py

选笔记规则(合并排序,定义在 common.review_key):每条笔记取「最近看过
时间」= 上次回顾,缺失时用保存时间顶替,推这个时间最早的一条。刚存的
排最后,存得久又没看过的排最前。回答(回车=跳过不记录)追加到正文末尾,
并更新头部「上次回顾」。
"""

import common


def main():
    common.setup_console()
    try:
        notes = common.list_notes()
        if not notes:
            print("没有笔记")
            return

        pick = common.pick_review_note(notes)
        meta = pick["meta"]
        rel = pick["path"].relative_to(common.BASE_DIR).as_posix()

        print("===== %s =====" % rel)
        print("标题: %s" % (meta.get("标题") or "(无)"))
        print("摘要: %s" % (meta.get("摘要") or "(无)"))
        print("标签: %s" % (meta.get("标签") or "(无)"))
        print("理由: %s" % (meta.get("理由") or "(无)"))
        last = meta.get("上次回顾")
        print("保存时间: %s(上次回顾: %s)" % (
            meta.get("保存时间") or "(无)", last or "从未"))

        try:
            answer = input("\n现在还有用吗?(回车=跳过不记录): ").strip()
        except EOFError:
            answer = ""  # stdin 被管道耗尽,按跳过处理
        if not answer:
            print("已跳过:这条不记录,下次回顾还会遇到它。")
            return

        updated = common.record_review(pick["path"], answer)
        print("已记录: [%s] %s" % (updated["meta"]["上次回顾"], answer))
    except KeyboardInterrupt:
        print("\n已退出,这条没有记录。")


if __name__ == "__main__":
    main()
