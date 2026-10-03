# MorseFun

Morse code generator for the bands where propagation is the loudest thing in the
signal: type a message and hear it the way it would come back off a rain cell at
10 GHz, off a layer on 2200 m, or off the Moon. It does 23 wpm and it does
[QRSS](#qrss-a-dit-that-lasts-seconds), where one dit lasts three seconds and the
message is read off a waterfall. If you have nothing to say it will
[write the message too](#something-to-copy-qsos-and-beacons): both sides of a QSO,
or a beacon, that belongs on the band you picked. It writes a WAV file only if you
ask for one, and it will [serve itself as a web page](#live-in-a-browser) if you
would rather turn the knobs in a browser.

```bash
python -m morsefun "cq cq de sq6emm sq6emm k" --wpm 23 --tone 600
```

```
playing through aplay
  text      cq cq de sq6emm sq6emm k
  code      -.-. --.-  /  -.-. --.-  /  -.. .  /  ... --.- -.... . -- --  /  ... --.- -.... . -- --  /  -.-
  keying    23 wpm, dit 52.2 ms, standard spacing
  tone      600 Hz, drift ±1.15 Hz, QSB 5 dB
  band      typical: S/N 12 dB in 500 Hz, QRN 0.6/s at +22 dB, measured 12.2 dB
            yo8e at +337 Hz, 32 wpm, -3 dB: "test yo8e"
            sq3pp at -370 Hz, 30 wpm, +4 dB: "r r ur8ux de sq3pp gm es tnx fer call <BT> ur rst 559 559"
  audio     13.0 s, 44100 Hz, 1124 KB, seed 23
```

## Playing

Playback is the default: there is no file, the samples go straight to whatever
command line player the machine already has, over a pipe. `aplay`, `pw-play`,
`paplay`, `ffplay`, `sox play` and `afplay` are recognised, in that order.

```bash
python -m morsefun "cq de sq6emm k" --repeat 3 --gap 2    # three times over, a new band each time
python -m morsefun --list-players                         # what is installed here
python -m morsefun "cq test" --player "ffplay -nodisp -autoexit -"
```

`--player` takes a full command line ending in the argument that means standard
input, so anything that reads a WAV from a pipe will do. Ctrl-C stops playback.
`--repeat` does not play the same file again: every pass is rendered afresh, on a
freshly drawn band, with seeds counting on from the first, so practice means the
same text under conditions that keep changing. The extra passes are reported in a
line each.

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
draws the waterfall of it — or set **send** to *a QSO, both sides* or *a beacon*
and let it draw the message for the band and path you picked; the text lands in
the box so you can read along, and editing it switches back to sending what you
typed. The page draws the waterfall with the transform length following the keying: a few
hundred Hz across for 23 wpm, a few Hz across and tenths of a Hz per bin for
QRSS, which is the only way a three-second dit is visible at all. **Another one
like it** re-draws the path with the same settings — a different cell, moonrise
or aeroplane — which is the quickest way to hear how little two signals on the
same mode have in common; every render reports its seed, and pinning the seed
brings that one back.

Every control can be left blank, and blank means *whatever the profile says*,
with the profile's own value shown in the box — or its range, like `6–14`, for a
knob the profile draws afresh every render. That matters more than it sounds:
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

## Something to copy: QSOs and beacons

```bash
python -m morsefun --qso --profile 40m-dx --my-call sq6emm --my-loc jo81lc --my-name dawid
python -m morsefun --qso --profile rain-scatter
python -m morsefun --beacon --profile tropo-10g
```

Instead of a text, let it draw one. `--qso` writes both sides of a contact that
belongs on the profile's band and path, `--beacon` writes what a beacon on that
band sends, and every pass is a new one — `--seed` brings a QSO back together
with the evening it was heard on. `--my-call` puts you in it, calling or
answering as the draw falls; `--my-loc` says where you are if the callsign does
not, and `--my-name` what you give on the air.

```
  text      A  cq cq de e77ib e77ib jn94 k
            B  e77ib de om4lrf om4lrf <AR>
            A  om4lrf de e77ib ur 57s 57s via rs in jn94ip jn94ip hw? om4lrf de e77ib <KN>
            B  e77ib de om4lrf agn pse ur rprt agn <KN>
            A  om4lrf de e77ib r ur 57s 57s 57s 57s in jn94ip jn94ip jn94ip k
            B  e77ib de om4lrf r r tnx ur 57s 57s via rs jn98pq jn98pq hw? <KN>
            A  om4lrf de e77ib rr cfm tnx fer nice qso 73 es gl om4lrf de e77ib <SK>
            B  e77ib de om4lrf qsl tnx fer qso 73 73 <SK>
  script    QSO E77IB (JN94IP, tuzla) with OM4LRF (JN98PQ, banska bystrica), 455 km: 8 overs, scatter, S reports
  other     the other station -41 Hz off, 21 wpm, -2 dB, 4 overs, 1.3 s to turn round
            its own path: hissy, the usual rain scatter note
```

**The callsigns are not random strings.** A call has a prefix that says which
country issued it, in many countries a digit that says which district, and a
suffix of two or three letters, and every country has its own habits — a German
beacon is `DB0` and three letters, a British one `GB3`, an Italian one signs
`/B`. `morsefun/traffic.py` keeps a table of fifty-odd countries with those
habits, the towns their stations are in, and the names their operators go by,
weighted by how often each is heard from the middle of Europe. So a station
comes with a locator that is where its callsign says it is: `SQ6EMM` is Lower
Silesia, so Wrocław or Opole and `JO81`; `GM4` is Scotland before it is
England; `W1` is New England. The same table now supplies the neighbours on the
band, so a QRM station giving its QTH gives one its prefix allows.

**The other station is within reach of the path.** Rain scatter carries 60 to
500 km, tropo 30 to 700, aircraft scatter 150 to 800, aurora works between
northern stations 300 to 2000 km apart, HF is anywhere with Europe most likely,
and the Moon does not care.

**The procedure follows the band and the path.** On HF it is a ragchew: CQ, the
answer, report, name and QTH, half the time the rig, power, antenna and weather
as well, and a proper `73 <SK>`. The reports follow the conditions — `559` at
the profile's 10 dB, `599` above 18, `wid qsb` when the fading is deep — and the
one you are given follows the other station's level against yours. On VHF and
up it is report and locator, each repeated, and a quarter of the time the report
did not make it and is asked for again. Rain scatter gives `S` reports, `57s via
rs`, aurora gives `A` reports, a contest profile gives serials or zones with cut
numbers (`5nn tt7`), the Moon gets the EME procedure — calls, `O`, `RO`, `RRR`,
`73`, each sent for a period — and a QRSS profile gets two overs, because at a
three-second dit anything longer takes an afternoon.

**The other station is a station.** It is rendered on its own note, 15 to 120 Hz
either side of yours, at its own speed within a fifth of yours, a few dB up or
down, with its own drift and fading, and down its own path — the same weather,
the same layer, the same Moon, but a fresh draw of everything that is drawn, so
off a rain cell it has its own spread and its own Doppler. It listens while you
send, and an operator's pause of one to two and a half seconds sits between the
overs. `--other-offset`, `--other-wpm`, `--other-db` and `--turnaround` pin any
of that. `--snr` stays yours: the other station's level is relative to you, and
the key-up gaps that count as quiet are the ones in which neither of you is
sending.

`--two-stations` does the same for a text of your own: every other line is the
other station, the first line being yours, which is how a QSO is written down.

**A beacon identifies and then holds the key down.** VHF and microwave beacons
send callsign and locator at 10 to 15 wpm and then key a carrier for tens of
seconds — the carrier is what the beacon is *for*, the identification only says
whose it is — and some key the carrier first. HF beacons sign `/b` and hold for
less; a QRSS beacon sends its callsign and perhaps a long dash. `--carrier` and
`--no-carrier` settle it, and a beacon keeps its slow speed unless `--wpm` says
otherwise. Short cycles are sent twice, so the shape can be heard.

The hold is written into the message as `[30s]`, and you can write it into any
message yourself: `[30s]` keeps the key down for thirty seconds, `[500ms]` for
half a second, `[2s pause]` keeps it up. The report shows it as written, since
there are no dits and dahs to show.

```bash
python -m morsefun "db0abc jo62qm [30s]" --wpm 12 --profile tropo-2m
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
python -m morsefun "cq de sq6emm k" --scatter snow --snow-wet   # the bright band
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
says and 45 mm/h comes back 9 dB stronger. Snow follows the aggregate relation,
`Z = 2000 R^2` with `R` the melted rate: for the same water a snowfall is bigger,
slower particles, so its *equivalent* reflectivity is higher than rain's, and
what makes snow scatter weak on the air is that snowfall rates are low — a
millimetre an hour melted is 7 dB down on the yardstick — while the melting layer,
the bright band, comes back 7 dB above the dry snow feeding it.
`--no-weather-level` turns that coupling off. Rain also attenuates the path it
crosses — ITU-R P.838, 0.277 dB/km at 12 mm/h on 10 GHz — which `--path-km`
applies, and which is why a storm core is loud and attenuated at once.

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
  tone      600 Hz, drift ±0.873 Hz, QSB 2 dB
  path      10 GHz, λ 30.0 mm, 67 Hz per m/s
            geometry  20.2° this end and 34.5° the other, 20° off the path
            volume 1.0 km up, 0.08×0.04×0.04 km, bistatic 122°
            so 0.48 of any motion is heard, stations 4 km apart
  scatter   storm rain 57.5 mm/h, 50 dBZ: Doppler +52.6 Hz tuned out, spread 222 Hz, 75% inside the filter
            — rough and wide, hard going
            4 cores  +381 Hz/151 Hz at -9 dB, +224 Hz/200 Hz at -10 dB
            -95 Hz/163 Hz at -5 dB, +38 Hz/154 Hz at -3 dB
            6000 scatterers, median drop 3.1 mm, lift +1.0 m/s ±4.5 per km
            turbulence 6.3 m/s, wind 16 m/s from 115° (-2.5 m/s along the bisector)
            shear 19 m/s per km, rearranging every 1.6 s, QSB 10 dB on top
            on the signal: reflectivity +9.9 dB, outside the filter -1.2 dB
            on the way: path attenuation -13.2 dB
  band      storm-front: S/N 3 dB in 500 Hz (asked 7, weather -5), measured 1.9 dB
  audio     7.8 s, 44100 Hz, 674 KB, seed 4
```

By default the return is tuned back onto your own note the way an operator
would, and the audio really is centred there — the report's `tuned out` figure is
measured on the output, not just claimed; `--no-retune` leaves it where the
Doppler put it. `--rician 6` mixes a
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
  band      lf-qrss: S/N -12 dB in 200 Hz, QRN 5.3/s at +28 dB, measured -18.1 dB
            carrier at +83 Hz, +2 dB
  qrss      QRSS3: dit 3 s, read in a bin 0.333 Hz wide, +28 dB on the 200 Hz filter
            so S/N -12 dB in the filter reads +15 dB on the waterfall
  audio     352.2 s, 8000 Hz, 5503 KB, seed 4
```

## HF: a channel that flutters, and a contest weekend

```bash
python -m morsefun "cq de sq6emm k" --profile 40m-dx
python -m morsefun "cq test sq6emm sq6emm test" --profile contest-40m
python -m morsefun "tu 5nn 15" --profile contest-20m
python -m morsefun "cq de sq6emm k" --qrm 8 --qrm-style contest       # any band, a pile-up
```

Above 160 m `--scatter iono` stops being a few carriers and becomes what an HF
receiver actually sees. The same layer motion is a hundred times more Doppler on
40 m than on 2200 m, the reflection is a patch of irregularities rather than a
point, and the hops and the two magneto-ionic components all arrive at once; so
each mode is rendered as a **Rayleigh process a few tenths of a Hz wide**, which
is the Watterson channel that HF modem simulators use (ITU-R F.1487: 0.1 Hz of
spread on a good path, 0.5 moderate, 1 Hz poor). A note like that fades about
once a second per Hz of spread — every two or three seconds on an ordinary night —
and it does so on its own; the profiles turn the QSB knob off because the path
already is the fading. `--layer-churn` and `--takeoff` pin the spread,
`--iono-modes` the number of ways in.

```
  path      7.03 MHz, λ 42.6 m, 46.90 mHz per m/s
  scatter   skywave, 2 mode(s): Doppler +0.358 Hz tuned out, spread 0.378 Hz, 100% inside the filter
            — fading every second or two, the usual HF sound
            layer rising 11.22 m/s at 44° take-off
            each mode a Rayleigh flutter 0.361 Hz wide, modes 0.033 Hz apart
            so it fades about every 2.6 s
  band      40m-dx: S/N 7 dB in 500 Hz, QRN 1.9/s at +22 dB, measured 5.8 dB
```

The **contest** profiles put six to ten other stations inside the one filter,
sending what a contest sounds like — `cq test`, `5nn 14`, serial numbers, `tu`,
`agn?` — at 26 to 40 wpm, with a pile-up sitting within a few tens of Hz of your
own note because that is where a pile-up sits. Every station on the band keeps
going for the whole render: it calls, listens for a second, calls again, each
over freshly drawn, so the band is as busy at the end of the file as at the
start. `--qrm-style contest` does the same to any profile, `--qrm-wpm` sets
how fast they send, and the report lists every one of them with what it was
sending when you tuned in:

```
  scatter   skywave, 2 mode(s): Doppler +0.013 Hz tuned out, spread 0.469 Hz, 100% inside the filter
            — fading every second or two, the usual HF sound
  band      contest-40m: S/N 11 dB in 500 Hz, QRN 1/s at +22 dB, measured 8.5 dB
            ea2ho at -303 Hz, 28 wpm, +1 dB: "tu ea2ho test"
            gm4l at +288 Hz, 28 wpm, -5 dB: "nr 859 859 tu"
            oh7ja at +44 Hz, 34 wpm, -8 dB: "ea9rr 5nn 9"
            yo6ias at -185 Hz, 38 wpm, +2 dB: "sq4l sq4l de yo6ias 5nn 253 k"
            ok7b at +189 Hz, 30 wpm, +2 dB: "on0h on0h de ok7b 5nn 1215 k"
            gm5eba at +48 Hz, 37 wpm, +2 dB: "oh6vt tu 5nn 32 32"
            ok7vo at +195 Hz, 34 wpm, -7 dB: "ve4b ur 5nn 73 bk"
            dl3p at +354 Hz, 33 wpm, +6 dB: "on8i tu 5nn 10 10"
            yo0d at +73 Hz, 34 wpm, -6 dB: "yo0d 599 1 tu"
  audio     10.3 s, 44100 Hz, 887 KB, seed 1
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
  band      eme-qrss: S/N -5 dB in 300 Hz, measured -6.1 dB
  qrss      QRSS3: dit 3 s, read in a bin 0.333 Hz wide, +30 dB on the 300 Hz filter
            so S/N -5 dB in the filter reads +25 dB on the waterfall
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
  band      air-scatter: S/N 8 dB in 500 Hz, measured 7.5 dB
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

The profiles draw too. Most of what a profile says is a range rather than a
number — `typical` is 6 to 14 dB of signal, nought to two neighbours, 3 to 9 dB
of QSB — resolved once per render from the same seed, so two renders of the same
profile are two different evenings on the band and not the same evening with
different noise samples. Only what would change what the mode *is* stays pinned:
the band, the path, a QRSS profile's dit. The web page shows a drawn knob as its
range, `6–14`, in the placeholder. `--repeat`, a batch, and *another one like it*
in the browser all count the seed on, one draw per pass.

## The band

The noise is not an ideal AWGN channel; it is an imitation of a receiver on the
band in question. Four things are generated separately, mixed on one bus and run
through the same IF filter:

| What | Flag | Model |
| --- | --- | --- |
| Noise floor | `--snr`, `--bandwidth`, `--tilt` | Gaussian noise band-limited to the filter, with a 1/f atmospheric tilt on HF and below and flat receiver noise on VHF and up |
| Scatter | `--scatter`, see above | rain, snow, aurora, skywave, the Moon, an aeroplane |
| Static crashes (QRN) | `--qrn`, `--qrn-db` | Poisson arrivals, log-normal strengths, each a decaying broadband burst — lightning, so an HF and LF thing: the VHF and microwave profiles have none |
| Other stations (QRM) | `--qrm`, `--qrm-db`, `--qrm-wpm`, `--qrm-style` | Real CW: callsigns a real licensing authority could have issued, with the town and locator to match, chat or contest exchanges, own speed, tone offset, drift and fading, calling and listening for the whole render |
| Heterodynes | `--birdies`, `--birdie-db` | A carrier that drifts slowly and never says anything |

The wanted signal gets its own imperfections: a finite envelope rise and fall
(`--rise-ms`, 5 ms by default, so no key clicks), slow frequency drift
(`--drift`), fading (`--qsb`), and mains hum on the carrier (`--hum`).

`--snr` is the wanted signal against the **noise floor** in the filter
bandwidth, which is how a signal report is meant. Crashes, other stations and
fading sit on top of that, so the `measured` figure in the report — everything
in the key-up gaps against the key-down average — usually comes out a decibel or
two below what you asked for. That gap is the rest of the band, not an error.

Finally the mix goes through the receiver's **AGC**: a gain that drops within
2 ms when a crash arrives and comes back over 120 ms, the fast setting a CW
operator uses, so a crash is rounded off and the floor sags and recovers behind
it the way it does in a real receiver. It is a gain, not a bend in the waveform —
the tanh limiter it replaces left the third harmonic of the note 29 dB down at
1800 Hz, outside any CW filter, where no receiver puts anything. `--no-limit`
switches the AGC off.

## Profiles

```bash
python -m morsefun --list-profiles
```

```
LF / MF  — 2200 m and 630 m: a stable path under a floor of lightning, so the trick is to be narrow rather than loud
  lf-qrss       2200 m QRSS3: a trace like a hair, under heavy static
  mf-qrss       630 m QRSS3: still razor thin, a little more layer motion
  lf-cw         2200 m at 8 wpm: readable by ear, buried in lightning

HF  — the ionosphere arriving by more than one path at once, each a Rayleigh flutter a few tenths of a Hz wide: that is where the fading comes from
  40m-dx        40 m at night: two or three modes, fluttering and fading every second or two
  contest-40m   40 m on a contest night: six to ten stations in the filter, a pile-up on you
  contest-20m   20 m contest by day: quieter floor, the same wall of stations at 30 wpm
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
  heavy-rain    10 GHz off a downpour: 30 to 70 mm/h, loud, wide and attenuated
  storm-front   10 GHz into a storm: several cores, lift, shear, aurora-like
  dry-snow      10 GHz off dry snow: narrow, wind-shifted, a few dB down
  wet-snow      10 GHz off the melting layer: the bright band, stronger than rain
  air-scatter   10 GHz off an airliner: a note that slides and is gone
  eme-10g       10 GHz moonbounce: 30 kHz of Doppler tracked out

Any band  — band conditions on their own, with no propagation model behind them
  typical       S/N 6 to 14 dB, slow fading, a neighbour or two in the pass band (default)
  quiet         good conditions, strong signal, the odd crash
  noisy         weak signal, deep QSB, crashes and other stations
  contest       a crowded band: four to seven stations and a carrier in a 700 Hz filter
  thunderstorm  heavy static, crashes several times a second
  worn-rig      clean band, drifting VFO and mains hum on the carrier
  clean         bare tone, no band at all
```

Profiles are grouped by band, because that is the order the questions come in:
where are you, and then what did the signal do to get here. A profile only sets
defaults, most of them ranges drawn afresh for every render; anything on the
command line still wins, so `--profile noisy --snr 12` is a bad band with a strong
signal in it, and `--profile lf-qrss --qrss 60` is 2200 m with a minute to each
dit. The noise floor follows the band: lightning and the 1/f tilt belong to HF
and below, and a 2 m or 10 GHz profile has white receiver noise and nothing else.

## Many files at once

```bash
python -m morsefun --batch practice.txt --outdir out/ --profile noisy
python -m morsefun --batch practice.txt --outdir out/ --play     # save and listen
```

One message per line (`#` comments are skipped), one WAV per line, named after
the message. Each line gets its own seed, so the band is different on every file.

## Repeating a render

Every run reports the seed it used. Pass it back with `--seed` and you get the
same evening on the band — the same draw of the profile, the same crashes, the
same neighbours and the same fades — useful when you want the same conditions at
two different speeds. A `--repeat` or a batch run with `--seed` comes back whole,
because each pass counts on from it.

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

A drawn QSO is the same call again, with the message written for you:

```python
import numpy as np
from morsefun import Config, compose, render

cfg = Config(band="7.03M", scatter="iono", wpm=20, seed=7)
script = compose("qso", cfg, np.random.default_rng(7), my_call="sq6emm", my_loc="jo81lc")
cfg.two_stations = script.two_stations
result = render(script.text, cfg)
print(script.note)                                  # who, where, how far, how many overs
print(result.meta["other_station"])                 # what the other side was rendered as
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
  `flake_diameters` — and the aggregate-snow reflectivity relation
  `Z = 2000 R^2`, melted rate, that sets a snowfall's level —
  `reflectivity_dbz`.

**Radar meteorology**

* R. J. Doviak and D. S. Zrnić, *Doppler Radar and Weather Observations*, 2nd
  ed., Academic Press, 1993 (Dover reprint, 2006). The contributions to the
  Doppler spectrum width that this model builds a cell out of — fall-speed
  dispersion, turbulence, wind shear through the volume and beam broadening —
  and the bright band.
* L. J. Battan, *Radar Observation of the Atmosphere*, University of Chicago
  Press, 1973. The dielectric factor `|K|²` of ice against water, 0.208 against
  0.93. An earlier version charged dry snow that 6.5 dB on top of the rain Z-R
  relation; it is already inside the measured snow relation above, which is why
  that version had snow 14 dB weaker than it is. The bright band is taken as
  7 dB over the dry snow above it, from Doviak and Zrnić.

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
  the interference between modes that arrive by different paths -- the low-band
  half of `morsefun/skywave.py`.
* C. C. Watterson, J. R. Juroshek and W. D. Bensema, "Experimental confirmation
  of an HF channel model", *IEEE Transactions on Communication Technology*,
  vol. 18, no. 6, pp. 792–803, 1970. Each HF mode as a Gaussian-spread Rayleigh
  process -- `iono_components`.
* Recommendation ITU-R F.1487, *Testing of HF modems with bandwidths of up to
  about 12 kHz using ionospheric channel simulators*, ITU, 2000. The Doppler
  spreads a path is given -- 0.1 Hz good, 0.5 Hz moderate, 1 Hz poor -- which is
  the range `HF_CHURN_RANGE` is chosen to cover at a typical take-off angle.

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
  `rician_weights` — and the level-crossing rate behind "fades about every
  N s" in the HF report.

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
a TEC model. A low-band skywave mode is rendered as one carrier with a slowly
wandering frequency rather than as a diffuse band, which is right for a specular
reflection and wrong in detail, and the line between that and the diffuse HF
channel is drawn at 1.5 MHz because it has to be drawn somewhere. The AGC's
2 ms attack and 120 ms release are a CW operator's fast setting, not a
measurement of any rig. And the QRSS arithmetic uses the conventional rule of thumb
that a dit of `T` seconds is read in a bin of `1/T` Hz, with the smearing penalty
taken as `10 log10(spread / bin)` -- near enough for a report, and not a detection
theory.

## Layout

```
morsefun/morse.py     text -> characters -> key-up/key-down timeline
morsefun/synth.py     timeline -> keyed tone, with drift, fading and hum
morsefun/noise.py     noise floor, static crashes, QRM stations, heterodynes
morsefun/traffic.py   who is on the air: callsigns by country, towns and locators, QSOs and beacons
morsefun/propagation.py  bands, drop and flake distributions, Doppler, ITU-R attenuation
morsefun/cell.py      the cell: cores, bistatic geometry, and how it all evolves
morsefun/skywave.py   skywave: coherent hops on a low band, Rayleigh flutter on HF
morsefun/moon.py      EME: libration, the 2.5 second delay, Doppler, Faraday
morsefun/aircraft.py  aircraft scatter: one reflector, moving, sliding
morsefun/scatter.py   the Rayleigh scatter channel, fixed or changing as you listen
morsefun/dsp.py       FFT bandpass, slow random modulation, the AGC
morsefun/render.py    the whole chain, levels and the S/N scaling, the other side of a QSO
morsefun/play.py      hands the samples to the system's audio player
morsefun/profiles.py  named band conditions, as ranges drawn once per render
morsefun/cli.py       argument parsing, batch mode, the report
morsefun/wav.py       16-bit mono PCM in and out, and in memory
morsefun/web.py       the browser front end: render, WAV, spectrogram, report
morsefun/page.html    that front end's one page
tests/                timing, S/N accuracy, the AGC, determinism, playback, CLI, a contest
                      propagation: Doppler, ITU attenuation, Rayleigh statistics
                      cell: bistatic geometry, the draw, the evolving channel
                      slow: QRSS bins and gain, skywave modes, HF fading, the lunar echo
                      aircraft: the slide, the pass, the swept channel
                      traffic: callsigns and locators, the procedure on each band, two stations, holds
                      web: what the page is told, and what it sends back
```
