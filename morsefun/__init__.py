"""MorseFun: Morse code audio file generator with realistic radio noise."""

from .cell import Cell, Core, Geometry, cell_doppler, draw_cell
from .moon import MoonSpec, draw_moon, moon_doppler
from .morse import MORSE, Character, Element, Timing, parse, timeline, to_code
from .noise import NoiseSpec, build_noise
from .play import PlaybackError, find_player, play
from .render import Config, Render, apply_qrss, render
from .skywave import IonoSpec, draw_iono, iono_carriers
from .synth import ToneSpec, keyed_tone, keying_envelope
from .traffic import Script, Station, compose, draw_station, maidenhead, station_from_call
from .wav import read_wav, wav_bytes, write_wav

__version__ = "0.5.0"

__all__ = [
    "Cell", "Core", "Geometry", "cell_doppler", "draw_cell",
    "MORSE", "Character", "Element", "Timing", "parse", "timeline", "to_code",
    "NoiseSpec", "build_noise", "Config", "Render", "render", "apply_qrss",
    "MoonSpec", "draw_moon", "moon_doppler",
    "IonoSpec", "draw_iono", "iono_carriers",
    "Script", "Station", "compose", "draw_station", "maidenhead", "station_from_call",
    "PlaybackError", "find_player", "play", "wav_bytes",
    "ToneSpec", "keyed_tone", "keying_envelope", "read_wav", "write_wav",
    "__version__",
]
