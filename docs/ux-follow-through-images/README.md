# Library follow-through screenshots

Historical capture pack. The manifest identifies its source; these images are not the current release. Use [UI standards](../ui-standards.md) for isolated reproduction.

Actual production Recordings Qt widget at 960 × 760, light and dark themes, long title plus uploaded and failed transfer states. Review remains silent and the player source is empty. Media/audio objects, thumbnail decoder and browser calls are mocked; files are synthetic temporary placeholders. This does not establish native video playback, desktop behavior or live provider permissions.

Generated through the isolated `scripts/test.sh` runner with `UNTANGLE_TEST_PATTERN=test_recordings_loom.py UNTANGLE_LIBRARY_SNAPSHOTS=1`. The test serializes PNG bytes to the log, which are extracted outside the read-only sandbox. No app launch, device access, authentication or network upload was performed.

Archive controls now use separate rows. Loom actions use two rows. Transfer status has a reserved full-width line in every recording row, so long titles cannot push it out. Geometry checks cover selected actions and archive buttons in both themes; screenshots were inspected after rendering.
