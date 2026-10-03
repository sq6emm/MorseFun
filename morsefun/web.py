"""A web front end: type a message, hear the rain cell it came off.

A small standard-library HTTP server, no framework and nothing to install
beyond NumPy.  It renders with exactly the same :func:`morsefun.render` call the
command line uses, hands the browser a WAV to play, and sends back the report
and a spectrogram so the Doppler spread of the cell can be seen as well as
heard -- press *another front* a few times and no two of them look alike.

    python -m morsefun.web --host 0.0.0.0 --port 8080

It is happy behind a reverse proxy on a path of its own.  Every URL the page
asks for is relative, routing ignores whatever prefix is left on the request,
and if the proxy says where the page lives -- ``X-Forwarded-Prefix``, or
``--base-path`` / ``MORSEFUN_BASE_PATH`` when it does not -- that goes into a
``<base>`` tag, so even a mount point without a trailing slash works.
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import os
import re
import secrets
import threading
import time
from collections import OrderedDict
from dataclasses import fields as dataclass_fields
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np

from .cell import CHARACTER_VALUES, parse_character
from .cli import DEFAULT_TEXT, OVERRIDES, apply_script, describe
from .morse import Timing, duration, parse, timeline
from .profiles import DEFAULT_PROFILE, DESCRIPTIONS, GROUPS, PROFILES, Draw, resolve
from .propagation import parse_band
from .render import (MODES, QRSS_DIT_S, Config, apply_qrss, mode_name,
                     qrss_label, render, streams)
from .traffic import compose
from .wav import wav_bytes

PAGE = Path(__file__).with_name("page.html")

#: Headers a proxy may use to say what path the page is mounted on.
PREFIX_HEADERS = ("X-Forwarded-Prefix", "X-Script-Name", "X-Ingress-Path")

_AUDIO = re.compile(r"/audio/([A-Za-z0-9_-]{1,64})\.wav$")

#: Nobody needs to tie the box up for longer than this with one message.  QRSS
#: is slow on purpose, so the ceiling is minutes rather than seconds -- a
#: three-second dit spends about half a minute on a single word.  A whole QSO,
#: both sides, rig and weather, runs to several hundred characters.
MAX_CHARACTERS = 1500
MAX_SECONDS = 2400.0
KEEP_RENDERS = 12

#: A QRSS render is minutes of audio, so the store is bounded by weight too.
KEEP_BYTES = 120_000_000

_TYPES = {f.name: str(f.type) for f in dataclass_fields(Config)}


def coerce(field: str, value):
    """Turn one JSON value into whatever that :class:`Config` field wants."""
    if value is None or value == "":
        return None
    if field == "cell_character":
        return parse_character(value)
    hint = _TYPES.get(field, "float")
    if hint.startswith("tuple"):
        parts = (value.replace(",", " ").split() if isinstance(value, str) else list(value))
        if len(parts) != 2:
            raise ValueError(f"{field} wants two numbers")
        return (float(parts[0]), float(parts[1]))
    if hint.startswith("bool"):
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    if hint.startswith("int"):
        return int(float(value))
    if hint.startswith("str"):
        return str(value)
    return float(value)


def config_from_payload(payload: dict) -> tuple[Config, str]:
    """Build a config the way the CLI does: a profile, then the overrides."""
    profile = str(payload.get("profile") or DEFAULT_PROFILE)
    if profile not in PROFILES:
        raise ValueError(f"unknown profile {profile!r}")
    # The seed comes first: the profile's ranges are drawn from it, so pinning
    # the seed brings back the same evening on the band as well as the same cloud.
    seed = coerce("seed", payload.get("seed"))
    seed = int(seed) if seed is not None else secrets.randbelow(2**31)
    cfg = profile_config(profile, streams(seed)["profile"])
    for key, value in payload.items():
        field = OVERRIDES.get(key)
        if field is None or field == "seed":
            continue
        wanted = coerce(field, value)
        if wanted is not None:
            setattr(cfg, field, wanted)
    if str(payload.get("no_noise", "")).lower() in ("1", "true", "yes", "on"):
        cfg.snr_db = None
    if str(payload.get("echo_test", "")).lower() in ("1", "true", "yes", "on"):
        cfg.rician_db = 6.0          # your own keying, with the echo under it
    qrss = coerce("wpm", payload.get("qrss"))
    if qrss:
        apply_qrss(cfg, float(qrss),
                   keep_rise=payload.get("rise_ms") not in (None, ""),
                   keep_rate=payload.get("rate") not in (None, ""))
    cfg.seed = seed
    return cfg, profile


def spectrogram(samples: np.ndarray, sample_rate: int, tone_hz: float,
                dit_s: float = 0.05, columns: int = 260, rows: int = 150) -> dict:
    """A small dB spectrogram around the note, as bytes a canvas can paint.

    This is where the path shows itself: a stratiform cell draws a thin line, a
    storm core a band that wanders and breathes, and a QRSS trace nothing at all
    unless the transform is long enough to see it.  So the window follows the
    keying -- half a dit, bounded -- and the span follows the window, which is
    how a waterfall program is set up by hand anyway.
    """
    want = float(np.clip(dit_s * sample_rate / 2.0, 2048, 65536))
    window = 1 << int(round(np.log2(want)))
    span_hz = float(np.clip(90.0 * sample_rate / window, 20.0, 900.0))
    if samples.size < window * 2:
        return {}
    hop = max((samples.size - window) // columns, 1)
    starts = np.arange(0, samples.size - window, hop)[:columns]
    taper = np.hanning(window)
    freqs = np.fft.rfftfreq(window, 1.0 / sample_rate)
    lo, hi = max(tone_hz - span_hz / 2, 0.0), tone_hz + span_hz / 2
    keep = (freqs >= lo) & (freqs <= hi)
    frame = np.stack([
        np.abs(np.fft.rfft(samples[start:start + window] * taper))[keep]
        for start in starts
    ])
    # Average the bins down to the pixel rows we are going to draw.
    edges = np.linspace(0, frame.shape[1], rows + 1).astype(int)
    tiles = np.stack([frame[:, a:max(b, a + 1)].mean(axis=1)
                      for a, b in zip(edges[:-1], edges[1:])], axis=1)
    db = 20.0 * np.log10(np.maximum(tiles, 1e-12))
    db -= db.max()
    shade = np.clip((db + 60.0) / 60.0, 0.0, 1.0)
    pixels = (shade * 255).astype(np.uint8)
    return {
        "columns": int(pixels.shape[0]),
        "rows": int(pixels.shape[1]),
        "low_hz": float(freqs[keep][0]),
        "high_hz": float(freqs[keep][-1]),
        "seconds": float(samples.size / sample_rate),
        "bin_hz": float(sample_rate / window),
        "data": base64.b64encode(pixels.tobytes()).decode("ascii"),
    }


class Renders:
    """The last few renders, so the browser can fetch the audio it was promised."""

    def __init__(self, keep: int = KEEP_RENDERS):
        self.keep = keep
        self._items: OrderedDict[str, tuple[bytes, float]] = OrderedDict()
        self._lock = threading.Lock()

    def put(self, payload: bytes) -> str:
        token = secrets.token_urlsafe(9)
        with self._lock:
            self._items[token] = (payload, time.time())
            while (len(self._items) > self.keep
                   or sum(len(item[0]) for item in self._items.values()) > KEEP_BYTES):
                if len(self._items) <= 1:
                    break
                self._items.popitem(last=False)
        return token

    def get(self, token: str) -> bytes | None:
        with self._lock:
            found = self._items.get(token)
        return found[0] if found else None


def profile_config(name: str, rng: np.random.Generator | None = None) -> Config:
    """The config a profile amounts to, with nothing else on top of it.

    With an ``rng`` the profile's ranges are drawn; without one they sit at the
    middle, which is what a form shows as the placeholder.
    """
    cfg = Config()
    for field, value in resolve(name, rng).items():
        setattr(cfg, field, value)
    return cfg


def profile_card(name: str) -> dict:
    """One profile as the page shows it: what band, what path, how fast.

    ``defaults`` is every control's effective value under this profile, so the
    page can put them in as placeholders and send nothing.  That matters: a form
    that always sends its own ``wpm`` would key a QRSS profile at 23 words a
    minute, which is how the whole point of it gets lost.
    """
    cfg = profile_config(name)
    dit = 1.2 / max(cfg.wpm, 1e-6)
    # A profile that names no band is about band conditions, not about a path.
    pinned_band = "band" in PROFILES[name]
    defaults: dict[str, object] = {}
    for key, field in OVERRIDES.items():
        drawn = PROFILES[name].get(field)
        if isinstance(drawn, Draw):
            defaults[key] = str(drawn)        # "6–14": drawn afresh every render
            continue
        value = getattr(cfg, field, None)
        if value is not None and not isinstance(value, (tuple, list)):
            defaults[key] = value
    if dit >= QRSS_DIT_S:
        defaults["qrss"] = round(dit, 3)
    wpm = PROFILES[name].get("wpm")
    if dit >= QRSS_DIT_S:
        speed = qrss_label(dit)
    elif isinstance(wpm, Draw):
        speed = f"{wpm} wpm"
    else:
        speed = f"{cfg.wpm:g} wpm"
    return {
        "name": name,
        "about": DESCRIPTIONS.get(name, ""),
        "band": parse_band(cfg.band).label if pinned_band else "any band",
        "mode": mode_name(cfg.scatter).replace("none", "direct"),
        "speed": speed,
        "defaults": defaults,
    }


def options() -> dict:
    """Everything the page needs to build its controls."""
    return {
        "groups": [{"name": group, "about": detail["about"],
                    "profiles": [profile_card(name) for name in detail["profiles"]]}
                   for group, detail in GROUPS.items()],
        "default_profile": DEFAULT_PROFILE,
        "characters": ["auto", *CHARACTER_VALUES],
        "scatter": [name for name in MODES],
        "qrm_style": ["ragchew", "contest", "mixed"],
        "qrss": [3, 10, 30, 60, 120],
        "generate": ["qso", "beacon"],
    }


def endpoint(path: str) -> tuple[str, str]:
    """What was asked for, whatever prefix a reverse proxy left on the way in."""
    clean = path.split("?")[0].split("#")[0]
    if clean.endswith("/api/options"):
        return "options", ""
    if clean.endswith("/api/render"):
        return "render", ""
    found = _AUDIO.search(clean)
    if found:
        return "audio", found.group(1)
    return "page", ""


def clean_prefix(value: str | None) -> str:
    """A mount path we are willing to write into the page, or nothing."""
    if not value:
        return ""
    prefix = "/" + str(value).strip().strip("/")
    if prefix == "/" or not re.fullmatch(r"[A-Za-z0-9/_.~-]+", prefix):
        return ""
    return prefix


class Handler(BaseHTTPRequestHandler):
    server_version = "morsefun"
    renders: Renders
    base_path: str = ""

    def mount(self) -> str:
        """Where the browser thinks this page lives."""
        if self.base_path:
            return self.base_path
        for header in PREFIX_HEADERS:
            prefix = clean_prefix(self.headers.get(header))
            if prefix:
                return prefix
        return ""

    def page(self) -> bytes:
        """The page, told where it is if anybody knows."""
        text = PAGE.read_text(encoding="utf-8")
        prefix = self.mount()
        if prefix:
            text = text.replace(
                "<head>", f'<head>\n<base href="{html.escape(prefix, quote=True)}/">', 1)
        return text.encode("utf-8")

    def log_message(self, fmt: str, *args) -> None:       # quieter than the default
        print(f"{self.address_string()} {fmt % args}", flush=True)

    def _send(self, code: int, body: bytes, kind: str, cache: bool = False) -> None:
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "public, max-age=3600" if cache else "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code: int, payload: dict) -> None:
        self._send(code, json.dumps(payload, default=str).encode("utf-8"),
                   "application/json; charset=utf-8")

    def do_GET(self) -> None:                             # noqa: N802
        kind, token = endpoint(self.path)
        if kind == "options":
            self._json(200, options())
        elif kind == "audio":
            audio = self.renders.get(token)
            if audio is None:
                self._json(404, {"error": "that render has scrolled off"})
            else:
                self._send(200, audio, "audio/wav", cache=True)
        elif kind == "render":
            self._json(405, {"error": "post to this one"})
        else:
            self._send(200, self.page(), "text/html; charset=utf-8")

    def do_HEAD(self) -> None:                            # noqa: N802
        self.do_GET()

    def do_POST(self) -> None:                            # noqa: N802
        if endpoint(self.path)[0] != "render":
            self._json(404, {"error": "no such thing here"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length > 64_000:
            self._json(413, {"error": "that is a lot of Morse"})
            return
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
            body = self.render(payload if isinstance(payload, dict) else {})
        except ValueError as err:
            self._json(400, {"error": str(err)})
            return
        self._json(200, body)

    def render(self, payload: dict) -> dict:
        text = str(payload.get("text") or DEFAULT_TEXT).strip()
        if len(text) > MAX_CHARACTERS:
            raise ValueError(f"keep it under {MAX_CHARACTERS} characters")
        cfg, profile = config_from_payload(payload)
        script = None
        kind = str(payload.get("generate") or "").strip().lower()
        if kind:
            # The message is drawn from the same seed as the band, so pinning
            # the seed brings back the QSO as well as the evening.
            band_known = "band" in PROFILES[profile] or payload.get("band") not in (None, "")
            script = compose(kind, cfg, streams(cfg.seed)["traffic"], band_known=band_known,
                             my_call=payload.get("my_call"), my_loc=payload.get("my_loc"))
            text = script.text
            apply_script(cfg, script, keep_wpm=payload.get("wpm") not in (None, "")
                         or payload.get("qrss") not in (None, ""))
        words, _ = parse(text)
        if not any(words):
            raise ValueError("nothing in there has a Morse equivalent")
        keyed = duration(timeline(words, Timing(cfg.wpm, cfg.effective_wpm)))
        if keyed > MAX_SECONDS:
            raise ValueError(f"that would run {keyed:.0f} s; keep it under "
                             f"{MAX_SECONDS:.0f} s or send it faster")
        started = time.time()
        result = render(text, cfg)
        if script:
            result.meta["script"] = {**script.detail, "note": script.note}
        token = self.renders.put(wav_bytes(result.samples, result.sample_rate))
        return {
            # Relative, so it still points here under a proxy's path.
            "audio": f"audio/{token}.wav",
            "text": text,
            "two_stations": bool(cfg.two_stations),
            "script": script.note if script else "",
            "report": describe(result, "", profile).strip("\n"),
            "spectrogram": spectrogram(result.samples, result.sample_rate, cfg.freq,
                                       float(result.meta["dit_ms"]) / 1000.0),
            "seed": cfg.seed,
            "profile": profile,
            "took_ms": round((time.time() - started) * 1000),
            "meta": {k: v for k, v in result.meta.items() if k != "config"},
        }


def serve(host: str = "0.0.0.0", port: int = 8080, base_path: str = "") -> None:
    handler = type("MorsefunHandler", (Handler,),
                   {"renders": Renders(), "base_path": clean_prefix(base_path)})
    server = ThreadingHTTPServer((host, port), handler)
    where = f"http://{host}:{port}{handler.base_path}"
    print(f"morsefun on {where}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("stopping.", flush=True)
    finally:
        server.server_close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="morsefun.web", description="serve the Morse generator as a web page")
    parser.add_argument("--host", default="0.0.0.0", help="address to bind (default: all)")
    parser.add_argument("--port", type=int, default=8080, help="port (default: 8080)")
    parser.add_argument("--base-path", default=os.environ.get("MORSEFUN_BASE_PATH", ""),
                        metavar="PATH",
                        help="the path a reverse proxy serves this under, e.g. /morsefun; "
                             "only needed if the proxy sends no X-Forwarded-Prefix")
    args = parser.parse_args(argv)
    serve(args.host, args.port, args.base_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
