# MorseFun

Morse code generator for the microwave bands: type a message, hear it the way it
would come back off a rain cell at 10 GHz. It writes a WAV file only if you ask
for one, and it will [serve itself as a web page](#live-in-a-browser) if you would
rather turn the knobs in a browser.

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

## Live in a browser

```bash
docker compose up -d --build        # then open http://<host>:8086
```

The same renderer behind a small standard-library HTTP server: type a message,
press **send it**, and the page plays what came back and draws the spectrogram of
it, so the Doppler spread of the cell can be seen as well as heard. **Another
front** re-rolls the weather with the same settings, which is the quickest way to
hear how little two rain scatter signals have in common; every render reports its
seed, and pinning the seed brings that front back. Every control can be left
blank, which means *drawn*.

`MORSEFUN_PORT` publishes it somewhere other than 8086. There is nothing to
install beyond NumPy and nothing is written to disk — the last two dozen renders
are kept in memory for the player to fetch.

It is meant to sit behind a reverse proxy on a path of its own. Every URL the
page asks for is relative and routing ignores whatever prefix is left on the
request, so `https://example/morsefun/` works with or without the proxy
stripping the prefix. If the mount point has no trailing slash, tell the page
where it lives — either send `X-Forwarded-Prefix`, or set
`MORSEFUN_BASE_PATH=/morsefun` (`--base-path`), which puts a `<base>` tag in the
page:

```bash
docker run --rm -p 8086:8080 -e MORSEFUN_BASE_PATH=/morsefun morsefun:web
```

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
docker run --rm -p 8086:8080 morsefun:dev                  # the web front end
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
python -m morsefun "cq cq de sq6emm sq6emm k" --profile rain-scatter
python -m morsefun "cq de sq6emm k" --profile light-rain      # almost clean CW
python -m morsefun "cq de sq6emm k" --profile storm-front     # aurora-like
python -m morsefun "cq de sq6emm k" --scatter snow --snow-wet
python -m morsefun "cq de sq6emm k" --profile aurora          # 2 m, where it works
```

The scattered signal is not a filtered tone. Each scatterer is sampled
individually, given its own Doppler frequency and its own weight, and the whole
population becomes the power spectrum of a complex Gaussian process that
multiplies the keying envelope. The envelope of that process is Rayleigh
distributed, so the signal flutters the way scatter really does, and the sound is
hiss shaped like the Doppler spectrum rather than a tone with noise added.

### Why no two rain scatter signals sound alike

Scattering is **bistatic**: the transmitter and the receiver each see their own
share of a scatterer's motion, and only the sum is heard.

```
f = (v . u_a + v . u_b) / lambda
```

`u_a` and `u_b` are the unit vectors from the scatterer to the two stations.
Their sum is `2 cos(beta/2)` long and points along the bisector of the two paths
— which for two stations looking into the same cloud at the same elevation is
*straight up*. Everything follows from that:

* what is heard is the **vertical** motion inside the cell: the fall speed of the
  drops, the updraught of a core, the churn around it, scaled by `sin(elevation)`;
* the **wind largely cancels** between the two ends, and only gets in when the
  path is lopsided — the cell nearer one station than the other — or the cell
  sits off the line between them;
* a long path looks into the cloud at one or two degrees and hears almost
  nothing of all that motion, so the note comes back nearly clean; a short path
  into a convective core at fifteen degrees hears all of it, and comes back a
  rasp no narrower than aurora.

So the cell is **drawn, not configured**. Every render samples a different front:

| Drawn each time | What it does to the sound |
| --- | --- |
| Character, 0 flat stratiform to 1 deep convective | sets the rain rate, the churn, the lift, the shear and how fast all of it changes |
| One to four cores, each with its own rate, lift, size and place in the beam | a multi-peaked spectrum: one louder note with others beside it |
| Lift, and how it changes across the volume | a core going up in one place and raining out in another spans tens of m/s — the aurora-like end of the range |
| Wind, and its shear through the volume | the mean note, and most of the width on a lopsided path |
| Elevation at each end, squint off the path, beamwidth, cell height | the geometry: how much of any of it is heard at all |

What is sampled inside that volume:

| What | How it is sampled |
| --- | --- |
| Rain | Drop sizes from Marshall-Palmer (`N(D) = N0 exp(-4.1 R^-0.21 D)`), fall speeds from Atlas, Srivastava and Sekhon (`v = 9.65 - 10.3 exp(-0.6 D)` m/s), each drop weighted by `D^6` |
| Snow | Aggregate sizes from Gunn-Marshall, falling at about a metre a second whatever their size, dry flakes 6.5 dB down on the ice dielectric factor, wet ones brighter than rain |
| Aurora | Field-aligned E-region irregularities drifting at hundreds of m/s with a turbulent spread, patchy log-normal reflectors, alive only part of the time |

### The cloud does not hold still

A cell is not a filter either. Cores grow and decay, the air through them speeds
up and slows down, the volume the beams share fills and empties, so the spectrum
is rebuilt frame by frame while the message goes out and one stream of white
noise is coloured through it with an overlap-add STFT. Nothing clicks at a frame
boundary — the note just goes on breathing. A convective cell rearranges itself
every second or two, stratiform rain barely at all; `--no-evolve` holds it still.

Any knob given on the command line is kept, and anything left alone is drawn:
`--cell stratiform|showers|convective|storm` (or a number), `--cores`,
`--rain-rate`, `--updraft`, `--turbulence`, `--shear`, `--wind`, `--elevation`,
`--squint`, `--beamwidth`, `--height`, `--depth`, `--evolve-rate`.

And because each station works the same cell down its own path, the other
stations on the band are scattered too, each off its own draw — one a clean note,
the next a rasp. `--no-qrm-scatter` brings them in direct instead.

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

The report says what the draw came up with, and what it sounds like:

```
  text      cq de sq6emm k
  code      -.-. --.-  /  -.. .  /  ... --.- -.... . -- --  /  -.-
  keying    23 wpm, dit 52.2 ms, standard spacing
  tone      600 Hz, drift ±1.0 Hz, QSB 2 dB
  path      10 GHz, λ 30.0 mm, 67 Hz per m/s
            geometry  14.0° this end and 23.9° the other, 20° off the path
            volume 1.0 km up, 0.16×0.06×0.06 km, bistatic 137°
            so 0.36 of any motion is heard, stations 6 km apart
  scatter   storm rain 62.7 mm/h, 57 dBZ: Doppler -33 Hz tuned out, spread 176 Hz, 86% inside the filter
            — rough and wide, hard going
            4 cores  +239 Hz/123 Hz at -9 dB, +121 Hz/162 Hz at -10 dB
            -127 Hz/126 Hz at -5 dB, -28 Hz/119 Hz at -3 dB
            6000 scatterers, median drop 3.2 mm, lift +1.0 m/s ±4.6 per km
            turbulence 6.7 m/s, wind 16 m/s from 115° (-2.5 m/s along the bisector)
            shear 20 m/s per km, rearranging every 1.5 s, QSB 11 dB on top
            on the signal: reflectivity +16.5 dB, outside the filter -0.6 dB
            path attenuation 26.5 dB
  band      storm-front: S/N 24 dB in 500 Hz (asked 8, weather +16), QRN 3/s at +24 dB, measured 20.2 dB
            i4sad at -278 Hz, 24 wpm, -1 dB, storm cell, spread 261 Hz
  audio     7.8 s, 44100 Hz, 674 KB, seed 4
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
OS, so no two renders see the same cell — a different character, different
cores, a different path into it. The seed that was used is always reported, so
any front you liked can be heard again, at another speed if you want.

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
light-rain    10 GHz off layered rain on a long path: almost clean CW
noisy         weak signal, deep QSB, crashes and two other stations
quiet         good conditions, strong signal, the odd crash
rain-scatter  10 GHz off a rain cell: a different front every time
storm-front   10 GHz into a storm: four cores, lift, shear, aurora-like
thunderstorm  heavy static, crashes several times a second
typical       S/N 10 dB, slow fading, one neighbour in the pass band (default)
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

## References

Where a number or a curve in this program came from. Each entry says what it is
actually used for, and the last paragraph says what has no reference at all
because it is a modelling choice rather than a result.

**Precipitation microphysics**

* J. S. Marshall and W. McK. Palmer, "The distribution of raindrops with size",
  *Journal of Meteorology*, vol. 5, no. 4, pp. 165–166, 1948. The exponential
  drop-size distribution `N(D) = N0 exp(-Λ D)` with `Λ = 4.1 R^-0.21` mm⁻¹, and
  the `Z = 200 R^1.6` reflectivity-rate relation — `drop_diameters` and
  `reflectivity_dbz` in `morsefun/propagation.py`.
* D. Atlas, R. C. Srivastava and R. S. Sekhon, "Doppler radar characteristics of
  precipitation at vertical incidence", *Reviews of Geophysics and Space
  Physics*, vol. 11, no. 1, pp. 1–35, 1973. The terminal-velocity fit
  `v = 9.65 - 10.3 exp(-0.6 D)` m/s — `drop_fall_speed`. (Often miscredited,
  including in an earlier version of this code, to Atlas and Ulbrich, whose 1977
  fit is the power law `v = 3.78 D^0.67`.)
* K. L. S. Gunn and J. S. Marshall, "The distribution with size of aggregate
  snowflakes", *Journal of Meteorology*, vol. 15, pp. 452–461, 1958. Aggregate
  sizes as melted diameter, in the commonly quoted form `Λ = 25.5 R^-0.48` —
  `flake_diameters`.

**Radar meteorology**

* R. J. Doviak and D. S. Zrnić, *Doppler Radar and Weather Observations*, 2nd
  ed., Academic Press, 1993 (Dover reprint, 2006). The contributions to the
  Doppler spectrum width that this model builds a cell out of — fall-speed
  dispersion, turbulence, wind shear through the volume and beam broadening —
  and the bright band.
* L. J. Battan, *Radar Observation of the Atmosphere*, University of Chicago
  Press, 1973. The dielectric factor `|K|²` of ice against water, 0.208 against
  0.93, which is the 6.5 dB that dry snow is down on the same rate of rain —
  `snow_relative_db`.

**The bistatic path**

* N. J. Willis, *Bistatic Radar*, Artech House, 1991 (2nd ed., SciTech, 2005).
  The common volume, the bistatic angle `β`, and the Doppler of a bistatic path
  as the sum of the closing rates towards the two ends, `2 cos(β/2)` along the
  bisector — `Geometry` and `cell_doppler` in `morsefun/cell.py`, and
  `Band.bistatic_doppler_hz`.
* Recommendation ITU-R P.838-3, *Specific attenuation model for rain for use in
  prediction methods*, ITU, 2005. The `k` and `α` coefficients for
  `γ = k R^α` dB/km, horizontal polarisation, 1 to 30 GHz —
  `rain_attenuation_db_km`.

**The fading channel**

* R. H. Clarke, "A statistical theory of mobile-radio reception", *Bell System
  Technical Journal*, vol. 47, no. 6, pp. 957–1000, 1968.
* W. C. Jakes (ed.), *Microwave Mobile Communications*, Wiley, 1974. Between
  them, the scatter channel this program uses: a sum over many scatterers is a
  complex Gaussian process whose power spectrum is their Doppler spectrum, so it
  can be synthesised by colouring complex white noise, and its envelope is
  Rayleigh distributed — `morsefun/scatter.py`.
* S. O. Rice, "Statistical properties of a sine wave plus random noise", *Bell
  System Technical Journal*, vol. 27, no. 1, pp. 109–157, 1948. The Rician
  mixture of a steady path with a scattered one — `--rician`,
  `rician_weights`.

**Signal processing**

* R. E. Crochiere, "A weighted overlap-add method of short-time Fourier
  analysis/synthesis", *IEEE Transactions on Acoustics, Speech and Signal
  Processing*, vol. 28, no. 1, pp. 99–102, 1980.
* J. B. Allen and L. R. Rabiner, "A unified approach to short-time Fourier
  analysis and synthesis", *Proceedings of the IEEE*, vol. 65, no. 11,
  pp. 1558–1564, 1977. How the spectrum of a cell is allowed to change while the
  message goes out without a seam at any frame boundary — `evolving_channel`.

**Morse code and the band**

* Recommendation ITU-R M.1677-1, *International Morse code*, ITU, 2009. The code
  itself and the relative timing: dot 1, dash 3, gap between elements 1, between
  characters 3, between words 7 — `morsefun/morse.py`.
* J. Bloom, KE3Z, "A standard for Morse timing using the Farnsworth technique",
  *QEX*, April 1990, pp. 8–9. The Farnsworth formula
  `t_a = (60 c - 37.2 s) / (s c)`, split 3:7 between character and word gaps —
  `Timing._farnsworth_delay`.
* Recommendation ITU-R P.372, *Radio noise*, ITU. Background for the shape of
  the noise floor — atmospheric noise rising towards the low end, which is what
  `--tilt` is — but none of its numbers are used: the floor here is set by
  `--snr`, not by an absolute noise figure.

**Operating practice on 10 GHz**

Rain scatter as it is actually worked — that it is a mode at all, what a station
points at, that the return is tuned back onto the operator's own note, and that
it ranges from a signal with a flutter on it to something as rough as aurora —
comes from amateur microwave literature rather than from any one paper:

* RSGB, *Microwave Handbook*, ed. M. W. Dixon, G3PFR, vols. 1–3, 1989–1992.
* ARRL, *The ARRL UHF/Microwave Experimenter's Manual*, 1990.
* *DUBUS* and *VHF Communications*, whose rain-scatter articles are the running
  record of the mode.

No figure in the code was taken from these; they are what the model is trying to
sound like.

**Tools**

* C. R. Harris et al., "Array programming with NumPy", *Nature*, vol. 585,
  pp. 357–362, 2020. The only dependency.

**What has no reference**

The cell is a model, not a measurement, and these parts of it are chosen rather
than cited: the character axis from 0 to 1 and everything mapped off it; the
Gaussian blob standing in for the beams' intersection, including its cigar
aspect ratio `1/tan(elevation)`; how many cores a front gets and how they are
placed, breathe and wander; the rates at which a cell rearranges itself; the
distributions the geometry is drawn from, which are meant to cover the paths
amateurs actually work rather than any surveyed population; the verdicts in
`sounds_like`; and the QRN, QRM and heterodyne models, which are there to make
the band sound busy and are not models of anything in particular.

## Layout

```
morsefun/morse.py     text -> characters -> key-up/key-down timeline
morsefun/synth.py     timeline -> keyed tone, with drift, fading and hum
morsefun/noise.py     noise floor, static crashes, QRM stations, heterodynes
morsefun/propagation.py  bands, drop and flake distributions, Doppler, ITU-R attenuation
morsefun/cell.py      the cell: cores, bistatic geometry, and how it all evolves
morsefun/scatter.py   the Rayleigh scatter channel, fixed or changing as you listen
morsefun/dsp.py       FFT bandpass, slow random modulation, soft limiter
morsefun/render.py    the whole chain, levels and the S/N scaling
morsefun/play.py      hands the samples to the system's audio player
morsefun/profiles.py  named band conditions
morsefun/cli.py       argument parsing, batch mode, the report
morsefun/wav.py       16-bit mono PCM in and out, and in memory
morsefun/web.py       the browser front end: render, WAV, spectrogram, report
morsefun/page.html    that front end's one page
tests/                timing, S/N accuracy, filtering, determinism, playback, CLI
                      propagation: Doppler, ITU attenuation, Rayleigh statistics
                      cell: bistatic geometry, the draw, the evolving channel
```
