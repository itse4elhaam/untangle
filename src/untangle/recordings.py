"""Local recordings browser using Qt's native media player."""
from collections import OrderedDict
from datetime import datetime
import shutil
from pathlib import Path
from .naming import has_automatic_name, recording_title, recording_files, rename_recording
from .naming_dialog import prompt_recording_name
from .loom import valid_share_url

from PySide6.QtCore import Qt, QUrl, Signal, QSize, QSignalBlocker, QProcess, QTimer, QEvent
from PySide6.QtGui import QDesktopServices, QIcon, QPixmap, QShortcut, QKeySequence
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QAbstractItemView, QWidget, QFrame, QSplitter, QStackedWidget, QLineEdit, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QComboBox, QSizePolicy, QSlider, QVBoxLayout, QApplication, QMessageBox, QStyle, QStyleOptionSlider,
)


class PlaybackSlider(QSlider):
    """Let a click on the track select a position, as well as dragging."""
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            option = QStyleOptionSlider()
            self.initStyleOption(option)
            handle = self.style().subControlRect(QStyle.CC_Slider, option, QStyle.SC_SliderHandle, self)
            if not handle.contains(event.position().toPoint()):
                span = self.width() - handle.width()
                self.setValue(QStyle.sliderValueFromPosition(
                    self.minimum(), self.maximum(), round(event.position().x() - handle.width() / 2),
                    span, option.upsideDown))
                event.accept()
                return
        super().mousePressEvent(event)


def timestamp(milliseconds):
    seconds = milliseconds // 1000
    return f'{seconds // 60}:{seconds % 60:02d}'


class Recordings(QWidget):
    back_requested = Signal()
    recording_deleted = Signal(str)
    recording_renamed = Signal(str, str)
    upload_requested = Signal(str)
    check_remote_requested = Signal(str)
    theme_requested = Signal(str)
    settings_requested = Signal()

    def __init__(self, directory, parent=None, deletion_blocked=None, upload_store=None):
        super().__init__(parent)
        self.directory = Path(directory)
        self.deletion_blocked = deletion_blocked or (lambda path: False)
        self.upload_store = upload_store
        self.setObjectName('recordingsPage')
        self.thumbnail_cache = OrderedDict()
        self.thumbnail_queue = []
        self.thumbnail_key = None
        self.thumbnail_process = QProcess(self)
        self.thumbnail_process.finished.connect(self.thumbnail_finished)
        self.thumbnail_process.errorOccurred.connect(self.thumbnail_error)
        self.thumbnail_timer = QTimer(self)
        self.thumbnail_timer.setSingleShot(True)
        self.thumbnail_timer.timeout.connect(self.thumbnail_process.kill)
        self.ffmpeg = shutil.which('ffmpeg')
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.audio.setVolume(.5)
        self.player.setAudioOutput(self.audio)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 24, 30, 24)
        layout.setSpacing(18)
        header = QHBoxLayout()
        self.back = QPushButton('←  Back to recorder')
        self.back.clicked.connect(self.reject)
        header.addWidget(self.back)
        header.addStretch()
        privacy = QLabel('Files on this computer')
        privacy.setObjectName('eyebrow')
        header.addWidget(privacy)
        self.theme_choice = QComboBox()
        self.theme_choice.setAccessibleName('Appearance')
        self.theme_choice.addItem('Light', 'light')
        self.theme_choice.addItem('Dark', 'dark')
        self.theme_choice.setCurrentIndex(self.theme_choice.findData(
            QApplication.instance().property('untangleTheme') or 'light'))
        self.theme_choice.currentIndexChanged.connect(
            lambda: self.theme_requested.emit(self.theme_choice.currentData()))
        self.theme_choice.setParent(self)
        self.theme_choice.hide()
        self.settings_button = QPushButton('Settings')
        self.settings_button.clicked.connect(self.settings_requested.emit)
        header.addWidget(self.settings_button)
        layout.addLayout(header)
        title = QLabel('Your recordings')
        title.setObjectName('title')
        layout.addWidget(title)
        subtitle = QLabel('Find a take, give it a name, or review it before sharing.')
        subtitle.setObjectName('muted')
        layout.addWidget(subtitle)
        body = self.body = QSplitter(Qt.Horizontal)
        body.setObjectName('librarySplitter')
        body.setHandleWidth(12)
        body.setChildrenCollapsible(False)
        library = QFrame()
        library.setObjectName('libraryBrowser')
        library_layout = QVBoxLayout(library)
        library_layout.setContentsMargins(12, 12, 12, 12)
        self.search = QLineEdit()
        self.search.setObjectName('librarySearch')
        self.search.setPlaceholderText('Search recordings…')
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.filter_files)
        library_layout.addWidget(self.search)
        self.count = QLabel()
        self.count.setObjectName('libraryCount')
        library_layout.addWidget(self.count)
        self.files = QListWidget()
        self.files.setObjectName('recordingFiles')
        self.files.setMinimumWidth(230)
        self.files.setIconSize(QSize(112, 64))
        self.files.setSpacing(4)
        self.files.setWordWrap(True)
        self.files.setAccessibleName('Recordings, newest first')
        self.files.setTextElideMode(Qt.ElideMiddle)
        self.files.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # Shift/Ctrl-click or Ctrl+A select several recordings for one deletion.
        self.files.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.files.itemSelectionChanged.connect(self.update_actions)
        delete_shortcut = QShortcut(QKeySequence.Delete, self.files)
        delete_shortcut.setContext(Qt.WidgetShortcut)
        delete_shortcut.activated.connect(self.delete_selected)
        library_layout.addWidget(self.files, 1)
        body.addWidget(library)
        preview = QFrame()
        preview.setObjectName('libraryReview')
        preview_layout = QVBoxLayout(preview)
        preview_layout.setContentsMargins(18, 18, 18, 18)
        heading = QLabel('Selected recording')
        heading.setObjectName('eyebrow')
        preview_layout.addWidget(heading)
        self.video = QVideoWidget()
        self.video.setMinimumSize(160, 120)
        self.stage = QStackedWidget()
        self.stage.setObjectName('libraryStage')
        self.placeholder = QLabel('Select a recording\nYour playback appears here')
        self.placeholder.setAlignment(Qt.AlignCenter)
        self.placeholder.setWordWrap(True)
        self.placeholder.setObjectName('libraryPlaceholder')
        self.poster = QLabel()
        self.poster.setObjectName('libraryPoster')
        self.poster.setAlignment(Qt.AlignCenter)
        self.poster.setMinimumSize(160, 90)
        self.poster.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.stage.addWidget(self.placeholder)
        self.stage.addWidget(self.video)
        self.stage.addWidget(self.poster)
        self.stage.installEventFilter(self)
        preview_layout.addWidget(self.stage, 1)
        body.addWidget(preview)
        body.setStretchFactor(0, 2)
        body.setStretchFactor(1, 3)
        body.setSizes([340, 620])
        layout.addWidget(body, 1)
        self.player.setVideoOutput(self.video)
        self.selected_title = QLabel('Choose a recording')
        self.selected_title.setObjectName('librarySelectedTitle')
        self.selected_title.setWordWrap(True)
        self.selected_title.setTextFormat(Qt.PlainText)
        preview_layout.addWidget(self.selected_title)
        self.metadata = QLabel('MP4 and MKV recordings appear here.')
        self.metadata.setObjectName('libraryMetadata')
        self.metadata.setWordWrap(True)
        self.metadata.setTextFormat(Qt.PlainText)
        preview_layout.addWidget(self.metadata)
        self.message = QLabel('Select a recording to play.')
        self.message.setObjectName('libraryMessage')
        self.message.setWordWrap(True)
        self.message.setTextFormat(Qt.PlainText)
        self.message.setMinimumWidth(0)
        preview_layout.addWidget(self.message)
        self.loom_status = QLabel()
        self.loom_status.setObjectName('libraryLoomStatus')
        self.loom_status.setTextFormat(Qt.PlainText)
        self.loom_status.setWordWrap(True)
        preview_layout.addWidget(self.loom_status)
        self.loom_title = QLabel()
        self.loom_title.setTextFormat(Qt.PlainText)
        self.loom_title.setWordWrap(True)
        preview_layout.addWidget(self.loom_title)
        loom_actions = QHBoxLayout()
        self.open_loom = QPushButton('Open in Loom')
        self.open_loom.clicked.connect(self.open_selected_loom)
        loom_actions.addWidget(self.open_loom)
        self.copy_loom = QPushButton('Copy Loom link')
        self.copy_loom.clicked.connect(self.copy_selected_loom)
        loom_actions.addWidget(self.copy_loom)
        self.check_loom = QPushButton('Check Loom link')
        self.check_loom.clicked.connect(self.check_selected_loom)
        loom_actions.addWidget(self.check_loom)
        self.forget_loom = QPushButton('Forget Loom link')
        self.forget_loom.setToolTip('Clear the saved link on this computer. The recording on Loom is unchanged.')
        self.forget_loom.clicked.connect(self.forget_selected_loom)
        loom_actions.addWidget(self.forget_loom)
        preview_layout.addLayout(loom_actions)
        controls = QHBoxLayout()
        self.toggle = QPushButton('Play')
        self.toggle.setObjectName('playRecording')
        self.toggle.clicked.connect(self.toggle_play)
        controls.addWidget(self.toggle)
        self.seek = PlaybackSlider(Qt.Horizontal)
        self.seek.setRange(0, 0)
        self.seek.setAccessibleName('Playback position')
        self.seek.valueChanged.connect(self.player.setPosition)
        controls.addWidget(self.seek, 1)
        self.time = QLabel('0:00 / 0:00')
        controls.addWidget(self.time)
        self.mute = QPushButton('Mute')
        self.mute.setCheckable(True)
        self.mute.toggled.connect(self.audio.setMuted)
        sound = QHBoxLayout()
        sound.addWidget(self.mute)
        self.volume = PlaybackSlider(Qt.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(50)
        self.volume.setFixedWidth(110)
        self.volume.setAccessibleName('Volume')
        self.volume.valueChanged.connect(self.set_volume)
        sound.addWidget(self.volume)
        self.volume_label = QLabel()
        self.volume_label.setMinimumWidth(42)
        sound.addWidget(self.volume_label)
        sound.addStretch()
        self.audio.volumeChanged.connect(self.sync_volume)
        self.audio.mutedChanged.connect(self.sync_volume)
        self.sync_volume()
        preview_layout.addLayout(controls)
        preview_layout.addLayout(sound)
        actions = QHBoxLayout()
        refresh = QPushButton('Refresh')
        refresh.clicked.connect(lambda: self.refresh())
        library_tools = QHBoxLayout()
        library_tools.addWidget(refresh)
        folder = QPushButton('Open folder ↗')
        folder.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.directory))))
        library_tools.addWidget(folder)
        library_layout.addLayout(library_tools)
        self.delete_unnamed_button = QPushButton('Delete unnamed…')
        self.delete_unnamed_button.setObjectName('deleteRecording')
        self.delete_unnamed_button.setToolTip('Delete every recording that still has its automatic, dated name')
        self.delete_unnamed_button.clicked.connect(self.delete_unnamed)
        library_layout.addWidget(self.delete_unnamed_button)

        self.drive = QPushButton('Google Drive…')
        self.drive.clicked.connect(self.open_drive)
        library_tools.addWidget(self.drive)

        self.upload = QPushButton('Upload to Loom')
        self.upload.clicked.connect(self.upload_selected)
        actions.addWidget(self.upload)
        self.copy = QPushButton('Copy path')
        self.copy.clicked.connect(self.copy_selected_path)
        actions.addWidget(self.copy)
        self.rename = QPushButton('Rename')
        self.rename.setToolTip('Rename the selected recording (F2)')
        self.rename.clicked.connect(self.rename_selected)
        rename_shortcut = QShortcut(QKeySequence('F2'), self)
        rename_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        rename_shortcut.activated.connect(self.rename_selected)
        actions.addWidget(self.rename)
        self.delete = QPushButton('Delete')
        self.delete.setObjectName('deleteRecording')
        self.delete.clicked.connect(self.delete_selected)
        actions.addWidget(self.delete)
        preview_layout.addLayout(actions)
        self.files.currentItemChanged.connect(self.select)
        self.player.playbackStateChanged.connect(lambda state: self.toggle.setText(
            'Pause' if state == QMediaPlayer.PlayingState else 'Play'))
        self.player.durationChanged.connect(self.update_position)
        self.player.positionChanged.connect(self.update_position)
        self.player.seekableChanged.connect(self.seek.setEnabled)
        self.player.errorOccurred.connect(self.failed)
        self.refresh()

    def refresh(self, selected=None):
        selected = Path(selected) if selected else (self.selected_path() or Path(self.player.source().toLocalFile()))
        self.stop_thumbnails()
        self.release()
        self.files.clear()
        self.update_actions()
        self.toggle.setEnabled(False)
        self.seek.setEnabled(False)
        try:
            if not self.directory.is_dir():
                raise FileNotFoundError(f'Recording folder is missing: {self.directory}')
            paths = recording_files(self.directory)
        except OSError as exc:
            self.count.setText('Library unavailable')
            self.placeholder.setText('Cannot open your library\nCheck the folder and try Refresh.')
            self.message.setText(f'Could not read recordings: {exc}')
            return
        self.placeholder.setText('Select a recording\nYour playback appears here' if paths else 'No recordings yet\nMake your first recording to see it here.')
        self.message.setText('Select a recording to play.' if paths else 'No recordings yet. Saved MP4 and MKV videos appear here.')
        for path in paths:
            try:
                stat = path.stat()
            except OSError:
                continue  # A file may disappear between scanning and displaying it.
            date = datetime.fromtimestamp(stat.st_mtime)
            day = 'Today' if date.date() == datetime.now().date() else date.strftime('%b %d, %Y')
            size = stat.st_size
            size_text = f'{size / 1024 ** 3:.1f} GB' if size >= 1024 ** 3 else f'{size / 1024 ** 2:.1f} MB'
            item = QListWidgetItem(f'{recording_title(path)}\n{day} · {date:%H:%M}  •  {size_text}  •  {path.suffix[1:].upper()}')
            item.setSizeHint(QSize(0, 96))
            item.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
            key = (str(path), stat.st_mtime_ns, stat.st_size)
            item.setData(Qt.UserRole + 1, key)
            if key in self.thumbnail_cache:
                item.setIcon(QIcon(self.thumbnail_cache[key]))
            # Decode a bounded initial batch; selecting older files prioritizes them.
            elif len(self.thumbnail_queue) < 48:
                self.thumbnail_queue.append(key)
            item.setData(Qt.UserRole, str(path))
            item.setData(Qt.UserRole + 2, item.text())
            item.setToolTip(str(path))
            self.files.addItem(item)
        self.start_thumbnail()
        self.filter_files(self.search.text())
        for index in range(self.files.count()):
            item = self.files.item(index)
            if Path(item.data(Qt.UserRole)) == selected:
                if not item.isHidden():
                    self.files.setCurrentItem(item)
                break
        else:
            if selected != Path('.') and not selected.is_file():
                self.message.setText('This recording is missing. Refresh the list.')

    def filter_files(self, text):
        visible = 0
        for index in range(self.files.count()):
            item = self.files.item(index)
            hidden = text.casefold() not in (item.data(Qt.UserRole + 2) + ' ' + Path(item.data(Qt.UserRole)).name).casefold()
            item.setHidden(hidden)
            visible += not hidden
        current = self.files.currentItem()
        if current is not None and current.isHidden():
            self.files.setCurrentItem(None)
        self.update_actions()
        self.count.setText(f'{visible} recording{"s" if visible != 1 else ""} · Newest first')
        if not visible and self.files.count():
            self.placeholder.setText('No matching recordings\nTry a different name or clear your search.')
            if self.player.source().isEmpty():
                self.stage.setCurrentWidget(self.placeholder)
            self.message.setText('No matching recordings. Try another search.')
        elif self.selected_path() is not None:
            self.show_selected_preview()
        elif self.player.source().isEmpty() and self.files.count():
            self.placeholder.setText('Select a recording\nYour playback appears here')
            self.message.setText('Select a recording to play.')
        elif not self.player.source().isEmpty():
            self.stage.setCurrentWidget(self.video)
            self.message.setText(recording_title(self.player.source().toLocalFile()))

    def set_volume(self, value):
        self.audio.setVolume(value / 100)
        if value > 0:
            self.audio.setMuted(False)

    def sync_volume(self, *_):
        value = round(self.audio.volume() * 100)
        with QSignalBlocker(self.volume):
            self.volume.setValue(value)
        with QSignalBlocker(self.mute):
            self.mute.setChecked(self.audio.isMuted())
        self.mute.setText('Unmute' if self.audio.isMuted() else 'Mute')
        self.volume_label.setText('Muted' if self.audio.isMuted() else f'{value}%')

    def selected_path(self):
        item = self.files.currentItem()
        return Path(item.data(Qt.UserRole)) if item is not None and not item.isHidden() else None

    def update_actions(self):
        for index in range(self.files.count()):
            item = self.files.item(index)
            row_path = Path(item.data(Qt.UserRole))
            state = self.upload_metadata(row_path)
            text = item.data(Qt.UserRole + 2) + '\n' + self.upload_state_text(state)
            if item.text() != text:
                item.setText(text)
        path = self.selected_path()
        exists = path is not None and path.is_file()
        state = self.upload_metadata(path) if exists else {}
        status = state.get('status')
        blocked = exists and self.deletion_blocked(path)
        upload_text = 'Prepare MP4' if path and path.suffix.lower() == '.mkv' else 'Upload to Loom'
        if status == 'uploading':
            upload_text = 'Uploading…'
        elif status == 'processing':
            upload_text = 'Processing in Loom…'
        elif status == 'uploaded':
            upload_text = 'Upload again to Loom'
        elif status in ('failed', 'uncertain'):
            upload_text = 'Retry upload'
        elif status == 'deleted':
            upload_text = 'Upload to Loom again'
        self.upload.setText(upload_text)
        self.upload.setEnabled(exists and not blocked and status not in ('uploading', 'processing'))
        self.copy.setEnabled(exists)
        self.rename.setEnabled(exists and not blocked)
        targets = [target for target in self.checked_paths() if target.is_file()]
        self.delete.setText(f'Delete {len(targets)}' if len(targets) > 1 else 'Delete')
        self.delete.setEnabled(bool(targets) and not any(self.deletion_blocked(target) for target in targets))
        if hasattr(self, 'delete_unnamed_button'):
            unnamed = len(self.unnamed_paths())
            self.delete_unnamed_button.setText(f'Delete unnamed ({unnamed})…' if unnamed else 'Delete unnamed…')
            self.delete_unnamed_button.setEnabled(bool(unnamed))
        url = self.loom_url(state)
        for button in (self.open_loom, self.copy_loom):
            button.setVisible(bool(url))
            button.setEnabled(bool(url))
        self.check_loom.setVisible(bool(url))
        self.check_loom.setEnabled(bool(url) and not blocked)
        self.forget_loom.setVisible(bool(state))
        self.forget_loom.setEnabled(bool(state) and not blocked)
        details = self.upload_state_text(state) if exists else ''
        if exists and status == 'uncertain':
            details += '\nCheck Loom before retrying. Another upload may create a duplicate.'
        if exists and status == 'uploaded' and not url:
            details += '\nNo usable Loom link is saved. Check Loom before uploading another copy.'
        if exists and status == 'deleted':
            details += '\nYour local recording is still on this computer.'
        for field in ('error', 'visibility_warning'):
            if state.get(field):
                details += '\n' + str(state[field])
        self.loom_status.setText(details)
        self.loom_status.setVisible(bool(details))
        title = state.get('title')
        self.loom_title.setText(f'Loom title: {title}' if title else '')
        self.loom_title.setVisible(bool(title))

    def upload_metadata(self, path):
        return self.upload_store.get(path) if self.upload_store is not None else {}

    @staticmethod
    def upload_state_text(state):
        return {
            'uploading': 'Uploading to Loom',
            'processing': 'Processing in Loom',
            'uploaded': 'Uploaded to Loom',
            'failed': 'Loom upload failed',
            'uncertain': 'Loom upload needs checking',
            'deleted': 'Deleted from Loom',
        }.get(state.get('status'), 'Not uploaded to Loom')

    @staticmethod
    def loom_url(state):
        if state.get('status') == 'deleted':
            return ''
        return valid_share_url(state.get('url'))

    def selected_loom_url(self):
        path = self.selected_path()
        self.update_actions()
        return self.loom_url(self.upload_metadata(path)) if path is not None and path.is_file() else ''

    def open_selected_loom(self):
        url = self.selected_loom_url()
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def copy_selected_loom(self):
        url = self.selected_loom_url()
        if url:
            QApplication.clipboard().setText(url)
            self.message.setText('Loom link copied.')

    def check_selected_loom(self):
        url = self.selected_loom_url()
        path = self.selected_path()
        if url and not self.deletion_blocked(path):
            self.check_remote_requested.emit(str(path))

    def forget_selected_loom(self):
        path = self.selected_path()
        self.update_actions()
        if path is None or not path.is_file() or self.deletion_blocked(path) or not self.upload_metadata(path):
            return
        answer = QMessageBox.question(self, 'Forget Loom link?',
            'Clear the saved Loom link and upload status on this computer?\n\n'
            'The recording on Loom is unchanged. Your local recording is kept.',
            QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
        if answer != QMessageBox.Yes:
            return
        if not path.is_file() or self.deletion_blocked(path):
            self.message.setText('This recording is missing or in use. Refresh or wait for the upload to finish.')
            self.update_actions()
            return
        try:
            self.upload_store.remove(path)
        except OSError as exc:
            self.message.setText(f'Could not forget Loom link: {exc}')
            return
        self.update_actions()
        self.message.setText('Saved Loom link cleared on this computer. The recording on Loom is unchanged.')

    def rename_selected(self):
        path = self.selected_path()
        self.update_actions()
        if path is None or not path.is_file() or self.deletion_blocked(path):
            return
        metadata_error = None
        def rename(title):
            nonlocal metadata_error
            # The modal event loop can deliver saving/uploading actions.
            if self.deletion_blocked(path):
                message = 'This recording is in use. Try again when saving or uploading finishes.'
                self.message.setText(message)
                self.update_actions()
                raise ValueError(message)
            self.release()
            try:
                renamed = rename_recording(path, title)
            except (OSError, ValueError) as exc:
                self.select(self.files.currentItem())
                self.message.setText(f'Could not rename {path.name}: {exc}')
                self.update_actions()
                raise
            if renamed != path:
                if self.upload_store is not None:
                    try:
                        self.upload_store.rename(path, renamed)
                    except OSError as exc:
                        metadata_error = exc
                self.recording_renamed.emit(str(path), str(renamed))
            return renamed
        renamed = prompt_recording_name(self, path, rename)
        if renamed is None:
            return
        # Keep the result visible if the old search no longer matches its title.
        if self.search.text().casefold() not in (recording_title(renamed) + ' ' + renamed.name).casefold():
            self.search.clear()
        self.refresh(renamed)
        self.message.setText(f'Renamed local file, but could not move its Loom details: {metadata_error}'
            if metadata_error else recording_title(renamed))

    def upload_selected(self):
        path = self.selected_path()
        self.update_actions()
        if not self.upload.isEnabled():
            return
        state = self.upload_metadata(path)
        if state.get('status') in ('uploaded', 'uncertain') or self.loom_url(state):
            answer = QMessageBox.question(self, 'Upload another copy to Loom?',
                'This recording may already be on Loom. Check the saved Loom link first if available.\n\n'
                'Uploading again creates another copy. Any existing Loom recording is unchanged. Continue?',
                QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
            if answer != QMessageBox.Yes:
                return
        # Confirmation can process events that start an automatic upload.
        self.update_actions()
        if (path.is_file() and self.selected_path() == path
                and self.upload.isEnabled() and not self.deletion_blocked(path)):
            self.upload_requested.emit(str(path))

    def copy_selected_path(self):
        path = self.selected_path()
        self.update_actions()
        if path is not None and path.is_file():
            QApplication.clipboard().setText(str(path))
            self.message.setText('File path copied. This file is on your computer.')

    def open_drive(self):
        from .drive_dialog import DriveDialog
        paths = self.checked_paths()
        if any(self.deletion_blocked(path) for path in paths):
            self.message.setText('Wait until the selected recordings are no longer busy.')
            return
        dialog = DriveDialog(paths, self)
        dialog.exec()

    def checked_paths(self):
        """Visible selected recordings in list order, or the current one."""
        items = sorted((item for item in self.files.selectedItems() if not item.isHidden()), key=self.files.row)
        paths = [Path(item.data(Qt.UserRole)) for item in items]
        current = self.selected_path()
        return paths or ([current] if current is not None else [])

    def unnamed_paths(self):
        """Every listed recording, search or not, that nobody has named yet."""
        paths = (Path(self.files.item(index).data(Qt.UserRole)) for index in range(self.files.count()))
        return [path for path in paths if has_automatic_name(path) and path.is_file()]

    @staticmethod
    def listing(paths, limit=8):
        names = [path.name for path in paths[:limit]]
        if len(paths) > limit:
            names.append(f'…and {len(paths) - limit} more')
        return '\n'.join(names)

    def delete_selected(self):
        paths = [path for path in self.checked_paths() if path.is_file()]
        if len(paths) == 1:
            self.delete_paths(paths, 'Delete recording?',
                f'Permanently delete this recording?\n\n{paths[0]}\n\nThis cannot be undone. '
                'Any recording on Loom is unchanged. Its saved link will be removed from this computer.')
        elif paths:
            self.delete_paths(paths, f'Delete {len(paths)} recordings?',
                f'Permanently delete these {len(paths)} recordings?\n\n{self.listing(paths)}\n\n'
                'This cannot be undone. Any recordings on Loom are unchanged.')
        else:
            self.update_actions()

    def delete_unnamed(self):
        paths = self.unnamed_paths()
        if not paths:
            self.message.setText('Every recording has a name. Nothing to clean up.')
            self.update_actions()
            return
        count = f'{len(paths)} recording{"s" if len(paths) != 1 else ""}'
        self.delete_paths(paths, 'Delete unnamed recordings?',
            f'Permanently delete {count} you never named?\n\n{self.listing(paths)}\n\n'
            'Recordings you named are kept. This cannot be undone. Any recordings on Loom are unchanged.')

    def delete_paths(self, paths, title, question):
        self.update_actions()
        if not paths or any(self.deletion_blocked(path) for path in paths):
            return
        answer = QMessageBox.question(self, title, question,
            QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
        if answer != QMessageBox.Yes:
            return
        # Recheck after the modal dialog, which can process application events.
        if any(self.deletion_blocked(path) for path in paths):
            self.message.setText('A recording is in use. Try again when saving or uploading finishes.'
                if len(paths) > 1 else 'This recording is in use. Try again when saving or uploading finishes.')
            self.update_actions()
            return
        self.release()
        deleted, failures, metadata_errors = [], [], []
        for path in paths:
            try:
                path.unlink()
            except OSError as exc:
                failures.append((path, exc))
                continue
            deleted.append(path)
            if self.upload_store is not None:
                try:
                    self.upload_store.remove(path)
                except OSError as exc:
                    metadata_errors.append(exc)
        if not deleted:
            path, exc = failures[0]
            self.message.setText(f'Could not delete {path.name}: {exc}')
            self.update_actions()
            return
        self.refresh()
        if len(paths) == 1:
            path = deleted[0]
            self.message.setText(f'Deleted {path.name}, but could not clear its saved Loom details: {metadata_errors[0]}'
                if metadata_errors else f'Deleted {path.name}.')
        else:
            text = f'Deleted {len(deleted)} recording{"s" if len(deleted) != 1 else ""}.'
            if failures:
                text += f' Could not delete {len(failures)}: {failures[0][0].name}: {failures[0][1]}'
            if metadata_errors:
                text += f' Some saved Loom details could not be cleared: {metadata_errors[0]}'
            self.message.setText(text)
        for path in deleted:
            self.recording_deleted.emit(str(path))

    def reject(self):
        self.stop_thumbnails()
        self.release()
        self.back_requested.emit()

    def hideEvent(self, event):
        self.stop_thumbnails()
        self.release()
        super().hideEvent(event)

    def select(self, item, previous=None):
        self.release()
        self.toggle.setEnabled(False)
        self.update_actions()
        self.selected_title.setText('Choose a recording')
        self.metadata.setText('MP4 and MKV recordings appear here.')
        if item is None:
            return
        path = Path(item.data(Qt.UserRole))
        if not path.is_file():
            self.message.setText('This recording is missing. Refresh the list.')
            return
        key = item.data(Qt.UserRole + 1)
        if key not in self.thumbnail_cache and key != self.thumbnail_key:
            if key in self.thumbnail_queue:
                self.thumbnail_queue.remove(key)
            self.thumbnail_queue.insert(0, key)
            del self.thumbnail_queue[48:]
            self.start_thumbnail()
        self.selected_title.setText(recording_title(path))
        self.metadata.setText(item.data(Qt.UserRole + 2).split('\n', 1)[-1])
        self.show_selected_preview()
        self.toggle.setEnabled(True)

    def show_selected_preview(self, update_message=True):
        item = self.files.currentItem()
        if item is None or item.isHidden():
            return
        if not self.player.source().isEmpty():
            self.stage.setCurrentWidget(self.video)
            return
        pixmap = self.thumbnail_cache.get(item.data(Qt.UserRole + 1))
        if pixmap is not None:
            self.poster.setPixmap(pixmap.scaled(
                self.stage.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.stage.setCurrentWidget(self.poster)
        else:
            self.placeholder.setText('Ready to review\nPress Play to watch this recording.')
            self.stage.setCurrentWidget(self.placeholder)
        if update_message:
            self.message.setText('Press Play to review. Uploading is a separate action.')

    def toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
            return
        path = self.selected_path()
        if path is None or not path.is_file():
            self.release()
            self.update_actions()
            self.message.setText('This recording is missing. Refresh the list.')
            return
        if self.player.source().isEmpty():
            self.player.setSource(QUrl.fromLocalFile(str(path)))
        elif self.player.mediaStatus() == QMediaPlayer.EndOfMedia:
            self.player.setPosition(0)
        self.stage.setCurrentWidget(self.video)
        self.message.setText(recording_title(path))
        self.player.play()

    def start_thumbnail(self):
        if (not self.ffmpeg or self.thumbnail_key is not None or not self.thumbnail_queue
                or self.thumbnail_process.state() != QProcess.NotRunning):
            return
        self.thumbnail_key = self.thumbnail_queue.pop(0)
        self.thumbnail_process.setStandardErrorFile(QProcess.nullDevice())
        self.thumbnail_process.start(self.ffmpeg, [
            '-hide_banner', '-loglevel', 'error', '-nostdin', '-threads', '1',
            '-protocol_whitelist', 'file,pipe', '-i', self.thumbnail_key[0],
            '-an', '-sn', '-dn', '-frames:v', '1', '-vf', 'scale=384:216:force_original_aspect_ratio=decrease',
            '-threads', '1', '-f', 'image2pipe', '-vcodec', 'png', 'pipe:1'])
        self.thumbnail_timer.start(5000)

    def thumbnail_error(self, error):
        if error == QProcess.FailedToStart:
            self.thumbnail_timer.stop()
            self.thumbnail_key = None
            self.thumbnail_queue.clear()

    def thumbnail_finished(self, code, status):
        self.thumbnail_timer.stop()
        key, self.thumbnail_key = self.thumbnail_key, None
        data = self.thumbnail_process.readAllStandardOutput()
        pixmap = QPixmap()
        if key is not None and code == 0 and status == QProcess.NormalExit and pixmap.loadFromData(data):
            self.thumbnail_cache[key] = pixmap
            evicted = set()
            while len(self.thumbnail_cache) > 48:
                old_key, _ = self.thumbnail_cache.popitem(last=False)
                evicted.add(old_key)
            for index in range(self.files.count()):
                item = self.files.item(index)
                if item.data(Qt.UserRole + 1) == key:
                    item.setIcon(QIcon(pixmap))
                elif item.data(Qt.UserRole + 1) in evicted:
                    item.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
            if (self.toggle.isEnabled() and self.files.currentItem() is not None
                    and self.files.currentItem().data(Qt.UserRole + 1) == key):
                self.show_selected_preview(update_message=False)
        self.start_thumbnail()

    def stop_thumbnails(self):
        self.thumbnail_queue.clear()
        self.thumbnail_key = None
        self.thumbnail_timer.stop()
        if self.thumbnail_process.state() != QProcess.NotRunning:
            # Completion is delivered asynchronously. Keep navigation responsive;
            # start_thumbnail waits for this child before using the process again.
            self.thumbnail_process.kill()

    def eventFilter(self, watched, event):
        if (watched is self.stage and event.type() == QEvent.Resize
                and self.stage.currentWidget() is self.poster):
            self.show_selected_preview(update_message=False)
        return super().eventFilter(watched, event)

    def update_position(self, *_):
        duration, position = self.player.duration(), self.player.position()
        with QSignalBlocker(self.seek):
            self.seek.setRange(0, duration)
            if not self.seek.isSliderDown():
                self.seek.setValue(position)
        self.time.setText(f'{timestamp(position)} / {timestamp(duration)}')

    def failed(self, error, message):
        self.player.stop()
        self.toggle.setEnabled(False)
        self.seek.setEnabled(False)
        self.placeholder.setText('This recording could not be played\nTry another video or refresh the list.')
        self.stage.setCurrentWidget(self.placeholder)
        self.message.setText(f'Could not play this recording: {message}. Your file is still on this computer.')

    def release(self, *_):
        self.stage.setCurrentWidget(self.placeholder)
        self.toggle.setEnabled(False)
        self.player.stop()
        self.player.setSource(QUrl())
        self.seek.setEnabled(False)
        self.update_position()
