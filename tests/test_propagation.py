"""Checks on the propagation primitives: bands, Doppler, drops, attenuation."""

from __future__ import annotations

import unittest

import numpy as np

from morsefun.propagation import (REFERENCE_RATE_MM_H, AuroraSpec, aurora_doppler,
                                  drop_diameters, drop_fall_speed, flake_diameters,
                                  flake_fall_speed, moments, parse_band,
                                  rain_attenuation_db_km, reflectivity_dbz,
                                  snow_relative_db, weighted_median)
from morsefun.render import STREAMS, streams
from morsefun.scatter import audible_fraction, channel, doppler_spectrum

X_BAND = parse_band("10G")
TWO_METRES = parse_band("144M")


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

    def test_bistatic_doppler_reduces_to_the_two_way_shift(self):
        # The sum of the closing speeds towards both ends; look both ways down
        # the same path and that sum is 2v, which is the familiar 2v/lambda.
        self.assertAlmostEqual(float(X_BAND.bistatic_doppler_hz(2.0)),
                               float(X_BAND.doppler_hz(1.0)), places=9)

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
        self.assertLess(snow_relative_db(False), snow_relative_db(True))


class TestPopulations(unittest.TestCase):
    def rng(self):
        return np.random.default_rng(1234)

    def test_heavier_rain_has_bigger_drops_falling_faster(self):
        light = drop_diameters(2.0, 20_000, self.rng())
        heavy = drop_diameters(50.0, 20_000, self.rng())
        self.assertLess(light.mean(), heavy.mean())
        self.assertLess(drop_fall_speed(light).mean(), drop_fall_speed(heavy).mean())
        # Atlas, Srivastava and Sekhon: a 2 mm drop falls at 6.5 m/s.
        self.assertAlmostEqual(float(drop_fall_speed(np.array([2.0]))[0]), 6.55, delta=0.1)

    def test_drops_are_sampled_not_fixed(self):
        a = drop_diameters(12.0, 5000, np.random.default_rng(1))
        b = drop_diameters(12.0, 5000, np.random.default_rng(2))
        self.assertNotAlmostEqual(float(a.mean()), float(b.mean()), places=4)

    def test_flakes_fall_at_about_a_metre_a_second(self):
        sizes = flake_diameters(4.0, 5000, self.rng())
        speed = flake_fall_speed(sizes)
        self.assertLess(speed.mean(), 1.5)
        self.assertGreater(flake_fall_speed(sizes, wet=True).mean(), speed.mean())

    def test_weighted_moments(self):
        values = np.array([1.0, 2.0, 3.0])
        weights = np.array([0.0, 1.0, 0.0])
        self.assertEqual(weighted_median(values, weights), 2.0)
        mean, spread = moments(values, np.ones(3))
        self.assertAlmostEqual(mean, 2.0)
        self.assertAlmostEqual(spread, np.sqrt(2.0 / 3.0))


class TestAurora(unittest.TestCase):
    def rng(self):
        return np.random.default_rng(1234)

    def test_aurora_is_a_vhf_mode(self):
        on_2m = aurora_doppler(AuroraSpec(), TWO_METRES, self.rng())[2]
        on_10g = aurora_doppler(AuroraSpec(), X_BAND, self.rng())[2]
        self.assertAlmostEqual(on_2m["shift_hz"], -577, delta=40)
        self.assertAlmostEqual(on_2m["spread_hz"], 192, delta=40)
        self.assertLess(on_10g["shift_hz"], -20000)      # thrown clear of the filter
        self.assertTrue(on_2m["from_physics"])

    def test_aurora_shift_can_be_set_by_hand(self):
        _, _, info = aurora_doppler(
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
        freqs = rng.normal(0.0, 120.0, size=6000)
        grid, psd = doppler_spectrum(freqs, np.full(freqs.size, 1.0 / freqs.size))
        h = channel(200_000, 44100, grid, psd, 600.0, rng)
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


class TestStreams(unittest.TestCase):
    def test_streams_are_independent_of_each_other(self):
        first = streams(1234)
        second = streams(1234)
        for name in STREAMS:
            self.assertEqual(first[name].random(), second[name].random())
        fresh = streams(1234)
        fresh["floor"].random()   # drawing from one stream must not move another
        self.assertEqual(fresh["scatter"].random(), streams(1234)["scatter"].random())


if __name__ == "__main__":
    unittest.main()
