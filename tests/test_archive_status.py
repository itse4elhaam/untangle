import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from untangle.archive_status import archive_status, scheduler_status


class ArchiveStatusTests(unittest.TestCase):
    def test_saved_settings_are_independent_of_scheduler_and_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            (state / 'archive.json').write_text(json.dumps({'enabled': True, 'folder': 'archive-folder'}))
            text = archive_status(state)
            self.assertIn('Destination saved: archive-folder', text)
            self.assertIn('Archiving enabled: Yes', text)
            self.assertIn('Scheduler observed: Not checked', text)
            self.assertIn('No verified upload recorded', text)
            (state / 'archive-uploads.json').write_text(json.dumps({
                'version': 1, 'uploads': {'a': {'verified_at': 100}}}))
            text = archive_status(state, scheduler='Not active.', now=800000)
            self.assertIn('over 7 days ago', text)
            self.assertIn('remote copy not checked here', text)
            self.assertIn('Scheduler observed: Not active.', text)

    def test_malformed_history_is_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            (state / 'archive-uploads.json').write_text('[]')
            self.assertIn('history could not be read', archive_status(state))

    def test_scheduler_observation_never_activates_it(self):
        with patch('untangle.archive_status.subprocess.run', return_value=Mock(
                returncode=0, stdout='LoadState=loaded\nActiveState=active\nUnitFileState=enabled\n')) as run:
            self.assertIn('Active when checked', scheduler_status())
        self.assertEqual(run.call_args.args[0][:4], ['systemctl', '--user', 'show', 'untangle-archive.timer'])
        with patch('untangle.archive_status.subprocess.run', side_effect=subprocess.TimeoutExpired('systemctl', 2)):
            self.assertIn('Unknown', scheduler_status())
