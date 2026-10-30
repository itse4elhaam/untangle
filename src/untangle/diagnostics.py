"""Local, bounded application diagnostics. Never record content or credentials."""
from datetime import datetime, timezone
from functools import wraps
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import os
import re
import subprocess
import sys
import threading
import time
import traceback
import uuid


logger = logging.getLogger('untangle.diagnostics')
logger.addHandler(logging.NullHandler())
logger.propagate = False
logger.setLevel(logging.INFO)
_run = uuid.uuid4().hex[:12]
_FIELDS = set('operation duration_ms exception_type frames mode recording paused busy counting '
              'visible minimized geometry screen_geometry window_id parent_id mapped override_redirect '
              'input_bounds input_rectangles role popup grabber native pointer_child stage '
              'error_count warning_count thread qt_type category source line outcome '
              'expected_geometry oversized elapsed_ms build_revision suppressed'.split())
_heartbeat = None


class Heartbeat:
    """Only the UI writes beat time; the watchdog never calls Qt or X11."""
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.last = clock()
        self.reported = False
        self.stopped = threading.Event()
        self.main_thread = threading.main_thread().ident

    def beat(self):
        self.last = self.clock()
        self.reported = False

    def check(self):
        delay = self.clock() - self.last
        if delay < 5 or self.reported:
            return
        self.reported = True
        frame = sys._current_frames().get(self.main_thread)
        frames = [dict(source=Path(item.filename).name, line=item.lineno, operation=item.name)
                  for item in traceback.extract_stack(frame)[-12:]] if frame else []
        event('application.ui_stalled', elapsed_ms=round(delay * 1000), frames=frames)

    def run(self):
        while not self.stopped.wait(2):
            self.check()


def beat():
    if _heartbeat is not None:
        _heartbeat.beat()


def shutdown():
    if _heartbeat is not None:
        _heartbeat.stopped.set()
    event('application.exit')


def revision():
    try:
        result = subprocess.run(['git', '-C', str(Path(__file__).resolve().parents[2]),
                                 'rev-parse', 'HEAD'], capture_output=True, text=True, timeout=1)
        value = result.stdout.strip()
        return value if result.returncode == 0 and re.fullmatch(r'[0-9a-f]{40,64}', value) else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def event(name, **fields):
    """Call on control threads only. Explicit fields prevent accidental payload logs."""
    try:
        record = dict(time=datetime.now(timezone.utc).isoformat(), event=name,
                      run=_run, pid=os.getpid(), thread=threading.current_thread().name)
        record.update({key: value for key, value in fields.items() if key in _FIELDS})
        logger.info(json.dumps(record, separators=(',', ':'), allow_nan=False))
    except Exception:
        pass  # Diagnostics must never prevent recording or cleanup.


def failure(name, error):
    # No exception messages/locals: these can contain OAuth tokens and filenames.
    frames = [dict(source=Path(frame.filename).name, line=frame.lineno,
                   operation=frame.name) for frame in traceback.extract_tb(error.__traceback__)[-12:]]
    event(name, exception_type=type(error).__name__, frames=frames)


def observed(operation):
    """Trace operation boundaries without inspecting arguments or return payloads."""
    def decorate(function):
        @wraps(function)
        def call(*args, **kwargs):
            started = time.monotonic()
            event(operation + '.start')
            try:
                result = function(*args, **kwargs)
            except Exception as exc:
                failure(operation + '.failed', exc)
                raise
            event(operation + '.done', duration_ms=round((time.monotonic() - started) * 1000))
            return result
        return call
    return decorate


def install(directory):
    """Install once at process entry, never when importing modules for tests."""
    if any(isinstance(handler, RotatingFileHandler) for handler in logger.handlers):
        return
    try:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / 'diagnostics.jsonl'
        # Private from creation, including every rotated replacement file.
        class PrivateHandler(RotatingFileHandler):
            def _open(self):
                fd = os.open(self.baseFilename, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
                os.fchmod(fd, 0o600)
                return os.fdopen(fd, 'a', encoding='utf-8')
        handler = PrivateHandler(path, maxBytes=2 * 1024 * 1024, backupCount=3)
        handler.setFormatter(logging.Formatter('%(message)s'))
        logger.addHandler(handler)
    except OSError:
        # The launcher's stderr log remains available if the disk is full.
        return
    previous = sys.excepthook
    def uncaught(kind, error, tb):
        failure('application.exception', error)
        previous(kind, error, tb)
    sys.excepthook = uncaught
    previous_thread = threading.excepthook
    def thread_uncaught(args):
        failure('worker.exception', args.exc_value)
        previous_thread(args)
    threading.excepthook = thread_uncaught
    from PySide6.QtCore import qInstallMessageHandler
    qt_last = {}
    def qt_message(kind, context, message):
        # Retain warning location/category, never arbitrary Qt message contents.
        key = (int(kind), context.category, context.file, context.line)
        now = time.monotonic()
        previous, suppressed = qt_last.get(key, (-float('inf'), 0))
        if now - previous < 10:
            qt_last[key] = (previous, suppressed + 1)
            return
        if len(qt_last) >= 64 and key not in qt_last:
            qt_last.pop(next(iter(qt_last)))
        qt_last[key] = (now, 0)
        event('qt.message', qt_type=int(kind), category=context.category,
              source=Path(context.file).name if context.file else None, line=context.line,
              suppressed=suppressed)
    previous_qt = qInstallMessageHandler(qt_message)
    # Keep the Python callback alive for the entire QApplication lifetime.
    install.qt_handler = qt_message
    install.previous_qt_handler = previous_qt
    event('application.start', build_revision=revision())
    global _heartbeat
    _heartbeat = Heartbeat()
    threading.Thread(target=_heartbeat.run, name='diagnostic-watchdog', daemon=True).start()


def window_state(widget):
    """Read existing native IDs without winId(), which can create windows."""
    if widget is None:
        return None
    rect = widget.geometry()
    from PySide6.QtWidgets import QWidget
    screen = QWidget.screen(widget).geometry()
    return dict(role=type(widget).__name__, visible=widget.isVisible(),
                geometry=[rect.x(), rect.y(), rect.width(), rect.height()],
                screen_geometry=[screen.x(), screen.y(), screen.width(), screen.height()],
                oversized=rect.width() > screen.width() or rect.height() > screen.height(),
                window_id=int(widget.effectiveWinId()) or None)


def snapshot(owner, stage, *, native=False):
    """UI-thread snapshot at transitions and at a low recording-only cadence."""
    if not any(not isinstance(handler, logging.NullHandler) for handler in logger.handlers):
        return
    try:
        from PySide6.QtWidgets import QApplication, QWidget
        from .window_diagnostics import native_window_state
        fields = dict(stage=stage, mode=owner.mode, recording=owner.recording,
                      paused=owner.paused, busy=owner.busy, counting=owner.counting,
                      popup=window_state(QApplication.activePopupWidget()),
                      grabber=window_state(QWidget.mouseGrabber()))
        for role, widget in [('main', owner), ('camera', owner.bubble)]:
            state = window_state(widget)
            if native and QApplication.platformName() == 'xcb' and state['window_id']:
                state['native'] = native_window_state(state['window_id'])
            event('window.snapshot', role=role, **state_fields(state), **fields)
    except Exception as exc:
        failure('window.snapshot.failed', exc)


def state_fields(state):
    return {key: value for key, value in state.items() if key != 'role'}
