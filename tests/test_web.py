"""Checks on the web front end: what the page is told, and what it sends back.

The one that matters most is that a profile's own keying survives an empty
form.  A form that always sent its own ``wpm`` keyed every QRSS profile at 23
words a minute, which turned a six-minute transmission into thirteen seconds of
something else entirely.
"""

from __future__ import annotations

import unittest

import numpy as np

from morsefun.profiles import GROUPS, PROFILES
from morsefun.web import (clean_prefix, config_from_payload, endpoint, options,
                          profile_card, spectrogram)


class TestOptions(unittest.TestCase):
    def test_every_profile_is_offered_under_exactly_one_band(self):
        listed = [name for group in GROUPS.values() for name in group["profiles"]]
        self.assertEqual(sorted(listed), sorted(PROFILES))
        self.assertEqual(len(listed), len(set(listed)))

    def test_the_page_is_given_bands_with_profiles_in_them(self):
        shown = options()
        self.assertEqual([group["name"] for group in shown["groups"]], list(GROUPS))
        for group in shown["groups"]:
            self.assertTrue(group["about"])
            for card in group["profiles"]:
                self.assertIn(card["name"], PROFILES)
                self.assertTrue(card["about"] and card["band"] and card["speed"])

    def test_a_card_says_the_band_the_path_and_the_speed(self):
        card = profile_card("lf-qrss")
        self.assertEqual(card["band"], "137.5 kHz")
        self.assertEqual(card["mode"], "iono")
        self.assertEqual(card["speed"], "QRSS3")
        self.assertAlmostEqual(card["defaults"]["qrss"], 3.0, places=3)
        self.assertAlmostEqual(card["defaults"]["wpm"], 0.4, places=6)
        # A profile that names no band is about band conditions, not a path.
        self.assertEqual(profile_card("typical")["band"], "any band")
        self.assertEqual(profile_card("typical")["mode"], "direct")
        self.assertNotIn("qrss", profile_card("typical")["defaults"])
        # A knob the profile draws is shown as its range, not as one number.
        self.assertEqual(profile_card("typical")["defaults"]["snr"], "6\u201314")
        self.assertEqual(profile_card("contest-40m")["speed"], "26\u201334 wpm")
        self.assertEqual(profile_card("contest-40m")["defaults"]["qrm_style"], "contest")

    def test_the_same_seed_draws_the_same_evening(self):
        a, _ = config_from_payload({"profile": "typical", "seed": "77"})
        b, _ = config_from_payload({"profile": "typical", "seed": "77"})
        c, _ = config_from_payload({"profile": "typical", "seed": "78"})
        self.assertEqual(a.snr_db, b.snr_db)
        self.assertNotEqual(a.snr_db, c.snr_db)
        self.assertEqual(a.seed, 77)


class TestPayload(unittest.TestCase):
    def test_an_empty_form_leaves_the_profile_alone(self):
        for name, wpm, rate in (("lf-qrss", 0.4, 8000), ("eme-qrss", 0.4, 8000),
                                ("air-scatter", 18.0, 44100), ("typical", 23.0, 44100)):
            cfg, profile = config_from_payload({"profile": name})
            self.assertEqual(profile, name)
            self.assertAlmostEqual(cfg.wpm, wpm, places=6)
            self.assertEqual(cfg.sample_rate, rate)

    def test_what_the_form_does_send_still_wins(self):
        cfg, _ = config_from_payload({"profile": "lf-qrss", "wpm": "23",
                                      "tone": "700", "snr": "-3"})
        self.assertAlmostEqual(cfg.wpm, 23.0)
        self.assertAlmostEqual(cfg.freq, 700.0)
        self.assertAlmostEqual(cfg.snr_db, -3.0)

    def test_qrss_from_the_form_sets_the_speed_and_the_envelope(self):
        cfg, _ = config_from_payload({"profile": "typical", "qrss": "10"})
        self.assertAlmostEqual(cfg.wpm, 0.12, places=6)
        self.assertAlmostEqual(cfg.rise_ms, 400.0)      # capped
        self.assertEqual(cfg.sample_rate, 8000)

    def test_the_checkboxes_mean_what_they_say(self):
        cfg, _ = config_from_payload({"profile": "rain-scatter", "evolve": False,
                                      "qrm_scatter": False, "no_noise": "on"})
        self.assertFalse(cfg.evolve)
        self.assertFalse(cfg.qrm_scatter)
        self.assertIsNone(cfg.snr_db)
        echo, _ = config_from_payload({"profile": "eme", "echo_test": "on"})
        self.assertAlmostEqual(echo.rician_db, 6.0)

    def test_nonsense_is_refused(self):
        with self.assertRaises(ValueError):
            config_from_payload({"profile": "no-such-profile"})
        with self.assertRaises(ValueError):
            config_from_payload({"profile": "typical", "cell": "drizzle-ish"})


class TestGenerated(unittest.TestCase):
    """The page can ask for a QSO or a beacon instead of sending a text."""

    def handler(self):
        from morsefun.web import Handler, Renders
        made = Handler.__new__(Handler)
        made.renders = Renders()
        return made

    def test_a_qso_comes_back_as_text_with_two_stations(self):
        body = self.handler().render({"profile": "tropo-2m", "generate": "qso",
                                      "seed": "21", "my_call": "sq6emm", "my_loc": "jo81lc"})
        self.assertIn("sq6emm", body["text"])
        self.assertIn("jo81lc", body["text"])
        self.assertTrue(body["two_stations"])
        self.assertGreaterEqual(len(body["text"].splitlines()), 4)
        self.assertIn("QSO", body["script"])
        self.assertIsNotNone(body["meta"]["other_station"])
        # The same seed draws the same QSO.
        again = self.handler().render({"profile": "tropo-2m", "generate": "qso",
                                       "seed": "21", "my_call": "sq6emm", "my_loc": "jo81lc"})
        self.assertEqual(again["text"], body["text"])

    def test_a_beacon_slows_down_unless_told_otherwise(self):
        body = self.handler().render({"profile": "tropo-10g", "generate": "beacon", "seed": "3"})
        self.assertFalse(body["two_stations"])
        self.assertLessEqual(body["meta"]["wpm"], 15.0)
        self.assertIn("beacon", body["script"])
        fast = self.handler().render({"profile": "tropo-10g", "generate": "beacon",
                                      "seed": "3", "wpm": "25"})
        self.assertAlmostEqual(fast["meta"]["wpm"], 25.0)
        with self.assertRaises(ValueError):
            self.handler().render({"profile": "typical", "generate": "sermon"})

    def test_two_stations_from_the_form(self):
        cfg, _ = config_from_payload({"profile": "typical", "two_stations": "on",
                                      "other_offset": "80", "other_db": "-3"})
        self.assertTrue(cfg.two_stations)
        self.assertAlmostEqual(cfg.other_offset_hz, 80.0)
        self.assertAlmostEqual(cfg.other_db, -3.0)
        cfg, _ = config_from_payload({"profile": "typical"})
        self.assertFalse(cfg.two_stations)


class TestWaterfall(unittest.TestCase):
    def test_the_window_follows_the_keying(self):
        samples = np.random.default_rng(1).standard_normal(8000 * 30)
        fast = spectrogram(samples, 8000, 600.0, dit_s=0.05)
        slow = spectrogram(samples, 8000, 600.0, dit_s=3.0)
        # A QRSS trace needs a long transform and only a few Hz of span.
        self.assertLess(slow["bin_hz"], fast["bin_hz"] / 4)
        self.assertLess(slow["high_hz"] - slow["low_hz"], 60.0)
        self.assertGreater(fast["high_hz"] - fast["low_hz"], 200.0)
        self.assertEqual(spectrogram(np.zeros(10), 8000, 600.0), {})


class TestRouting(unittest.TestCase):
    def test_a_proxy_prefix_is_ignored(self):
        self.assertEqual(endpoint("/api/render")[0], "render")
        self.assertEqual(endpoint("/morsefun/api/render")[0], "render")
        self.assertEqual(endpoint("/deep/path/api/options")[0], "options")
        self.assertEqual(endpoint("/x/audio/abc_1.wav"), ("audio", "abc_1"))
        self.assertEqual(endpoint("/morsefun/")[0], "page")

    def test_a_mount_path_has_to_look_like_one(self):
        self.assertEqual(clean_prefix("/morsefun"), "/morsefun")
        self.assertEqual(clean_prefix("morsefun/"), "/morsefun")
        self.assertEqual(clean_prefix('/a"b'), "")
        self.assertEqual(clean_prefix("/"), "")
        self.assertEqual(clean_prefix(None), "")


if __name__ == "__main__":
    unittest.main()
