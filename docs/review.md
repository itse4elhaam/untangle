# Frame review

`untangle-review` reviews video edits the way code is reviewed. Each review holds the versions of one video. Comments point at an exact frame, and optionally at a region of it. Agents read the comments through MCP, reply in the thread, add the next render and mark comments addressed. You check the frame in the new version and resolve it. It is a local web app plus a command line and an MCP server. It is standard-library Python, needs FFmpeg, and never starts the recorder.

## Start reviewing

```bash
bin/untangle-review add launch-teaser ~/Videos/teaser-v1.mp4 --create --label "v1 rough cut"
bin/untangle-review add launch-teaser https://drive.google.com/file/d/<id>/view --label v2
bin/untangle-review serve            # http://127.0.0.1:8740
```

A source can be a local file, a Google Drive file link or a direct video URL. Drive files download by file ID through an existing rclone Drive remote, so private files work without new credentials. Set `UNTANGLE_REVIEW_DRIVE_REMOTE` to choose a remote; otherwise the first Drive-type remote is used. Files shared by link fall back to Google's public download. If both fail, download the file yourself and add it with `--origin <link>` so it can be fetched again later.

Reviews live in `~/Videos/reviews/<name>/` (`--root` or `UNTANGLE_REVIEW_ROOT` changes this). `review.json` holds versions and comments. `sources/` holds downloads and `frames/` holds extracted stills; both are caches. `untangle-review prune <name>` deletes them, and the app downloads and extracts them again from the recorded origin when you reopen the review. Local files you added are never deleted. Extraction and downloads refuse to start when free space runs short.

## In the app

Step with the arrow keys (Shift for ten frames), scrub the timeline, or click the timecode and type a frame number or `mm:ss:ff`. Drag on the frame to mark a region, then write the comment; Ctrl+Enter sends. Choose another version under **Compare with** to see the same moment side by side, as a wipe, or as a difference image that shows only what changed. Playback uses the original video, with sound off until you press M. Pausing returns to the exact extracted frame, so a comment always matches what you saw. **Hand off to agent** copies a prompt for an agent thread. Press `?` for every shortcut.

Comments are **open**, **addressed** in a named version, or **resolved**. Agents can reply and mark comments addressed; only the reviewer resolves or reopens. An addressed comment offers **Check in v2**, which opens the newer version at the same moment beside the version you commented on.

## Agents

Register the MCP server once per agent:

```bash
claude mcp add -s user untangle-review -- /path/to/untangle/bin/untangle-review mcp
codex mcp add untangle-review -- /path/to/untangle/bin/untangle-review mcp
```

The tools are `list_reviews`, `get_review`, `add_version`, `list_comments`, `get_frame`, `add_comment`, `reply`, `mark_addressed`, `open_review` and `export_review`. `get_frame` returns the frame as an image, plus a crop of the commented region and, on request, the same moment in another version. `open_review` starts the app if it is not running and returns a deep link to a version, frame or comment; T3 Code can show it in the preview panel. Without MCP, `untangle-review list <name>`, `reply`, `status --agent` and `export` cover the same loop.

## Frame accuracy

Frames are numbered from 0 on the source's nominal constant frame rate, and comments store that number with its time. When a version has an edit decision list (`--edl`, segments mapping output to source time), the app carries comments to other versions through source time, which survives trims. Otherwise it maps by time and says so. Variable-frame-rate sources are flagged, because their playback can differ from the frame grid by a frame. Replacing a file after adding it is also flagged; add the new render as a new version instead.

## Safety

The app listens on 127.0.0.1 only. It rejects other Host headers and cross-site writes, and serves only versions registered through the command line or MCP. The page never receives local file paths. Nothing is uploaded, and media stays out of Git. Implementation lives in [src/untangle/review](../src/untangle/review/); tests in [tests/test_review.py](../tests/test_review.py) cover the frame grid, locking, guards, Drive fetching and the MCP protocol with synthetic clips.
