import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from unittest.mock import Mock
import pytest
from PySide6.QtWidgets import QApplication
from tgs.gui import Window
from tgs.storage import Vault


@pytest.fixture
def window(tmp_path, monkeypatch):
    monkeypatch.setattr(Vault, 'get', lambda *a: None)
    app = QApplication.instance() or QApplication([])
    w = Window(tmp_path)
    yield w
    w.worker.loop.call_soon_threadsafe(w.worker.loop.stop)
    w.worker.thread.join(timeout=2)
    w.ledger.db.close()
    w.deleteLater()
    app.processEvents()


def test_cancel_never_sends(window):
    window.queue = [{'peer': 1, 'title': 'Тест'}]
    window.run_text = 'text'
    window.paused = False
    window.confirm = Mock(return_value=False)
    window.launch = Mock()
    window.next_send()
    assert window.paused
    window.launch.assert_not_called()
    assert window.ledger.previous(1, 'text') is None


def test_stop_prevents_next_confirmation(window):
    window.queue = [{'peer': 1, 'title': 'Тест'}]
    window.confirm = Mock()
    window.stop()
    window.next_send()
    window.confirm.assert_not_called()


def test_previous_attempt_is_visible(window):
    window.queue = [{'peer': 1, 'title': 'Тест'}]
    window.run_text = 'text'; window.paused = False
    window.ledger.record(1, 'text', 'начато')
    window.confirm = Mock(return_value=False)
    window.next_send()
    assert 'избежание дубликата' in window.confirm.call_args.args[1]
