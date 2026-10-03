"""Checks on the parts that are easy to get quietly wrong: timing and levels."""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np

from morsefun import Config, Timing, parse, render, timeline, to_code
from morsefun.cli import main
from morsefun.play import describe_players
from morsefun.profiles import DESCRIPTIONS, GROUPS, PROFILES, Draw, resolve
from morsefun.dsp import agc, rms
from morsefun.morse import duration
from morsefun.wav import read_wav

PARIS = "paris"


def word_time(wpm: float, effective: float | None = None) -> float:
    """Keyed time for one PARIS word including the following word gap."""
    timing = Timing(wpm, effective)
    words, _ = parse(PARIS)
    return duration(timeline(words, timing)) + timing.word_gap


class TestTiming(unittest.TestCase):
    def test_paris_is_fifty_units(self):
        for wpm in (5, 13, 23, 40):
            self.assertAlmostEqual(word_time(wpm), 60.0 / wpm, places=9)

    def test_dit_length(self):
        self.assertAlmostEqual(Timing(23).unit * 1000, 52.17391, places=4)

    def test_standard_gaps(self):
        timing = Timing(23)
        self.assertAlmostEqual(timing.char_gap, 3 * timing.unit, places=12)
        self.assertAlmostEqual(timing.word_gap, 7 * timing.unit, places=12)
        self.assertFalse(timing.is_farnsworth)

    def test_farnsworth_hits_the_effective_speed(self):
        # Characters stay at 23 wpm, the whole word takes 60/13 s.
        self.assertAlmostEqual(word_time(23, 13), 60.0 / 13.0, places=9)
        timing = Timing(23, 13)
        self.assertAlmostEqual(timing.unit, 1.2 / 23, places=12)
        self.assertGreater(timing.char_gap, 3 * timing.unit)
        self.assertTrue(timing.is_farnsworth)

    def test_effective_never_exceeds_keying_speed(self):
        self.assertEqual(Timing(20, 30).effective, 20)


class TestMorse(unittest.TestCase):
    def test_known_characters(self):
        words, unknown = parse("cq de sq6emm")
        self.assertEqual(unknown, [])
        self.assertEqual(to_code(words), "-.-. --.-  /  -.. .  /  ... --.- -.... . -- --")

    def test_prosign_is_one_character(self):
        words, _ = parse("<ar>")
        self.assertEqual(len(words[0]), 1)
        self.assertEqual(words[0][0].code, ".-.-.")
        self.assertEqual(words[0][0].label, "<AR>")
        self.assertEqual(parse("<sk>")[0][0][0].code, "...-.-")

    def test_unknown_characters_are_reported_not_keyed(self):
        words, unknown = parse("ok é")
        self.assertEqual(unknown, ["é"])
        self.assertEqual(len(words), 1)


class TestRender(unittest.TestCase):
    def test_clean_render_is_silent_between_elements(self):
        cfg = Config(snr_db=None, qsb_db=0, drift_hz=0, pad=0.2, seed=1)
        out = render("e e", cfg)
        self.assertAlmostEqual(float(np.max(np.abs(out.samples))), cfg.peak, places=6)
        self.assertLess(rms(out.samples[: int(0.15 * out.sample_rate)]), 1e-9)

    def test_duration_matches_the_timing(self):
        cfg = Config(wpm=23, pad=0.5, seed=7)
        out = render("paris", cfg)
        expected = 60.0 / 23 - Timing(23).word_gap + 2 * cfg.pad
        self.assertAlmostEqual(out.duration, expected, places=2)

    def test_snr_lands_where_asked(self):
        cfg = Config(snr_db=10.0, crash_rate=0, qrm_count=0, birdie_count=0,
                     qsb_db=0, drift_hz=0, limit=False, seed=42)
        for target in (3.0, 10.0, 20.0):
            out = render("cq cq de sq6emm k", replace(cfg, snr_db=target))
            measured = out.meta["measured_snr_db"]
            self.assertIsNotNone(measured)
            self.assertAlmostEqual(measured, target, delta=1.5)

    def test_noise_fills_the_gaps(self):
        quiet = render("cq test", Config(snr_db=None, seed=3))
        noisy = render("cq test", Config(snr_db=6.0, seed=3))
        head = int(0.4 * noisy.sample_rate)
        self.assertLess(rms(quiet.samples[:head]), 1e-9)
        self.assertGreater(rms(noisy.samples[:head]), 1e-3)

    def test_noise_stays_inside_the_filter(self):
        cfg = Config(snr_db=6.0, bandwidth=500.0, freq=600.0, crash_rate=2.0,
                     qrm_count=2, birdie_count=1, limit=False, seed=11)
        out = render("cq cq de sq6emm k", cfg)
        spectrum = np.abs(np.fft.rfft(out.samples))
        freqs = np.fft.rfftfreq(out.samples.size, 1.0 / out.sample_rate)
        inside = spectrum[(freqs > 400) & (freqs < 800)].mean()
        outside = spectrum[(freqs > 2500) & (freqs < 5000)].mean()
        self.assertGreater(inside / max(outside, 1e-12), 100.0)

    def test_seed_is_reproducible(self):
        a = render("cq de sq6emm", Config(seed=99))
        b = render("cq de sq6emm", Config(seed=99))
        c = render("cq de sq6emm", Config(seed=100))
        np.testing.assert_allclose(a.samples, b.samples)
        self.assertFalse(np.allclose(a.samples, c.samples))

    def test_band_report_names_the_other_stations(self):
        out = render("cq de sq6emm", Config(qrm_count=2, seed=5))
        self.assertEqual(len(out.meta["noise"]["qrm"]), 2)

    def test_a_contest_is_a_wall_of_stations_that_keep_sending(self):
        out = render("tu 5nn 15", Config(scatter="iono", band="7.02M", wpm=30,
                                          qrm_count=8, qrm_style="contest",
                                          qrm_wpm=(26.0, 40.0), snr_db=10.0, seed=4))
        notes = out.meta["noise"]["qrm"]
        self.assertEqual(len(notes), 8)
        texts = [note.split('"')[1] for note in notes]
        self.assertTrue(any("5nn" in t or "test" in t or "599" in t for t in texts))
        self.assertFalse(any("fb om" in t or "hw?" in t for t in texts))
        # A pile-up sits close to the frequency: somebody within 50 Hz of us.
        offsets = [abs(float(note.split(" at ")[1].split(" Hz")[0])) for note in notes]
        self.assertLess(min(offsets), 50.0)
        # And the band is busy right to the end of the render, not just at the start.
        head = int(2.0 * out.sample_rate)
        tail = out.samples[-head:]
        self.assertGreater(rms(tail), 0.3 * rms(out.samples[head:2 * head]))

    def test_empty_text_renders_nothing_keyed(self):
        out = render("   ", Config(seed=1))
        self.assertEqual(out.meta["characters"], 0)


class TestWav(unittest.TestCase):
    def test_round_trip(self):
        out = render("cq de sq6emm", Config(sample_rate=22050, seed=2))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.wav"
            from morsefun.wav import write_wav

            write_wav(path, out.samples, out.sample_rate)
            data, sr = read_wav(path)
            self.assertEqual(sr, out.sample_rate)
            self.assertEqual(data.size, out.samples.size)
            np.testing.assert_allclose(data, out.samples, atol=2e-4)


class TestPlayback(unittest.TestCase):
    """The player is faked with a shell script, so nothing has to make a sound."""

    def fake_player(self, tmp: str, target: Path, append: bool = False) -> str:
        script = Path(tmp) / "fake-player"
        script.write_text(f'#!/bin/sh\ncat {">>" if append else ">"} "{target}"\n')
        script.chmod(0o755)
        return str(script)

    def test_playing_is_the_default_and_writes_no_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            captured = Path(tmp) / "captured.wav"
            code = main(["cq de sq6emm", "--profile", "clean", "--seed", "1", "-q",
                         "--player", self.fake_player(tmp, captured)])
            self.assertEqual(code, 0)
            data, sr = read_wav(captured)
            self.assertEqual(sr, 44100)
            expected = render("cq de sq6emm", Config(snr_db=None, crash_rate=0, qrm_count=0,
                                                    qsb_db=0, drift_hz=0, birdie_count=0,
                                                    hum_depth=0, limit=False, seed=1))
            np.testing.assert_allclose(data, expected.samples, atol=2e-4)
            self.assertEqual(list(Path(tmp).glob("*.wav")), [captured])

    def test_repeat_plays_it_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            captured = Path(tmp) / "captured.raw"
            player = self.fake_player(tmp, captured, append=True)
            main(["e", "--profile", "clean", "--seed", "1", "-q", "--player", player])
            once = captured.stat().st_size
            captured.unlink()
            main(["e", "--profile", "clean", "--seed", "1", "-q", "--player", player,
                  "--repeat", "3", "--gap", "0"])
            self.assertEqual(captured.stat().st_size, 3 * once)

    def test_writing_a_file_does_not_play(self):
        with tempfile.TemporaryDirectory() as tmp:
            captured = Path(tmp) / "captured.wav"
            out = Path(tmp) / "cq.wav"
            player = self.fake_player(tmp, captured)
            main(["cq de sq6emm", "-o", str(out), "--seed", "1", "-q", "--player", player])
            self.assertTrue(out.exists())
            self.assertFalse(captured.exists())
            main(["cq de sq6emm", "-o", str(out), "--seed", "1", "-q", "--player", player, "--play"])
            self.assertTrue(captured.exists())

    def test_missing_player_is_an_error_not_a_crash(self):
        self.assertEqual(main(["e", "--player", "/nonexistent/player", "-q"]), 2)

    def test_player_search_lists_what_it_looks_for(self):
        self.assertIn("aplay", describe_players())
        self.assertEqual(main(["--list-players"]), 0)


class TestCli(unittest.TestCase):
    def test_single_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cq.wav"
            code = main(["cq cq de sq6emm sq6emm k", "--wpm", "23", "--tone", "600",
                         "-o", str(path), "--seed", "1", "-q"])
            self.assertEqual(code, 0)
            data, sr = read_wav(path)
            self.assertEqual(sr, 44100)
            self.assertGreater(data.size / sr, 10.0)

    def test_batch_writes_one_file_per_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            listing = Path(tmp) / "msgs.txt"
            listing.write_text("# practice\ncq cq de sq6emm k\ntu 73 <sk>\n\n")
            code = main(["--batch", str(listing), "--outdir", tmp, "--seed", "4", "-q"])
            self.assertEqual(code, 0)
            files = sorted(p.name for p in Path(tmp).glob("*.wav"))
            self.assertEqual(files, ["001-cq-cq-de-sq6emm-k.wav", "002-tu-73-sk.wav"])

    def test_profiles_listing(self):
        self.assertEqual(main(["--list-profiles"]), 0)


class TestProfiles(unittest.TestCase):
    def test_every_profile_is_described_grouped_and_renders(self):
        listed = [name for group in GROUPS.values() for name in group["profiles"]]
        self.assertEqual(sorted(listed), sorted(PROFILES))
        for name in PROFILES:
            self.assertTrue(DESCRIPTIONS.get(name), f"{name} has no description")
            cfg = Config(seed=3)
            for field, value in resolve(name, np.random.default_rng(3)).items():
                setattr(cfg, field, value)
            out = render("e", cfg)          # one dit: enough to prove it works
            self.assertTrue(np.isfinite(out.samples).all(), name)
            self.assertGreater(out.samples.size, 0, name)

    def test_a_profile_is_a_different_evening_every_time(self):
        a = resolve("typical", np.random.default_rng(1))
        b = resolve("typical", np.random.default_rng(2))
        self.assertNotAlmostEqual(a["snr_db"], b["snr_db"], places=3)
        lo, hi = PROFILES["typical"]["snr_db"].lo, PROFILES["typical"]["snr_db"].hi
        for _ in range(50):
            drawn = resolve("typical", np.random.default_rng())["snr_db"]
            self.assertTrue(lo <= drawn <= hi)
        # No rng: the middle of each range, which is what a form shows.
        self.assertAlmostEqual(resolve("typical")["snr_db"], (lo + hi) / 2)
        self.assertEqual(Draw(0, 2, integer=True).pick(None), 1)
        self.assertEqual(str(Draw(6.0, 14.0)), "6\u201314")

    def test_lightning_does_not_reach_vhf_or_microwave(self):
        from morsefun.propagation import parse_band
        for name, values in PROFILES.items():
            band = values.get("band")
            if band and parse_band(band).hz >= 50e6:
                self.assertEqual(values.get("crash_rate"), 0.0, name)
                self.assertEqual(values.get("tilt"), 0.0, name)


class TestReceiver(unittest.TestCase):
    def harmonic_db(self, cfg: Config) -> float:
        """Third harmonic of the 600 Hz note against the note itself, dB."""
        out = render("cq cq de sq6emm sq6emm k", cfg)
        power = np.abs(np.fft.rfft(out.samples)) ** 2
        freqs = np.fft.rfftfreq(out.samples.size, 1.0 / out.sample_rate)
        band = lambda lo, hi: power[(freqs >= lo) & (freqs < hi)].sum()
        return 10 * np.log10(band(1700, 1900) / band(550, 650))

    def test_the_agc_puts_nothing_outside_the_filter(self):
        # A tanh limiter bent the waveform and left the third harmonic 29 dB
        # down at 1800 Hz, outside any CW filter.  An AGC changes gain, not shape.
        self.assertLess(self.harmonic_db(Config(snr_db=10.0, seed=23)), -55.0)

    def test_the_agc_catches_a_crash_and_lets_the_signal_through(self):
        x = 0.5 * np.sin(2 * np.pi * 600 * np.arange(44100) / 44100)
        x[20000:20400] += 6.0 * np.random.default_rng(1).standard_normal(400)
        y = agc(x, 44100)
        self.assertLess(float(np.abs(y[20000:20400]).max()), 1.2)      # rounded off
        np.testing.assert_allclose(y[:19000], x[:19000])                # untouched
        # ...and the gain comes back over a few hundred ms, not instantly.
        self.assertLess(float(np.abs(y[21000:22000]).max()), 0.5)
        self.assertGreater(float(np.abs(y[40000:44100]).max()), 0.45)


if __name__ == "__main__":
    unittest.main()
