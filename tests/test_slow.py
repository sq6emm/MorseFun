"""Checks on the slow end: QRSS keying, a low band, and the Moon.

The claims here are the ones that make or break these modes.  A QRSS bin is
1/dit wide and buys exactly the processing gain that implies, as long as the
path leaves the trace narrower than the bin.  A low band is a few coherent hops
whose Doppler is milliHertz and whose beat is the fading.  The Moon is 2.5
seconds away, spread by libration in proportion to the band, and shifted by
hundreds of Hz that a rig has to follow.
"""

from __future__ import annotations

import unittest

import numpy as np

from morsefun.moon import (APOGEE_KM, PERIGEE_KM, draw_moon, faraday_fade,
                           libration_rate_rad_s, moon_doppler)
from morsefun.propagation import parse_band
from morsefun.render import (MAX_SAMPLES, Config, apply_qrss, mode_name, qrss_label,
                             render)
from morsefun.scatter import Carrier, block_size, coherent_channel
from morsefun.skywave import draw_iono, iono_carriers

TWO_METRES = parse_band("144M")
TWENTY_THREE_CM = parse_band("1296")
X_BAND = parse_band("10G")
TOP_BAND = parse_band("1.8M")
LF = parse_band("137.5k")


class TestQrss(unittest.TestCase):
    def test_a_dit_in_seconds_is_just_a_very_low_speed(self):
        cfg = apply_qrss(Config(), 3.0)
        self.assertAlmostEqual(cfg.wpm, 0.4, places=9)
        out = render("e", cfg)
        self.assertAlmostEqual(out.meta["dit_ms"], 3000.0, places=6)
        self.assertEqual(qrss_label(3.0), "QRSS3")
        self.assertEqual(qrss_label(0.1), "dit 100 ms")

    def test_it_slows_the_envelope_and_drops_the_sample_rate(self):
        # A three-second dit with a 5 ms edge would have sidebands 200 Hz out,
        # which is absurd when the trace is a third of a Hz wide.
        cfg = apply_qrss(Config(), 3.0)
        self.assertAlmostEqual(cfg.rise_ms, 200.0)
        self.assertEqual(cfg.sample_rate, 8000)
        kept = apply_qrss(Config(rise_ms=8.0, sample_rate=44100), 3.0,
                          keep_rise=True, keep_rate=True)
        self.assertAlmostEqual(kept.rise_ms, 8.0)
        self.assertEqual(kept.sample_rate, 44100)
        with self.assertRaises(ValueError):
            apply_qrss(Config(), 0.0)

    def test_the_bin_is_one_over_the_dit_and_pays_for_itself(self):
        cfg = apply_qrss(Config(snr_db=-12.0, bandwidth=200.0, crash_rate=0.0,
                               qrm_count=0, seed=5), 3.0)
        qrss = render("e e", cfg).meta["qrss"]
        self.assertAlmostEqual(qrss["bandwidth_hz"], 1 / 3, places=9)
        self.assertAlmostEqual(qrss["processing_gain_db"],
                               10 * np.log10(200.0 * 3.0), places=6)
        # -12 dB in 200 Hz is +15 dB in a third of a Hz, which is why anybody
        # bothers with this.
        self.assertAlmostEqual(qrss["waterfall_snr_db"], -12.0 + 27.8, delta=0.5)
        self.assertFalse(qrss["smeared"])

    def test_fast_keying_is_not_qrss_and_says_nothing_about_bins(self):
        self.assertEqual(render("e", Config(wpm=23, seed=1)).meta["qrss"], {})

    def test_a_spread_path_takes_the_gain_back(self):
        quiet = render("e", apply_qrss(Config(
            scatter="eme", band="144M", libration_deg_day=0.25, snr_db=-6.0,
            qrm_count=0, crash_rate=0.0, seed=3), 3.0)).meta["qrss"]
        busy = render("e", apply_qrss(Config(
            scatter="eme", band="144M", libration_deg_day=8.0, snr_db=-6.0,
            qrm_count=0, crash_rate=0.0, seed=3), 3.0)).meta["qrss"]
        self.assertFalse(quiet["smeared"])
        self.assertTrue(busy["smeared"])
        self.assertLess(busy["waterfall_snr_db"], quiet["waterfall_snr_db"] - 3)

    def test_an_absurd_request_is_refused_rather_than_swallowing_the_machine(self):
        cfg = apply_qrss(Config(), 120.0)
        with self.assertRaises(ValueError) as caught:
            render("cq cq de sq6emm sq6emm k", cfg)
        self.assertIn("minutes", str(caught.exception))
        self.assertGreater(MAX_SAMPLES, 10_000_000)


class TestSkywave(unittest.TestCase):
    def test_the_layer_moving_is_the_whole_doppler(self):
        spec = draw_iono(np.random.default_rng(1), TOP_BAND, modes=1,
                         height_rate_mps=2.0, turbulence_mps=0.1, elevation_deg=30.0)
        carriers, info = iono_carriers(spec, TOP_BAND)
        expected = TOP_BAND.doppler_hz(2.0 * np.sin(np.radians(30.0)))
        self.assertAlmostEqual(info["shift_hz"], float(expected), delta=0.2 * abs(expected))
        self.assertEqual(len(carriers), 1)
        self.assertEqual(info["beat_hz"], 0.0)       # one way in, nothing to beat

    def test_a_long_wave_hardly_notices_what_a_short_one_does(self):
        def spread(band):
            spec = draw_iono(np.random.default_rng(4), band, modes=2,
                             height_rate_mps=2.0, turbulence_mps=0.4,
                             elevation_deg=30.0)
            return iono_carriers(spec, band)[1]["spread_hz"]
        ratio = spread(parse_band("10.14M")) / spread(LF)
        self.assertAlmostEqual(ratio, 10.14e6 / 137.5e3, delta=4.0)
        self.assertLess(spread(LF), 0.01)            # 2200 m: a trace like a hair

    def test_more_than_one_mode_means_fading(self):
        spec = draw_iono(np.random.default_rng(2), parse_band("10.14M"), modes=3)
        info = iono_carriers(spec, parse_band("10.14M"))[1]
        self.assertEqual(len(info["modes"]), 3)
        self.assertGreater(info["beat_hz"], 0.0)
        self.assertAlmostEqual(info["fade_period_s"], 1.0 / info["beat_hz"], places=6)

    def test_carriers_beat_at_the_difference_between_them(self):
        beat = 0.05
        rng = np.random.default_rng(6)
        process = coherent_channel(60 * 4000, 4000, [
            Carrier(shift_hz=0.0, spread_hz=0.0, level=1.0),
            Carrier(shift_hz=beat, spread_hz=0.0, level=1.0),
        ], rng)
        self.assertAlmostEqual(float(np.mean(np.abs(process) ** 2)), 1.0, places=6)
        envelope = np.abs(process) - np.mean(np.abs(process))
        spectrum = np.abs(np.fft.rfft(envelope))
        freqs = np.fft.rfftfreq(envelope.size, 1.0 / 4000)
        self.assertAlmostEqual(float(freqs[spectrum.argmax()]), beat, delta=0.01)

    def test_a_low_band_render_keeps_the_trace_inside_the_bin(self):
        out = render("e", apply_qrss(Config(
            scatter="iono", band="137.5k", layer_rate_mps=1.0, snr_db=-12.0,
            qrm_count=0, crash_rate=0.0, seed=7), 3.0))
        scatter, qrss = out.meta["scatter"], out.meta["qrss"]
        self.assertEqual(scatter["kind"], "skywave")
        self.assertLess(scatter["spread_hz"], qrss["bandwidth_hz"])
        self.assertFalse(qrss["smeared"])
        self.assertTrue(np.isfinite(out.samples).all())


class TestMoon(unittest.TestCase):
    def rng(self):
        return np.random.default_rng(11)

    def test_the_moon_is_two_and_a_half_seconds_away(self):
        for seed in range(8):
            spec = draw_moon(np.random.default_rng(seed), TWO_METRES)
            self.assertGreaterEqual(spec.distance_km, PERIGEE_KM)
            self.assertLessEqual(spec.distance_km, APOGEE_KM)
            self.assertAlmostEqual(spec.delay_s, 2.5, delta=0.2)

    def test_the_echo_really_does_arrive_late(self):
        cfg = Config(scatter="eme", band="144M", snr_db=None, qsb_db=0.0,
                     drift_hz=0.0, rician_db=6.0, pad=0.3, seed=3)
        out = render("t", cfg)
        rate = out.sample_rate
        level = np.abs(out.samples)
        loud = np.where(level > 0.1 * level.max())[0]
        breaks = np.where(np.diff(loud) > rate // 4)[0]
        starts = [loud[0] / rate] + [loud[index + 1] / rate for index in breaks]
        self.assertEqual(len(starts), 2)         # your own keying, then the echo
        self.assertAlmostEqual(starts[1] - starts[0],
                               out.meta["scatter"]["delay_s"], delta=0.05)

    def test_the_level_is_measured_where_the_echo_actually_is(self):
        # The echo lands two and a half seconds after it was keyed, so measuring
        # the key-down power against the transmitted envelope would measure the
        # gaps and scale the noise against nothing at all.
        out = render("cq de sq6emm k", Config(scatter="eme", band="144M",
                                              snr_db=10.0, crash_rate=0.0,
                                              qrm_count=0, seed=6))
        self.assertAlmostEqual(out.meta["measured_snr_db"], 10.0, delta=2.5)

    def test_libration_spreads_it_in_proportion_to_the_band(self):
        def spread(band):
            spec = draw_moon(self.rng(), band, libration_deg_day=2.5)
            return moon_doppler(spec, band, self.rng())[2]["spread_hz"]
        self.assertAlmostEqual(spread(TWENTY_THREE_CM) / spread(TWO_METRES),
                               1296.0 / 144.0, delta=0.5)
        self.assertAlmostEqual(spread(TWO_METRES), 0.33, delta=0.1)
        self.assertAlmostEqual(spread(X_BAND), 23.0, delta=6.0)

    def test_libration_minimum_is_worth_waiting_for(self):
        def spread(rate):
            spec = draw_moon(self.rng(), TWO_METRES, libration_deg_day=rate)
            return moon_doppler(spec, TWO_METRES, self.rng())[2]["spread_hz"]
        self.assertLess(spread(0.2) * 10, spread(8.0))
        self.assertGreater(libration_rate_rad_s(2.5), 0.0)

    def test_the_rig_has_to_follow_the_doppler(self):
        kept = render("e", Config(scatter="eme", band="144M", moon_range_rate_mps=400.0,
                                  moon_accel_mps2=0.03, doppler_track=False,
                                  retune=False, snr_db=10.0, qrm_count=0, seed=2))
        tracked = render("e", Config(scatter="eme", band="144M", moon_range_rate_mps=400.0,
                                     moon_accel_mps2=0.03, doppler_track=True,
                                     snr_db=10.0, qrm_count=0, seed=2))
        self.assertAlmostEqual(kept.meta["scatter"]["own_doppler_hz"],
                               float(TWO_METRES.doppler_hz(400.0)), delta=1.0)
        # 400 m/s on 2 m is 384 Hz of self-Doppler, left in the audio.
        self.assertGreater(abs(kept.meta["scatter"]["shift_hz"]), 300.0)
        self.assertAlmostEqual(tracked.meta["scatter"]["shift_hz"], 0.0, delta=1.0)
        self.assertEqual(tracked.meta["scatter"]["residual_drift_hz_s"], 0.0)
        self.assertNotEqual(kept.meta["scatter"]["residual_drift_hz_s"], 0.0)

    def test_untracked_doppler_on_10ghz_lands_outside_the_filter(self):
        out = render("e", Config(scatter="eme", band="10G", moon_range_rate_mps=400.0,
                                 doppler_track=False, retune=False, snr_db=10.0,
                                 qrm_count=0, seed=2))
        self.assertGreater(abs(out.meta["scatter"]["own_doppler_hz"]), 20_000)
        self.assertLess(out.meta["scatter"]["audible_fraction"], 0.05)

    def test_faraday_is_a_vhf_problem_only(self):
        self.assertAlmostEqual(draw_moon(self.rng(), TWO_METRES).faraday_db, 22.0,
                               delta=0.1)
        self.assertLess(draw_moon(self.rng(), TWENTY_THREE_CM).faraday_db, 1.0)
        self.assertEqual(draw_moon(self.rng(), X_BAND).faraday_db, 0.0)  # below 0.5 dB

    def test_faraday_fades_to_nothing_and_comes_back(self):
        fade = faraday_fade(60 * 4000, 4000, self.rng(), 20.0, 120.0)
        self.assertLessEqual(float(fade.max()), 1.0)
        self.assertLess(float(fade.min()), 0.2)
        self.assertGreater(float(fade.mean()), 0.3)
        self.assertTrue(np.all(fade > 0.0))
        self.assertTrue(np.allclose(faraday_fade(10, 4000, self.rng(), 0.0, 120.0), 1.0))

    def test_names_people_actually_use(self):
        self.assertEqual(mode_name("EME"), "moon")
        self.assertEqual(mode_name("skywave"), "iono")
        self.assertEqual(mode_name(None), "none")
        with self.assertRaises(ValueError):
            render("e", Config(scatter="meteor", seed=1))

    def test_a_block_is_never_longer_than_the_message(self):
        # A milliHertz spectrum would otherwise ask for a transform longer than
        # the whole render, which leaves nothing to overlap-add.
        self.assertLessEqual(block_size(0.001, 8000, 100_000, hi=1 << 20), 32768)
        self.assertGreater(block_size(0.001, 8000, 8_000_000, hi=1 << 20), 65536)


if __name__ == "__main__":
    unittest.main()
