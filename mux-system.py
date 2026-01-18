#!/usr/bin/env python3
"""
MuxTools Automation Script for Non Non Biyori Vacation.

Automates the process of muxing anime episodes using MuxTools.
Optimized for efficiency, readability, and correct resource resolution.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

try:
    from muxtools import (
        AudioFile,
        Chapters,
        GlobSearch,
        Premux,
        Setup,
        SubFile,
        TmdbConfig,
        log,
        mux,
    )
except ImportError as e:
    sys.exit(f"Error: {e}. Run 'uv sync' to install dependencies.")

__all__ = ["RunMode", "ShowConfig", "mux_episode", "main"]


class RunMode(Enum):
    NORMAL = "normal"
    DRYRUN = "dryrun"


@dataclass(frozen=True, slots=True)
class ShowConfig:
    """Immutable configuration for the anime show."""

    name: str
    premux_dir: Path
    sub_dir: Path
    audio_dir: Path
    tmdb_id: int = 0
    titles: tuple[str, ...] = ()

    @classmethod
    def from_defaults(cls) -> ShowConfig:
        """Create configuration relative to the script location."""
        # Resolution relative to script location (root)
        base = Path(__file__).resolve().parent

        return cls(
            name="Non Non Biyori Vacation",
            premux_dir=base / "premux",
            sub_dir=base / "subtitle",
            audio_dir=base / "audio",
            tmdb_id=494471,
            titles=("Liburan",),
        )


CONFIG = ShowConfig.from_defaults()


@dataclass(slots=True)
class MuxResult:
    episode: str | int
    success: bool
    error: str | None = None


def _get_episode_str(episode: str | int) -> str:
    """Convert episode identifier to standard string format."""
    if isinstance(episode, int):
        return f"{episode:02d}"
    return str(episode)


def _find_video(ep_str: str, config: ShowConfig) -> Path:
    """Find the video file for the given episode string."""
    search = GlobSearch(
        "*.mkv",
        allow_multiple=True,
        recursive=True,
        dir=str(config.premux_dir),
    )

    for p in search.paths:
        name = Path(p).name

        # Standard episode match: " - 01 ", "E01)", or "S01E01"
        if f" - {ep_str} " in name or f"E{ep_str})" in name or f"S01E{ep_str}" in name:
            return Path(p)

    # Fallback for movies (usually treated as ep 01)
    if (ep_str == "01" or ep_str.lower() == "movie") and search.paths:
        # If only one video file, assume it's the movie
        if len(search.paths) == 1:
            return Path(search.paths[0])

        # Or if filename contains "Vacation" (specific to this show)
        for p in search.paths:
            if "Vacation" in Path(p).name:
                return Path(p)

    raise FileNotFoundError(f"Video file not found for episode {ep_str}")


def _find_audio(ep_str: str, config: ShowConfig) -> Path:
    """Find the audio file for the given episode string."""
    # Map "Movie" to "01" for audio search if needed
    search_str = ep_str
    if ep_str.lower() == "movie":
        search_str = "01"

    search = GlobSearch(
        f"*Audio*{search_str}*.flac",
        allow_multiple=True,
        recursive=True,
        dir=str(config.audio_dir),
    )

    if not search.paths:
        # specific fallback for this show/audio naming
        if ep_str.lower() == "movie":
            search = GlobSearch(
                "*Audio*01*.flac",
                allow_multiple=True,
                recursive=True,
                dir=str(config.audio_dir),
            )

        if not search.paths:
            raise FileNotFoundError(f"Audio file not found for episode {ep_str}")

    return Path(search.paths[0])


def _get_subtitle_file(path: Path, delay: int = 0) -> SubFile:
    """Prepare a subtitle file."""
    if not path.exists():
        raise FileNotFoundError(f"Subtitle file not found at {path}")

    sub = SubFile(str(path), container_delay=delay)
    # Apply cleaning
    sub.merge(r"common/warning.ass").clean_styles().clean_garbage()
    return sub


def mux_episode(
    episode: str | int,
    out_dir: Path,
    version: int = 1,
    flag: str = "testing",
    mode: RunMode = RunMode.NORMAL,
    config: ShowConfig | None = None,
) -> MuxResult:
    config = config or CONFIG
    ep_str = _get_episode_str(episode)
    version_str = "" if version == 1 else f" v{version}"

    # Title handling
    title = ""
    if (
        isinstance(episode, int)
        and config.titles
        and 1 <= episode <= len(config.titles)
    ):
        title = f" | {config.titles[episode - 1]}"

    setup = Setup(
        ep_str,
        None,
        show_name=config.name,
        out_name=f"[{flag}] $show$ - $ep${version_str} (BDRip 1920x1080 HEVC FLAC) [$crc32$]",
        mkv_title_naming=f"$show$ - $ep${version_str}{title}",
        out_dir=str(out_dir),
        clean_work_dirs=False,
    )

    try:
        # Locating Resources
        video_file = _find_video(ep_str, config)
        audio_file = _find_audio(ep_str, config)

        caramel_path = config.sub_dir / "Caramel.ass"
        melody_path = config.sub_dir / "Melody.ass"

        log.info("Resources found:")
        log.info(f"  Video:   {video_file}")
        log.info(f"  Audio:   {audio_file}")
        log.info(f"  Sub(Caramel): {caramel_path}")
        log.info(f"  Sub(Melody):  {melody_path}")

        if mode == RunMode.DRYRUN:
            log.info(f"[Dry Run] Would mux episode {ep_str} to {out_dir}")
            return MuxResult(episode, True)

        setup.set_default_sub_timesource(str(video_file))

        # Audio
        audio = AudioFile(str(audio_file))

        # Prepare Subtitles
        caramel_sub = _get_subtitle_file(caramel_path, delay=1000)
        melody_sub = _get_subtitle_file(melody_path)

        # Chapters & Fonts
        chapters = Chapters(r"./subtitle/chapter.xml")

        # Collect fonts from both subtitle tracks
        fonts_caramel = caramel_sub.collect_fonts(
            use_system_fonts=False, additional_fonts=r"./subtitle/font-caramel"
        )

        fonts_melody = melody_sub.collect_fonts(
            use_system_fonts=False, additional_fonts=r"./subtitle/font-melody"
        )

        # Muxing
        premux = Premux(
            str(video_file),
            audio=None,
            subtitles=None,
            keep_attachments=False,
            mkvmerge_args=["--no-global-tags", "--no-chapters"],
        )

        mux_args = [
            premux,
            audio.to_track(lang="ja", default=True),
            caramel_sub.to_track("Caramel Fansub", "id", default=True),
            melody_sub.to_track("Melody Fansub", "id", default=False),
            *fonts_caramel,
            *fonts_melody,
        ]

        if chapters:
            mux_args.append(chapters)

        outfile = mux(
            *mux_args,
            tmdb=TmdbConfig(config.tmdb_id, write_cover=True, movie=True),
        )
        log.info(f"Muxed: {outfile.name}")
        return MuxResult(episode, True)

    except Exception as e:
        log.error(f"Failed to mux {ep_str}: {e}")
        return MuxResult(episode, False, str(e))


def parse_episodes(arg: str) -> list[str | int]:
    """Parse episode argument into a list of episode identifiers."""
    if arg.lower() == "all":
        # Integer episodes
        eps = {
            int(p.stem[:2])
            for p in CONFIG.sub_dir.glob("*.ass")
            if p.stem[:2].isdigit()
        }
        return sorted(list(eps), key=lambda x: str(x))

    eps = []
    for part in arg.split(","):
        part = part.strip()
        if "-" in part and part.replace("-", "").isdigit():
            start, end = map(int, part.split("-"))
            eps.extend(range(start, end + 1))
        elif part.isdigit():
            eps.append(int(part))
        else:
            eps.append(part)

    # Deduplicate while preserving order
    return list(dict.fromkeys(eps))


def main() -> int:
    parser = argparse.ArgumentParser(description="Optimized Mux System")
    parser.add_argument("episodes", help="Episodes to mux (e.g., 1, 1-5, all)")
    parser.add_argument(
        "outdir",
        nargs="?",
        default="muxed",
        help="Output directory",
    )
    parser.add_argument("-f", "--flag", default="pololer", help="Release group/flag")
    parser.add_argument("-d", "--dry-run", action="store_true", help="Dry run")
    parser.add_argument("-v", "--version", type=int, default=1, help="Version number")

    args = parser.parse_args()

    try:
        episodes = parse_episodes(args.episodes)
    except ValueError:
        log.error("Invalid episode specification")
        return 1

    if not episodes:
        log.error("No episodes found")
        return 1

    out_dir = Path(args.outdir).resolve()
    if not args.dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)

    results = [
        mux_episode(
            ep,
            out_dir,
            flag=args.flag,
            mode=RunMode.DRYRUN if args.dry_run else RunMode.NORMAL,
            version=args.version,
        )
        for ep in episodes
    ]

    success_count = sum(1 for r in results if r.success)
    log.info(f"Processed {success_count}/{len(results)} episodes successfully.")

    return 0 if success_count == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
