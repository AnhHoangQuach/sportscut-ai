import argparse
import json
import re
import sys
from pathlib import Path

from sportscut import __version__
from sportscut import eval_crop
from sportscut import evaluate
from sportscut import subtitles
from sportscut.commentary import eval_meta
from sportscut.commentary import publish
from sportscut.commentary import voiceover
from sportscut.detect import find_highlights
from sportscut.eval_player import evaluate_dir
from sportscut.media import MediaError
from sportscut.pipeline import PipelineError, run
from sportscut.player import PlayerQuery
from sportscut.ranking import parse_events
from sportscut.reel import MANIFEST_NAME, make_player_reel

NOTICE = (
    "sportscut: notice: subtitles need the [asr] extra: pip install 'sportscut[asr]'; "
    "vertical clips are rendered without subtitles"
)
VO_NOTICE = (
    "sportscut: notice: voice-over needs the [tts] extra: pip install 'sportscut[tts]'; "
    "only the commentary scripts are written"
)


def _events_arg(text: str) -> tuple[str, ...]:
    try:
        return parse_events(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _score_box_arg(text):
    if re.fullmatch(r"\d+,\d+,\d+,\d+", text.strip()) is None:
        raise argparse.ArgumentTypeError("expected x,y,w,h as four non-negative integers")
    return tuple(int(v) for v in text.split(","))


def _add_match_options(parser) -> None:
    for flag, what in (("--home", "home team"), ("--away", "away team"), ("--competition", "competition")):
        parser.add_argument(flag, help=f"{what} name")
    parser.add_argument("--kickoff", type=float, help="kickoff time in seconds into the video; the minute needs it")
    parser.add_argument("--match-info", help="match.json with home, away, competition, score, kickoff; flags win")


def _match_from_args(args) -> dict | None:
    match = {}
    if args.match_info:
        try:
            match = json.loads(Path(args.match_info).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError(f"cannot read {args.match_info}: {exc}") from exc
        if not isinstance(match, dict):
            raise ValueError(f"{args.match_info}: expected a JSON object")
    match.update({k: getattr(args, k) for k in ("home", "away", "competition", "kickoff") if getattr(args, k) is not None})
    return match or None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sportscut",
        description="Find and export highlights from sports videos.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"sportscut {__version__}",
    )
    subparsers = parser.add_subparsers(dest="command")
    detect_parser = subparsers.add_parser("detect", help="detect highlight segments")
    detect_parser.add_argument("video")
    detect_parser.add_argument("--top", type=int, default=10)
    detect_parser.add_argument("--min-len", type=float, default=10)
    detect_parser.add_argument("--max-len", type=float, default=30)
    detect_parser.add_argument("--json", action="store_true")
    cut_parser = subparsers.add_parser("cut", help="detect and export highlight clips")
    cut_parser.add_argument("video")
    cut_parser.add_argument("--out", required=True)
    cut_parser.add_argument("--top", type=int, default=10)
    cut_parser.add_argument("--min-len", type=float, default=10)
    cut_parser.add_argument("--max-len", type=float, default=30)
    cut_parser.add_argument(
        "--events",
        type=_events_arg,
        default=None,
        help="comma-separated events to keep: goal,save,red_card,controversy,other",
    )
    cut_parser.add_argument(
        "--vertical",
        action="store_true",
        help="also write 1080x1920 (9:16) clips to OUT/vertical/",
    )
    cut_parser.add_argument(
        "--score-box",
        type=_score_box_arg,
        default=None,
        metavar="X,Y,W,H",
        help="scoreboard box in source pixels for --vertical, when detection fails",
    )
    cut_parser.add_argument(
        "--subtitles",
        action="store_true",
        help="burn commentary subtitles into --vertical clips (needs the [asr] extra)",
    )
    cut_parser.add_argument(
        "--voiceover",
        action="store_true",
        help="also write OUT/clip_NN.script.json and a Vietnamese voice-over copy "
        "OUT/clip_NN.vo.mp4 (and vertical/clip_NN.vo.mp4 with --vertical); "
        "audio needs the [tts] extra",
    )
    cut_parser.add_argument(
        "--meta",
        action="store_true",
        help="also write titles, captions and hashtags: OUT/captions.txt, OUT/reel.json "
        "and the title, caption, hashtags keys in OUT/highlights.json",
    )
    cut_parser.add_argument(
        "--meta-backend", choices=("template", "llm"), default=None,
        help="metadata generator for --meta (default template); "
        "llm needs ANTHROPIC_API_KEY and the [llm] extra",
    )
    _add_match_options(cut_parser)
    eval_player_parser = subparsers.add_parser("eval-player", help="evaluate player-touch detection")
    eval_player_parser.add_argument("directory")
    eval_player_parser.add_argument("--json", action="store_true")
    eval_player_parser.add_argument("--debug", action="store_true", help="add each clip's touch candidates to the report")
    eval_parser = subparsers.add_parser("eval", help="evaluate highlight detection")
    eval_parser.add_argument("directory", metavar="DIRECTORY")
    eval_parser.add_argument("--json", action="store_true")
    eval_meta_parser = subparsers.add_parser(
        "eval-meta", help="evaluate clip titles, captions and hashtags"
    )
    eval_meta_parser.add_argument("directory", metavar="DIRECTORY")
    eval_meta_parser.add_argument("--json", action="store_true")
    eval_meta_parser.add_argument(
        "--meta-backend", choices=("template", "llm"), default="template",
        help="metadata generator to score; llm needs ANTHROPIC_API_KEY and the [llm] extra",
    )
    eval_meta_parser.add_argument(
        "--script", action="store_true",
        help="score timed commentary scripts (10 s and 30 s clips) instead of metadata",
    )
    eval_crop_parser = subparsers.add_parser(
        "eval-crop", help="evaluate 9:16 crop framing"
    )
    eval_crop_parser.add_argument("directory", metavar="DIRECTORY")
    eval_crop_parser.add_argument("--json", action="store_true")
    meta_parser = subparsers.add_parser("meta", help="write titles, captions and hashtags for the clips in OUT_DIR")
    meta_parser.add_argument("out_dir", metavar="OUT_DIR")
    _add_match_options(meta_parser)
    meta_parser.add_argument(
        "--meta-backend", choices=("template", "llm"), default="template",
        help="metadata generator to score; llm needs ANTHROPIC_API_KEY and the [llm] extra",
    )
    player_parser = subparsers.add_parser("player", help="export a reel of one player's touches")
    player_parser.add_argument("video")
    player_parser.add_argument("--team", required=True)
    player_parser.add_argument("--number", required=True, type=int)
    player_parser.add_argument("--out", required=True)
    player_parser.add_argument("--pre", type=float, default=3.0)
    player_parser.add_argument("--post", type=float, default=2.0)
    player_parser.add_argument("--merge-gap", type=float, default=4.0)
    serve_parser = subparsers.add_parser("serve", help="serve the highlights HTTP API")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8000)
    download_parser = subparsers.add_parser(
        "download-models", help="download the speech-to-text model used by cut --subtitles"
    )
    download_parser.add_argument(
        "--tts",
        action="store_true",
        help="download the Vietnamese Piper voice used by cut --voiceover instead",
    )

    args = parser.parse_args(argv)
    if args.command == "cut" and args.score_box is not None and not args.vertical:
        cut_parser.error("--score-box needs --vertical")
    if args.command == "cut" and args.subtitles and not args.vertical:
        cut_parser.error("--subtitles needs --vertical")
    if args.command == "cut" and not (args.meta or args.voiceover) and any(
        getattr(args, k) is not None for k in ("home", "away", "competition", "kickoff", "match_info")
    ):
        cut_parser.error("--home, --away, --competition, --kickoff and --match-info need --meta or --voiceover")
    if args.command == "cut" and args.meta_backend is not None and not args.meta:
        cut_parser.error("--meta-backend needs --meta")
    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "serve":
        try:
            import uvicorn
            from sportscut.api import app
        except ImportError:
            print(
                "sportscut: error: the API needs the [api] extra: "
                "pip install 'sportscut[api]'",
                file=sys.stderr,
            )
            return 1
        uvicorn.run(app, host=args.host, port=args.port)
        return 0

    if args.command == "player":
        try:
            query = PlayerQuery(args.team, args.number)
            manifest = make_player_reel(
                args.video, query, args.out, args.pre, args.post, args.merge_gap
            )
        except ValueError as exc:
            print(f"sportscut player: error: {exc}", file=sys.stderr)
            return 2
        except (MediaError, OSError) as exc:
            print(f"sportscut player: error: {exc}", file=sys.stderr)
            return 1
        if manifest["reel"]:
            print(
                f"wrote {Path(args.out) / manifest['reel']}: "
                f"{len(manifest['touches'])} touches in {len(manifest['clips'])} clips, "
                f"{manifest['total_duration']:.1f} s"
            )
        else:
            print(
                f"no touches found for {query.team} {query.number}; "
                f"wrote {Path(args.out) / MANIFEST_NAME}"
            )
        return 0

    if args.command == "eval-player":
        try:
            report = evaluate_dir(args.directory, debug=args.debug)
        except (ValueError, OSError, MediaError) as exc:
            print(f"sportscut eval-player: error: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(report) if args.json else json.dumps(report, indent=2))
        return 0

    if args.command == "eval":
        try:
            report = evaluate.evaluate_dir(args.directory)
        except (ValueError, OSError, MediaError) as exc:
            print(f"sportscut eval: error: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(report) if args.json else json.dumps(report, indent=2))
        return 0

    if args.command == "eval-meta":
        try:
            report = eval_meta.evaluate_meta_dir(
                args.directory, backend=args.meta_backend, script=args.script
            )
        except (ValueError, OSError) as exc:
            print(f"sportscut eval-meta: error: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(report) if args.json else json.dumps(report, indent=2))
        return 0

    if args.command == "eval-crop":
        try:
            report = eval_crop.evaluate_dir(args.directory)
        except (ValueError, OSError, MediaError) as exc:
            print(f"sportscut eval-crop: error: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(report) if args.json else json.dumps(report, indent=2))
        return 0

    if args.command == "download-models" and args.tts:
        try:
            path = voiceover.download_voice()
        except Exception as exc:
            print(f"sportscut download-models: error: {exc}", file=sys.stderr)
            return 1
        print(f"downloaded Piper voice {voiceover.VOICE} to {path}")
        return 0

    if args.command == "download-models":
        try:
            path = subtitles.download_models()
        except ImportError:
            print(
                f"sportscut download-models: error: needs the [asr] extra: {subtitles.ASR_HINT}",
                file=sys.stderr,
            )
            return 1
        except Exception as exc:
            print(f"sportscut download-models: error: {exc}", file=sys.stderr)
            return 1
        print(f"downloaded faster-whisper base model to {path}")
        return 0

    if args.command == "meta":
        try:
            publish.write_meta(args.out_dir, _match_from_args(args), backend=args.meta_backend)
        except (ValueError, OSError) as exc:
            print(f"sportscut meta: error: {exc}", file=sys.stderr)
            return 1
        for name in (publish.MANIFEST_NAME, publish.CAPTIONS_NAME, publish.REEL_NAME):
            print(Path(args.out_dir) / name)
        return 0

    if args.command == "cut":
        try:
            match = _match_from_args(args)
        except (ValueError, OSError) as exc:
            print(f"sportscut: error: {exc}", file=sys.stderr)
            return 1
        transcriber = None
        if args.subtitles:
            transcriber = subtitles.default_transcriber()
            if transcriber is None:
                print(NOTICE, file=sys.stderr)
        synthesizer = None
        if args.voiceover:
            synthesizer = voiceover.default_synthesizer()
            if synthesizer is None:
                print(VO_NOTICE, file=sys.stderr)
        try:
            entries = run(
                args.video, args.out, top=args.top,
                min_len=args.min_len, max_len=args.max_len,
                events=args.events,
                vertical=args.vertical,
                score_box=args.score_box,
                transcriber=transcriber,
                voiceover=args.voiceover,
                synthesizer=synthesizer,
                match=match,
            )
        except (PipelineError, MediaError) as exc:
            print(f"sportscut: error: {exc}", file=sys.stderr)
            return 1
        if args.meta and entries:
            try:
                publish.write_meta(args.out, match, backend=args.meta_backend or "template")
            except (ValueError, OSError) as exc:
                print(f"sportscut: error: {exc}", file=sys.stderr)
                return 1
        elif args.meta:
            print("sportscut: notice: no clips were cut; --meta wrote nothing", file=sys.stderr)
        for entry in entries:
            print(Path(args.out) / entry["file"])
            if "vertical_file" in entry:
                print(Path(args.out) / entry["vertical_file"])
            if "script_file" in entry:
                print(Path(args.out) / entry["script_file"])
            for key in ("voiceover_file", "vertical_voiceover_file"):
                if key in entry:
                    print(Path(args.out) / entry[key])
        if args.meta and entries:
            print(Path(args.out) / publish.CAPTIONS_NAME)
            print(Path(args.out) / publish.REEL_NAME)
        return 0

    try:
        segments = find_highlights(
            args.video, top=args.top, min_len=args.min_len, max_len=args.max_len
        )
    except (MediaError, ValueError) as exc:
        print(f"sportscut: error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps([segment.to_dict() for segment in segments]))
    else:
        for segment in segments:
            print(
                f"{segment.start:.1f}\t{segment.end:.1f}\t"
                f"{segment.score:.2f}\t{segment.reason}"
            )
    return 0
