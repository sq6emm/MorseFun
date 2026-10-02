# MorseFun

Morse code generator for the microwave bands: type a message, hear it the way it
would come back off a rain cell at 10 GHz. It writes a WAV file only if you ask
for one.

```bash
python -m morsefun "cq cq de sq6emm sq6emm k" --wpm 23 --tone 600
```

```
playing through aplay
  text      cq cq de sq6emm sq6emm k
  code      -.-. --.-  /  -.-. --.-  /  -.. .  /  ... --.- -.... . -- --  /  ... --.- -.... . -- --  /  -.-
  keying    23 wpm, dit 52.2 ms, standard spacing
  tone      600 Hz, drift ±1.5 Hz, QSB 6 dB
  band      typical: S/N 10 dB in 500 Hz, QRN 0.8/s at +22 dB, measured 8.5 dB
            f0lv at -286 Hz, 17 wpm, +3 dB
  audio     13.0 s, 44100 Hz, 1124 KB, seed 23
```

## Playing

Playback is the default: there is no file, the samples go straight to whatever
command line player the machine already has, over a pipe. `aplay`, `pw-play`,
`paplay`, `ffplay`, `sox play` and `afplay` are recognised, in that order.

```bash
python -m morsefun "cq de sq6emm k" --repeat 3 --gap 2    # three times over, for practice
python -m morsefun --list-players                         # what is installed here
python -m morsefun "cq test" --player "ffplay -nodisp -autoexit -"
```

`--player` takes a full command line ending in the argument that means standard
input, so anything that reads a WAV from a pipe will do. Ctrl-C stops playback.

`-o cq.wav` writes a file instead of playing; `-o cq.wav --play` does both.

## Running it

Everything runs in a container; nothing is installed on the host. Playback needs
the sound device passed in:

```bash
docker build -t morsefun:dev .
docker run --rm --device /dev/snd -v "$PWD":/work -w /work morsefun:dev \
    python -m morsefun "cq cq de sq6emm sq6emm k" --wpm 23 --tone 600
docker run --rm -v "$PWD":/work -w /work morsefun:dev \
    python -m morsefun "cq cq de sq6emm sq6emm k" -o out/cq.wav
docker run --rm -v "$PWD":/work -w /work morsefun:dev python -m unittest discover -s tests
```

The only dependency is NumPy; nothing is needed for playback beyond the player
that is already on the machine.

## Timing

One dit is `1200 ms / WPM` — 52.2 ms at 23 wpm — a dah is three dits, elements
inside a character are one dit apart, characters three and words seven. That is
the PARIS standard: the word PARIS plus its word space is exactly 50 dits, so
`morsefun` at 23 wpm sends 23 of them a minute.

`--effective-wpm` switches on Farnsworth spacing: characters stay at the keying
speed and only the gaps stretch, using the ARRL formula, so slow practice still
trains the sound of a character at full speed.

```bash
python -m morsefun "sq6emm de dl1abc" --wpm 25 --effective-wpm 13
```

## Scatter: rain, snow and aurora

On 10 GHz the wavelength is 30 mm, so **one metre per second of radial motion is
67 Hz of Doppler**. That single number is the whole character of microwave
scatter: a tone bounced off something that is moving, and churning, comes back as
a hiss.

```bash
python -m morsefun "cq cq de sq6emm sq6emm k" --scatter rain --rain-rate 12
python -m morsefun "cq de sq6emm k" --profile heavy-rain --path-km 15
python -m morsefun "cq de sq6emm k" --scatter snow --snow-wet --snow-rate 6
python -m morsefun "cq de sq6emm k" --profile aurora          # 2 m, where it works
```

The scattered signal is not a filtered tone. Each scatterer is sampled
individually, given its own Doppler frequency and its own weight, and the whole
population becomes the power spectrum of a complex Gaussian process that
multiplies the keying envelope. The envelope of that process is Rayleigh
distributed, so the signal flutters the way scatter really does, and the sound is
hiss shaped like the Doppler spectrum rather than a tone with noise added.

| What | How it is sampled |
| --- | --- |
| Rain | Drop sizes from Marshall-Palmer (`N(D) = N0 exp(-4.1 R^-0.21 D)`), fall speeds from Atlas-Ulbrich (`v = 9.65 - 10.3 exp(-0.6 D)` m/s), each drop weighted by `D^6` |
| Snow | Aggregate sizes from Gunn-Marshall, falling at about a metre a second whatever their size, dry flakes 6.5 dB down on the ice dielectric factor, wet ones brighter than rain |
| Aurora | Field-aligned E-region irregularities drifting at hundreds of m/s with a turbulent spread, patchy log-normal reflectors, alive only part of the time |

Turbulence inside the volume does most of the broadening at 10 GHz
(`--turbulence`, 2.5 m/s for rain by default, which is 167 Hz), the wind sets the
mean offset (`--wind`, `--wind-azimuth`, random each render unless you fix it),
and the elevation of the common volume decides how much of the fall speed is
radial (`--elevation`).

Two things follow from the physics and are reported rather than hidden:

**Reflectivity sets the level.** Received power follows the scattering volume's
reflectivity, so 12 mm/h of rain is the yardstick at which `--snr` means what it
says, 45 mm/h comes back 9 dB stronger, and dry snow at 4 mm/h is 14 dB weaker
and barely copyable. `--no-weather-level` turns that coupling off. Rain also
attenuates the path it crosses — ITU-R P.838, 0.277 dB/km at 12 mm/h on 10 GHz —
which `--path-km` applies.

**Aurora is not a 10 GHz mode, and the model says so.** A curtain drifting at
600 m/s puts 579 Hz of Doppler on a 2 m signal, which is the familiar hoarse
note; the same motion at 10 GHz throws it 40 kHz off. The spread cannot be tuned
out, so almost nothing lands inside the filter, the signal is charged for what it
lost, and the report tells you to try `--band 144M` or to set the audio-domain
figures by hand with `--doppler-shift` and `--doppler-spread`.

```
  path      10 GHz, λ 30.0 mm, 67 Hz per m/s
  scatter   rain 12 mm/h, 40 dBZ: Doppler -291 Hz tuned out, spread 173 Hz, 87% inside the filter
            6000 scatterers, median drop 2.7 mm, wind -5.8 m/s radial from 191°
            on the signal: reflectivity +0.0 dB
            path attenuation 1.7 dB
```

By default the return is tuned back onto your own note the way an operator
would; `--no-retune` leaves it where the Doppler put it. `--rician 6` mixes a
direct path back in at 6 dB above the scatter, for a path that is not entirely
over the horizon.

## Truly random

Every render draws from `np.random.SeedSequence(seed).spawn(...)`: one
independent stream each for the keying, the weather, the scatter process, the
noise floor, the crashes, the other stations and the carriers. Turning on QRM
cannot reshuffle the raindrops, and with no `--seed` the entropy comes from the
OS, so no two renders see the same cell. The seed that was used is always
reported, so any band you liked can be heard again.

## The band

The noise is not an ideal AWGN channel; it is a lazy imitation of an HF receiver
on a mediocre day. Four things are generated separately, mixed on one bus and run
through the same IF filter:

| What | Flag | Model |
| --- | --- | --- |
| Noise floor | `--snr`, `--bandwidth`, `--tilt` | Gaussian noise with a 1/f atmospheric tilt, band-limited to the filter |
| Scatter | `--scatter`, see above | rain, snow or aurora, sampled scatterer by scatterer |
| Static crashes (QRN) | `--qrn`, `--qrn-db` | Poisson arrivals, log-normal strengths, each a decaying broadband burst |
| Other stations (QRM) | `--qrm`, `--qrm-db` | Real CW: random callsigns and patterns, own speed, tone offset, drift and fading |
| Heterodynes | `--birdies`, `--birdie-db` | A carrier that drifts slowly and never says anything |

The wanted signal gets its own imperfections: a finite envelope rise and fall
(`--rise-ms`, 5 ms by default, so no key clicks), slow frequency drift
(`--drift`), fading (`--qsb`), and mains hum on the carrier (`--hum`).

`--snr` is the wanted signal against the **noise floor** in the filter
bandwidth, which is how a signal report is meant. Crashes, other stations and
fading sit on top of that, so the `measured` figure in the report — everything
in the key-up gaps against the key-down average — usually comes out a decibel or
two below what you asked for. That gap is the rest of the band, not an error.

Finally the mix passes a tanh soft limiter, the way an AGC rounds off a crash
instead of clipping it square. `--no-limit` turns that off.

## Profiles

```bash
python -m morsefun --list-profiles
```

```
aurora        aurora on 2 m, where it works: hoarse, bursty, shifted down
clean         bare tone, no band at all
contest       a crowded band: four stations and a carrier in a 700 Hz filter
dry-snow      10 GHz off dry snow: narrow, wind-shifted and very weak
heavy-rain    10 GHz off a downpour: 45 mm/h, loud, wide and attenuated
noisy         weak signal, deep QSB, crashes and two other stations
quiet         good conditions, strong signal, the odd crash
rain-scatter  10 GHz off a rain cell: 12 mm/h, hissy and spread ~140 Hz
thunderstorm  heavy static, crashes several times a second
typical       S/N 10 dB in 500 Hz, slow fading, one neighbour (default)
wet-snow      10 GHz off the melting layer: the bright band, much stronger
worn-rig      clean band, drifting VFO and mains hum on the carrier
```

A profile only sets defaults; anything on the command line still wins, so
`--profile noisy --snr 12` is a bad band with a strong signal in it.

## Many files at once

```bash
python -m morsefun --batch practice.txt --outdir out/ --profile noisy
python -m morsefun --batch practice.txt --outdir out/ --play     # save and listen
```

One message per line (`#` comments are skipped), one WAV per line, named after
the message. Each line gets its own seed, so the band is different on every file.

## Repeating a render

Every run reports the seed it used. Pass it back with `--seed` and you get the
same crashes, the same neighbours and the same fades again — useful when you want
the same band conditions at two different speeds.

## Using it as a library

```python
from morsefun import Config, play, render, write_wav

result = render("cq cq de sq6emm sq6emm k", Config(wpm=23, freq=600, snr_db=10, seed=23))
play(result.samples, result.sample_rate)          # straight to the speakers
write_wav("cq.wav", result.samples, result.sample_rate)
print(result.meta["dit_ms"], result.meta["measured_snr_db"])
```

`render` returns the float samples plus a `meta` dict with the code, the timing,
the levels and a note on every station and carrier that was put on the band.
`--json` prints the same thing from the command line.

## Layout

```
morsefun/morse.py     text -> characters -> key-up/key-down timeline
morsefun/synth.py     timeline -> keyed tone, with drift, fading and hum
morsefun/noise.py     noise floor, static crashes, QRM stations, heterodynes
morsefun/propagation.py  bands, drop and flake distributions, Doppler, ITU-R attenuation
morsefun/scatter.py   the Rayleigh scatter channel built from a Doppler spectrum
morsefun/dsp.py       FFT bandpass, slow random modulation, soft limiter
morsefun/render.py    the whole chain, levels and the S/N scaling
morsefun/play.py      hands the samples to the system's audio player
morsefun/profiles.py  named band conditions
morsefun/cli.py       argument parsing, batch mode, the report
morsefun/wav.py       16-bit mono PCM in and out, and in memory
tests/                timing, S/N accuracy, filtering, determinism, playback, CLI
                      propagation: Doppler, ITU attenuation, Rayleigh statistics
```
