# -*- coding: utf-8 -*-
"""app.py — 「拾遗」打包入口:单进程跑网页服务 + 桌面悬浮窗。

打包后:
    拾遗.exe                 # 悬浮窗 + 内置网页服务(无黑窗)
    拾遗.exe --serve-only    # 只跑网页服务(悬浮窗冷拉起用)

开发模式直接 python app.py 效果相同。
"""

import sys
import threading

import common
import edge
import web


def main():
    if "--serve-only" in sys.argv:
        web.serve(quiet=True)   # 阻塞;端口被占/资源缺失时静默返回
        return
    # web 服务放 daemon 线程,悬浮窗 mainloop 跑主线程;退出时线程随进程消亡
    threading.Thread(target=web.serve, kwargs={"quiet": True},
                     daemon=True).start()
    edge.run_app()


if __name__ == "__main__":
    main()
