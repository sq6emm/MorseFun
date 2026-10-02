"""Checks on the 10 GHz propagation layer: Doppler, levels, and randomness."""

from __future__ import annotations

import unittest

import numpy as np

from morsefun import Config, render
from morsefun.propagation import (REFERENCE_RATE_MM_H, AuroraSpec, RainSpec, SnowSpec,
                                  aurora_doppler, parse_band, rain_attenuation_db_km,
                                  rain_doppler, reflectivity_dbz, snow_doppler)
from morsefun.render import STREAMS, streams
from morsefun.scatter import audible_fraction, channel, doppler_spectrum

X_BAND = parse_band("10G")
TWO_METRES = parse_band("144M")


def note_width(cfg: Config, tone: float = 600.0) -> float:
    """Spectral width of the keyed note in Hz, measured on the render."""
    out = render("eeeeee", cfg)
    power = np.abs(np.fft.rfft(out.samples)) ** 2
    freqs = np.fft.rfftfreq(out.samples.size, 1.0 / out.sample_rate)
    keep = (freqs > tone - 500) & (freqs < tone + 500)
    power, freqs = power[keep], freqs[keep]
    centre = np.sum(freqs * power) / np.sum(power)
    return float(np.sqrt(np.sum(power * (freqs - centre) ** 2) / np.sum(power)))


class TestBand(unittest.TestCase):
    def test_parsing(self):
        self.assertAlmostEqual(parse_band("10G").ghz, 10.0)
        self.assertAlmostEqual(parse_band("10.368GHz").ghz, 10.368)
        self.assertAlmostEqual(parse_band("144M").hz, 144e6)
        self.assertAlmostEqual(parse_band("1296").hz, 1296e6, places=0)  # bare = MHz
        self.assertAlmostEqual(parse_band("3cm").ghz, 9.993, places=2)
        with self.assertRaises(ValueError):
            parse_band("ten gigahertz")

    def test_wavelength_and_doppler(self):
        self.assertAlmostEqual(X_BAND.wavelength_m * 1000, 29.98, places=2)
        self.assertAlmostEqual(X_BAND.doppler_hz(1.0), 66.7, places=1)
        self.assertAlmostEqual(TWO_METRES.doppler_hz(1.0), 0.96, places=2)

    def test_attenuation_matches_itu_table(self):
        # ITU-R P.838: k=0.01217, alpha=1.2571 at 10 GHz, horizontal.
        self.assertAlmostEqual(rain_attenuation_db_km(1.0, X_BAND), 0.01217, places=5)
        self.assertAlmostEqual(rain_attenuation_db_km(12.0, X_BAND), 0.2766, places=3)
        self.assertEqual(rain_attenuation_db_km(0.0, X_BAND), 0.0)
        self.assertGreater(rain_attenuation_db_km(50.0, X_BAND),
                           rain_attenuation_db_km(10.0, X_BAND))

    def test_reflectivity_grows_with_rate(self):
        self.assertAlmostEqual(reflectivity_dbz(REFERENCE_RATE_MM_H), 40.3, places=1)
        self.assertLess(reflectivity_dbz(2.0), reflectivity_dbz(50.0))


class TestScatterers(unittest.TestCase):
    def rng(self):
        return np.random.default_rng(1234)

    def test_rain_spread_scales_with_frequency(self):
        spec = RainSpec(wind_azimuth_deg=0.0)
        _, _, x = rain_doppler(spec, X_BAND, self.rng())
        _, _, l = rain_doppler(spec, parse_band("1296"), self.rng())
        ratio = x["spread_hz"] / l["spread_hz"]
        self.assertAlmostEqual(ratio, 10000.0 / 1296.0, delta=0.5)

    def test_rain_drops_are_sampled_not_fixed(self):
        a = rain_doppler(RainSpec(), X_BAND, np.random.default_rng(1))[2]
        b = rain_doppler(RainSpec(), X_BAND, np.random.default_rng(2))[2]
        self.assertNotAlmostEqual(a["spread_hz"], b["spread_hz"], places=3)
        self.assertGreater(a["median_drop_mm"], 1.0)   # the big drops carry the power

    def test_heavier_rain_is_wider_and_louder(self):
        light = rain_doppler(RainSpec(rate_mm_h=2, wind_azimuth_deg=0.0), X_BAND, self.rng())[2]
        heavy = rain_doppler(RainSpec(rate_mm_h=50, wind_azimuth_deg=0.0), X_BAND, self.rng())[2]
        self.assertGreater(heavy["dbz"], light["dbz"] + 15)
        self.assertGreater(heavy["spread_hz"], light["spread_hz"])

    def test_snow_is_narrower_than_rain_and_wet_snow_is_brighter(self):
        rain = rain_doppler(RainSpec(wind_azimuth_deg=0.0), X_BAND, self.rng())[2]
        dry = snow_doppler(SnowSpec(wind_azimuth_deg=0.0), X_BAND, self.rng())[2]
        wet = snow_doppler(SnowSpec(wet=True, wind_azimuth_deg=0.0), X_BAND, self.rng())[2]
        self.assertLess(dry["spread_hz"], rain["spread_hz"])
        self.assertGreater(wet["dbz"], dry["dbz"] + 5)

    def test_aurora_is_a_vhf_mode(self):
        on_2m = aurora_doppler(AuroraSpec(), TWO_METRES, self.rng())[2]
        on_10g = aurora_doppler(AuroraSpec(), X_BAND, self.rng())[2]
        self.assertAlmostEqual(on_2m["shift_hz"], -577, delta=40)
        self.assertAlmostEqual(on_2m["spread_hz"], 192, delta=40)
        self.assertLess(on_10g["shift_hz"], -20000)      # thrown clear of the filter
        self.assertTrue(on_2m["from_physics"])

    def test_aurora_shift_can_be_set_by_hand(self):
        freqs, weights, info = aurora_doppler(
            AuroraSpec(shift_hz=-120.0, spread_hz=90.0), X_BAND, self.rng())
        self.assertFalse(info["from_physics"])
        self.assertAlmostEqual(info["shift_hz"], -120, delta=10)
        self.assertAlmostEqual(info["spread_hz"], 90, delta=10)

    def test_drift_direction(self):
        toward = aurora_doppler(AuroraSpec(toward=True), TWO_METRES, self.rng())[2]
        self.assertGreater(toward["shift_hz"], 0)


class TestChannel(unittest.TestCase):
    def test_envelope_is_rayleigh(self):
        rng = np.random.default_rng(7)
        freqs, weights, _ = rain_doppler(RainSpec(), X_BAND, rng)
        grid, psd = doppler_spectrum(freqs, weights)
        h = channel(200_000, 44100, grid - grid[psd.argmax()], psd, 600.0, rng)
        # Unit-power Rayleigh: mean 0.886, std 0.463.
        self.assertAlmostEqual(float(np.abs(h).mean()), 0.886, delta=0.02)
        self.assertAlmostEqual(float(np.abs(h).std()), 0.463, delta=0.02)

    def test_doppler_past_nyquist_is_dropped_not_aliased(self):
        rng = np.random.default_rng(3)
        freqs, weights, _ = aurora_doppler(
            AuroraSpec(shift_hz=40_000.0, spread_hz=500.0), X_BAND, rng)
        grid, psd = doppler_spectrum(freqs, weights)
        self.assertEqual(audible_fraction(grid, psd, 600.0, 500.0, 44100), 0.0)
        h = channel(50_000, 44100, grid, psd, 600.0, rng)
        self.assertLess(float(np.abs(h).max()), 1e-9)   # silence, not a fake tone


class TestRenderWithScatter(unittest.TestCase):
    def test_scatter_broadens_the_note(self):
        clean = note_width(Config(snr_db=None, qsb_db=0, drift_hz=0, seed=1))
        snow = note_width(Config(snr_db=None, scatter="snow", seed=1))
        rain = note_width(Config(snr_db=None, scatter="rain", seed=1))
        self.assertLess(clean, 40)
        self.assertLess(clean * 2, snow)
        self.assertLess(snow, rain)

    def test_reflectivity_sets_the_signal_strength(self):
        light = render("cq test", Config(scatter="rain", rain_rate=2, seed=9))
        heavy = render("cq test", Config(scatter="rain", rain_rate=50, seed=9))
        self.assertLess(light.meta["effective_snr_db"], heavy.meta["effective_snr_db"] - 15)
        dry = render("cq test", Config(scatter="snow", seed=9))
        wet = render("cq test", Config(scatter="snow", snow_wet=True, seed=9))
        self.assertLess(dry.meta["effective_snr_db"], wet.meta["effective_snr_db"] - 5)

    def test_weather_level_can_be_turned_off(self):
        # Reflectivity no longer sets the level; the filter loss still counts.
        out = render("cq test", Config(scatter="rain", rain_rate=50,
                                       weather_level=False, snr_db=10.0, seed=9))
        self.assertNotIn("level_offset_db", out.meta["scatter"])
        self.assertAlmostEqual(out.meta["effective_snr_db"], 10.0, delta=1.5)

    def test_retuning_brings_the_return_back_into_the_filter(self):
        tuned = render("cq test", Config(scatter="aurora", band="144M", seed=4))
        raw = render("cq test", Config(scatter="aurora", band="144M", retune=False, seed=4))
        self.assertGreater(tuned.meta["scatter"]["audible_fraction"],
                           raw.meta["scatter"]["audible_fraction"] + 0.3)
        self.assertAlmostEqual(tuned.meta["scatter"]["tuned_out_hz"],
                               tuned.meta["scatter"]["shift_hz"], places=6)

    def test_aurora_at_10ghz_is_hopeless_in_the_report_and_in_the_level(self):
        out = render("cq test", Config(scatter="aurora", band="10G",
                                       snr_db=12.0, seed=4))
        self.assertLess(out.meta["scatter"]["audible_fraction"], 0.05)
        # Power thrown outside the filter is power you do not get.
        self.assertLess(out.meta["scatter"]["filter_loss_db"], -12.0)
        self.assertLess(out.meta["effective_snr_db"], 0.0)

    def test_rain_keeps_nearly_all_of_its_power_in_the_filter(self):
        out = render("cq test", Config(scatter="rain", snr_db=10.0, seed=4))
        self.assertGreater(out.meta["scatter"]["audible_fraction"], 0.8)
        self.assertGreater(out.meta["scatter"]["filter_loss_db"], -1.5)

    def test_path_attenuation_follows_the_path_length(self):
        near = render("cq test", Config(scatter="rain", path_km=0, seed=2))
        far = render("cq test", Config(scatter="rain", path_km=20, seed=2))
        self.assertEqual(near.meta["scatter"]["attenuation_db"], 0.0)
        self.assertGreater(far.meta["scatter"]["attenuation_db"], 4.0)

    def test_unknown_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            render("cq", Config(scatter="hail", seed=1))


class TestRandomness(unittest.TestCase):
    def test_streams_are_independent_of_each_other(self):
        first = streams(1234)
        second = streams(1234)
        for name in STREAMS:
            self.assertEqual(first[name].random(), second[name].random())
        fresh = streams(1234)
        fresh["floor"].random()   # drawing from one stream must not move another
        self.assertEqual(fresh["scatter"].random(), streams(1234)["scatter"].random())

    def test_adding_other_stations_does_not_change_the_weather(self):
        quiet = render("cq test", Config(scatter="rain", qrm_count=0, seed=77))
        busy = render("cq test", Config(scatter="rain", qrm_count=3, seed=77))
        self.assertEqual(quiet.meta["scatter"]["spread_hz"],
                         busy.meta["scatter"]["spread_hz"])
        self.assertEqual(quiet.meta["scatter"]["median_drop_mm"],
                         busy.meta["scatter"]["median_drop_mm"])

    def test_without_a_seed_every_render_is_different(self):
        a = render("cq test", Config(scatter="rain"))
        b = render("cq test", Config(scatter="rain"))
        self.assertNotAlmostEqual(a.meta["scatter"]["spread_hz"],
                                  b.meta["scatter"]["spread_hz"], places=6)
        self.assertFalse(np.allclose(a.samples, b.samples))

    def test_a_seed_brings_the_same_weather_back(self):
        a = render("cq test", Config(scatter="rain", seed=31))
        b = render("cq test", Config(scatter="rain", seed=31))
        np.testing.assert_allclose(a.samples, b.samples)


if __name__ == "__main__":
    unittest.main()
