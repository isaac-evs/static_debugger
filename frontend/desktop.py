"""
Desktop launcher for AbinDebugger.

Wraps the existing Flask app (app.py, unmodified) in a native window via
pywebview, so a non-technical user gets a single double-click app --
no terminal, no "open your browser to localhost:5000" step. Built into
a standalone executable with PyInstaller for both macOS and Windows;
see AbinDebugger.spec and .github/workflows/build-desktop.yml.

Running this directly from source works the same way:

    python3 frontend/desktop.py
"""
import socket
import threading
import time
import urllib.request

import webview

from app import app


class Api:
    """ Exposed to the page as window.pywebview.api.* (see the JS bridge
    docs: https://pywebview.flowrl.com/guide/api.html). Used only for the
    CSV download -- WKWebView (macOS) doesn't honor <a download>/
    Content-Disposition inside a bare pywebview window: instead of saving
    a file, it just navigates the single window to the raw CSV text, with
    no browser chrome to navigate back from. Routing the save through a
    native OS "Save As" dialog avoids that navigation entirely. """

    def save_csv(self, csv_text: str, suggested_name: str) -> bool:
        """ :rtype: bool """
        result = webview.windows[0].create_file_dialog(
            webview.FileDialog.SAVE,
            save_filename=suggested_name,
            file_types=("CSV Files (*.csv)", "All files (*.*)"),
        )
        if not result:
            return False
        path = result if isinstance(result, str) else result[0]
        with open(path, "w", newline="") as f:
            f.write(csv_text)
        return True


def _free_port() -> int:
    """ Picks an available local TCP port, so a leftover process already
    bound to the default port can never block this launch.
    :rtype: int
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_until_ready(port: int, timeout: float = 15.0) -> None:
    """ Blocks until the Flask server (started on another thread) is
    actually accepting connections, so the webview window doesn't try
    to load the page before it exists.
    :rtype: None
    """
    deadline = time.time() + timeout
    url = f"http://127.0.0.1:{port}/"
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=0.5)
            return
        except Exception:
            time.sleep(0.1)
    raise RuntimeError("AbinDebugger server did not start in time.")


def main() -> None:
    port = _free_port()
    threading.Thread(
        target=lambda: app.run(host="127.0.0.1", port=port, threaded=True,
                                use_reloader=False, debug=False),
        daemon=True,
    ).start()
    _wait_until_ready(port)

    webview.create_window("AbinDebugger", f"http://127.0.0.1:{port}/", width=1280, height=860,
                           min_size=(900, 600), js_api=Api())
    webview.start()


if __name__ == "__main__":
    main()
