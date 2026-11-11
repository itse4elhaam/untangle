"""untangle-review: frame-accurate video review for people and agents."""
import argparse
import json
import os
import sys

from .frames import Frames
from .store import Review, ReviewError, STATUSES, default_root, timecode


def build_parser():
    parser = argparse.ArgumentParser(prog='untangle-review', description=__doc__)
    parser.add_argument('--root', default=None, help=f'Review folder (default {default_root()}, or UNTANGLE_REVIEW_ROOT).')
    commands = parser.add_subparsers(dest='command', required=True)

    new = commands.add_parser('new', help='Create a review.')
    new.add_argument('name')
    new.add_argument('--title')

    add = commands.add_parser('add', help='Add a version from a file, Google Drive link or URL.')
    add.add_argument('review')
    add.add_argument('source')
    add.add_argument('--label')
    add.add_argument('--note', default='')
    add.add_argument('--captions', help='SRT, timed segments, or caption groups JSON.')
    add.add_argument('--edl', help='JSON segments mapping output time to source time.')
    add.add_argument('--origin', help='Link a local file came from, so it can be fetched again after pruning.')
    add.add_argument('--create', action='store_true', help='Create the review if missing.')
    add.add_argument('--title', help='Title when creating.')
    add.add_argument('--wait', action='store_true', help='Extract frames before returning.')

    serve = commands.add_parser('serve', help='Run the review app on 127.0.0.1.')
    serve.add_argument('--port', type=int, default=int(os.environ.get('UNTANGLE_REVIEW_PORT', '8740')))
    serve.add_argument('--open', action='store_true', help='Open the app in the default browser.')

    show = commands.add_parser('list', help='List reviews, or the comments of one review.')
    show.add_argument('review', nargs='?')
    show.add_argument('--status', default='unresolved', choices=['unresolved', 'all', *STATUSES])
    show.add_argument('--json', action='store_true')

    reply = commands.add_parser('reply', help='Reply in a comment thread.')
    reply.add_argument('review')
    reply.add_argument('comment')
    reply.add_argument('text')
    reply.add_argument('--agent', action='store_true', help='Reply as an agent.')

    status = commands.add_parser('status', help='Set a comment status.')
    status.add_argument('review')
    status.add_argument('comment')
    status.add_argument('status', choices=STATUSES)
    status.add_argument('--version', help='Version that addresses it.')
    status.add_argument('--agent', action='store_true')

    export = commands.add_parser('export', help='Print unresolved comments as Markdown or JSON.')
    export.add_argument('review')
    export.add_argument('--json', action='store_true')

    frames = commands.add_parser('frames', help='Extract frames now (otherwise the app does it on demand).')
    frames.add_argument('review')
    frames.add_argument('--version')

    prune = commands.add_parser('prune', help='Delete rebuildable caches: frames and downloaded sources.')
    prune.add_argument('review')
    prune.add_argument('--frames-only', action='store_true')

    commands.add_parser('mcp', help='Run the MCP server on stdio for agents.')
    return parser


def author(agent):
    if agent:
        return os.environ.get('UNTANGLE_REVIEW_AGENT_NAME', 'Agent'), 'agent'
    from .server import reviewer_name
    return reviewer_name(), 'human'


def print_comments(review, status, as_json):
    data = review.load()
    versions = {v['id']: v for v in data['versions']}
    chosen = [c for c in data['comments']
              if status == 'all' or (status == 'unresolved' and c['status'] != 'resolved') or c['status'] == status]
    if as_json:
        print(json.dumps(chosen, indent=1, ensure_ascii=False))
        return
    if not chosen:
        print('No comments.')
    for comment in chosen:
        version = versions[comment['version']]
        where = f'{version["label"]} {timecode(comment["frame"], version["fps"])} (frame {comment["frame"]})'
        print(f'#{comment["number"]} [{comment["id"]}] {where} · {comment["status"]}')
        if comment.get('caption'):
            print(f'  “{comment["caption"]}”')
        for message in comment['thread']:
            print(f'  {message["author"]}: {message["text"]}')


def main(argv=None):
    args = build_parser().parse_args(argv)
    root = args.root
    try:
        if args.command == 'new':
            review = Review.create(args.name, args.title, root)
            print(review.path)
        elif args.command == 'add':
            from .sources import add as add_source
            try:
                review = Review.open(args.review, root)
            except ReviewError:
                if not args.create:
                    raise
                review = Review.create(args.review, args.title, root)
            version = add_source(review, args.source, label=args.label, captions=args.captions, edl=args.edl,
                                 note=args.note, origin=args.origin,
                                 progress=lambda message: print(message, file=sys.stderr))
            print(f'{review.name}: added {version["id"]} ({version["width"]}x{version["height"]}, '
                  f'{version["fps"]:g} fps, {version["frames"]} frames)')
            if version.get('variable_rate'):
                print('Warning: variable frame rate source; frames follow a constant-rate grid.', file=sys.stderr)
            if args.wait:
                print(f'{Frames(review, version).extract()} frames ready')
        elif args.command == 'serve':
            from .server import serve

            def ready(server):
                print(f'Untangle Review on {server.url}  (root {server.root})', flush=True)
                if args.open:
                    import webbrowser
                    webbrowser.open(server.url)
            try:
                serve(root, args.port, ready=ready)
            except KeyboardInterrupt:
                pass
        elif args.command == 'list':
            if args.review:
                print_comments(Review.open(args.review, root), args.status, args.json)
            else:
                reviews = Review.list(root)
                if args.json:
                    print(json.dumps(reviews, indent=1))
                for item in [] if args.json else reviews:
                    counts = item['counts']
                    print(f'{item["name"]:32} {len(item["versions"])} versions · {counts["open"]} open · '
                          f'{counts["addressed"]} addressed · {counts["resolved"]} resolved')
        elif args.command == 'reply':
            name, role = author(args.agent)
            Review.open(args.review, root).reply(args.comment, args.text, name, role)
        elif args.command == 'status':
            name, role = author(args.agent)
            Review.open(args.review, root).set_status(args.comment, args.status, name, role, args.version)
        elif args.command == 'export':
            review = Review.open(args.review, root)
            if args.json:
                print(json.dumps(review.load(), indent=1, ensure_ascii=False))
            else:
                print(review.export_markdown())
        elif args.command == 'frames':
            review = Review.open(args.review, root)
            data = review.load()
            for version in data['versions']:
                if not args.version or version['id'] == args.version:
                    from .sources import refetch
                    refetch(review, version)
                    print(f'{version["id"]}: {Frames(review, version).extract()} frames')
        elif args.command == 'prune':
            freed = Review.open(args.review, root).prune(sources=not args.frames_only)
            print(f'Freed {freed / (1 << 20):.1f} MB')
        elif args.command == 'mcp':
            from .mcp import run
            run(root)
    except ReviewError as error:
        print(f'untangle-review: {error}', file=sys.stderr)
        return 1
    return 0
