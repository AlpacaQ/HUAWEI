"""Start the local environment check and open its page after it is ready."""

import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path


def find_port() -> int:
    for port in range(8501, 8511):
        with socket.socket() as candidate:
            try:
                candidate.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("Ports 8501-8510 are busy. Close a previous check and retry.")


def main(app_filename: str = "environment_check.py", label: str = "environment check") -> None:
    project = Path(__file__).resolve().parent
    port = find_port()
    url = f"http://127.0.0.1:{port}"
    process = subprocess.Popen(
        [
            sys.executable, "-m", "streamlit", "run",
            str(project / app_filename),
            "--server.address", "127.0.0.1",
            "--server.port", str(port),
            "--server.headless", "true",
            "--browser.gatherUsageStats", "false",
        ],
        cwd=project,
    )
    # Loopback requests do not need the computer's proxy settings.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    print(f"Starting {label}. Keep this window open.", flush=True)
    try:
        for _ in range(120):
            if process.poll() is not None:
                raise RuntimeError("Streamlit exited before startup completed.")
            try:
                with opener.open(url + "/_stcore/health", timeout=1) as response:
                    if response.status == 200:
                        break
            except (urllib.error.URLError, TimeoutError, OSError):
                time.sleep(0.5)
        else:
            raise RuntimeError("Startup timed out. Check the messages above.")
        print(f"Open {url} in your browser. Press Ctrl+C here to stop.", flush=True)
        if "--check-only" in sys.argv:
            print("Local Streamlit health check: OK", flush=True)
            return
        webbrowser.open(url)
        process.wait()
    except KeyboardInterrupt:
        print("Stopping environment check.", flush=True)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Environment check failed: {error}", flush=True)
        if "--check-only" not in sys.argv:
            input("Press Enter to close this window.")
        sys.exit(1)
