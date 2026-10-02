"""Play a render straight out of the speakers, with no file in between.

There is no audio library here on purpose: the samples are handed to whatever
command line player the machine already has, over a pipe.  ALSA and PulseAudio
players take raw PCM on stdin, the rest take a whole WAV file.
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .wav import to_pcm16, wav_bytes


class PlaybackError(RuntimeError):
    """No usable player, or the player itself failed."""


@dataclass(frozen=True)
class Player:
    """A command that can be handed mono audio on stdin."""

    name: str
    template: tuple[str, ...]
    raw: bool = False        # headerless PCM instead of a WAV container
    via_file: bool = False   # cannot read stdin at all

    def argv(self, sample_rate: int) -> list[str]:
        return [part.format(rate=sample_rate) for part in self.template]


#: Tried in this order; the first one on PATH wins.
PLAYERS: tuple[Player, ...] = (
    Player("aplay", ("aplay", "-q", "-")),
    Player("pw-play", ("pw-play", "--format=s16", "--rate={rate}", "--channels=1", "-"), raw=True),
    Player("paplay", ("paplay", "--raw", "--format=s16le", "--rate={rate}", "--channels=1", "-"), raw=True),
    Player("ffplay", ("ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", "-")),
    Player("sox", ("play", "-q", "-t", "wav", "-")),
    Player("afplay", ("afplay",), via_file=True),   # macOS, needs a real file
)


def find_player(command: str | None = None) -> Player:
    """Pick a player, or raise with the list of the ones looked for.

    ``command`` overrides the search: give the full command line, ending in the
    argument that means standard input, for example ``"ffplay -nodisp -autoexit -"``.
    """
    if command:
        parts = tuple(shlex.split(command))
        if not parts:
            raise PlaybackError("empty --player command")
        if shutil.which(parts[0]) is None and not Path(parts[0]).exists():
            raise PlaybackError(f"player not found: {parts[0]}")
        return Player(parts[0], parts)
    for player in PLAYERS:
        if shutil.which(player.template[0]):
            return player
    looked = ", ".join(p.template[0] for p in PLAYERS)
    raise PlaybackError(
        "no audio player found. Install one of: " + looked + "\n"
        "        or write a file instead: -o cq.wav\n"
        "        in a container, playback needs the sound device: "
        "docker run --rm --device /dev/snd ..."
    )


def play(
    samples: np.ndarray,
    sample_rate: int,
    command: str | None = None,
    repeat: int = 1,
    gap: float = 1.5,
) -> Player:
    """Send ``samples`` to the speakers ``repeat`` times.  Returns the player used."""
    player = find_player(command)
    payload = to_pcm16(samples) if player.raw else wav_bytes(samples, sample_rate)

    for turn in range(max(1, repeat)):
        if turn:
            time.sleep(max(0.0, gap))
        try:
            if player.via_file:
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
                    tmp.write(payload)
                    tmp.flush()
                    done = subprocess.run([*player.argv(sample_rate), tmp.name])
            else:
                done = subprocess.run(player.argv(sample_rate), input=payload)
        except FileNotFoundError as err:  # pragma: no cover - checked in find_player
            raise PlaybackError(f"could not run {player.name}: {err}") from err
        except KeyboardInterrupt:
            raise
        if done.returncode != 0:
            raise PlaybackError(
                f"{player.name} exited with status {done.returncode}. "
                "Is an output device available?"
            )
    return player


def describe_players() -> str:
    """One line per known player, marking the ones present on this machine."""
    lines = []
    for player in PLAYERS:
        found = shutil.which(player.template[0])
        kind = "raw PCM" if player.raw else ("temp file" if player.via_file else "WAV on stdin")
        lines.append(f"{player.name:<8} {kind:<13} {found or '-'}")
    return "\n".join(lines)


if __name__ == "__main__":  # pragma: no cover
    print(describe_players(), file=sys.stdout)
