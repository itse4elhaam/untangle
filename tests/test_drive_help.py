"""Guide rendering uses mocked widgets, no app session, browser or Google client."""
import importlib.util
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch


class DriveHelpTests(unittest.TestCase):
    def load_help(self):
        widgets = types.ModuleType('PySide6.QtWidgets')
        for name in ('QDialog', 'QVBoxLayout', 'QTextBrowser', 'QPushButton'):
            setattr(widgets, name, MagicMock())
        source = Path(__file__).resolve().parents[1] / 'src/untangle/drive_help.py'
        spec = importlib.util.spec_from_file_location('synthetic_drive_help', source)
        module = importlib.util.module_from_spec(spec)
        with patch.dict('sys.modules', {'PySide6': types.ModuleType('PySide6'),
                                       'PySide6.QtWidgets': widgets}):
            spec.loader.exec_module(module)
        return module, widgets

    def test_local_guide_resolves_outside_working_directory_and_opens_no_browser(self):
        module, widgets = self.load_help()
        parent = object()
        with tempfile.TemporaryDirectory() as directory, patch('os.getcwd', return_value=directory):
            module.show_drive_setup_guide(parent)
        text = widgets.QTextBrowser.return_value.setMarkdown.call_args.args[0]
        self.assertIn('./scripts/setup-drive-wizard.sh', text)
        self.assertIn('Recovery, disabling and revocation', text)
        self.assertIn('seven-day', text)
        widgets.QDialog.assert_called_once_with(parent)
        widgets.QDialog.return_value.exec.assert_called_once_with()
        widgets.QPushButton.return_value.clicked.connect.assert_called_once_with(
            widgets.QDialog.return_value.accept)

    def test_missing_local_guide_has_actionable_recovery(self):
        module, widgets = self.load_help()
        with tempfile.TemporaryDirectory() as directory:
            module.GUIDE = Path(directory) / 'missing.md'
            module.show_drive_setup_guide()
        widgets.QTextBrowser.return_value.setMarkdown.assert_not_called()
        text = widgets.QTextBrowser.return_value.setPlainText.call_args.args[0]
        self.assertIn('Restore docs/google-drive.md', text)
        self.assertIn('scripts/setup-drive-wizard.sh', text)
