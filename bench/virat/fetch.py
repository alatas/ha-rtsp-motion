"""Opt-in VIRAT download. Each person using the data must accept the VIRAT
Usage Agreement themselves; nothing from the dataset may be redistributed.

    python -m virat.fetch --accept-virat-terms [--subset PATH] [--dest /data/virat]
"""
import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

import av

from virat.truth import moving_intervals

API = "https://data.kitware.com/api/v1"
VIDEOS_FOLDER = "56f581ce8d777f753209ca43"
ANN_FOLDER = "56f57e748d777f753209bed8"
TERMS_URLS = (
    "https://data.kitware.com/api/v1/collection/56f56db28d777f753209ba9f (field: terms)",
    "https://viratdata.org/",
)
ANN_SUFFIX = ".viratdata.objects.txt"


def _print_terms(file) -> None:
    print("VIRAT is released under its own Usage Agreement. Read it here:", file=file)
    for u in TERMS_URLS:
        print("  " + u, file=file)


def _get(url: str):
    return urllib.request.urlopen(url, timeout=60)


def list_items(folder_id: str) -> list[dict]:
    """All items of a Girder folder ({_id, name, size, ...})."""
    out: list[dict] = []
    offset = 0
    while True:
        with _get(f"{API}/item?folderId={folder_id}&limit=500&offset={offset}") as r:
            page = json.load(r)
        out += page
        if len(page) < 500:
            return out
        offset += 500


def download_item(item_id: str, dest: str) -> None:
    with _get(f"{API}/item/{item_id}/download") as r, open(dest, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)


def _fetch_file(item: dict, path: Path) -> None:
    if path.exists() and path.stat().st_size == item["size"]:
        return
    tmp = path.with_name(path.name + ".part")
    download_item(item["_id"], str(tmp))
    os.replace(tmp, path)


def _video_info(path: Path) -> tuple[float, int]:
    with av.open(str(path)) as c:
        s = c.streams.video[0]
        return float(s.average_rate), s.codec_context.width


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="virat.fetch")
    ap.add_argument("--accept-virat-terms", action="store_true")
    ap.add_argument("--subset", default=str(Path(__file__).with_name("subset.txt")))
    ap.add_argument("--dest", default="/data/virat")
    args = ap.parse_args(argv)

    if not args.accept_virat_terms:
        _print_terms(sys.stderr)
        print(
            "Not downloading. Accept the agreement yourself, then re-run with "
            "--accept-virat-terms.",
            file=sys.stderr,
        )
        return 2

    _print_terms(sys.stdout)
    print(
        "By continuing you confirm that you personally accept that agreement "
        "and will not redistribute the data.",
        flush=True,
    )

    clips = [c.strip() for c in Path(args.subset).read_text().splitlines() if c.strip()]
    dest = Path(args.dest)
    (dest / "videos").mkdir(parents=True, exist_ok=True)
    (dest / "truth").mkdir(parents=True, exist_ok=True)
    videos = {i["name"]: i for i in list_items(VIDEOS_FOLDER)}
    anns = {i["name"]: i for i in list_items(ANN_FOLDER)}

    failed = 0
    for n, clip in enumerate(clips, 1):
        v, a = videos.get(clip + ".mp4"), anns.get(clip + ANN_SUFFIX)
        if v is None or a is None:
            print(f"[{n}/{len(clips)}] {clip}: not in the listing, skipped")
            failed += 1
            continue
        vpath = dest / "videos" / (clip + ".mp4")
        apath = dest / "truth" / (clip + ANN_SUFFIX)
        _fetch_file(v, vpath)
        _fetch_file(a, apath)
        fps, width = _video_info(vpath)
        truth = moving_intervals(apath.read_text().splitlines(), fps, width)
        out = {"fps": fps, "width": width, "truth": [[round(s, 3), round(e, 3)] for s, e in truth]}
        (dest / "truth" / (clip + ".json")).write_text(json.dumps(out))
        print(f"[{n}/{len(clips)}] {clip}: {len(truth)} motion interval(s)", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
