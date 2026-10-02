# MorseFun

Morse code generator for the bands where propagation is the loudest thing in the
signal: type a message and hear it the way it would come back off a rain cell at
10 GHz, off a layer on 2200 m, or off the Moon. It does 23 wpm and it does
[QRSS](#qrss-a-dit-that-lasts-seconds), where one dit lasts three seconds and the
message is read off a waterfall. It writes a WAV file only if you ask for one, and
it will [serve itself as a web page](#live-in-a-browser) if you would rather turn
the knobs in a browser.

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

The same renderer behind a small standard-library HTTP server, laid out the way
the questions come: **pick a band** — LF/MF, HF, VHF/UHF, microwave, or none in
particular — and then **pick what the signal did to get there**, from the modes
that band actually offers. Each one says what it is in a line, and choosing it
renders straight away.

Then type a message, press **send it**, and the page plays what came back and
draws the waterfall of it, with the transform length following the keying: a few
hundred Hz across for 23 wpm, a few Hz across and tenths of a Hz per bin for
QRSS, which is the only way a three-second dit is visible at all. **Another one
like it** re-draws the path with the same settings — a different cell, moonrise
or aeroplane — which is the quickest way to hear how little two signals on the
same mode have in common; every render reports its seed, and pinning the seed
brings that one back.

Every control can be left blank, and blank means *whatever the profile says*,
with the profile's own value shown in the box. That matters more than it sounds:
a form that insists on its own 23 wpm would key a QRSS profile at 23 wpm, and a
transmission that should run for six minutes comes out as thirteen seconds of
something else.

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

## QRSS: a dit that lasts seconds

```bash
python -m morsefun "vvv de sq6emm" --profile lf-qrss              # 2200 m, dit 3 s
python -m morsefun "vvv de sq6emm" --profile 30m-qrss --qrss 10
python -m morsefun "vvv de sq6emm" --profile eme-qrss             # off the Moon
python -m morsefun "vvv" --qrss 3 --band 137.5k --scatter iono --snr -14
```

QRSS is CW slowed down until it stops being something you hear and becomes
something you look at. `--qrss 3` is a three-second dit, which is nothing more
exotic than 0.4 wpm, and the point of it is the bin: a signal that takes three
seconds to say a dit can be read in a bandwidth of about a third of a Hz, which
is 32 dB narrower than a 500 Hz filter. That is the whole trade — the message
takes a thousand times longer and arrives 30 dB stronger.

| `--qrss` | dit | bin | against a 500 Hz filter | `vvv de sq6emm` takes |
| --- | --- | --- | --- | --- |
| 3 | 3 s | 0.33 Hz | +32 dB | 6 min |
| 10 | 10 s | 0.1 Hz | +37 dB | 20 min |
| 30 | 30 s | 33 mHz | +42 dB | 1 h |
| 60 | 60 s | 17 mHz | +45 dB | 2 h |
| 120 | 120 s | 8 mHz | +48 dB | 4 h |

Two things come with `--qrss` unless you ask for something else. The envelope
slows down — a three-second dit with the usual 5 ms edge has sidebands 200 Hz
out, which is absurd when the trace is a third of a Hz wide — and the sample
rate drops to 8 kHz, because nothing above a couple of kHz is wanted and the
file would otherwise be enormous. Even so, a render that would run for hours is
refused rather than attempted.

The report says what the bin is worth, and the model is honest about what takes
it back: **anything that smears the trace wider than the bin.** A path spread of
1 Hz against a 0.33 Hz bin throws away 5 dB of the gain, and so does a rig that
drifts further than the bin is wide — which the report also says, because a
free-running VFO is the usual reason a QRSS trace is unreadable.

## Low bands: a layer that will not hold still

```bash
python -m morsefun "vvv de sq6emm" --profile lf-qrss     # 2200 m
python -m morsefun "vvv de sq6emm" --profile mf-qrss     # 630 m
python -m morsefun "vvv de sq6emm" --profile 30m-qrss    # the knights' band
```

`--scatter iono` is a skywave hop on a low band. At 137 kHz the wavelength is
2.2 km, so a metre per second of motion is 0.9 **milli**Hertz: nothing, unless
you are looking at the signal in a bin a tenth of a Hz wide, which is exactly
what QRSS does. The one thing that matters at these wavelengths is that the
reflecting layer moves up and down, and a one-hop path gets longer by twice the
height change times the sine of the take-off angle:

```
f = 2 (dh/dt) sin(elevation) / lambda
```

Overnight that is a few tenths of a metre per second; at dawn and dusk the layer
can run at several metres a second. On 2200 m that is still a milliHertz or two
and the trace is drawn as a hair, while the same motion on 30 m is a couple of
tenths of a Hz and the trace comes out fuzzy and wandering — which is why QRSS30
and QRSS60 belong on the low bands and QRSS3 is what gets used on HF.

A hop arrives as a **carrier**, not as a diffuse band: the model synthesises each
mode as one coherent tone with a slowly wandering frequency rather than as
filtered noise, because that is what a specular reflection is. When the path
arrives more than one way — two hops, or the two magneto-ionic components — the
modes sit a few milliHertz apart and **beat**, and that beat is the slow QSB
every low-band QRSS screen shows. It falls out of the sum; there is no fading
model behind it. The report gives the period.

`--layer-rate`, `--layer-churn`, `--takeoff` and `--iono-modes` pin what is
otherwise drawn.

```
  text      vvv de sq6emm
  code      ...- ...- ...-  /  -.. .  /  ... --.- -.... . -- --
  keying    0.40 wpm, dit 3 s, standard spacing
  tone      600 Hz, drift ±0.020 Hz, hum 6% at 50 Hz
  path      137.5 kHz, λ 2180.3 m, 0.92 mHz per m/s
  scatter   skywave, 3 mode(s): Doppler -0.32 mHz tuned out, spread 0.35 mHz, 100% inside the filter
            — almost clean CW, just a flutter on it
            layer falling 0.80 m/s at 26° take-off, wandering 0.27 mHz
            modes 0.22 mHz apart, so it fades every 232 min
  band      lf-qrss: S/N -12 dB in 200 Hz, QRN 5/s at +28 dB, measured -16.0 dB
            carrier at +83 Hz, +2 dB
  qrss      QRSS3: dit 3 s, read in a bin 0.333 Hz wide, +28 dB on the 200 Hz filter
            so S/N -12 dB in the filter reads +16 dB on the waterfall
  audio     352.2 s, 8000 Hz, 5503 KB, seed 4
```

## EME: 2.5 seconds behind you

```bash
python -m morsefun "vvv de sq6emm" --profile eme-qrss            # 2 m, QRSS3
python -m morsefun "cq de sq6emm k" --profile eme                # 2 m, 12 wpm
python -m morsefun "t t t t" --scatter eme --band 432M --echo-test
python -m morsefun "cq" --scatter eme --band 10G --libration 0.3
```

`--scatter eme` bounces the signal off the Moon, which is the same kind of thing
as a rain cell — a population of scatterers, each with its own Doppler — with the
geometry replaced by a sphere 1738 km across. Patches are spread over the visible
face and weighted by `cos^n` of the angle from the sub-radar point, because the
Moon answers from the middle far more than from the edge.

**Libration** is what moves them: the Moon's apparent rotation as seen from the
station, a couple of degrees a day, one limb coming towards you and the other
going away. The spread is `2 omega R / lambda`, so it scales straight with the
band:

| Libration | 144 MHz | 432 MHz | 1296 MHz | 10 GHz |
| --- | --- | --- | --- | --- |
| 0.2°/day, a libration minimum | 0.03 Hz | 0.08 Hz | 0.24 Hz | 1.8 Hz |
| 2.5°/day, an ordinary day | 0.33 Hz | 0.98 Hz | 2.9 Hz | 23 Hz |
| 8°/day | 1.0 Hz | 3.1 Hz | 9.4 Hz | 73 Hz |

This is why operators wait for libration minimum, and the model says so in the
arithmetic rather than in a comment: at 0.2°/day a 2 m echo fits inside a QRSS3
bin and keeps all 30 dB of its processing gain, and at 8°/day it does not.

Three more things the path does, all reported:

* **Delay.** 356 500 km at perigee to 406 700 at apogee, so the echo arrives 2.38
  to 2.71 s after it was keyed. `--echo-test` (the same as `--rician 6`) mixes
  your own keying in as well, so you hear it, then hear the Moon answer.
* **Doppler.** The station is carried around the Earth at up to 465 m/s, which is
  ±450 Hz on 2 m and ±30 kHz on 10 GHz, and it *changes* by a few hundredths of a
  Hz per second — tens of Hz across a QRSS message. Rigs track it and so does
  this; `--no-doppler-track` leaves the ramp in and the trace slopes off its own
  line. Leave both off on 10 GHz and nothing lands inside the filter at all,
  which the report will tell you.
* **Faraday rotation** on VHF: the plane of polarisation turns as the TEC drifts,
  so the echo fades to nothing and comes back over minutes. It goes as `1/f^2`,
  so it is 22 dB on 2 m, a couple of dB on 23 cm, and nothing at all on 10 GHz.

Not modelled: the Moon is 11.6 ms deep, so the limb answers later than the
middle. That smears fast CW and is neither here nor there at QRSS speeds.

```
  text      vvv de sq6emm
  code      ...- ...- ...-  /  -.. .  /  ... --.- -.... . -- --
  keying    0.40 wpm, dit 3 s, standard spacing
  tone      600 Hz, drift ±0.050 Hz
  path      144 MHz, λ 2.1 m, 0.96 Hz per m/s
  scatter   moon at 377,408 km: Doppler +203 Hz tracked out, spread 0.106 Hz, 100% inside the filter
            — almost clean CW, just a flutter on it
            the echo is 2.52 s late, libration 0.74° a day, limb 0.248 Hz
            6000 patches, cos^1.6 across the disc
            own Doppler +203 Hz, drifting +0.74 mHz a second, both followed
            Faraday 22 dB nulls every 19 min
  band      eme-qrss: S/N -6 dB in 300 Hz, QRN 0.2/s at +22 dB
  qrss      QRSS3: dit 3 s, read in a bin 0.333 Hz wide, +30 dB on the 300 Hz filter
            so S/N -6 dB in the filter reads +24 dB on the waterfall
  audio     354.7 s, 8000 Hz, 5543 KB, seed 12
```

## Aircraft scatter: a note that slides

```bash
python -m morsefun "cq cq cq de sq6emm k" --profile air-scatter
python -m morsefun "cq de sq6emm k" --scatter air --band 1296 --plane-heading 90
```

Nothing else on the microwave bands sounds like this. A rain cell is a population
of scatterers and comes back as a hiss; an airliner is one lump of metal 60 m
long doing 250 m/s, so it comes back as a **tone that slides**. The Doppler is
bistatic as always, but the velocity is now a single vector and the two unit
vectors swing round as the aeroplane crosses between the stations: it arrives
high, slides down through zero as it passes the middle of the path, and goes out
the other side, while the strength rises and falls with `1/(R_a R_b)^2` and with
how far off each antenna's beam it is.

At 10 GHz that slide is hundreds of Hz over a minute or two, and part of it
slides out of the filter, which the report charges for. On 2 m the same aeroplane
moves the note by a few Hz and nobody notices. A plane flying *along* the path
instead of across it does almost nothing, which is also true.

The aeroplane is not quite a point: it is tens of metres across and its aspect
turns slowly, so several reflecting parts answer at slightly different Doppler.
That is a few Hz of roughness at 10 GHz, derived from the limb speed of something
`L` long turning at the rate the geometry gives it, and it is why the note is not
perfectly clean. `--baseline-km`, `--altitude`, `--plane-speed`,
`--plane-heading`, `--plane-length` and `--beamwidth` pin what is otherwise
drawn; the pass is centred on the message, because nobody keys into an empty sky.

```
  text      cq cq cq de sq6emm sq6emm k
  code      -.-. --.-  /  -.-. --.-  /  -.-. --.-  /  -.. .  /  ... --.- -.... . -- --  /  ... --.- -.......
  keying    18 wpm, dit 66.7 ms, standard spacing
  tone      600 Hz, drift ±1.00 Hz
  path      10 GHz, λ 30.0 mm, 67 Hz per m/s
  scatter   aircraft: Doppler +1054 Hz tuned out, spread 2.12 Hz, 100% inside the filter
            — a tone sliding through the filter
            239 m/s at 9.4 km, heading 67° across a 507 km path
            sliding -12.5 Hz a second, +235 Hz to +0.00 mHz
            73 m of aeroplane, so 2.12 Hz of roughness on the note
            loudest 19 s in, usable for 19 s
  band      air-scatter: S/N 6 dB in 500 Hz, QRN 0.05/s at +22 dB, measured 5.0 dB
  audio     18.6 s, 44100 Hz, 1602 KB, seed 11
```

Tropo gets no model of its own: on `--scatter none` with a band and some fading
it is already what tropo is, a signal that arrives whole and comes and goes. The
`tropo-2m` and `tropo-10g` profiles are exactly that, with the scintillation rate
and the rig drift that each band deserves.

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
LF / MF  — 2200 m and 630 m: a stable path under a floor of lightning, so the trick is to be narrow rather than loud
  lf-qrss       2200 m QRSS3: a trace like a hair, under heavy static
  mf-qrss       630 m QRSS3: still razor thin, a little more layer motion
  lf-cw         2200 m at 8 wpm: readable by ear, buried in lightning

HF  — the ionosphere arriving by more than one path at once, which is where fading comes from
  40m-dx        40 m at night: three hops beating against each other
  30m-qrss      30 m QRSS3: the knights' band, fuzzy and wandering

VHF / UHF  — line of sight, and the three ways past it: tropo, an auroral curtain, and the Moon
  tropo-2m      2 m tropo: steady, with a slow fade on it
  aurora        aurora on 2 m, where it works: hoarse, bursty, shifted down
  eme           2 m moonbounce at 12 wpm: hollow, fluttery, 2.5 s behind you
  eme-qrss      2 m EME QRSS3: the echo 2.5 s late, libration and Faraday

Microwave  — 10 GHz, where the weather is the propagation: rain, snow, aeroplanes and the Moon
  tropo-10g     10 GHz tropo: scintillating, and the rig wanders
  rain-scatter  10 GHz off a rain cell: a different front every time
  light-rain    10 GHz off layered rain on a long path: almost clean CW
  heavy-rain    10 GHz off a downpour: 45 mm/h, loud, wide and attenuated
  storm-front   10 GHz into a storm: four cores, lift, shear, aurora-like
  dry-snow      10 GHz off dry snow: narrow, wind-shifted and very weak
  wet-snow      10 GHz off the melting layer: the bright band, much stronger
  air-scatter   10 GHz off an airliner: a note that slides and is gone
  eme-10g       10 GHz moonbounce: 30 kHz of Doppler tracked out

Any band  — band conditions on their own, with no propagation model behind them
  typical       S/N 10 dB, slow fading, one neighbour in the pass band (default)
  quiet         good conditions, strong signal, the odd crash
  noisy         weak signal, deep QSB, crashes and two other stations
  contest       a crowded band: four stations and a carrier in a 700 Hz filter
  thunderstorm  heavy static, crashes several times a second
  worn-rig      clean band, drifting VFO and mains hum on the carrier
  clean         bare tone, no band at all
```

Profiles are grouped by band, because that is the order the questions come in:
where are you, and then what did the signal do to get here. A profile only sets
defaults; anything on the command line still wins, so `--profile noisy --snr 12`
is a bad band with a strong signal in it, and `--profile lf-qrss --qrss 60` is
2200 m with a minute to each dit.

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

Slow modes are the same call with the keying set from a dit length:

```python
from morsefun import Config, apply_qrss, render

cfg = apply_qrss(Config(scatter="eme", band="144M", snr_db=-6), 3.0)   # QRSS3
result = render("vvv de sq6emm", cfg)
print(result.meta["scatter"]["delay_s"])            # the echo, seconds late
print(result.meta["qrss"]["waterfall_snr_db"])      # what the bin makes of it
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

**The Moon**

* J. V. Evans and T. Hagfors, *Radar Astronomy*, McGraw-Hill, 1968 (their chapter
  on radar studies of the Moon). The lunar echo: a quasi-specular return from near
  the sub-radar point with a diffuse component towards the limb, which is the
  `cos^n` weighting across the disc, and the libration spreading that follows from
  the limbs moving at `omega R` -- `moon_doppler` in `morsefun/moon.py`. The
  perigee and apogee distances, and so the 2.38 to 2.71 s delay, are the usual
  quoted figures.
* J. Taylor, K1JT, and the WSJT development group, *WSJT-X User Guide*. How EME
  Doppler is reckoned and tracked in practice, which is what `--no-doppler-track`
  turns off, and libration spreading as operators meet it.

**The ionosphere on a low band**

* K. Davies, *Ionospheric Radio*, Peter Peregrinus / IEE, 1990. Doppler from a
  reflecting layer that is moving, `f = 2 (dh/dt) sin(elevation) / lambda`, and
  the interference between modes that arrive by different paths -- the whole of
  `morsefun/skywave.py`.

**QRSS**

* M. Dennison, G3XDV, *LF Today: A Guide to Success on 136 and 500 kHz*, 3rd ed.,
  RSGB, 2013. What QRSS is for on the low bands, the dit lengths in use, and why
  the keying has to be shaped.
* A. di Bene, I2PHD, *Argo*. The waterfall program these traces are actually read
  in, and the reason the web front end draws a spectrogram at all.

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

The aeroplane is a model too: the speeds, altitudes and lengths are the ranges an
airliner falls in, the antenna is a Gaussian beam pointed along the path rather
than a measured pattern, the radar cross section never enters (the level is
normalised and `--snr` sets it), and the pass is centred on the message instead of
being drawn in time.

The same goes for the slow modes. The libration rates are drawn from 0.2 to
8 degrees a day because that is the range operators talk about, not from an
ephemeris. The Faraday depth is a rule, 22 dB at 144 MHz falling as `1/f^2`, not
a TEC model. A skywave mode is rendered as one carrier with a slowly wandering
frequency rather than as a diffuse band, which is right for a specular reflection
and wrong in detail. And the QRSS arithmetic uses the conventional rule of thumb
that a dit of `T` seconds is read in a bin of `1/T` Hz, with the smearing penalty
taken as `10 log10(spread / bin)` -- near enough for a report, and not a detection
theory.

## Layout

```
morsefun/morse.py     text -> characters -> key-up/key-down timeline
morsefun/synth.py     timeline -> keyed tone, with drift, fading and hum
morsefun/noise.py     noise floor, static crashes, QRM stations, heterodynes
morsefun/propagation.py  bands, drop and flake distributions, Doppler, ITU-R attenuation
morsefun/cell.py      the cell: cores, bistatic geometry, and how it all evolves
morsefun/skywave.py   a low band: coherent hops off a layer that moves
morsefun/moon.py      EME: libration, the 2.5 second delay, Doppler, Faraday
morsefun/aircraft.py  aircraft scatter: one reflector, moving, sliding
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
                      slow: QRSS bins and gain, skywave modes, the lunar echo
                      aircraft: the slide, the pass, the swept channel
                      web: what the page is told, and what it sends back
```
