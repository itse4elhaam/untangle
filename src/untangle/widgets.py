"""Shared controls for scrollable recording and settings forms."""
from PySide6.QtWidgets import QComboBox


class ScrollComboBox(QComboBox):
    """Scroll past a closed choice; use its popup or keyboard to change it."""

    def wheelEvent(self, event):
        if self.view().isVisible():
            super().wheelEvent(event)
        else:
            event.ignore()
