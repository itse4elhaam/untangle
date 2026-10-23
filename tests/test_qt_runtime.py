"""Subprocess regression for the Qt/Python reference-count crash; no capture."""
import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


class QtRuntimeChecks(unittest.TestCase):
    def test_theme_change_with_collectable_widget_cycles_does_not_crash(self):
        env = os.environ.copy()
        env.pop('DISPLAY', None)
        env.pop('WAYLAND_DISPLAY', None)
        env['QT_QPA_PLATFORM'] = 'offscreen'
        env['PYTHONPATH'] = str(Path(__file__).resolve().parents[1] / 'src') + os.pathsep + env.get('PYTHONPATH', '')
        code = textwrap.dedent('''
            import gc
            import resource
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
            from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel
            from untangle.theme import apply_theme, tokens
            from untangle.microphone_meter import MicrophoneMeter
            app = QApplication([])
            meter = MicrophoneMeter()
            meter.show_status(dict(state='silent', peak_db=-30), 'Synthetic input')

            def enumerate_widgets():
                # Pin collection to the native enumeration boundary. In Qt 6.11
                # collecting widget cycles while allWidgets builds its Python
                # result can crash before the wrappers are returned.
                gc.collect()
                gc.disable()
                widget = QWidget()
                widget.cycle = widget
                layout = QVBoxLayout(widget)
                for i in range(10):
                    layout.addWidget(QLabel(str(i)))
                del widget, layout
                gc.set_threshold(gc.get_count()[0] + 1, 100000, 100000)
                gc.enable()
                return QApplication.allWidgets()

            app.allWidgets = enumerate_widgets
            for theme in ('dark', 'light'):
                apply_theme(app, theme)
                app.processEvents()  # Hidden widgets receive queued palette events.
                assert tokens(theme)['warning'] in meter.level.styleSheet()
                assert meter.level.value() == 30
                assert meter.name.text() == 'Synthetic input'
                assert meter.message.text() == 'Silent audio received · -30 dBFS'
            print('theme cycle regression passed')
        ''')
        result = subprocess.run([sys.executable, '-X', 'faulthandler', '-c', code],
                                cwd=Path(__file__).resolve().parents[1], env=env,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr[-4000:])
        self.assertIn('theme cycle regression passed', result.stdout)

    def test_repeated_meter_updates_do_not_abort_python(self):
        env = os.environ.copy()
        env.pop('DISPLAY', None)
        env['QT_QPA_PLATFORM'] = 'offscreen'
        env['PYTHONPATH'] = str(Path(__file__).resolve().parents[1] / 'src') + os.pathsep + env.get('PYTHONPATH', '')
        code = textwrap.dedent('''
            import resource
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
            from PySide6.QtWidgets import QApplication
            from untangle.microphone_meter import MicrophoneMeter
            app = QApplication([])
            meter = MicrophoneMeter()
            for i in range(10000):
                meter.show_status(dict(source='synthetic', state='signal', peak_db=-18),
                                  'Synthetic microphone')
            meter.close()
            print('meter update stress passed')
        ''')
        result = subprocess.run([sys.executable, '-c', code],
                                cwd=Path(__file__).resolve().parents[1], env=env,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr[-4000:])
        self.assertIn('meter update stress passed', result.stdout)
