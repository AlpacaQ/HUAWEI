"""双击桌面入口时，使用项目环境打开正式界面模块。"""

import sys

from start_environment import main


if __name__ == "__main__":
    try:
        main("app.py", "ROI transfer interface")
    except Exception as error:
        print(f"Could not start the interface: {error}", flush=True)
        if "--check-only" not in sys.argv:
            input("Press Enter to close this window.")
        sys.exit(1)
