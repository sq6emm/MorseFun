"""Checks on aircraft scatter: one reflector, moving fast through the beam."""

from __future__ import annotations

import unittest

import numpy as np

from morsefun.aircraft import aircraft_track, draw_aircraft
from morsefun.propagation import parse_band
from morsefun.render import Config, render
from morsefun.scatter import swept_channel

X_BAND = parse_band("10G")
TWENTY_THREE_CM = parse_band("1296")
TWO_METRES = parse_band("144M")


def crossing(**pinned):
    """An airliner crossing the middle of a 300 km path, straight across."""
    settings = dict(baseline_km=300.0, altitude_km=10.0, speed_mps=250.0,
                    heading_deg=90.0, offset_km=0.0, miss_km=0.0,
                    length_m=55.0, beamwidth_deg=6.0)
    settings.update(pinned)
    return draw_aircraft(np.random.default_rng(1), **settings)


class TestTrack(unittest.TestCase):
    def test_the_note_slides_down_through_zero(self):
        times, doppler, level, spread, info = aircraft_track(crossing(), X_BAND, 120.0)
        self.assertGreater(doppler[0], 0.0)
        self.assertLess(doppler[-1], 0.0)
        self.assertAlmostEqual(abs(doppler[0]), abs(doppler[-1]), delta=1.0)
        self.assertLess(info["sweep_hz_s"], -5.0)
        self.assertAlmostEqual(info["best_at_s"], 60.0, delta=5.0)

    def test_the_slide_scales_with_the_band(self):
        def sweep(band):
            return abs(aircraft_track(crossing(), band, 120.0)[4]["sweep_hz_s"])
        self.assertAlmostEqual(sweep(X_BAND) / sweep(TWENTY_THREE_CM),
                               10000.0 / 1296.0, delta=0.3)
        # On 2 m the same aeroplane moves the note by a few Hz and nobody notices.
        self.assertLess(abs(aircraft_track(crossing(), TWO_METRES, 120.0)[1]).max(), 40.0)

    def test_following_the_path_does_almost_nothing(self):
        across = aircraft_track(crossing(heading_deg=90.0), X_BAND, 120.0)[4]
        along = aircraft_track(crossing(heading_deg=0.0), X_BAND, 120.0)[4]
        self.assertLess(abs(along["sweep_hz_s"]) * 5, abs(across["sweep_hz_s"]))

    def test_it_is_only_in_both_beams_for_a_while(self):
        wide = aircraft_track(crossing(beamwidth_deg=12.0), X_BAND, 240.0)[4]
        narrow = aircraft_track(crossing(beamwidth_deg=2.0), X_BAND, 240.0)[4]
        self.assertGreater(wide["window_s"], narrow["window_s"] * 2)
        self.assertGreater(narrow["window_s"], 1.0)

    def test_the_level_peaks_at_the_crossing_and_falls_away(self):
        times, _, level, _, info = aircraft_track(
            crossing(beamwidth_deg=4.0), X_BAND, 240.0)
        peak = int(np.argmax(level))
        self.assertAlmostEqual(float(level[peak]), 1.0, places=9)
        self.assertLess(level[0], 0.2)
        self.assertLess(level[-1], 0.2)
        self.assertAlmostEqual(times[peak], info["best_at_s"], places=6)

    def test_a_bigger_aeroplane_is_a_rougher_note(self):
        small = aircraft_track(crossing(length_m=25.0), X_BAND, 120.0)[4]
        large = aircraft_track(crossing(length_m=75.0), X_BAND, 120.0)[4]
        self.assertAlmostEqual(large["spread_hz"] / small["spread_hz"], 3.0, delta=0.2)
        self.assertLess(small["spread_hz"], 10.0)       # roughness, not a hiss

    def test_what_is_drawn_covers_what_is_up_there(self):
        for seed in range(12):
            spec = draw_aircraft(np.random.default_rng(seed))
            self.assertGreaterEqual(spec.speed_mps, 180.0)
            self.assertLessEqual(spec.speed_mps, 290.0)
            self.assertGreaterEqual(spec.altitude_km, 7.0)
            self.assertLessEqual(spec.altitude_km, 12.5)


class TestSweptChannel(unittest.TestCase):
    def test_the_process_follows_the_track(self):
        rate = 8000
        times = np.linspace(0.0, 4.0, 40)
        doppler = np.linspace(200.0, -200.0, 40)        # sliding through zero
        process = swept_channel(4 * rate, rate, times, doppler, np.ones(40),
                                np.zeros(40), np.random.default_rng(2))
        self.assertAlmostEqual(float(np.mean(np.abs(process) ** 2)), 1.0, places=6)
        self.assertTrue(np.isfinite(process).all())
        # Instantaneous frequency from the phase: it should land on the track.
        phase = np.unwrap(np.angle(process))
        measured = np.gradient(phase) * rate / (2 * np.pi)
        for at in (0.5, 2.0, 3.5):
            index = int(at * rate)
            self.assertAlmostEqual(float(np.mean(measured[index:index + 400])),
                                   float(np.interp(at, times, doppler)), delta=3.0)

    def test_a_pass_that_fades_is_quiet_at_the_ends(self):
        rate = 8000
        times = np.linspace(0.0, 4.0, 40)
        level = np.exp(-0.5 * ((times - 2.0) / 0.4) ** 2)
        process = swept_channel(4 * rate, rate, times, np.zeros(40), level,
                                np.zeros(40), np.random.default_rng(3))
        middle = np.abs(process[2 * rate - 200:2 * rate + 200]).mean()
        edge = np.abs(process[:400]).mean()
        self.assertGreater(middle, 20 * edge)


class TestRenderWithAircraft(unittest.TestCase):
    def test_a_pass_is_reported_and_audible(self):
        out = render("cq cq de sq6emm k", Config(
            scatter="aircraft", band="10G", baseline_km=300.0, altitude_km=10.0,
            plane_speed_mps=250.0, plane_heading_deg=90.0, snr_db=10.0,
            qrm_count=0, seed=4))
        scatter = out.meta["scatter"]
        self.assertEqual(scatter["kind"], "aircraft")
        self.assertEqual(scatter["scatterers"], 1)
        self.assertNotEqual(scatter["sweep_hz_s"], 0.0)
        self.assertTrue(np.isfinite(out.samples).all())
        self.assertIn("sliding", scatter["sounds_like"])

    def test_a_slide_out_of_the_filter_is_charged_for(self):
        narrow = render("cq de sq6emm k", Config(
            scatter="aircraft", band="10G", baseline_km=160.0, plane_speed_mps=280.0,
            plane_heading_deg=90.0, bandwidth=200.0, snr_db=10.0, qrm_count=0, seed=4))
        self.assertLess(narrow.meta["scatter"]["audible_fraction"], 1.0)
        self.assertLess(narrow.meta["effective_snr_db"], 10.0)

    def test_two_m_hardly_notices_the_aeroplane(self):
        out = render("cq de sq6emm k", Config(
            scatter="aircraft", band="144M", snr_db=10.0, qrm_count=0, seed=4))
        self.assertLess(abs(out.meta["scatter"]["sweep_hz_s"]), 2.0)


if __name__ == "__main__":
    unittest.main()
