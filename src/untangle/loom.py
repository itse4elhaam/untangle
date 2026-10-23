"""Pure parsers for the official TWG CLI. This module never runs a command.

Use JSON stdout with ``--output-summary none`` and keep stderr separate. CLI
help and public capability limits are recorded in docs/loom-integration.md.
"""
import json
from pathlib import Path
import re
from urllib.parse import urlsplit


JSON_ARGS = ['-o', 'json', '--output-summary', 'none']
ACCOUNT_ARGS = ['whoami', *JSON_ARGS]
DISCONNECT_ARGS = ['logout', *JSON_ARGS]
AUTO_TITLE_HELP_URL = 'https://support.atlassian.com/loom/docs/how-auto-titles-summaries-and-chapters-work/'
WORKSPACE_SETTINGS_URL = 'https://www.loom.com/settings/workspace'
_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}')
_SHARE_PATH = re.compile(r'/share/([A-Za-z0-9]+)/?')
_ARI = re.compile(r'ari:cloud:loom:[^:/\s]*:video/(?:activation/[^/\s]+/)?([A-Za-z0-9_-]+)')
_ANSI = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')


def valid_share_url(value):
    """Return a canonical Loom HTTPS share URL, or '' for any unsafe URL."""
    if not isinstance(value, str) or any(ch.isspace() or ord(ch) < 32 for ch in value):
        return ''
    try:
        parsed = urlsplit(value)
    except ValueError:
        return ''
    if parsed.scheme != 'https' or parsed.netloc.lower() not in ('loom.com', 'www.loom.com'):
        return ''
    match = _SHARE_PATH.fullmatch(parsed.path)
    return f'https://www.loom.com/share/{match[1]}' if match else ''


def video_id(value):
    """Extract a video ID from a share URL, a Loom video ARI, or a bare ID."""
    if not isinstance(value, str):
        return ''
    url = valid_share_url(value)
    if url:
        return url.rsplit('/', 1)[1]
    match = _ARI.fullmatch(value)
    if match:
        return match[1]
    return value if _ID.fullmatch(value) else ''


def video_info_args(value):
    if not video_id(value):
        raise ValueError('Choose a Loom video ID or a valid HTTPS share URL.')
    return ['loom', 'video', 'get', value, *JSON_ARGS]


def supports_option(help_text, flag):
    """Match an advertised option, not a similar name or example text."""
    return bool(re.search(r'^\s+(?:-\w,\s+)?' + re.escape(flag) + r'(?=[\s=<]|$)',
                          _text(help_text), re.MULTILINE))


def rename_title_args(value, title, help_text):
    """Build the supported manual rename command only after its help was read."""
    if not video_id(value) or not isinstance(title, str) or not title.strip():
        raise ValueError('A Loom video and a nonempty title are required.')
    if not supports_option(help_text, '--title'):
        raise ValueError('This CLI does not advertise manual video titles.')
    return ['loom', 'video', 'rename', value, '--title', title.strip(), *JSON_ARGS]


def upload_args(path, help_text, visibility='owner', title=None, prefer_loom_titles=True):
    """Build verified upload syntax. Loom titles never receive a --title override.

    Older CLIs need a separate visibility command after upload. Callers must
    inspect ``supports_option(help_text, '--visibility')`` to choose that flow.
    """
    if visibility not in ('owner', 'workspace', 'public'):
        raise ValueError('Unknown Loom visibility.')
    text = _text(help_text)
    if supports_option(text, '--file'):
        file_args = ['--file', str(Path(path))]
    elif re.search(r'^Usage:.*\bupload\b.*<file>', text, re.MULTILINE):
        # An absolute path cannot be mistaken for a CLI option.
        file_args = [str(Path(path).absolute())]
    else:
        raise ValueError('The CLI upload syntax could not be verified.')
    args = ['loom', 'video', 'upload', *file_args, *JSON_ARGS]
    if supports_option(text, '--visibility'):
        args += ['--visibility', visibility]
    if not prefer_loom_titles and title:
        if not supports_option(text, '--title'):
            raise ValueError('This CLI does not advertise manual upload titles.')
        args += ['--title', str(title)]
    return args


def _text(value):
    return value.decode('utf-8', errors='replace') if isinstance(value, bytes) else str(value or '')


def _records(output):
    """Read one JSON document or JSONL without scraping links from diagnostics."""
    if isinstance(output, dict):
        return [output]
    text = _text(output).strip()
    try:
        value = json.loads(text)
    except (ValueError, RecursionError):
        values = []
        for line in text.splitlines():
            try:
                value = json.loads(line)
            except (ValueError, RecursionError):
                continue
            if isinstance(value, dict):
                values.append(value)
        return values
    return [value] if isinstance(value, dict) else []


def _error_codes(records):
    return {record['error'].get('code') for record in records
            if isinstance(record.get('error'), dict)
            and isinstance(record['error'].get('code'), str)}


def _data(record):
    value = record.get('data', record)
    return value if isinstance(value, dict) else {}


def _field(value):
    return ''.join(ch for ch in value if ord(ch) >= 32).strip()[:1000] if isinstance(value, str) else ''


def parse_account_status(stdout, exit_code=0, stderr=''):
    """whoami proves Atlassian identity, not Loom entitlement or AI settings."""
    result = {'status': 'unknown', 'name': '', 'email': '', 'account_id': '',
              'auto_titles_entitled': None, 'auto_titles_enabled': None}
    records = _records(stdout)
    codes = _error_codes(records + _records(stderr))
    if exit_code == 77 or codes & {'AUTH_REQUIRED', 'AUTH_INVALID', 'AUTH_EXPIRED'}:
        result['status'] = 'disconnected'
        return result
    if exit_code != 0:
        return result
    for record in reversed(records):
        if record.get('ok') is False or record.get('error'):
            continue
        data = _data(record)
        account_id = _field(data.get('accountId'))
        if account_id:
            result.update(status='connected', account_id=account_id,
                          name=_field(data.get('name')), email=_field(data.get('email')))
            break
    return result


def _video_fields(data):
    raw_id = _field(data.get('id'))
    remote_id = raw_id if video_id(raw_id) else ''
    url = valid_share_url(data.get('url'))
    if not remote_id and url:
        remote_id = video_id(url)
    visibility = _field(data.get('visibility')).lower()
    return {'url': url, 'title': _field(data.get('name')) or _field(data.get('title')),
            'remote_id': remote_id,
            'visibility': visibility if visibility in ('owner', 'workspace', 'public') else ''}


def parse_video_info(stdout, exit_code=0, stderr=''):
    """Only an explicit DELETED video state invalidates a link.

    Current public TWG builds do not expose this state. It is accepted here for
    an explicit future response; missing/private/archived/auth failures remain
    unknown. In particular a NOT_FOUND error does not establish deletion.
    """
    result = {'status': 'unknown', 'url': '', 'title': '', 'remote_id': '',
              'visibility': '', 'is_complete': None}
    if exit_code != 0:
        return result
    for record in reversed(_records(stdout)):
        if record.get('ok') is False or record.get('error') or record.get('errors'):
            continue
        data = _data(record)
        if isinstance(data.get('video'), dict):
            data = data['video']
        fields = _video_fields(data)
        if not (fields['remote_id'] or fields['url']):
            continue
        result.update(fields)
        if isinstance(data.get('isComplete'), bool):
            result['is_complete'] = data['isComplete']
        if data.get('status') == 'DELETED':
            result.update(status='deleted', url='')
        elif data.get('isArchived') is not True and data.get('status') not in ('PRIVATE', 'UNAUTHORIZED', 'NOT_FOUND', 'ARCHIVED'):
            result['status'] = 'available'
        break
    return result


def parse_upload_result(stdout, exit_code=0, stderr=''):
    """Keep a published link even if a later sharing step failed.

    Failure without a link is uncertain: a process can stop after publication.
    A structured preflight/auth error is safe to classify as failed.
    """
    records = _records(stdout)
    result = {'url': '', 'title': '', 'remote_id': '', 'status': 'uncertain', 'visibility': ''}
    for record in reversed(records):
        data = _data(record)
        video = data.get('video')
        if not isinstance(video, dict):
            # Plain video output is supported; error URLs and request payloads
            # are deliberately never searched recursively.
            video = data if not record.get('error') and record.get('ok') is not False else {}
        fields = _video_fields(video)
        if fields['url'] or fields['remote_id']:
            result.update(fields)
            if exit_code == 0 and record.get('ok') is not False and not record.get('error'):
                result['status'] = 'processing' if video.get('isComplete') is False else 'uploaded'
            break
    if not result['url'] and not result['remote_id']:
        codes = _error_codes(records + _records(stderr))
        if exit_code == 77 or codes & {'AUTH_REQUIRED', 'AUTH_INVALID', 'AUTH_EXPIRED', 'VALIDATION_ERROR', 'INVALID_ARGUMENT'}:
            result['status'] = 'failed'
    return result


def parse_upload_progress(output):
    """Read labeled human progress only; JSON result byte counts are not progress.

    No public JSON upload-progress event schema is documented. Most CLI builds
    emit no intermediate percentage, in which case the UI stays indeterminate.
    """
    result = None
    for line in _ANSI.sub('', _text(output)).replace('\r', '\n').splitlines():
        if line.lstrip().startswith(('{', '[')):
            continue
        match = re.search(r'\b(uploading|processing)\b', line, re.IGNORECASE)
        if not match:
            continue
        percent = re.search(r'(?<![\w.\-])([0-9]+(?:\.[0-9]+)?)\s*%', line)
        number = float(percent[1]) if percent else None
        if number is not None and not 0 <= number <= 100:
            continue
        result = {'stage': match[1].lower(), 'percent': number}
    return result
