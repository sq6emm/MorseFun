"""Checks on the cell model: the geometry, the draw, and what it sounds like.

The claim this file is defending is that rain scatter is not one sound.  The
geometry has to behave the way bistatic scattering does, a drawn cell has to
cover everything from a nearly clean note to an aurora-like rasp, and pinning
a knob has to pin it.
"""

from __future__ import annotations

import unittest

import numpy as np

from morsefun import Config, render
from morsefun.cell import (Cell, Core, Geometry, cell_doppler, character_from_rate,
                           character_name, draw_cell, evolution, parse_character,
                           sounds_like)
from morsefun.propagation import parse_band
from morsefun.scatter import (Component, EvolvingSpectrum, block_size,
                              evolving_channel, frame_count)

X_BAND = parse_band("10G")
TWENTY_THREE_CM = parse_band("1296")


def spread_of(cell: Cell, band=X_BAND, seed: int = 5, scatterers: int = 4000) -> float:
    _, info = cell_doppler(cell, band, np.random.default_rng(seed), scatterers)
    return float(info["spread_hz"])


def note_width(cfg: Config, tone: float = 600.0) -> float:
    """Spectral width of the keyed note in Hz, measured on the render."""
    out = render("eeeeee", cfg)
    power = np.abs(np.fft.rfft(out.samples)) ** 2
    freqs = np.fft.rfftfreq(out.samples.size, 1.0 / out.sample_rate)
    keep = (freqs > tone - 500) & (freqs < tone + 500)
    power, freqs = power[keep], freqs[keep]
    centre = np.sum(freqs * power) / np.sum(power)
    return float(np.sqrt(np.sum(power * (freqs - centre) ** 2) / np.sum(power)))


class TestGeometry(unittest.TestCase):
    def test_a_symmetric_path_listens_straight_up(self):
        for elevation in (1.0, 8.0, 30.0):
            geometry = Geometry(elevation_deg=elevation, far_elevation_deg=elevation,
                                squint_deg=0.0)
            self.assertAlmostEqual(geometry.sensitivity,
                                   np.sin(np.radians(elevation)), places=6)
            self.assertAlmostEqual(geometry.bistatic_angle_deg, 180 - 2 * elevation,
                                   places=4)

    def test_falling_rain_is_heard_scaled_by_the_elevation(self):
        geometry = Geometry(elevation_deg=10.0, far_elevation_deg=10.0, squint_deg=0.0)
        closing = geometry.closing_vectors(np.zeros((3, 1)))
        falling = np.array([[0.0], [0.0], [-7.0]])      # 7 m/s straight down
        hz = float(X_BAND.bistatic_doppler_hz(np.sum(falling * closing, axis=0))[0])
        self.assertAlmostEqual(hz, float(X_BAND.doppler_hz(7.0 * np.sin(np.radians(10.0)))),
                               places=6)
        self.assertGreater(hz, 0.0)                     # falling drops are closing in

    def test_the_wind_cancels_on_a_symmetric_path_and_gets_in_on_a_lopsided_one(self):
        wind = np.array([[20.0], [0.0], [0.0]])         # straight along the path
        even = Geometry(elevation_deg=6.0, far_elevation_deg=6.0, squint_deg=0.0)
        lopsided = Geometry(elevation_deg=20.0, far_elevation_deg=2.0, squint_deg=0.0)
        squinted = Geometry(elevation_deg=6.0, far_elevation_deg=6.0, squint_deg=20.0)

        def hz(geometry):
            closing = geometry.closing_vectors(np.zeros((3, 1)))
            return abs(float(X_BAND.bistatic_doppler_hz(
                np.sum(wind * closing, axis=0))[0]))

        self.assertLess(hz(even), 1.0)          # one end sees it coming, the other going
        self.assertGreater(hz(lopsided), 30.0)
        self.assertGreater(hz(squinted), 30.0)

    def test_the_volume_is_a_cigar_at_low_elevation(self):
        along, across, upright = Geometry(
            elevation_deg=2.0, far_elevation_deg=2.0, beamwidth_deg=2.0).blob_sigma_m()
        self.assertGreater(along, 5 * across)
        steep = Geometry(elevation_deg=30.0, far_elevation_deg=30.0,
                         beamwidth_deg=2.0).blob_sigma_m()
        self.assertLess(steep[0], 3 * steep[1])
        self.assertGreater(upright, 0.0)

    def test_the_stations_end_up_a_sensible_distance_apart(self):
        # 3 km up, seen at 2 degrees from both ends: about 85 km each way.
        geometry = Geometry(elevation_deg=2.0, far_elevation_deg=2.0, height_km=3.0)
        self.assertAlmostEqual(geometry.baseline_km, 171.0, delta=3.0)


class TestCharacter(unittest.TestCase):
    def test_names_follow_the_rate(self):
        self.assertEqual(character_name(character_from_rate(2.0)), "stratiform")
        self.assertEqual(character_name(character_from_rate(10.0)), "showers")
        self.assertEqual(character_name(character_from_rate(25.0)), "convective")
        self.assertEqual(character_name(character_from_rate(70.0)), "storm")

    def test_parsing(self):
        self.assertIsNone(parse_character("auto"))
        self.assertIsNone(parse_character(None))
        self.assertEqual(parse_character("storm"), parse_character("sto"))
        self.assertAlmostEqual(parse_character("0.5"), 0.5)
        self.assertAlmostEqual(parse_character(2.0), 1.0)      # clipped
        with self.assertRaises(ValueError):
            parse_character("drizzle-ish")

    def test_sounds_like_covers_the_whole_range(self):
        verdicts = {sounds_like(hz) for hz in (5, 25, 70, 180, 600)}
        self.assertEqual(len(verdicts), 5)
        self.assertIn("aurora", sounds_like(600))
        self.assertIn("nothing", sounds_like(80, audible=0.0))


class TestDraw(unittest.TestCase):
    def test_what_is_pinned_stays_pinned(self):
        cell = draw_cell(np.random.default_rng(3), "rain", character=0.5,
                         rate_mm_h=20.0, cores=2, updraft_mps=4.0,
                         turbulence_mps=3.0, shear_mps_km=8.0, wind_mps=12.0,
                         wind_azimuth_deg=90.0, elevation_deg=7.0, squint_deg=4.0,
                         beamwidth_deg=1.5, height_km=4.0, depth_km=1.0,
                         evolve_rate_hz=0.25, scintillation_db=6.0)
        self.assertEqual(len(cell.cores), 2)
        self.assertAlmostEqual(cell.character, 0.5)
        self.assertAlmostEqual(cell.wind_mps, 12.0)
        self.assertAlmostEqual(cell.shear_mps_km, 8.0)
        self.assertAlmostEqual(cell.geometry.elevation_deg, 7.0)
        self.assertAlmostEqual(cell.geometry.squint_deg, 4.0)
        self.assertAlmostEqual(cell.scintillation_db, 6.0)
        for core in cell.cores:
            self.assertAlmostEqual(core.updraft_mps, 4.0)
            self.assertAlmostEqual(core.rate_mm_h, 20.0, delta=20.0)

    def test_a_rate_implies_a_kind_of_cloud(self):
        quiet = draw_cell(np.random.default_rng(1), "rain", rate_mm_h=2.0)
        heavy = draw_cell(np.random.default_rng(1), "rain", rate_mm_h=70.0)
        self.assertLess(quiet.character, heavy.character)
        self.assertLess(quiet.cores[0].turbulence_w_mps, heavy.cores[0].turbulence_w_mps)

    def test_no_two_fronts_are_the_same(self):
        spreads = []
        for seed in range(80):
            rng = np.random.default_rng(seed)
            spreads.append(spread_of(draw_cell(rng, "rain"), seed=seed, scatterers=2000))
        spreads = np.array(spreads)
        # Nearly clean CW at one end, aurora-like at the other: the point of
        # the whole model is that this range is wide.
        self.assertLess(np.percentile(spreads, 5), 20.0)
        self.assertGreater(np.percentile(spreads, 95), 90.0)
        self.assertGreater(spreads.max() / max(spreads.min(), 1e-9), 10.0)
        self.assertGreater(len({sounds_like(s) for s in spreads}), 3)

    def test_a_storm_is_rougher_than_layered_rain(self):
        flat = [spread_of(draw_cell(np.random.default_rng(s), "rain", character=0.05),
                          seed=s, scatterers=2000) for s in range(12)]
        storm = [spread_of(draw_cell(np.random.default_rng(s), "rain", character=0.95),
                           seed=s, scatterers=2000) for s in range(12)]
        self.assertLess(np.median(flat) * 3, np.median(storm))

    def test_the_same_cell_sounds_different_from_a_steeper_path(self):
        core = Core(rate_mm_h=20.0, updraft_mps=3.0, turbulence_w_mps=2.0,
                    turbulence_h_mps=1.0)
        shallow = Cell(cores=[core], geometry=Geometry(elevation_deg=1.5,
                                                       far_elevation_deg=1.5))
        steep = Cell(cores=[core], geometry=Geometry(elevation_deg=20.0,
                                                     far_elevation_deg=20.0))
        self.assertLess(spread_of(shallow) * 4, spread_of(steep))

    def test_snow_is_quieter_air_than_rain(self):
        rain = draw_cell(np.random.default_rng(4), "rain")
        snow = draw_cell(np.random.default_rng(4), "snow")
        self.assertLess(snow.character, 0.45)
        self.assertLess(snow.cores[0].turbulence_w_mps, rain.cores[0].turbulence_w_mps)
        self.assertEqual(snow.kind, "snow")

    def test_spread_scales_with_the_band(self):
        cell = draw_cell(np.random.default_rng(9), "rain", character=0.6)
        ratio = spread_of(cell, X_BAND) / spread_of(cell, TWENTY_THREE_CM)
        self.assertAlmostEqual(ratio, 10000.0 / 1296.0, delta=0.6)

    def test_cores_are_reported_one_by_one(self):
        cell = draw_cell(np.random.default_rng(2), "rain", character=0.9, cores=3)
        _, info = cell_doppler(cell, X_BAND, np.random.default_rng(2), 3000)
        self.assertEqual(len(info["cores"]), 3)
        self.assertAlmostEqual(sum(10 ** (c["level_db"] / 10) for c in info["cores"]),
                               1.0, places=6)
        self.assertGreater(info["dbz"], 40.0)

    def test_attenuation_follows_the_path(self):
        cell = draw_cell(np.random.default_rng(2), "rain", rate_mm_h=20.0)
        self.assertEqual(cell.attenuation_db(X_BAND, 0.0), 0.0)
        self.assertGreater(cell.attenuation_db(X_BAND, 20.0), 5.0)
        snow = draw_cell(np.random.default_rng(2), "snow", rate_mm_h=20.0)
        self.assertLess(snow.attenuation_db(X_BAND, 20.0),
                        cell.attenuation_db(X_BAND, 20.0))


class TestEvolvingChannel(unittest.TestCase):
    def components(self, seed=1, evolve=True, character=0.9):
        rng = np.random.default_rng(seed)
        cell = draw_cell(rng, "rain", character=character, elevation_deg=12.0)
        samples, info = cell_doppler(cell, X_BAND, rng, 3000)
        frames = frame_count(200_000, 8192)
        return evolution(cell, samples, frames, 4096 / 44100, rng, evolve), info

    def test_a_narrow_spectrum_gets_a_longer_block(self):
        self.assertGreater(block_size(10.0, 44100, 500_000),
                           block_size(400.0, 44100, 500_000))
        self.assertEqual(block_size(10.0, 44100, 500_000) % 2, 0)

    def test_a_block_is_never_longer_than_a_quarter_of_the_message(self):
        # No transform resolves anything narrower than one over its own length,
        # so a block that spans the whole render buys nothing and leaves nothing
        # to overlap-add.
        self.assertLessEqual(block_size(0.5, 44100, 200_000), 65536)
        self.assertLessEqual(block_size(0.5, 44100, 40_000), 8192)

    def test_the_ends_of_the_overlap_add_do_not_crack(self):
        # The window power goes to zero at the two ends, and dividing by it would
        # leave a spike there louder than the signal it was meant to carry.
        components, _ = self.components()
        spectrum = EvolvingSpectrum(components)
        process = evolving_channel(60_000, 44100, spectrum, 600.0,
                                   np.random.default_rng(1), 32768)
        self.assertLess(float(np.abs(process).max()), 6.0)   # a Rayleigh peak, not a crack
        self.assertAlmostEqual(float(np.mean(np.abs(process) ** 2)), 1.0, places=6)

    def test_the_grid_covers_everywhere_a_core_wanders(self):
        components, _ = self.components()
        spectrum = EvolvingSpectrum(components)
        for frame in (0, spectrum.frames // 2, spectrum.frames - 1):
            psd = spectrum.psd(frame)
            self.assertGreater(psd.sum(), 0.0)
            self.assertLess(psd[0] + psd[-1], 1e-6 * psd.sum())   # nothing clipped
        mean, spread = spectrum.moments()
        self.assertTrue(np.isfinite(mean) and spread > 0)

    def test_the_process_has_unit_power_and_fades_as_the_cell_breathes(self):
        for evolve in (False, True):
            components, _ = self.components(evolve=evolve)
            spectrum = EvolvingSpectrum(components)
            process = evolving_channel(200_000, 44100, spectrum, 600.0,
                                       np.random.default_rng(4), 8192)
            self.assertAlmostEqual(float(np.mean(np.abs(process) ** 2)), 1.0, places=6)
            self.assertTrue(np.isfinite(process).all())
            blocks = np.abs(process[:198_000].reshape(-1, 22_000)).mean(axis=1)
            if evolve:
                self.assertGreater(blocks.std() / blocks.mean(), 0.05)
            else:
                self.assertLess(blocks.std() / blocks.mean(), 0.1)

    def test_holding_the_cell_still_narrows_what_is_heard(self):
        still = EvolvingSpectrum(self.components(evolve=False)[0]).moments()[1]
        alive = EvolvingSpectrum(self.components(evolve=True)[0]).moments()[1]
        self.assertGreater(alive, still)


class TestRetune(unittest.TestCase):
    def test_retune_moves_the_synthesised_spectrum(self):
        rng = np.random.default_rng(0)
        component = Component(freqs=rng.normal(100.0, 5.0, 3000),
                              weights=np.full(3000, 1 / 3000), centre_hz=100.0)
        spectrum = EvolvingSpectrum([component], smooth_hz=2.0)
        spectrum.retune(-100.0)
        psd = spectrum.psd(0)
        self.assertGreater(psd.sum(), 0.0)                       # nothing dropped
        self.assertAlmostEqual(float(spectrum.grid[np.argmax(psd)]), 0.0, delta=3.0)
        process = evolving_channel(200_000, 44100, spectrum, 600.0,
                                   np.random.default_rng(1), 8192)
        power = np.abs(np.fft.fft(process)) ** 2
        freqs = np.fft.fftfreq(process.size, 1.0 / 44100)
        self.assertAlmostEqual(float(np.sum(freqs * power) / power.sum()), 0.0, delta=3.0)

    def test_the_rain_scattered_note_comes_back_on_the_tone(self):
        # The report said the return had been tuned back onto the note while the
        # audio sat tens of Hz away with part of its spectrum thrown away.
        cfg = Config(scatter="rain", snr_db=None, qsb_db=0.0, drift_hz=0.0,
                     scintillation_db=0.0, seed=4)
        out = render("tttttttt", cfg)
        scatter = out.meta["scatter"]
        self.assertGreater(abs(scatter["tuned_out_hz"]), 30.0)   # a shift worth tuning out
        power = np.abs(np.fft.rfft(out.samples)) ** 2
        freqs = np.fft.rfftfreq(out.samples.size, 1.0 / out.sample_rate)
        keep = (freqs > 200) & (freqs < 1000)
        centroid = float(np.sum(freqs[keep] * power[keep]) / power[keep].sum())
        self.assertAlmostEqual(centroid, 600.0, delta=8.0)
        raw = render("tttttttt", Config(scatter="rain", snr_db=None, qsb_db=0.0,
                                        drift_hz=0.0, scintillation_db=0.0,
                                        retune=False, seed=4))
        power = np.abs(np.fft.rfft(raw.samples)) ** 2
        centroid = float(np.sum(freqs[keep] * power[keep]) / power[keep].sum())
        self.assertAlmostEqual(centroid - 600.0, scatter["tuned_out_hz"], delta=10.0)


class TestRenderWithScatter(unittest.TestCase):
    def test_scatter_broadens_the_note(self):
        # The keying itself is worth about 16 Hz of sidebands, so that is the
        # floor any of this is measured against.
        clean = note_width(Config(snr_db=None, qsb_db=0, drift_hz=0, seed=1))
        self.assertLess(clean, 40)
        rain = note_width(Config(snr_db=None, scatter="rain", cell_character=0.9,
                                 elevation_deg=14.0, seed=1))
        snow = note_width(Config(snr_db=None, scatter="snow", snow_rate=4.0,
                                 elevation_deg=14.0, seed=1))
        self.assertGreater(rain, 4 * clean)
        self.assertLess(snow * 2, rain)          # a metre a second, and little churn
        # On a long path dry snow barely touches the note at all.
        flat = note_width(Config(snr_db=None, qsb_db=0, drift_hz=0, scatter="snow",
                                 snow_rate=4.0, elevation_deg=1.5, squint_deg=2.0,
                                 wind_mps=5.0, seed=1))
        self.assertLess(flat, clean * 1.6)

    def test_reflectivity_sets_the_signal_strength(self):
        light = render("cq test", Config(scatter="rain", rain_rate=2, seed=9))
        heavy = render("cq test", Config(scatter="rain", rain_rate=50, seed=9))
        self.assertLess(light.meta["effective_snr_db"],
                        heavy.meta["effective_snr_db"] - 15)
        dry = render("cq test", Config(scatter="snow", snow_rate=1, seed=9))
        wet = render("cq test", Config(scatter="snow", snow_rate=1, snow_wet=True, seed=9))
        self.assertLess(dry.meta["effective_snr_db"], wet.meta["effective_snr_db"] - 5)
        # A millimetre an hour of snow is several dB down on 12 mm/h of rain.
        self.assertLess(dry.meta["scatter"]["level_offset_db"], -4.0)

    def test_weather_level_can_be_turned_off(self):
        out = render("cq test", Config(scatter="rain", rain_rate=50,
                                       weather_level=False, snr_db=10.0, seed=9))
        self.assertNotIn("level_offset_db", out.meta["scatter"])
        self.assertAlmostEqual(out.meta["effective_snr_db"], 10.0, delta=1.5)

    def test_retuning_brings_the_return_back_into_the_filter(self):
        tuned = render("cq test", Config(scatter="aurora", band="144M", seed=4))
        raw = render("cq test", Config(scatter="aurora", band="144M",
                                       retune=False, seed=4))
        self.assertGreater(tuned.meta["scatter"]["audible_fraction"],
                           raw.meta["scatter"]["audible_fraction"] + 0.3)
        self.assertAlmostEqual(tuned.meta["scatter"]["tuned_out_hz"],
                               tuned.meta["scatter"]["shift_hz"], places=6)

    def test_aurora_at_10ghz_is_hopeless_in_the_report_and_in_the_level(self):
        out = render("cq test", Config(scatter="aurora", band="10G", snr_db=12.0, seed=4))
        self.assertLess(out.meta["scatter"]["audible_fraction"], 0.05)
        self.assertLess(out.meta["scatter"]["filter_loss_db"], -12.0)
        self.assertLess(out.meta["effective_snr_db"], 0.0)
        self.assertIn("nothing", out.meta["scatter"]["sounds_like"])

    def test_rain_keeps_nearly_all_of_its_power_in_the_filter(self):
        out = render("cq test", Config(scatter="rain", snr_db=10.0, seed=4))
        self.assertGreater(out.meta["scatter"]["audible_fraction"], 0.8)
        self.assertGreater(out.meta["scatter"]["filter_loss_db"], -1.5)

    def test_path_attenuation_follows_the_path_length(self):
        near = render("cq test", Config(scatter="rain", rain_rate=20, path_km=0, seed=2))
        far = render("cq test", Config(scatter="rain", rain_rate=20, path_km=20, seed=2))
        self.assertEqual(near.meta["scatter"]["attenuation_db"], 0.0)
        self.assertGreater(far.meta["scatter"]["attenuation_db"], 4.0)

    def test_every_station_on_the_cell_sounds_different(self):
        out = render("cq test", Config(scatter="rain", qrm_count=3, seed=5))
        notes = out.meta["noise"]["qrm"]
        self.assertEqual(len(notes), 3)
        spreads = []
        for note in notes:
            self.assertIn("cell, spread", note)
            spreads.append(float(note.split("spread")[1].split("Hz")[0]))
        self.assertEqual(len(set(spreads)), 3)

    def test_the_neighbours_can_come_in_direct_instead(self):
        out = render("cq test", Config(scatter="rain", qrm_count=2,
                                       qrm_scatter=False, seed=5))
        for note in out.meta["noise"]["qrm"]:
            self.assertNotIn("cell", note)

    def test_unknown_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            render("cq", Config(scatter="hail", seed=1))

    def test_the_audio_is_finite_and_level(self):
        out = render("cq de sq6emm", Config(scatter="rain", seed=12))
        self.assertTrue(np.isfinite(out.samples).all())
        self.assertAlmostEqual(float(np.abs(out.samples).max()), 0.89, places=6)


class TestRandomness(unittest.TestCase):
    def test_adding_other_stations_does_not_change_the_weather(self):
        quiet = render("cq test", Config(scatter="rain", qrm_count=0, seed=77))
        busy = render("cq test", Config(scatter="rain", qrm_count=3, seed=77))
        self.assertEqual(quiet.meta["scatter"]["spread_hz"],
                         busy.meta["scatter"]["spread_hz"])
        self.assertEqual(quiet.meta["scatter"]["median_drop_mm"],
                         busy.meta["scatter"]["median_drop_mm"])

    def test_without_a_seed_every_render_sees_another_cloud(self):
        a = render("cq test", Config(scatter="rain"))
        b = render("cq test", Config(scatter="rain"))
        self.assertNotAlmostEqual(a.meta["scatter"]["spread_hz"],
                                  b.meta["scatter"]["spread_hz"], places=6)
        self.assertFalse(np.allclose(a.samples, b.samples))

    def test_a_seed_brings_the_same_cloud_back(self):
        a = render("cq test", Config(scatter="rain", seed=31))
        b = render("cq test", Config(scatter="rain", seed=31))
        np.testing.assert_allclose(a.samples, b.samples)
        self.assertEqual(a.meta["scatter"]["cores"], b.meta["scatter"]["cores"])


if __name__ == "__main__":
    unittest.main()
