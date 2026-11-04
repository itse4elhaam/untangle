"""Non-destructive recording projects and cancellable versioned trim exports."""
import fcntl
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading


class ExportCancelled(RuntimeError):
    pass


def identity(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError('The original recording is missing or is not a regular file.')
    stat = path.stat()
    return [stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns]


def _save(path, data):
    """Replace metadata only after its complete contents have reached disk."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, prefix='.project-',
                                         delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(data, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class RecordingProject:
    def __init__(self, source):
        self.source = Path(source).absolute()
        self.directory = self.source.with_name(self.source.name + '.untangle-project')
        self.metadata = self.directory / 'project.json'

    def _load(self):
        current = identity(self.source)
        if self.metadata.exists():
            data = json.loads(self.metadata.read_text())
            if data.get('schema') != 1 or data.get('source') != str(self.source):
                raise ValueError('Unsupported project metadata. Keep the project and original for recovery.')
            if data.get('identity') != current:
                raise ValueError('The original changed since this project was created. Keep the project and reopen a separate copy.')
        else:
            data = {'schema': 1, 'source': str(self.source), 'identity': current,
                    'tracks': [
                        {'role': 'composed_video', 'source': str(self.source),
                         'stream': 'v:0', 'editable_layout': False},
                        {'role': 'mixed_audio_if_present', 'source': str(self.source),
                         'stream': 'a:0?', 'editable_layout': False}], 'versions': []}
        # Names are derived from numeric version IDs, never trusted metadata paths.
        for version in data['versions']:
            number = version['number']
            if type(number) is not int or number < 1:
                raise ValueError('Invalid export version in project metadata.')
            if version['status'] == 'pending':
                self._partial(number).unlink(missing_ok=True)
                output = self.output(number)
                version['status'] = 'recovered' if output.is_file() and output.stat().st_size else 'interrupted'
        return data

    def output(self, number):
        return self.directory / f'export-v{number:04d}.mp4'

    def _partial(self, number):
        return self.directory / f'.export-v{number:04d}.partial.mp4'

    def _lock(self):
        if self.directory.is_symlink():
            raise ValueError('Project directory must not be a symbolic link.')
        self.directory.mkdir(exist_ok=True)
        handle = (self.directory / '.lock').open('a')
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close()
            raise RuntimeError('Another export is using this recording project.') from None
        return handle

    def history(self):
        with self._lock():
            data = self._load()
            _save(self.metadata, data)
            return data['versions']

    def export(self, start=0., end=0., cancel=None):
        start, end = float(start), float(end)
        if not all(math.isfinite(value) and value >= 0 for value in (start, end)):
            raise ValueError('Trim times must be finite, positive seconds or zero.')
        if end and end <= start:
            raise ValueError('End must be later than start. Use zero for the recording end.')
        cancel = cancel or threading.Event()
        ffmpeg = shutil.which('ffmpeg')
        ffprobe = shutil.which('ffprobe')
        if not ffmpeg or not ffprobe:
            raise RuntimeError('Install ffmpeg and ffprobe before exporting.')
        with self._lock():
            data = self._load()
            if cancel.is_set():
                raise ExportCancelled('Export cancelled. The original is unchanged.')
            # ffprobe only reads the selected local recording; never opens an input device.
            probe = subprocess.run([ffprobe, '-v', 'error', '-protocol_whitelist', 'file,pipe', '-show_entries', 'format=duration',
                                    '-of', 'json', str(self.source)], capture_output=True,
                                   text=True, timeout=15, check=True)
            duration = float(json.loads(probe.stdout)['format']['duration'])
            if not math.isfinite(duration) or start >= duration or (end and end > duration + .01):
                raise ValueError(f'Trim times must be within the recording ({duration:.2f} seconds).')
            number = max((item['number'] for item in data['versions']), default=0) + 1
            # Also skip an orphan final file from an interrupted metadata write.
            while self.output(number).exists() or self._partial(number).exists():
                number += 1
            version = {'number': number, 'start': start, 'end': end or duration,
                       'status': 'pending', 'format': 'h264/aac-mp4'}
            data['versions'].append(version)
            _save(self.metadata, data)
            partial = self._partial(number)
            output = self.output(number)
            command = [ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'error', '-n',
                       '-protocol_whitelist', 'file,pipe', '-i', str(self.source), '-ss', str(start), '-t', str((end or duration) - start),
                       '-map', '0:v:0', '-map', '0:a:0?', '-c:v', 'libx264', '-preset', 'fast',
                       '-crf', '20', '-c:a', 'aac', '-movflags', '+faststart', str(partial)]
            process = None
            try:
                # A file avoids pipe backpressure while allowing bounded cancellation waits.
                with tempfile.TemporaryFile() as errors:
                    process = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                               stdout=subprocess.DEVNULL, stderr=errors)
                    while True:
                        if cancel.is_set():
                            raise ExportCancelled('Export cancelled. The original is unchanged.')
                        try:
                            code = process.wait(timeout=.1)
                            break
                        except subprocess.TimeoutExpired:
                            pass
                    if code:
                        errors.seek(0)
                        detail = errors.read(4096).decode(errors='replace').strip()
                        raise RuntimeError('Export failed. Check available disk space. ' + detail)
                if cancel.is_set():
                    raise ExportCancelled('Export cancelled. The original is unchanged.')
                if identity(self.source) != data['identity']:
                    raise RuntimeError('The original changed during export. No version was published.')
                if not partial.is_file() or not partial.stat().st_size:
                    raise RuntimeError('The encoder produced no export.')
                with partial.open('rb') as handle:
                    os.fsync(handle.fileno())
                os.link(partial, output)  # Atomic publish and never overwrite a prior version.
                partial.unlink()
                version['status'] = 'completed'
                _save(self.metadata, data)
                return output
            except Exception as exc:
                if process is not None and process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                partial.unlink(missing_ok=True)
                # A published export can outlive a metadata failure. Retain it for recovery.
                version['status'] = ('recovered' if output.exists() else
                                     'cancelled' if isinstance(exc, ExportCancelled) else 'failed')
                version['error'] = str(exc)[:1000]
                try:
                    _save(self.metadata, data)
                except OSError:
                    pass  # Pending journal is recovered on next open, including ENOSPC.
                raise
