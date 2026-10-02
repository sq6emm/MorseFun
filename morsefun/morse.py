"""Text to Morse code and to a key-up/key-down timeline.

Timing follows the PARIS standard: one dit is 1200 ms / WPM, a dah is three
dits, elements inside a character are separated by one dit, characters by
three and words by seven.  Lowering the effective speed below the keying
speed stretches only the character and word gaps (Farnsworth spacing), using
the ARRL formula, so each character still arrives at full speed.
"""

from __future__ import annotations

from dataclasses import dataclass

MORSE: dict[str, str] = {
    "a": ".-", "b": "-...", "c": "-.-.", "d": "-..", "e": ".", "f": "..-.",
    "g": "--.", "h": "....", "i": "..", "j": ".---", "k": "-.-", "l": ".-..",
    "m": "--", "n": "-.", "o": "---", "p": ".--.", "q": "--.-", "r": ".-.",
    "s": "...", "t": "-", "u": "..-", "v": "...-", "w": ".--", "x": "-..-",
    "y": "-.--", "z": "--..",
    "0": "-----", "1": ".----", "2": "..---", "3": "...--", "4": "....-",
    "5": ".....", "6": "-....", "7": "--...", "8": "---..", "9": "----.",
    ".": ".-.-.-", ",": "--..--", "?": "..--..", "'": ".----.", "!": "-.-.--",
    "/": "-..-.", "(": "-.--.", ")": "-.--.-", "&": ".-...", ":": "---...",
    ";": "-.-.-.", "=": "-...-", "+": ".-.-.", "-": "-....-", "_": "..--.-",
    '"': ".-..-.", "$": "...-..-", "@": ".--.-.",
}

#: Prosigns are written in angle brackets and keyed as one run-together
#: character: <AR> end of message, <SK> end of contact, <BT> break, and so on.
PROSIGN_HINT = "<AR> <SK> <BT> <AS> <KN> <VE>"


@dataclass(frozen=True)
class Character:
    """One keyed character: ``label`` as written, ``code`` in dits and dahs."""

    label: str
    code: str


@dataclass(frozen=True)
class Element:
    """One stretch of key-down or key-up time."""

    on: bool
    seconds: float
    kind: str  # dit | dah | element-gap | char-gap | word-gap


@dataclass(frozen=True)
class Timing:
    """Dit length and gap lengths for a keying speed."""

    wpm: float
    effective_wpm: float | None = None

    def __post_init__(self) -> None:
        if self.wpm <= 0:
            raise ValueError("wpm must be positive")
        if self.effective_wpm is not None and self.effective_wpm <= 0:
            raise ValueError("effective_wpm must be positive")

    @property
    def effective(self) -> float:
        """Effective speed, never faster than the keying speed."""
        if self.effective_wpm is None:
            return self.wpm
        return min(self.effective_wpm, self.wpm)

    @property
    def unit(self) -> float:
        """Dit length in seconds."""
        return 1.2 / self.wpm

    @property
    def _farnsworth_delay(self) -> float:
        """Total added delay per PARIS word, in seconds (ARRL formula)."""
        c, s = self.wpm, self.effective
        return (60.0 * c - 37.2 * s) / (c * s)

    @property
    def char_gap(self) -> float:
        """Gap between characters; 3 dits when no Farnsworth spacing."""
        return 3.0 * self._farnsworth_delay / 19.0

    @property
    def word_gap(self) -> float:
        """Gap between words; 7 dits when no Farnsworth spacing."""
        return 7.0 * self._farnsworth_delay / 19.0

    @property
    def is_farnsworth(self) -> bool:
        return self.effective < self.wpm


def parse(text: str) -> tuple[list[list[Character]], list[str]]:
    """Split ``text`` into words of characters, plus the characters dropped.

    Angle brackets mark a prosign: ``<AR>`` is keyed as A and R with no gap
    between them.  Anything with no Morse equivalent is reported instead of
    being keyed.
    """
    words: list[list[Character]] = []
    unknown: list[str] = []

    def drop(ch: str) -> None:
        if ch.strip() and ch not in unknown:
            unknown.append(ch)

    for raw in text.lower().split():
        chars: list[Character] = []
        i = 0
        while i < len(raw):
            if raw[i] == "<":
                close = raw.find(">", i)
                if close > i + 1:
                    inner = raw[i + 1 : close]
                    code = ""
                    for ch in inner:
                        part = MORSE.get(ch)
                        if part is None:
                            drop(ch)
                            code = ""
                            break
                        code += part
                    if code:
                        chars.append(Character(f"<{inner.upper()}>", code))
                    i = close + 1
                    continue
            code = MORSE.get(raw[i])
            if code:
                chars.append(Character(raw[i].upper(), code))
            else:
                drop(raw[i])
            i += 1
        if chars:
            words.append(chars)
    return words, unknown


def timeline(words: list[list[Character]], timing: Timing) -> list[Element]:
    """Expand parsed words into alternating key-down and key-up elements."""
    unit = timing.unit
    out: list[Element] = []
    for w, chars in enumerate(words):
        for c, char in enumerate(chars):
            if c:
                out.append(Element(False, timing.char_gap, "char-gap"))
            for s, symbol in enumerate(char.code):
                if s:
                    out.append(Element(False, unit, "element-gap"))
                if symbol == "-":
                    out.append(Element(True, 3 * unit, "dah"))
                else:
                    out.append(Element(True, unit, "dit"))
        if w < len(words) - 1:
            out.append(Element(False, timing.word_gap, "word-gap"))
    return out


def duration(elements: list[Element]) -> float:
    """Total keyed length in seconds, without any leading or trailing pad."""
    return sum(e.seconds for e in elements)


def to_code(words: list[list[Character]]) -> str:
    """Render parsed words as dits and dahs, words split by ``/``."""
    return "  /  ".join(" ".join(c.code for c in w) for w in words)
