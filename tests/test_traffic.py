"""Checks on the stations, the QSOs and the beacons: that what is drawn could
have been heard, and that the text it makes keys the way it is written."""

from __future__ import annotations

import re
import unittest

import numpy as np

from morsefun import Config, render
from morsefun.morse import Timing, duration, parse, timeline, to_code
from morsefun.noise import station_text
from morsefun.render import overs, plan
from morsefun.traffic import (COUNTRIES, Station, band_class, beacon, compose, distance_km,
                              draw_station, expand, locator_centre, maidenhead, qso,
                              station_from_call)

#: A prefix of one to three characters with a letter in it; a district digit;
#: one to four letters; an optional /B.
CALL = re.compile(r"^[A-Z0-9]?[A-Z][A-Z0-9]?[0-9][A-Z]{1,4}(?:/B)?$")
LOCATOR = re.compile(r"^[A-R]{2}[0-9]{2}[A-X]{2}$")


class TestHolds(unittest.TestCase):
    def test_a_bracket_is_a_carrier_or_a_pause(self):
        words, unknown = parse("db0abc jo62qm [30s] [2s pause] k")
        self.assertEqual(unknown, [])
        holds = [(e.on, e.seconds, e.kind) for e in timeline(words, Timing(12))
                 if e.kind in ("carrier", "pause")]
        self.assertEqual(holds, [(True, 30.0, "carrier"), (False, 2.0, "pause")])
        self.assertIn("[30s]", to_code(words))
        self.assertIn("[2s pause]", to_code(words))

    def test_units_and_nonsense(self):
        words, _ = parse("[500ms] [1.5 min] [2 sec off]")
        self.assertAlmostEqual(words[0][0].hold, 0.5)
        self.assertAlmostEqual(words[1][0].hold, 90.0)
        self.assertFalse(words[2][0].on)
        _, unknown = parse("e [sometime] [ e")
        self.assertEqual(unknown, ["[sometime]", "["])

    def test_the_carrier_is_keyed_for_as_long_as_it_says(self):
        out = render("e [3s] e", Config(snr_db=None, qsb_db=0, drift_hz=0, pad=0.1, seed=1,
                                        rise_ms=5.0))
        block = out.sample_rate // 1000                      # the envelope, per millisecond
        trimmed = out.samples[: (out.samples.size // block) * block]
        loud = np.abs(trimmed).reshape(-1, block).max(axis=1) > 0.3
        longest = max(len(run) for run in "".join("1" if v else "0" for v in loud).split("0"))
        self.assertAlmostEqual(longest / 1000.0, 3.0, delta=0.05)


class TestStations(unittest.TestCase):
    def test_callsigns_have_the_shape_of_callsigns(self):
        rng = np.random.default_rng(1)
        for _ in range(400):
            self.assertRegex(draw_station(rng).call, CALL)
        for _ in range(100):
            self.assertRegex(draw_station(rng, beacon=True).call, CALL)

    def test_every_template_expands_to_a_callsign(self):
        rng = np.random.default_rng(2)
        for country in COUNTRIES:
            for pattern, _ in country.calls:
                self.assertRegex(expand(pattern, rng, country.digits), CALL, pattern)
            for pattern in country.beacons:
                self.assertRegex(expand(pattern, rng, country.digits), CALL, pattern)

    def test_the_locator_is_where_the_town_is(self):
        rng = np.random.default_rng(3)
        for _ in range(200):
            s = draw_station(rng)
            self.assertRegex(s.locator, LOCATOR)
            centre = locator_centre(s.locator)
            self.assertLess(distance_km(centre, (s.lat, s.lon)), 8.0)
        self.assertEqual(maidenhead(51.11, 17.03)[:4], "JO81")       # Wroclaw
        self.assertEqual(maidenhead(52.52, 13.40)[:4], "JO62")       # Berlin
        self.assertEqual(maidenhead(40.71, -74.01)[:4], "FN20")      # New York
        self.assertEqual(maidenhead(-33.87, 151.21)[:4], "QF56")     # Sydney

    def test_a_district_digit_puts_the_station_in_its_district(self):
        rng = np.random.default_rng(4)
        towns = {"wroclaw": (51.11, 17.03), "opole": (50.67, 17.93)}
        for _ in range(60):
            s = station_from_call("SQ6EMM", rng)
            self.assertEqual(s.country, "Poland")
            self.assertIn(s.qth, towns)
            self.assertLess(distance_km(locator_centre(s.locator), towns[s.qth]), 25.0)
        self.assertEqual(station_from_call("GM4XYZ", rng).country, "Scotland")
        self.assertEqual(station_from_call("IT9ABC", rng).country, "Sicily")
        self.assertEqual(station_from_call("2E0ABC", rng).country, "England")
        self.assertEqual(station_from_call("OZ7IGY", rng).country, "Denmark")
        self.assertEqual(station_from_call("W1AW", rng).qth, "boston")
        # A locator wins over the digit, and a name is kept as given.
        s = station_from_call("sq6emm", rng, "JO81LC", "dawid")
        self.assertEqual((s.locator, s.name, s.call), ("JO81LC", "dawid", "SQ6EMM"))
        self.assertEqual(station_from_call("XX9ZZ", rng, "JN47").square, "JN47")

    def test_a_neighbour_is_within_reach(self):
        rng = np.random.default_rng(5)
        me = station_from_call("SQ6EMM", rng)
        for _ in range(60):
            other = draw_station(rng, near=me, min_km=60.0, max_km=500.0)
            km = distance_km((me.lat, me.lon), (other.lat, other.lon))
            self.assertTrue(60.0 <= km <= 500.0 + 40.0, km)       # the jitter is allowed
        north = draw_station(rng, min_lat=50.0)
        self.assertGreaterEqual(north.lat, 49.5)

    def test_the_neighbours_on_the_band_use_the_same_table(self):
        rng = np.random.default_rng(6)
        s = draw_station(rng)
        text = station_text("ragchew", s, rng)
        self.assertIn(s.call.lower(), text)


class TestQso(unittest.TestCase):
    def test_a_ragchew_has_the_usual_shape(self):
        rng = np.random.default_rng(7)
        script = qso(rng, band="hf", snr_db=10.0)
        a, b = (s["call"].lower() for s in script.detail["stations"])
        self.assertTrue(script.two_stations)
        self.assertGreaterEqual(len(script.lines), 6)
        self.assertTrue(script.lines[0].startswith("cq"))
        self.assertIn(f"de {a}", script.lines[0])
        self.assertTrue(script.lines[1].startswith(a))
        self.assertIn(f"de {b}", script.lines[1])
        self.assertIn("rst", script.lines[2])
        self.assertIn("<SK>", script.lines[-1])
        # Alternate lines are alternate stations, and each signs with its own call.
        for index, line in enumerate(script.lines[1:], start=1):
            mine = a if index % 2 == 0 else b
            self.assertIn(mine, line, line)
        self.assertEqual(parse(script.text)[1], [])

    def test_the_report_follows_the_conditions(self):
        strong = qso(np.random.default_rng(8), snr_db=24.0).lines[3]
        weak = qso(np.random.default_rng(8), snr_db=0.0).lines[3]
        self.assertRegex(strong, r"rst 5[89]9")
        self.assertRegex(weak, r"rst [345][345]9")

    def test_vhf_exchanges_locators_and_aurora_gives_a_reports(self):
        rng = np.random.default_rng(9)
        tropo = qso(rng, band="vhf", mode="none")
        self.assertRegex(tropo.text, r"[a-r]{2}[0-9]{2}[a-x]{2}")
        self.assertLess(tropo.detail["distance_km"], 760)
        aurora = qso(rng, band="vhf", mode="aurora")
        self.assertRegex(aurora.text, r"ur 5[1-9]a 5[1-9]a")
        rain = qso(rng, band="microwave", mode="rain")
        self.assertIn("via rs", rain.text)
        self.assertLess(rain.detail["distance_km"], 560)

    def test_a_contest_and_the_moon_have_their_own_procedure(self):
        rng = np.random.default_rng(10)
        contest = qso(rng, band="hf", contest=True)
        self.assertIn("5nn", contest.text)
        self.assertTrue(contest.lines[0].endswith("test"))
        vhf = qso(rng, band="vhf", contest=True)
        self.assertRegex(vhf.text, r"5nn [0-9tn]{3} [a-r]{2}[0-9]{2}[a-x]{2}")
        moon = qso(rng, band="vhf", mode="moon")
        self.assertEqual(len(moon.lines), 4)
        self.assertTrue(moon.lines[1].startswith(("ro", "rm")))
        self.assertIn("rrr", moon.lines[2])
        self.assertIn("73", moon.lines[3])

    def test_you_can_be_in_it(self):
        rng = np.random.default_rng(11)
        me = station_from_call("SQ6EMM", rng, "JO81LC", "dawid")
        calls, answers = 0, 0
        for _ in range(20):
            script = qso(rng, me=me)
            self.assertIn("sq6emm", script.text)
            self.assertIn("dawid", script.text)
            if "you call" in script.note:
                calls += 1
            else:
                answers += 1
        self.assertTrue(calls and answers)

    def test_the_same_seed_is_the_same_qso(self):
        cfg = Config(band="7.03M", scatter="iono", wpm=20)
        a = compose("qso", cfg, np.random.default_rng(12))
        b = compose("qso", cfg, np.random.default_rng(12))
        c = compose("qso", cfg, np.random.default_rng(13))
        self.assertEqual(a.text, b.text)
        self.assertNotEqual(a.text, c.text)
        with self.assertRaises(ValueError):
            compose("sermon", cfg, np.random.default_rng(1))


class TestBeacon(unittest.TestCase):
    def test_a_microwave_beacon_identifies_and_keys_a_carrier(self):
        rng = np.random.default_rng(14)
        script = beacon(rng, band="microwave", carrier=True)
        call = script.detail["station"]["call"].lower()
        self.assertIn(call, script.text)
        self.assertRegex(script.text, r"\[[0-9]+s\]")
        self.assertRegex(script.text, r"[a-r]{2}[0-9]{2}")
        self.assertTrue(10.0 <= script.wpm <= 15.0)
        self.assertFalse(script.two_stations)
        self.assertEqual(parse(script.text)[1], [])
        quiet = beacon(rng, band="vhf", carrier=False)
        self.assertNotRegex(quiet.text, r"\[[0-9]+s\]")

    def test_the_carrier_can_come_first(self):
        seen_before = False
        for seed in range(80):
            script = beacon(np.random.default_rng(seed), band="microwave")
            if script.detail["carrier_before_s"]:
                seen_before = True
                self.assertTrue(script.text.startswith("["))
        self.assertTrue(seen_before)

    def test_hf_and_qrss_beacons_look_like_theirs(self):
        rng = np.random.default_rng(15)
        hf = beacon(rng, band="hf")
        self.assertRegex(hf.text, r"[a-r]{2}[0-9]{2} ")          # a four-character locator
        self.assertTrue(10.0 <= hf.wpm <= 16.0)
        own = beacon(rng, band="hf", me=station_from_call("SQ6EMM", rng))
        self.assertIn("sq6emm/b", own.text)
        slow = beacon(rng, band="lf", qrss=True)
        self.assertIsNone(slow.wpm)
        self.assertLess(len(slow.text), 40)

    def test_your_own_beacon(self):
        script = beacon(np.random.default_rng(16), band="vhf",
                        me=station_from_call("SQ6EMM", np.random.default_rng(1), "JO81LC"))
        self.assertIn("sq6emm jo81lc", script.text)

    def test_the_band_is_read_off_the_config(self):
        self.assertEqual(band_class("137.5k"), "lf")
        self.assertEqual(band_class("7.03M"), "hf")
        self.assertEqual(band_class("144M"), "vhf")
        self.assertEqual(band_class("432M"), "uhf")
        self.assertEqual(band_class("10G"), "microwave")
        slow = compose("beacon", Config(band="137.5k", scatter="iono", wpm=0.4),
                       np.random.default_rng(17))
        self.assertIsNone(slow.wpm)
        self.assertNotIn("[", slow.text.split("]")[0].split("[")[0])


class TestTwoStations(unittest.TestCase):
    TEXT = ("cq cq de sp3abc sp3abc k\nsp3abc de dl2xyz dl2xyz k\n"
            "dl2xyz de sp3abc ur 579 579 jo82kl k\nr r 73 <SK>")

    def test_lines_alternate_and_the_timelines_match(self):
        script, unknown = overs(self.TEXT, True)
        self.assertEqual([who for who, _ in script], [0, 1, 0, 1])
        self.assertEqual(unknown, [])
        a, b = plan(script, Timing(20), Timing(25), 1.5)
        self.assertAlmostEqual(duration(a), duration(b), places=9)
        self.assertTrue(any(e.kind == "turnaround" for e in a))
        self.assertEqual(len(overs(self.TEXT, False)[0]), 1)

    def test_the_other_station_is_there_and_is_somewhere_else(self):
        cfg = Config(two_stations=True, snr_db=12.0, seed=5, other_offset_hz=100.0,
                     other_db=0.0, qsb_db=0.0, drift_hz=0.0, crash_rate=0.0,
                     qrm_count=0, birdie_count=0)
        out = render(self.TEXT, cfg)
        other = out.meta["other_station"]
        self.assertEqual(other["overs"], 2)
        self.assertAlmostEqual(other["offset_hz"], 100.0)
        # The second over is the other station, so it is at 700 Hz, not 600.
        start = int((0.6 + 0.5) * out.sample_rate)        # into the first over
        first = out.samples[start:start + out.sample_rate]
        spectrum = np.abs(np.fft.rfft(first))
        freqs = np.fft.rfftfreq(first.size, 1.0 / out.sample_rate)
        peak = freqs[np.argmax(spectrum)]
        self.assertAlmostEqual(peak, 600.0, delta=15.0)
        second = render(self.TEXT.split("\n")[1], Config(snr_db=None, seed=5))
        self.assertGreater(out.duration, second.duration + 20.0)
        # Without the flag the same text is one station, start to finish.
        one = render(self.TEXT, Config(seed=5))
        self.assertIsNone(one.meta["other_station"])

    def test_the_other_station_keeps_its_speed_under_qrss(self):
        from morsefun.render import draw_other
        slow = draw_other(Config(wpm=0.4), np.random.default_rng(1))
        self.assertAlmostEqual(slow.wpm, 0.4)
        fast = draw_other(Config(wpm=20.0), np.random.default_rng(1))
        self.assertTrue(15.0 <= fast.wpm <= 25.0)


if __name__ == "__main__":
    unittest.main()
