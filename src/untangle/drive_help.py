"""Local Drive setup instructions; opening help runs no rclone or Google operation."""
from pathlib import Path

from PySide6.QtWidgets import QDialog, QVBoxLayout, QTextBrowser, QPushButton


GUIDE = Path(__file__).resolve().parents[2] / 'docs' / 'google-drive.md'


def show_drive_setup_guide(parent=None):
    dialog = QDialog(parent)
    dialog.setWindowTitle('Google Drive setup and recovery')
    dialog.resize(720, 640)
    layout = QVBoxLayout(dialog)
    guide = QTextBrowser()
    guide.setOpenExternalLinks(True)
    try:
        guide.setMarkdown(GUIDE.read_text(encoding='utf-8'))
    except OSError:
        guide.setPlainText('The local Google Drive guide is missing. Restore docs/google-drive.md '
                           'and scripts/setup-drive-wizard.sh from your reviewed Untangle checkout. '
                           'Untangle uploads with rclone: run "rclone config" in a terminal to add a '
                           'Google Drive remote, then load folders here. Run the wizard in a terminal '
                           'for prerequisites, recovery and optional scheduling. Do not share rclone.conf.')
    layout.addWidget(guide)
    done = QPushButton('Done')
    done.clicked.connect(dialog.accept)
    layout.addWidget(done)
    dialog.exec()
