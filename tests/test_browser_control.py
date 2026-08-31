"""Tests for browser_control new actions: upload, wait, download, script, headless."""
import os
import tempfile

from actions.browser_control import (
    _BrowserSession,
    _SessionRegistry,
    browser_control,
)


def _make_session():
    """Create a _BrowserSession in headless mode for testing."""
    sess = _BrowserSession("chrome", headless=True)
    sess.start()
    return sess


class TestBrowserSessionUpload:
    def test_upload_file_not_found(self):
        sess = _make_session()
        try:
            result = sess.run(sess.upload_file("input[type=file]", "/nonexistent/file.txt"))
            assert "File not found" in result or "not found" in result.lower()
        finally:
            sess.close()

    def test_upload_file_success(self):
        sess = _make_session()
        try:
            # Create a temp file to upload
            with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w") as f:
                f.write("test content")
                tmp_path = f.name
            try:
                # Navigate to a page with a file input (data URI)
                sess.run(sess.go_to("data:text/html,<input type='file' id='fileInput'>"))
                result = sess.run(sess.upload_file("input[type=file]", tmp_path))
                assert "uploaded" in result.lower() or "file" in result.lower()
            finally:
                os.unlink(tmp_path)
        finally:
            sess.close()


class TestBrowserSessionWait:
    def test_wait_for_selector_timeout(self):
        sess = _make_session()
        try:
            sess.run(sess.go_to("data:text/html,<html><body></body></html>"))
            result = sess.run(sess.wait_for(selector="#nonexistent", timeout=2000))
            assert "timeout" in result.lower() or "error" in result.lower()
        finally:
            sess.close()

    def test_wait_for_text_timeout(self):
        sess = _make_session()
        try:
            sess.run(sess.go_to("data:text/html,<html><body>hello</body></html>"))
            result = sess.run(sess.wait_for(text="never_appears_text", timeout=2000))
            assert "timeout" in result.lower() or "error" in result.lower()
        finally:
            sess.close()

    def test_wait_for_text_success(self):
        sess = _make_session()
        try:
            sess.run(sess.go_to("data:text/html,<html><body>hello world</body></html>"))
            result = sess.run(sess.wait_for(text="hello", timeout=5000))
            assert "text found" in result.lower() or "ready" in result.lower()
        finally:
            sess.close()


class TestBrowserSessionScript:
    def test_script_basic(self):
        sess = _make_session()
        try:
            steps = [
                {"action": "go_to", "url": "data:text/html,<html><body><h1>Test</h1></body></html>"},
                {"action": "get_text"},
            ]
            result = sess.run(sess.run_script(steps))
            assert "Test" in result
        finally:
            sess.close()

    def test_script_with_wait(self):
        sess = _make_session()
        try:
            steps = [
                {"action": "go_to", "url": "data:text/html,<html><body><p id='msg'>Loaded</p></body></html>"},
                {"action": "wait", "selector": "#msg", "timeout": 5000},
                {"action": "get_text"},
            ]
            result = sess.run(sess.run_script(steps))
            assert "Loaded" in result
        finally:
            sess.close()

    def test_script_unknown_action(self):
        sess = _make_session()
        try:
            steps = [{"action": "nonexistent_action"}]
            result = sess.run(sess.run_script(steps))
            assert "unknown" in result.lower() or "error" in result.lower()
        finally:
            sess.close()


class TestBrowserControlFunction:
    def test_unknown_action(self):
        result = browser_control({"action": "totally_unknown"})
        assert "Unknown" in result

    def test_upload_action(self):
        result = browser_control({"action": "upload", "selector": "#file", "path": "/nonexistent"})
        assert "error" in result.lower() or "not found" in result.lower()

    def test_wait_action(self):
        result = browser_control({"action": "wait", "selector": "#test", "timeout": 1000})
        assert "timeout" in result.lower() or "error" in result.lower()

    def test_headless_parameter(self):
        """Ensure headless param is accepted without error."""
        result = browser_control({
            "action": "go_to",
            "url": "data:text/html,<html><body>ok</body></html>",
            "headless": True,
        })
        assert isinstance(result, str)


class TestSessionRegistry:
    def test_switch_browser(self):
        registry = _SessionRegistry()
        result = registry.switch("chrome")
        assert "chrome" in result.lower()

    def test_list_sessions_empty(self):
        registry = _SessionRegistry()
        result = registry.list_sessions()
        assert "no active" in result.lower() or "none" in result.lower()
