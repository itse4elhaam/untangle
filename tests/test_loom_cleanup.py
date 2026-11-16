"""Local copy deletion after a verified Loom upload, and the notification panel.

Run only this file: UNTANGLE_TEST_PATTERN=test_loom_cleanup.py ./scripts/test.sh
Synthetic files, inert processes and a temporary review root only. Nothing is
uploaded and no real recording is touched.
"""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import test_loom_workflow as workflow
from untangle import loom_cleanup
from untangle.notifications import NotificationLog
from untangle.upload_store import UploadStore

from PySide6.QtWidgets import QCheckBox, QSystemTrayIcon

qt = workflow.qt
URL = workflow.URL
IDENTITY = {'device': 1, 'inode': 2, 'size': 3, 'mtime_ns': 4}
ROW = {'status': 'uploaded', 'url': URL, 'remote_id': 'abc123'}
REMOTE = {'status': 'available', 'remote_id': 'abc123', 'url': URL, 'is_complete': True}


class DecisionChecks(unittest.TestCase):
    def decide(self, **changes):
        options = dict(enabled=True, row=ROW, upload_identity=IDENTITY,
                       current_identity=IDENTITY, remote=REMOTE)
        options.update(changes)
        return loom_cleanup.decide(**options)

    def test_only_a_complete_matching_available_video_is_verified(self):
        self.assertEqual(self.decide(), 'verified')
        self.assertEqual(self.decide(remote=None), 'check_remote')

    def test_every_missing_or_unknown_fact_keeps_the_file(self):
        cases = {
            'disabled': dict(enabled=False),
            'processing': dict(row=dict(ROW, status='processing')),
            'not_uploaded': dict(row=dict(ROW, status='uncertain')),
            'no_link': dict(row=dict(ROW, url='https://example.invalid/share/abc123')),
            'changed': dict(current_identity=dict(IDENTITY, size=99)),
            'remote_unverified': dict(remote=dict(REMOTE, status='unknown')),
            'remote_mismatch': dict(remote=dict(REMOTE, remote_id='other999', url='')),
            'remote_incomplete': dict(remote=dict(REMOTE, is_complete=None)),
        }
        for reason, changes in cases.items():
            with self.subTest(reason=reason):
                self.assertEqual(self.decide(**changes), reason)
                self.assertIn(reason, loom_cleanup.REASONS)
        self.assertEqual(self.decide(row={}, current_identity=None), 'not_uploaded')
        self.assertEqual(self.decide(remote=dict(REMOTE, is_complete=False)), 'remote_incomplete')
        self.assertEqual(self.decide(remote=dict(REMOTE, url='https://www.loom.com/share/zzz')), 'remote_mismatch')


class ReviewReferenceChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.video = self.root / 'take.mp4'
        self.video.write_bytes(b'synthetic')

    def write_review(self, name, payload):
        folder = self.root / 'reviews' / name
        folder.mkdir(parents=True)
        (folder / 'review.json').write_text(payload if isinstance(payload, str) else json.dumps(payload))

    def test_registered_path_hard_link_and_unreadable_reviews_block_deletion(self):
        reviews = self.root / 'reviews'
        self.assertEqual(loom_cleanup.review_reason(self.video, reviews), '')
        self.write_review('other', {'versions': [{'path': str(self.root / 'missing.mp4')}]})
        self.assertEqual(loom_cleanup.review_reason(self.video, reviews), '')
        link = self.root / 'linked.mp4'
        os.link(self.video, link)
        self.write_review('linked', {'versions': [{'path': str(link)}]})
        self.assertEqual(loom_cleanup.review_reason(self.video, reviews), 'review')
        (reviews / 'linked' / 'review.json').unlink()
        self.write_review('broken', '{not json')
        self.assertEqual(loom_cleanup.review_reason(self.video, reviews), 'review_unknown')


class NotificationLogChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'state' / 'notifications.json'

    def test_entries_persist_newest_first_with_unread_count(self):
        log = NotificationLog(self.path)
        log.add('kept', 'First')
        log.add('deleted', 'Second', 'detail', URL)
        reopened = NotificationLog(self.path)
        self.assertEqual([entry['title'] for entry in reopened.entries()], ['Second', 'First'])
        self.assertEqual(reopened.unread(), 2)
        self.assertEqual(reopened.entries()[0]['url'], URL)
        reopened.mark_all_read()
        self.assertEqual(NotificationLog(self.path).unread(), 0)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_log_is_capped_and_clearable(self):
        log = NotificationLog(self.path)
        for number in range(60):
            log.add('kept', f'Item {number}')
        self.assertEqual(len(NotificationLog(self.path).entries()), 50)
        self.assertEqual(log.entries()[0]['title'], 'Item 59')
        log.clear()
        self.assertEqual(NotificationLog(self.path).entries(), [])

    def test_malformed_file_is_never_overwritten(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text('{"version": 2}')
        log = NotificationLog(self.path)
        self.assertTrue(log.error)
        log.add('kept', 'In memory only')
        self.assertEqual(log.unread(), 1)
        self.assertEqual(self.path.read_text(), '{"version": 2}')


class RemoteOnlyStoreChecks(unittest.TestCase):
    def test_marked_rows_stay_reachable_after_the_file_is_gone(self):
        with tempfile.TemporaryDirectory() as folder:
            video = Path(folder) / 'take.mp4'
            video.write_bytes(b'synthetic')
            store = UploadStore(Path(folder) / 'uploads.json')
            identity = store.file_identity(video)
            store.update(video, expected_identity=identity, status='uploaded', url=URL)
            self.assertEqual(store.remote_only(), [])
            store.update(video, expected_identity=identity, local_copy='deleted', local_deleted_at=1.0)
            self.assertEqual(store.remote_only(), [])  # The file still exists.
            video.unlink()
            rows = UploadStore(Path(folder) / 'uploads.json').remote_only()
            self.assertEqual([(row['path'], row['url']) for row in rows], [(str(video), URL)])

    def test_retired_row_survives_a_new_file_at_the_same_path(self):
        with tempfile.TemporaryDirectory() as folder:
            video = Path(folder) / 'Daily standup.mp4'
            video.write_bytes(b'synthetic')
            store = UploadStore(Path(folder) / 'uploads.json')
            identity = store.file_identity(video)
            store.update(video, expected_identity=identity, status='uploaded', url=URL,
                         local_copy='deleted', local_deleted_at=5.0)
            store.retire_deleted(video, 5.0)  # Refused: the file still exists.
            self.assertEqual(store.get(video)['url'], URL)
            video.unlink()
            store.retire_deleted(video, 5.0)
            video.write_bytes(b'a later take with the same name')
            store.update(video, status='uploading')
            other = Path(folder) / 'renamed.mp4'
            other.write_bytes(b'renamed onto the old name')
            store.update(other, status='uploaded', url='https://www.loom.com/share/zzz999')
            video.unlink()
            other.rename(video)
            store.rename(other, video)
            rows = UploadStore(Path(folder) / 'uploads.json').remote_only()
            self.assertEqual([(row['path'], row['url']) for row in rows], [(str(video), URL)])
            self.assertEqual(store.get(video)['url'], 'https://www.loom.com/share/zzz999')


class LoomCleanupWorkflowChecks(unittest.TestCase):
    def setUp(self):
        workflow.LoomWorkflowChecks.setUp(self)
        self.window.prefs.setValue(loom_cleanup.PREFERENCE, True)
        self.reviews = self.root / 'reviews'
        review_root = patch.dict(os.environ, {'UNTANGLE_REVIEW_ROOT': str(self.reviews)})
        review_root.start()
        self.addCleanup(review_root.stop)

    publish = workflow.LoomWorkflowChecks.publish
    begin_upload = workflow.LoomWorkflowChecks.begin_upload
    open_library = workflow.LoomWorkflowChecks.open_library
    inspect_sharing = workflow.LoomWorkflowChecks.inspect_sharing

    def cleanup_probe(self):
        probes = [process for process in self.window.loom_probes
                  if process.arguments[:3] == ['loom', 'video', 'get']]
        self.assertEqual(len(probes), 1)
        self.assertEqual(probes[0].arguments[3], 'abc123')
        return probes[0]

    def notifications(self):
        return self.window.notification_log.entries()

    def assert_kept(self, reason):
        self.assertTrue(self.path.is_file())
        self.assertEqual(self.window.upload_store.remote_only(), [])
        self.assertIn(loom_cleanup.REASONS[reason], self.notifications()[0]['title'])
        self.assertEqual(self.notifications()[0]['kind'], 'kept')

    def test_verified_upload_deletes_local_file_and_keeps_link(self):
        page = self.open_library()
        self.publish(isComplete=True)
        with patch.object(QSystemTrayIcon, 'supportsMessages', return_value=True), \
                patch.object(self.window.tray, 'isVisible', return_value=True), \
                patch.object(self.window.tray, 'showMessage') as balloon:
            self.cleanup_probe().finish(workflow.video_response(isComplete=True))
        self.assertFalse(self.path.exists())
        entry = self.notifications()[0]
        self.assertEqual(entry['kind'], 'deleted')
        self.assertIn('local copy deleted', entry['title'])
        self.assertEqual(entry['url'], URL)
        balloon.assert_called_once()
        self.assertEqual(self.window.notifications_button.text(), 'Notifications (1)')
        # The Loom link stays reachable from the recorder, the library and after restart.
        qt.clipboard().setText('unchanged')
        self.window.copy_uploaded_link()
        self.assertEqual(qt.clipboard().text(), URL)
        self.assertFalse(page.loom_only.isHidden())
        self.assertEqual(page.loom_only.text(), 'On Loom only (1)')
        page.build_loom_only_menu()
        self.assertEqual(len(page.loom_only_menu.actions()), 1)
        actions = {action.text(): action for action in page.loom_only_menu.actions()[0].menu().actions()}
        qt.clipboard().setText('unchanged')
        actions['Copy Loom link'].trigger()
        self.assertEqual(qt.clipboard().text(), URL)
        with patch.object(workflow.recordings.QDesktopServices, 'openUrl') as opened:
            actions['Open in Loom ↗'].trigger()
        self.assertEqual(opened.call_args.args[0].toString(), URL)
        rows = UploadStore(self.root / 'uploads.json').remote_only()
        self.assertEqual(rows[0]['url'], URL)
        self.assertEqual(rows[0]['local_copy'], 'deleted')
        self.assertIsNone(self.window.last_file)

    def test_opening_panel_marks_read_and_survives_restart(self):
        self.publish(isComplete=True)
        self.cleanup_probe().finish(workflow.video_response(isComplete=True))
        self.window.open_notifications()
        panel = self.window.notification_panel
        self.assertEqual(self.window.notifications_button.text(), 'Notifications')
        buttons = {button.text() for button in panel.findChildren(workflow.QPushButton)}
        self.assertTrue({'Copy link', 'Open in Loom ↗', 'Clear all'} <= buttons)
        qt.clipboard().setText('unchanged')
        next(button for button in panel.findChildren(workflow.QPushButton)
             if button.text() == 'Copy link').click()
        self.assertEqual(qt.clipboard().text(), URL)
        from untangle import notification_panel
        with patch.object(notification_panel.QDesktopServices, 'openUrl') as opened:
            next(button for button in panel.findChildren(workflow.QPushButton)
                 if button.text() == 'Open in Loom ↗').click()
        self.assertEqual(opened.call_args.args[0].toString(), URL)
        persisted = NotificationLog(self.root / 'notifications.json')
        self.assertEqual(persisted.unread(), 0)
        self.assertEqual(persisted.entries()[0]['url'], URL)
        panel.close()

    def test_remote_mismatch_keeps_file(self):
        self.publish(isComplete=True)
        self.cleanup_probe().finish(workflow.video_response(
            id='other999', url='https://www.loom.com/share/other999', isComplete=True))
        self.assert_kept('remote_mismatch')

    def test_unknown_completion_keeps_file(self):
        self.publish(isComplete=True)
        self.cleanup_probe().finish(workflow.video_response(isComplete=None))
        self.assert_kept('remote_incomplete')

    def test_failed_probe_keeps_file(self):
        self.publish(isComplete=True)
        self.cleanup_probe().finish('', 1)
        self.assert_kept('remote_unverified')

    def test_file_changed_after_upload_is_kept(self):
        self.publish(isComplete=True)
        probe = self.cleanup_probe()
        with self.path.open('ab') as stream:
            stream.write(b' edited')
        probe.finish(workflow.video_response(isComplete=True))
        self.assert_kept('changed')

    def test_frame_review_registration_keeps_file(self):
        self.publish(isComplete=True)
        folder = self.reviews / 'walkthrough'
        folder.mkdir(parents=True)
        (folder / 'review.json').write_text(json.dumps({'versions': [{'path': str(self.path)}]}))
        self.cleanup_probe().finish(workflow.video_response(isComplete=True))
        self.assert_kept('review')

    def test_busy_recording_defers_then_deletes_when_idle(self):
        self.publish(isComplete=True)
        probe = self.cleanup_probe()
        self.window.recording = True
        try:
            probe.finish(workflow.video_response(isComplete=True))
            self.assertTrue(self.path.is_file())
            self.assertIn(self.path.absolute(), self.window._loom_cleanup_pending)
            self.assertTrue(self.window._loom_cleanup_timer.isActive())
            self.window.retry_local_cleanups()  # Still recording: no new probe yet.
            self.assertTrue(self.path.is_file())
            self.assertFalse([process for process in self.window.loom_probes if process is not probe
                              and process.arguments[:3] == ['loom', 'video', 'get']])
        finally:
            self.window.recording = False
        self.window.retry_local_cleanups()
        self.cleanup_probe().finish(workflow.video_response(isComplete=True))
        self.assertFalse(self.path.exists())
        self.assertFalse(self.window._loom_cleanup_timer.isActive())

    def test_playback_keeps_file_and_gives_up_with_reason(self):
        page = self.open_library()
        self.publish(isComplete=True)
        probe = self.cleanup_probe()
        with patch.object(self.window, 'local_copy_busy_reason', return_value='playback'):
            probe.finish(workflow.video_response(isComplete=True))
            for _ in range(45):
                self.window.retry_local_cleanups()
        self.assert_kept('playback')
        self.assertFalse(self.window._loom_cleanup_pending)
        self.assertIsNotNone(page)

    def test_playback_source_is_busy(self):
        page = self.open_library()
        from PySide6.QtCore import QUrl
        with patch.object(page.player, 'source', return_value=QUrl.fromLocalFile(str(self.path))):
            self.assertEqual(self.window.local_copy_busy_reason(self.path), 'playback')
        self.assertEqual(self.window.local_copy_busy_reason(self.path), '')

    def test_toggle_off_keeps_file_without_probe(self):
        self.window.prefs.setValue(loom_cleanup.PREFERENCE, False)
        self.publish(isComplete=True)
        self.assertFalse([process for process in self.window.loom_probes
                          if process.arguments[:3] == ['loom', 'video', 'get']])
        self.assertTrue(self.path.is_file())
        self.assertIn('Automatic deletion is off', self.notifications()[0]['detail'])

    def test_processing_upload_keeps_file_without_probe(self):
        self.publish()
        self.assertFalse(self.window.loom_probes)
        self.assert_kept('processing')

    def test_delete_failure_restores_metadata_and_keeps_file(self):
        self.publish(isComplete=True)
        original = Path.unlink
        def protected(path, *args, **kwargs):
            if path == self.path.absolute():
                raise PermissionError('protected')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'unlink', protected):
            self.cleanup_probe().finish(workflow.video_response(isComplete=True))
        self.assert_kept('delete_failed')
        self.assertEqual(self.window.upload_store.get(self.path)['local_copy'], '')

    def test_unsaved_status_keeps_file_and_says_why(self):
        original = self.window.upload_store.update
        def failing(path, **fields):
            if fields.get('status') == 'uploaded':
                raise OSError('read-only metadata')
            return original(path, **fields)
        with patch.object(self.window.upload_store, 'update', side_effect=failing):
            self.publish(isComplete=True)
        self.assertFalse(self.window.loom_probes)
        self.assert_kept('metadata')
        self.assertEqual(self.notifications()[0]['url'], URL)

    def test_processing_promoted_by_link_check_deletes_and_keeps_message(self):
        page = self.open_library()
        self.publish()
        self.window.check_loom_video(self.path.absolute())
        self.cleanup_probe().finish(workflow.video_response(isComplete=True))
        self.assertFalse(self.path.exists())
        self.assertIn('Deleted the local copy', page.message.text())
        self.assertEqual(self.notifications()[0]['kind'], 'deleted')

    def test_sharing_toggle_defaults_on_and_persists(self):
        self.window.prefs.remove(loom_cleanup.PREFERENCE)
        def inspect(dialog):
            boxes = {box.text(): box for box in dialog.findChildren(QCheckBox)}
            box = boxes['Delete local copy after a verified Loom upload']
            self.assertTrue(box.isChecked())
            box.setChecked(False)
        self.inspect_sharing(inspect)
        self.assertFalse(self.window.prefs.value(loom_cleanup.PREFERENCE, True, type=bool))


if __name__ == '__main__':
    unittest.main()
