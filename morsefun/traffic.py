"""Something to copy: stations, QSOs and beacons drawn the way they are heard.

A callsign is not a random string.  It has a prefix that says which country
issued it, a digit that in many countries says which district, and a suffix of
two or three letters -- one for a contest call, three for a newer licence --
and every country has its own habits: a German beacon is ``DB0`` and three
letters, a British one ``GB3``, a French one ``F`` a digit ``Z`` and two.  This
module keeps a table of those habits, and of the towns the stations are in, so
a station comes with a locator that is where its callsign says it is, a name
its operator would have, and a town in the right country.

On top of that it writes two kinds of message:

* a **QSO**, both sides of it, in the shape operators actually use -- a CQ, an
  answer, the exchange of report, name and QTH on HF, report and locator on
  VHF and up, serials in a contest, ``O`` / ``RO`` / ``RRR`` off the Moon, an
  ``A`` tone report on aurora -- and the other station chosen within the
  distance the path can carry;
* a **beacon**, identifying itself with callsign and locator the way the
  beacons on that band do, with the long carrier most of them key before or
  after the identification.

Everything is drawn from the caller's generator, so a seed brings the same QSO
back, and the text is ordinary message text: ``[30s]`` is the carrier.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

import numpy as np

from .propagation import parse_band

# ---------------------------------------------------------------------------
# Who is on the air
# ---------------------------------------------------------------------------

#: A place: town, latitude, longitude and, where the country numbers its
#: districts, the digit a call from there carries.
Place = tuple

@dataclass(frozen=True)
class Country:
    """How one country issues callsigns, and where its stations are.

    ``calls`` are templates with a weight each: ``#`` is a digit from
    ``digits`` (or the district digit of the place drawn), ``@`` any letter,
    ``[...]`` one of the characters inside, anything else literal.  ``beacons``
    are templates for the beacon callsigns the country uses.
    """

    name: str
    calls: tuple[tuple[str, float], ...]
    places: tuple[Place, ...]
    names: tuple[str, ...]
    digits: str = "123456789"
    beacons: tuple[str, ...] = ()
    weight: float = 1.0          # how often it is heard, from the middle of Europe
    zone: int = 14               # CQ zone, for a contest exchange
    continent: str = "EU"


COUNTRIES: tuple[Country, ...] = (
    Country(
        "Poland", (("SP#@@", 2.0), ("SP#@@@", 3.5), ("SQ#@@@", 3.5), ("SQ#@@", 0.5),
                   ("SO#@@@", 0.8), ("SN#@@", 0.2), ("3Z#@@@", 0.3), ("HF#@@@", 0.2)),
        (("wroclaw", 51.11, 17.03, "6"), ("opole", 50.67, 17.93, "6"),
         ("warszawa", 52.23, 21.01, "5"), ("krakow", 50.06, 19.94, "9"),
         ("katowice", 50.26, 19.02, "9"), ("poznan", 52.41, 16.93, "3"),
         ("gdansk", 54.35, 18.65, "2"), ("bydgoszcz", 53.12, 18.01, "2"),
         ("torun", 53.01, 18.60, "2"), ("lodz", 51.77, 19.46, "7"),
         ("kielce", 50.87, 20.63, "7"), ("szczecin", 53.43, 14.55, "1"),
         ("zielona gora", 51.94, 15.50, "1"), ("lublin", 51.25, 22.57, "8"),
         ("rzeszow", 50.04, 22.00, "8"), ("olsztyn", 53.78, 20.49, "4"),
         ("bialystok", 53.13, 23.16, "4")),
        ("jan", "piotr", "tomek", "marek", "andrzej", "wojtek", "darek", "jacek", "adam",
         "zbig", "kuba", "michal", "robert", "pawel", "leszek", "janusz", "dawid",
         "krzys", "maciek", "rysiek"),
        beacons=("SR#@@@", "SR#VHF", "SR#UHF", "SR#SHF"), weight=3.0, zone=15),
    Country(
        "Germany", (("DL#@@", 2.0), ("DL#@@@", 4.0), ("DJ#@@", 0.6), ("DJ#@@@", 0.6),
                    ("DK#@@", 0.8), ("DK#@@@", 1.0), ("DG#@@@", 1.2), ("DO#@@@", 1.2),
                    ("DF#@@@", 1.0), ("DH#@@@", 0.6), ("DB#@@@", 0.5), ("DM#@@@", 0.5),
                    ("DC#@@@", 0.5), ("DD#@@@", 0.4), ("DL0@@", 0.2)),
        (("berlin", 52.52, 13.40), ("hamburg", 53.55, 9.99), ("muenchen", 48.14, 11.58),
         ("koeln", 50.94, 6.96), ("frankfurt", 50.11, 8.68), ("dresden", 51.05, 13.74),
         ("leipzig", 51.34, 12.37), ("hannover", 52.37, 9.73), ("bremen", 53.08, 8.80),
         ("nuernberg", 49.45, 11.08), ("stuttgart", 48.78, 9.18), ("kassel", 51.31, 9.49),
         ("rostock", 54.09, 12.10), ("kiel", 54.32, 10.14), ("erfurt", 50.98, 11.03),
         ("augsburg", 48.37, 10.90), ("freiburg", 47.99, 7.85), ("magdeburg", 52.13, 11.63),
         ("cottbus", 51.76, 14.33), ("goerlitz", 51.15, 14.99)),
        ("uli", "hans", "klaus", "peter", "wolf", "dieter", "bernd", "rolf", "horst", "gerd",
         "jens", "frank", "ralf", "thomas", "uwe", "jochen", "heinz", "manfred", "kurt", "lutz"),
        beacons=("DB0@@@", "DM0@@@"), weight=5.0, zone=14),
    Country(
        "Czech Republic", (("OK#@@", 1.5), ("OK#@@@", 3.0), ("OL#@@@", 0.2)),
        (("praha", 50.08, 14.44, "1"), ("plzen", 49.75, 13.38, "1"),
         ("liberec", 50.77, 15.06, "1"), ("hradec kralove", 50.21, 15.83, "1"),
         ("ceske budejovice", 48.97, 14.47, "1"), ("pardubice", 50.03, 15.78, "1"),
         ("brno", 49.20, 16.61, "2"), ("ostrava", 49.83, 18.26, "2"),
         ("olomouc", 49.59, 17.25, "2"), ("zlin", 49.22, 17.67, "2")),
        ("pavel", "jiri", "petr", "karel", "honza", "milan", "zdenek", "josef", "vlada",
         "mirek", "tomas", "jarda"),
        digits="12", beacons=("OK0E@", "OK0@@"), weight=1.8, zone=15),
    Country(
        "Slovakia", (("OM#@@", 1.0), ("OM#@@@", 2.0)),
        (("bratislava", 48.15, 17.11, "1"), ("nitra", 48.31, 18.09, "5"),
         ("zilina", 49.22, 18.74, "6"), ("banska bystrica", 48.74, 19.15, "4"),
         ("kosice", 48.72, 21.26, "8"), ("presov", 49.00, 21.24, "8")),
        ("jozef", "peter", "milan", "stefan", "juraj", "marian", "ivan", "laco"),
        digits="1345678", beacons=("OM0@@@",), weight=1.0, zone=15),
    Country(
        "Austria", (("OE#@@", 0.8), ("OE#@@@", 2.5)),
        (("wien", 48.21, 16.37, "1"), ("salzburg", 47.80, 13.04, "2"),
         ("st poelten", 48.20, 15.62, "3"), ("eisenstadt", 47.85, 16.52, "4"),
         ("linz", 48.31, 14.29, "5"), ("graz", 47.07, 15.44, "6"),
         ("innsbruck", 47.27, 11.40, "7"), ("klagenfurt", 46.62, 14.31, "8"),
         ("bregenz", 47.50, 9.75, "9")),
        ("franz", "fritz", "josef", "hans", "gerhard", "kurt", "walter", "herbert", "erwin", "sepp"),
        beacons=("OE#X@@",), weight=1.0, zone=15),
    Country(
        "Hungary", (("HA#@@", 1.5), ("HA#@@@", 1.5), ("HG#@@", 0.6), ("HG#@@@", 0.8)),
        (("budapest", 47.50, 19.04, "5"), ("gyor", 47.69, 17.63, "1"),
         ("sopron", 47.69, 16.59, "1"), ("pecs", 46.07, 18.23, "3"),
         ("miskolc", 48.10, 20.78, "6"), ("debrecen", 47.53, 21.63, "0"),
         ("szeged", 46.25, 20.15, "8"), ("szekesfehervar", 47.19, 18.41, "7")),
        ("laci", "gabor", "tibor", "zoli", "pista", "feri", "karcsi", "jozsi", "imre", "andras"),
        digits="0135678", beacons=("HG#B@@",), weight=0.9, zone=15),
    Country(
        "Slovenia", (("S5#@", 0.3), ("S5#@@", 1.5), ("S5#@@@", 1.0)),
        (("ljubljana", 46.05, 14.51), ("maribor", 46.56, 15.65), ("celje", 46.24, 15.27),
         ("kranj", 46.24, 14.36), ("koper", 45.55, 13.73), ("nova gorica", 45.96, 13.65)),
        ("tone", "janez", "marko", "igor", "boris", "franci", "miro", "lojze"),
        digits="0123456789", beacons=("S55Z@@",), weight=0.6, zone=15),
    Country(
        "Croatia", (("9A#@", 0.2), ("9A#@@", 1.5), ("9A#@@@", 1.0)),
        (("zagreb", 45.81, 15.98), ("split", 43.51, 16.44), ("rijeka", 45.33, 14.44),
         ("osijek", 45.56, 18.69), ("zadar", 44.12, 15.23), ("pula", 44.87, 13.85)),
        ("ivan", "marko", "zeljko", "dado", "tomo", "ante", "boris", "drago"),
        digits="23456789", beacons=("9A0@@@",), weight=0.7, zone=15),
    Country(
        "Serbia", (("YU#@@", 1.0), ("YU#@@@", 1.0), ("YT#@@", 0.5), ("YT#@@@", 0.5)),
        (("beograd", 44.80, 20.47), ("novi sad", 45.25, 19.85), ("nis", 43.32, 21.90),
         ("kragujevac", 44.01, 20.91), ("subotica", 46.10, 19.67)),
        ("zoran", "dragan", "milan", "goran", "nenad", "boban", "pedja", "sasa"),
        weight=0.5, zone=15),
    Country(
        "Bosnia and Herzegovina", (("E7#@@", 1.0), ("E7#@@@", 1.0)),
        (("sarajevo", 43.86, 18.41), ("banja luka", 44.78, 17.19), ("tuzla", 44.54, 18.68),
         ("mostar", 43.34, 17.81)),
        ("emir", "mirza", "goran", "dragan", "zoran", "amir"),
        digits="1234567", weight=0.3, zone=15),
    Country(
        "North Macedonia", (("Z3#@@", 1.0), ("Z3#@@@", 0.6)),
        (("skopje", 42.00, 21.43), ("bitola", 41.03, 21.33), ("ohrid", 41.12, 20.80)),
        ("goran", "zoran", "igor", "nikola", "dragan"),
        digits="123456789", weight=0.2, zone=15),
    Country(
        "Romania", (("YO#@@", 1.5), ("YO#@@@", 2.5), ("YP#@@@", 0.2), ("YR#@@@", 0.1)),
        (("bucuresti", 44.43, 26.10, "3"), ("cluj", 46.77, 23.59, "5"),
         ("oradea", 47.05, 21.93, "5"), ("timisoara", 45.75, 21.23, "2"),
         ("iasi", 47.16, 27.59, "8"), ("constanta", 44.18, 28.63, "4"),
         ("brasov", 45.66, 25.61, "6"), ("craiova", 44.33, 23.79, "7"),
         ("ploiesti", 44.94, 26.02, "9")),
        ("dan", "mihai", "radu", "ion", "gigi", "nicu", "sorin", "florin", "adi", "cristi"),
        digits="23456789", beacons=("YO#KX@",), weight=0.9, zone=20),
    Country(
        "Bulgaria", (("LZ#@@", 1.5), ("LZ#@@@", 1.5)),
        (("sofia", 42.70, 23.32, "1"), ("plovdiv", 42.14, 24.75, "1"),
         ("varna", 43.21, 27.91, "2"), ("burgas", 42.50, 27.47, "2"),
         ("ruse", 43.85, 25.95, "2"), ("stara zagora", 42.43, 25.63, "2")),
        ("ivan", "georgi", "petar", "dimitar", "nikola", "krasi", "mitko", "vasil"),
        digits="12", beacons=("LZ0@@@",), weight=0.7, zone=20),
    Country(
        "Greece", (("SV#@@", 0.6), ("SV#@@@", 2.0)),
        (("athina", 37.98, 23.73, "1"), ("thessaloniki", 40.64, 22.94, "2"),
         ("patra", 38.25, 21.73, "3"), ("larisa", 39.64, 22.42, "4"),
         ("ioannina", 39.67, 20.85, "6"), ("iraklio", 35.34, 25.13, "9")),
        ("nikos", "kostas", "yannis", "dimitris", "makis", "takis", "giorgos", "manolis"),
        digits="1234679", weight=0.5, zone=20),
    Country(
        "Italy", (("I#@@", 0.6), ("I#@@@", 1.2), ("IK#@@@", 2.0), ("IZ#@@@", 2.5),
                  ("IW#@@@", 0.8), ("IU#@@@", 1.5)),
        (("roma", 41.90, 12.50, "0"), ("torino", 45.07, 7.69, "1"), ("genova", 44.41, 8.93, "1"),
         ("milano", 45.46, 9.19, "2"), ("brescia", 45.54, 10.22, "2"),
         ("venezia", 45.44, 12.33, "3"), ("verona", 45.44, 10.99, "3"),
         ("padova", 45.41, 11.88, "3"), ("bologna", 44.49, 11.34, "4"),
         ("firenze", 43.77, 11.26, "5"), ("ancona", 43.62, 13.52, "6"),
         ("bari", 41.12, 16.87, "7"), ("napoli", 40.85, 14.27, "8")),
        ("luca", "marco", "paolo", "gianni", "pino", "franco", "aldo", "enzo", "beppe",
         "sergio", "mario", "dino", "nino", "carlo"),
        digits="012345678", beacons=("IQ#@@/B", "I#@@@/B"), weight=2.5, zone=15),
    Country(
        "Sicily", (("IT9@@@", 1.0), ("IT9@@", 0.3)),
        (("palermo", 38.12, 13.36), ("catania", 37.50, 15.09), ("messina", 38.19, 15.55)),
        ("salvo", "pippo", "nino", "turi", "enzo", "carlo"),
        beacons=("IT9@@@/B",), weight=0.3, zone=15),
    Country(
        "Sardinia", (("IS0@@@", 1.0),),
        (("cagliari", 39.22, 9.12), ("sassari", 40.73, 8.56), ("olbia", 40.92, 9.50)),
        ("efisio", "gianni", "marco", "sergio", "pino"),
        weight=0.15, zone=15),
    Country(
        "Friuli", (("IV3@@@", 1.0), ("IV3@@", 0.3)),
        (("trieste", 45.65, 13.78), ("udine", 46.06, 13.24), ("pordenone", 45.96, 12.66)),
        ("mauro", "paolo", "renzo", "luca", "franco"),
        beacons=("IV3@@@/B",), weight=0.3, zone=15),
    Country(
        "Trentino", (("IN3@@@", 1.0),),
        (("trento", 46.07, 11.12), ("bolzano", 46.50, 11.35)),
        ("walter", "luca", "paolo", "franz"),
        weight=0.15, zone=15),
    Country(
        "France", (("F#@@", 0.5), ("F#@@@", 4.0)),
        (("paris", 48.86, 2.35), ("lyon", 45.76, 4.84), ("marseille", 43.30, 5.37),
         ("toulouse", 43.60, 1.44), ("nice", 43.71, 7.26), ("nantes", 47.22, -1.55),
         ("strasbourg", 48.57, 7.75), ("bordeaux", 44.84, -0.58), ("lille", 50.63, 3.06),
         ("rennes", 48.11, -1.68), ("grenoble", 45.19, 5.72), ("dijon", 47.32, 5.04),
         ("brest", 48.39, -4.49), ("tours", 47.39, 0.69), ("metz", 49.12, 6.18)),
        ("jean", "pierre", "michel", "alain", "marc", "rene", "andre", "luc", "yves",
         "gerard", "bernard", "claude", "didier", "serge", "paul"),
        digits="14556688", beacons=("F#Z@@",), weight=1.8, zone=14),
    Country(
        "Spain", (("EA#@@", 1.5), ("EA#@@@", 2.5), ("EB#@@@", 0.5), ("EC#@@@", 0.4)),
        (("vigo", 42.24, -8.72, "1"), ("gijon", 43.54, -5.66, "1"),
         ("valladolid", 41.65, -4.72, "1"), ("bilbao", 43.26, -2.93, "2"),
         ("zaragoza", 41.65, -0.89, "2"), ("barcelona", 41.39, 2.17, "3"),
         ("girona", 41.98, 2.82, "3"), ("madrid", 40.42, -3.70, "4"),
         ("valencia", 39.47, -0.38, "5"), ("alicante", 38.35, -0.48, "5"),
         ("murcia", 37.99, -1.13, "5"), ("palma", 39.57, 2.65, "6"),
         ("sevilla", 37.39, -5.98, "7"), ("malaga", 36.72, -4.42, "7")),
        ("pepe", "paco", "jose", "juan", "manolo", "luis", "carlos", "miguel", "toni",
         "javi", "pedro", "rafa", "angel", "fernando"),
        digits="1234567", beacons=("ED#Y@@",), weight=1.5, zone=14),
    Country(
        "Portugal", (("CT1@@", 0.6), ("CT1@@@", 1.5), ("CT2@@@", 0.6), ("CT7@@@", 0.6)),
        (("lisboa", 38.72, -9.14), ("porto", 41.15, -8.61), ("coimbra", 40.21, -8.43),
         ("braga", 41.55, -8.42), ("faro", 37.02, -7.93), ("aveiro", 40.64, -8.65)),
        ("joao", "jose", "manuel", "antonio", "carlos", "rui", "paulo", "luis", "nuno", "pedro"),
        weight=0.5, zone=14),
    Country(
        "England", (("G[034678]@@@", 3.0), ("G[2345]@@", 1.5), ("M[0367]@@@", 3.0),
                    ("M5@@", 0.3), ("2E[01]@@@", 1.0)),
        (("london", 51.51, -0.13), ("birmingham", 52.49, -1.90), ("manchester", 53.48, -2.24),
         ("leeds", 53.80, -1.55), ("bristol", 51.45, -2.59), ("bath", 51.38, -2.36),
         ("york", 53.96, -1.08), ("norwich", 52.63, 1.30), ("exeter", 50.72, -3.53),
         ("derby", 52.92, -1.48), ("cambridge", 52.21, 0.12), ("oxford", 51.75, -1.26),
         ("newcastle", 54.98, -1.61), ("plymouth", 50.38, -4.14), ("dover", 51.13, 1.31)),
        ("john", "dave", "mike", "pete", "ian", "bob", "tony", "steve", "chris", "phil",
         "roger", "alan", "colin", "brian", "nigel"),
        beacons=("GB3@@@",), weight=2.0, zone=14),
    Country(
        "Scotland", (("GM[034678]@@@", 2.0), ("GM[34]@@", 0.8), ("MM[0367]@@@", 1.5),
                     ("2M0@@@", 0.4)),
        (("glasgow", 55.86, -4.25), ("edinburgh", 55.95, -3.19), ("aberdeen", 57.15, -2.09),
         ("dundee", 56.46, -2.97), ("inverness", 57.48, -4.22)),
        ("ian", "jock", "andy", "dave", "alan", "gordon", "iain", "neil"),
        beacons=("GB3@@@",), weight=0.5, zone=14),
    Country(
        "Wales", (("GW[034678]@@@", 2.0), ("GW[34]@@", 0.6), ("MW[0367]@@@", 1.5),
                  ("2W0@@@", 0.3)),
        (("cardiff", 51.48, -3.18), ("swansea", 51.62, -3.94), ("bangor", 53.23, -4.13),
         ("aberystwyth", 52.42, -4.08)),
        ("dai", "huw", "gareth", "dave", "john", "owen", "rhys"),
        beacons=("GB3@@@",), weight=0.4, zone=14),
    Country(
        "Northern Ireland", (("GI[034678]@@@", 2.0), ("MI[0367]@@@", 1.0)),
        (("belfast", 54.60, -5.93), ("derry", 54.99, -7.31), ("newry", 54.18, -6.34)),
        ("sean", "john", "paddy", "liam", "dave", "michael"),
        beacons=("GB3@@@",), weight=0.2, zone=14),
    Country(
        "Ireland", (("EI#@@", 1.5), ("EI#@@@", 1.5)),
        (("dublin", 53.35, -6.26), ("cork", 51.90, -8.47), ("galway", 53.27, -9.05),
         ("limerick", 52.66, -8.63), ("waterford", 52.26, -7.11), ("sligo", 54.27, -8.47)),
        ("john", "pat", "mick", "sean", "tom", "declan", "liam", "brendan", "kevin", "paddy"),
        digits="23456789", beacons=("EI0@@@",), weight=0.5, zone=14),
    Country(
        "Netherlands", (("PA0@@", 1.0), ("PA#@@@", 3.0), ("PD#@@@", 1.2), ("PE#@@@", 1.0),
                        ("PH#@@@", 0.4), ("PI4@@@", 0.2)),
        (("amsterdam", 52.37, 4.90), ("rotterdam", 51.92, 4.48), ("utrecht", 52.09, 5.12),
         ("eindhoven", 51.44, 5.47), ("groningen", 53.22, 6.57), ("den haag", 52.08, 4.31),
         ("arnhem", 51.98, 5.91), ("nijmegen", 51.84, 5.85), ("enschede", 52.22, 6.89),
         ("maastricht", 50.85, 5.69), ("leeuwarden", 53.20, 5.80), ("zwolle", 52.51, 6.09)),
        ("jan", "piet", "henk", "kees", "wim", "hans", "gerrit", "bert", "ruud", "frans",
         "peter", "rob", "joop", "dick", "cor"),
        digits="0123456789", beacons=("PI7@@@",), weight=1.5, zone=14),
    Country(
        "Belgium", (("ON#@@", 1.0), ("ON#@@@", 3.0), ("OO#@@@", 0.2), ("OT#@@@", 0.2)),
        (("brussel", 50.85, 4.35), ("antwerpen", 51.22, 4.40), ("gent", 51.05, 3.73),
         ("liege", 50.63, 5.57), ("brugge", 51.21, 3.22), ("namur", 50.47, 4.87),
         ("leuven", 50.88, 4.70), ("charleroi", 50.41, 4.44), ("hasselt", 50.93, 5.34)),
        ("marc", "jean", "luc", "paul", "dirk", "guy", "jos", "frank", "patrick", "etienne"),
        digits="45678", beacons=("ON0@@@",), weight=0.9, zone=14),
    Country(
        "Luxembourg", (("LX1@@", 1.0), ("LX1@@@", 0.5), ("LX2@@", 0.3)),
        (("luxembourg", 49.61, 6.13), ("esch", 49.50, 5.98)),
        ("jean", "marc", "claude", "pierre", "paul"),
        weight=0.15, zone=14),
    Country(
        "Switzerland", (("HB9@@", 2.0), ("HB9@@@", 2.5), ("HB3Y@@", 0.3)),
        (("zuerich", 47.38, 8.54), ("bern", 46.95, 7.45), ("basel", 47.56, 7.59),
         ("genf", 46.20, 6.14), ("lausanne", 46.52, 6.63), ("luzern", 47.05, 8.31),
         ("st gallen", 47.42, 9.37), ("lugano", 46.00, 8.95), ("chur", 46.85, 9.53)),
        ("hans", "peter", "urs", "fritz", "ruedi", "walter", "kurt", "heinz", "bruno", "markus"),
        beacons=("HB9@@/B",), weight=0.9, zone=14),
    Country(
        "Denmark", (("OZ#@@", 1.5), ("OZ#@@@", 2.0), ("OU#@@@", 0.2), ("5P#@@", 0.1)),
        (("kobenhavn", 55.68, 12.57), ("aarhus", 56.16, 10.20), ("odense", 55.40, 10.39),
         ("aalborg", 57.05, 9.92), ("esbjerg", 55.47, 8.45), ("roskilde", 55.64, 12.08)),
        ("ole", "lars", "per", "niels", "soren", "jens", "hans", "henrik", "erik", "bent"),
        digits="0123456789", beacons=("OZ7IGY", "OZ#@@@"), weight=0.7, zone=14),
    Country(
        "Norway", (("LA#@@", 1.5), ("LA#@@@", 2.0), ("LB#@@@", 0.8)),
        (("oslo", 59.91, 10.75), ("bergen", 60.39, 5.32), ("trondheim", 63.43, 10.40),
         ("stavanger", 58.97, 5.73), ("kristiansand", 58.15, 8.00), ("tromso", 69.65, 18.96),
         ("drammen", 59.74, 10.20)),
        ("ole", "lars", "per", "nils", "bjorn", "kjell", "odd", "arne", "tor", "geir"),
        beacons=("LA#VHF", "LA#UHF", "LA#SHF"), weight=0.7, zone=14),
    Country(
        "Sweden", (("SM#@@", 1.5), ("SM#@@@", 2.5), ("SA#@@@", 1.0), ("SE#@@@", 0.3),
                   ("SK#@@", 0.2)),
        (("stockholm", 59.33, 18.07, "0"), ("visby", 57.64, 18.30, "1"),
         ("umea", 63.83, 20.26, "2"), ("lulea", 65.58, 22.16, "2"),
         ("sundsvall", 62.39, 17.31, "3"), ("orebro", 59.27, 15.21, "4"),
         ("karlstad", 59.38, 13.50, "4"), ("uppsala", 59.86, 17.64, "5"),
         ("vasteras", 59.61, 16.55, "5"), ("linkoping", 58.41, 15.62, "5"),
         ("goteborg", 57.71, 11.97, "6"), ("malmo", 55.60, 13.00, "7")),
        ("sven", "lars", "erik", "bjorn", "nils", "anders", "olle", "kjell", "gunnar", "bengt"),
        digits="01234567", beacons=("SK#@@@",), weight=1.0, zone=14),
    Country(
        "Finland", (("OH#@@", 1.5), ("OH#@@@", 2.5), ("OG#@@@", 0.2), ("OF#@@", 0.1)),
        (("turku", 60.45, 22.27, "1"), ("helsinki", 60.17, 24.94, "2"),
         ("tampere", 61.50, 23.76, "3"), ("lahti", 60.98, 25.66, "3"),
         ("kuopio", 62.89, 27.68, "7"), ("vaasa", 63.10, 21.62, "6"),
         ("jyvaskyla", 62.24, 25.75, "6"), ("oulu", 65.01, 25.47, "8"),
         ("rovaniemi", 66.50, 25.73, "9")),
        ("jukka", "pekka", "timo", "kari", "hannu", "matti", "seppo", "juha", "mikko", "raimo"),
        beacons=("OH#VHF", "OH#SHF"), weight=0.9, zone=15),
    Country(
        "Estonia", (("ES#@@", 1.0), ("ES#@@@", 1.0)),
        (("tallinn", 59.44, 24.75), ("tartu", 58.38, 26.72), ("narva", 59.38, 28.19),
         ("parnu", 58.39, 24.50)),
        ("toomas", "mart", "peeter", "andres", "jaan", "tonu"),
        digits="12345678", weight=0.3, zone=15),
    Country(
        "Latvia", (("YL2@@", 1.0), ("YL3@@", 0.6), ("YL2@@@", 0.6)),
        (("riga", 56.95, 24.11), ("daugavpils", 55.87, 26.52), ("liepaja", 56.51, 21.01),
         ("jelgava", 56.65, 23.71)),
        ("janis", "andris", "juris", "peteris", "aivars", "valdis"),
        weight=0.3, zone=15),
    Country(
        "Lithuania", (("LY#@@", 1.5), ("LY#@@@", 1.0)),
        (("vilnius", 54.69, 25.28), ("kaunas", 54.90, 23.90), ("klaipeda", 55.71, 21.13),
         ("siauliai", 55.93, 23.31), ("panevezys", 55.73, 24.36)),
        ("jonas", "petras", "vytas", "rimas", "gintas", "saulius"),
        digits="12345", weight=0.4, zone=15),
    Country(
        "European Russia", (("UA#@@", 1.5), ("UA#@@@", 2.0), ("RA#@@", 1.0), ("RA#@@@", 1.0),
                            ("R#@@", 0.8), ("R#@@@", 0.8), ("RK#@@@", 0.4), ("RW#@@@", 0.4),
                            ("RU#@@@", 0.4), ("RN#@@@", 0.4), ("RV#@@@", 0.3), ("RX#@@@", 0.3),
                            ("RZ#@@@", 0.3), ("UB#@@@", 0.5)),
        (("st petersburg", 59.93, 30.32, "1"), ("murmansk", 68.97, 33.08, "1"),
         ("arkhangelsk", 64.54, 40.54, "1"), ("kaliningrad", 54.71, 20.51, "2"),
         ("moskva", 55.76, 37.62, "3"), ("voronezh", 51.67, 39.21, "3"),
         ("nizhny novgorod", 56.33, 44.00, "3"), ("kazan", 55.80, 49.11, "4"),
         ("samara", 53.20, 50.15, "4"), ("saratov", 51.53, 46.03, "4"),
         ("volgograd", 48.71, 44.51, "4"), ("rostov", 47.24, 39.71, "6"),
         ("krasnodar", 45.04, 38.98, "6")),
        ("igor", "oleg", "serg", "vlad", "alex", "yuri", "dima", "boris", "andy", "valery",
         "nick", "victor", "misha", "kolya", "sasha"),
        digits="1346", weight=1.5, zone=16),
    Country(
        "Asiatic Russia", (("UA9@@", 1.0), ("UA9@@@", 1.0), ("RA9@@@", 0.5), ("R9@@", 0.5),
                           ("UA0@@@", 0.4), ("R0@@", 0.2)),
        (("yekaterinburg", 56.84, 60.61), ("chelyabinsk", 55.16, 61.40),
         ("novosibirsk", 55.01, 82.93), ("omsk", 54.99, 73.37), ("perm", 58.01, 56.23),
         ("krasnoyarsk", 56.01, 92.87)),
        ("igor", "oleg", "serg", "vlad", "alex", "yuri", "dima", "boris", "andy", "valery"),
        weight=0.4, zone=17, continent="AS"),
    Country(
        "Ukraine", (("UR#@@", 1.0), ("UR#@@@", 1.5), ("UT#@@", 1.0), ("UT#@@@", 1.2),
                    ("US#@@@", 0.8), ("UX#@@", 0.5), ("UW#@@", 0.4), ("UY#@@@", 0.4),
                    ("UZ#@@@", 0.2), ("UV#@@@", 0.2)),
        (("kyiv", 50.45, 30.52), ("kharkiv", 49.99, 36.23), ("odesa", 46.48, 30.73),
         ("dnipro", 48.47, 35.04), ("lviv", 49.84, 24.03), ("zaporizhzhia", 47.84, 35.14),
         ("vinnytsia", 49.23, 28.47), ("poltava", 49.59, 34.55), ("chernihiv", 51.50, 31.29),
         ("cherkasy", 49.44, 32.06)),
        ("igor", "oleg", "serg", "vlad", "alex", "yuri", "dima", "taras", "bogdan", "vasyl",
         "andriy", "sasha", "max"),
        digits="0123456789", weight=1.0, zone=16),
    Country(
        "Belarus", (("EW#@@", 1.0), ("EW#@@@", 1.0), ("EU#@@@", 0.5), ("EV#@@@", 0.3)),
        (("minsk", 53.90, 27.57), ("gomel", 52.44, 31.00), ("brest", 52.10, 23.70),
         ("grodno", 53.67, 23.83), ("vitebsk", 55.19, 30.20), ("mogilev", 53.90, 30.33)),
        ("igor", "oleg", "serg", "sasha", "vlad", "alex", "dima", "andrey"),
        digits="12345678", weight=0.3, zone=16),
    Country(
        "Iceland", (("TF#@@", 1.0), ("TF#@@@", 0.6)),
        (("reykjavik", 64.15, -21.94), ("akureyri", 65.68, -18.09)),
        ("jon", "gunnar", "siggi", "einar"),
        weight=0.1, zone=40),
    Country(
        "Israel", (("4X#@@", 1.0), ("4X#@@@", 0.6), ("4Z#@@", 0.8), ("4Z#@@@", 0.6)),
        (("tel aviv", 32.07, 34.78), ("haifa", 32.79, 34.99), ("jerusalem", 31.77, 35.21),
         ("beer sheva", 31.25, 34.79)),
        ("avi", "moshe", "yossi", "dov", "shlomo", "gadi", "eli", "rafi"),
        digits="1456", weight=0.3, zone=20, continent="AS"),
    Country(
        "Turkey", (("TA#@@", 1.0), ("TA#@@@", 1.5)),
        (("istanbul", 41.01, 28.98), ("ankara", 39.93, 32.86), ("izmir", 38.42, 27.14),
         ("bursa", 40.19, 29.06), ("antalya", 36.90, 30.70), ("adana", 37.00, 35.32)),
        ("mehmet", "ali", "ahmet", "mustafa", "hasan", "murat", "kemal", "erol"),
        weight=0.4, zone=20, continent="AS"),
    Country(
        "Malta", (("9H1@@", 1.0), ("9H1@@@", 0.6), ("9H5@@", 0.3)),
        (("valletta", 35.90, 14.51), ("birkirkara", 35.90, 14.46)),
        ("joe", "tony", "carmel", "paul", "john"),
        weight=0.1, zone=15),
    Country(
        "Cyprus", (("5B4@@", 1.0), ("5B4@@@", 0.6)),
        (("nicosia", 35.19, 33.38), ("limassol", 34.68, 33.04), ("larnaca", 34.92, 33.63)),
        ("andreas", "costas", "nicos", "george"),
        weight=0.1, zone=20, continent="AS"),
    Country(
        "United States", (("K#@@", 0.8), ("K#@@@", 1.5), ("W#@@", 0.8), ("W#@@@", 1.2),
                          ("N#@@", 0.6), ("N#@@@", 1.2), ("K[A-GI-KM-OQ-Z]#@@@", 2.0),
                          ("W[A-GI-KM-OQ-Z]#@@@", 1.5), ("N[A-GI-KM-OQ-Z]#@@@", 1.0),
                          ("A[A-L]#@@", 0.6), ("A[A-L]#@", 0.1), ("K#@", 0.1),
                          ("W#@", 0.1), ("N#@", 0.1)),
        (("boston", 42.36, -71.06, "1"), ("new york", 40.71, -74.01, "2"),
         ("philadelphia", 39.95, -75.17, "3"), ("baltimore", 39.29, -76.61, "3"),
         ("atlanta", 33.75, -84.39, "4"), ("miami", 25.76, -80.19, "4"),
         ("nashville", 36.16, -86.78, "4"), ("raleigh", 35.78, -78.64, "4"),
         ("dallas", 32.78, -96.80, "5"), ("houston", 29.76, -95.37, "5"),
         ("austin", 30.27, -97.74, "5"), ("los angeles", 34.05, -118.24, "6"),
         ("san diego", 32.72, -117.16, "6"), ("san francisco", 37.77, -122.42, "6"),
         ("seattle", 47.61, -122.33, "7"), ("portland", 45.52, -122.68, "7"),
         ("phoenix", 33.45, -112.07, "7"), ("salt lake city", 40.76, -111.89, "7"),
         ("cleveland", 41.50, -81.69, "8"), ("detroit", 42.33, -83.05, "8"),
         ("columbus", 39.96, -83.00, "8"), ("chicago", 41.88, -87.63, "9"),
         ("milwaukee", 43.04, -87.91, "9"), ("indianapolis", 39.77, -86.16, "9"),
         ("minneapolis", 44.98, -93.27, "0"), ("kansas city", 39.10, -94.58, "0"),
         ("denver", 39.74, -104.99, "0"), ("st louis", 38.63, -90.20, "0")),
        ("bob", "jim", "bill", "tom", "joe", "dave", "mike", "ken", "don", "ron", "gary",
         "carl", "ed", "al", "fred", "larry", "steve", "jack", "rich", "dan"),
        digits="0123456789", beacons=("K#@@@/B", "W#@@@/B", "N#@@@/B"),
        weight=0.6, zone=5, continent="NA"),
    Country(
        "Canada", (("VE#@@", 1.5), ("VE#@@@", 1.5), ("VA#@@@", 1.0)),
        (("montreal", 45.50, -73.57, "2"), ("quebec", 46.81, -71.21, "2"),
         ("toronto", 43.65, -79.38, "3"), ("ottawa", 45.42, -75.70, "3"),
         ("winnipeg", 49.90, -97.14, "4"), ("regina", 50.45, -104.62, "5"),
         ("calgary", 51.05, -114.07, "6"), ("edmonton", 53.55, -113.49, "6"),
         ("vancouver", 49.28, -123.12, "7"), ("halifax", 44.65, -63.57, "1")),
        ("bob", "jim", "bill", "tom", "joe", "dave", "mike", "pierre", "jean", "ken"),
        weight=0.2, zone=5, continent="NA"),
    Country(
        "Brazil", (("PY#@@", 1.0), ("PY#@@@", 1.5), ("PP#@@@", 0.3), ("PU#@@@", 0.5)),
        (("sao paulo", -23.55, -46.63, "2"), ("rio de janeiro", -22.91, -43.17, "1"),
         ("belo horizonte", -19.92, -43.94, "4"), ("curitiba", -25.43, -49.27, "5"),
         ("porto alegre", -30.03, -51.23, "3"), ("brasilia", -15.79, -47.88, "2"),
         ("salvador", -12.97, -38.51, "6"), ("recife", -8.05, -34.88, "7")),
        ("paulo", "carlos", "jose", "luiz", "marcos", "pedro", "sergio", "tony"),
        weight=0.15, zone=11, continent="SA"),
    Country(
        "Argentina", (("LU#@@", 1.0), ("LU#@@@", 1.5), ("LW#@@@", 0.3)),
        (("buenos aires", -34.60, -58.38), ("cordoba", -31.42, -64.18),
         ("rosario", -32.95, -60.64), ("mendoza", -32.89, -68.83)),
        ("juan", "carlos", "jorge", "luis", "pedro", "ricardo", "raul", "jose"),
        weight=0.1, zone=13, continent="SA"),
    Country(
        "South Africa", (("ZS#@@", 1.0), ("ZS#@@@", 1.5), ("ZR#@@@", 0.3)),
        (("johannesburg", -26.20, 28.05, "6"), ("cape town", -33.93, 18.42, "1"),
         ("durban", -29.86, 31.02, "5"), ("pretoria", -25.75, 28.19, "6"),
         ("port elizabeth", -33.96, 25.60, "2")),
        ("john", "dave", "pete", "andre", "piet", "mike", "chris", "hennie"),
        digits="123456", weight=0.1, zone=38, continent="AF"),
    Country(
        "Japan", (("JA#@@", 1.0), ("JA#@@@", 1.5), ("JH#@@@", 1.0), ("JR#@@@", 0.8),
                  ("JE#@@@", 0.6), ("JF#@@@", 0.5), ("JG#@@@", 0.5), ("JI#@@@", 0.4),
                  ("JK#@@@", 0.4), ("JL#@@@", 0.4), ("JM#@@@", 0.3), ("JO#@@@", 0.3),
                  ("JP#@@@", 0.3), ("JQ#@@@", 0.3), ("JS#@@@", 0.2)),
        (("tokyo", 35.68, 139.69, "1"), ("yokohama", 35.44, 139.64, "1"),
         ("nagoya", 35.18, 136.91, "2"), ("osaka", 34.69, 135.50, "3"),
         ("kobe", 34.69, 135.20, "3"), ("hiroshima", 34.39, 132.46, "4"),
         ("matsuyama", 33.84, 132.77, "5"), ("fukuoka", 33.59, 130.40, "6"),
         ("sendai", 38.27, 140.87, "7"), ("sapporo", 43.06, 141.35, "8"),
         ("kanazawa", 36.56, 136.66, "9"), ("niigata", 37.92, 139.04, "0")),
        ("taka", "hiro", "ken", "aki", "yoshi", "kaz", "nori", "masa", "jun", "sato"),
        digits="0123456789", weight=0.3, zone=25, continent="AS"),
    Country(
        "Australia", (("VK#@@", 1.0), ("VK#@@@", 1.5)),
        (("sydney", -33.87, 151.21, "2"), ("melbourne", -37.81, 144.96, "3"),
         ("brisbane", -27.47, 153.03, "4"), ("adelaide", -34.93, 138.60, "5"),
         ("perth", -31.95, 115.86, "6"), ("hobart", -42.88, 147.33, "7"),
         ("canberra", -35.28, 149.13, "1")),
        ("bob", "bruce", "dave", "steve", "pete", "john", "mick", "wayne"),
        weight=0.1, zone=30, continent="OC"),
    Country(
        "New Zealand", (("ZL#@@", 1.0), ("ZL#@@@", 1.0)),
        (("auckland", -36.85, 174.76, "1"), ("wellington", -41.29, 174.78, "2"),
         ("christchurch", -43.53, 172.64, "3"), ("dunedin", -45.87, 170.50, "4")),
        ("bob", "ian", "dave", "john", "steve", "peter", "mike"),
        digits="1234", weight=0.05, zone=32, continent="OC"),
)

EUROPE = tuple(c for c in COUNTRIES if c.continent == "EU")

RIGS = ("ic7300", "ft991", "ts590", "ic705", "ft817", "k3", "kx3", "ft1000mp", "ic756pro",
        "ts850", "ft450", "ic7610", "hb", "qcx", "ft857", "ts480", "ic718", "ft2000")
POWERS = ("100 w", "100 w", "100 w", "50 w", "5 w", "10 w", "400 w", "1 kw", "20 w", "80 w")
ANTENNAS = ("dipole", "inv v", "vertical", "gp", "g5rv", "windom", "3 el yagi", "beam",
            "loop", "long wire", "efhw", "delta loop", "quad", "doublet", "lw")
WEATHER = ("sunny", "cloudy", "rain", "overcast", "snow", "fog", "windy", "clear", "cold",
           "sunny es warm", "rainy es cold", "hot", "wet", "dry")
GREETINGS = (("gm", 0.35), ("ga", 0.3), ("ge", 0.35))

#: Half a city: how far a station is jittered off its town's centre before the
#: locator is worked out, so the same town yields several sub-squares.
JITTER_DEG = (0.12, 0.2)


@dataclass(frozen=True)
class Station:
    """One station: who, where, and how to address it."""

    call: str
    country: str
    name: str
    qth: str
    lat: float
    lon: float
    locator: str          # six characters, e.g. JO81LC
    zone: int = 14
    continent: str = "EU"

    @property
    def square(self) -> str:
        """The four-character locator, ``JO81``."""
        return self.locator[:4]


def maidenhead(lat: float, lon: float, length: int = 6) -> str:
    """The Maidenhead locator of a point: field, square and sub-square."""
    lon = (float(lon) + 180.0) % 360.0
    lat = min(max(float(lat) + 90.0, 0.0), 179.999)
    field = chr(ord("A") + int(lon // 20)) + chr(ord("A") + int(lat // 10))
    square = str(int((lon % 20) // 2)) + str(int(lat % 10))
    sub = (chr(ord("A") + int((lon % 2) * 12)) + chr(ord("A") + int((lat % 1) * 24)))
    return (field + square + sub)[:length]


def locator_centre(locator: str) -> tuple[float, float]:
    """Latitude and longitude of the middle of a four- or six-character locator."""
    loc = locator.strip().upper()
    if not re.fullmatch(r"[A-R]{2}[0-9]{2}(?:[A-X]{2})?", loc):
        raise ValueError(f"{locator!r} is not a Maidenhead locator")
    lon = (ord(loc[0]) - ord("A")) * 20.0 + int(loc[2]) * 2.0
    lat = (ord(loc[1]) - ord("A")) * 10.0 + int(loc[3])
    if len(loc) == 6:
        lon += (ord(loc[4]) - ord("A")) / 12.0 + 1.0 / 24.0
        lat += (ord(loc[5]) - ord("A")) / 24.0 + 1.0 / 48.0
    else:
        lon += 1.0
        lat += 0.5
    return lat - 90.0, lon - 180.0


def distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance between two (lat, lon) points."""
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 2.0 * 6371.0 * math.asin(math.sqrt(min(1.0, h)))


def expand(pattern: str, rng: np.random.Generator, digits: str = "0123456789",
           digit: str | None = None) -> str:
    """Fill a callsign template: ``#`` a digit, ``@`` a letter, ``[..]`` a choice."""
    out = []
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "#":
            out.append(digit if digit else digits[int(rng.integers(0, len(digits)))])
        elif ch == "@":
            out.append(chr(int(rng.integers(65, 91))))
        elif ch == "[":
            close = pattern.index("]", i)
            choices = _charset(pattern[i + 1:close])
            out.append(choices[int(rng.integers(0, len(choices)))])
            i = close
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def _charset(spec: str) -> str:
    """``A-L`` or ``034678`` as the characters it stands for."""
    out = ""
    i = 0
    while i < len(spec):
        if i + 2 < len(spec) and spec[i + 1] == "-":
            out += "".join(chr(c) for c in range(ord(spec[i]), ord(spec[i + 2]) + 1))
            i += 3
        else:
            out += spec[i]
            i += 1
    return out


def _pick(rng: np.random.Generator, items, weights) -> object:
    w = np.asarray(weights, dtype=float)
    return items[int(rng.choice(len(items), p=w / w.sum()))]


def _station_at(country: Country, place: Place, call: str, rng: np.random.Generator) -> Station:
    name, lat, lon = place[0], float(place[1]), float(place[2])
    lat += float(rng.uniform(-JITTER_DEG[0], JITTER_DEG[0]))
    lon += float(rng.uniform(-JITTER_DEG[1], JITTER_DEG[1]))
    return Station(call=call, country=country.name, name=str(rng.choice(country.names)),
                   qth=name, lat=lat, lon=lon, locator=maidenhead(lat, lon),
                   zone=country.zone, continent=country.continent)


def draw_station(rng: np.random.Generator, near: Station | tuple[float, float] | None = None,
                 min_km: float = 0.0, max_km: float | None = None,
                 min_lat: float | None = None, beacon: bool = False,
                 countries: tuple[Country, ...] = COUNTRIES) -> Station:
    """Draw a station, weighted by how often its country is heard.

    ``near`` with ``min_km`` / ``max_km`` keeps it within reach of another
    station -- a tropo QSO is a few hundred kilometres, a rain-scatter QSO
    fewer -- and ``min_lat`` keeps an aurora QSO in the north where it works.
    ``beacon`` draws a beacon callsign from the countries that have a pattern
    for one.  If nothing fits the constraints they are relaxed, because an
    empty band is not an answer.
    """
    here = (near.lat, near.lon) if isinstance(near, Station) else near

    def candidates(strict: bool):
        pairs, weights = [], []
        for country in countries:
            if beacon and not country.beacons:
                continue
            for place in country.places:
                if strict and here is not None:
                    km = distance_km(here, (place[1], place[2]))
                    if km < min_km or (max_km is not None and km > max_km):
                        continue
                if strict and min_lat is not None and place[1] < min_lat:
                    continue
                pairs.append((country, place))
                weights.append(country.weight / len(country.places))
        return pairs, weights

    pairs, weights = candidates(strict=True)
    if not pairs:
        pairs, weights = candidates(strict=False)
    country, place = _pick(rng, pairs, weights)
    digit = str(place[3]) if len(place) > 3 else None
    if beacon:
        pattern = str(rng.choice(country.beacons))
    else:
        pattern = _pick(rng, [p for p, _ in country.calls], [w for _, w in country.calls])
    call = expand(pattern, rng, country.digits, digit)
    return _station_at(country, place, call, rng)


def station_from_call(call: str, rng: np.random.Generator,
                      locator: str | None = None, name: str | None = None) -> Station:
    """The station behind a callsign: its country from the prefix, its town
    from the district digit where the country has them, or from ``locator``."""
    station = _station_from_call(call, rng, locator)
    if name and str(name).strip():
        station = Station(**{**station.__dict__, "name": str(name).strip().lower()})
    return station


def _station_from_call(call: str, rng: np.random.Generator,
                       locator: str | None = None) -> Station:
    clean = call.strip().upper().split("/")[0]
    best: tuple[int, Country] | None = None
    for country in COUNTRIES:
        for pattern, _ in country.calls + tuple((b, 1.0) for b in country.beacons):
            # The longest literal head of any template that the call starts
            # with wins: GM4 is Scotland before it is England, IT9 is Sicily.
            literal = re.match(r"[A-Z0-9]*", pattern.replace("#", "").split("[")[0]).group(0)
            if literal and clean.startswith(literal) and (best is None or len(literal) > best[0]):
                best = (len(literal), country)
    digit_match = re.search(r"[0-9](?=[A-Z]*$)", clean)
    digit = digit_match.group(0) if digit_match else None
    if best is None:
        country = Country("somewhere", (), (), ("op",), weight=0.0)
        if locator:
            lat, lon = locator_centre(locator)
        else:
            lat, lon = 50.0, 15.0
        return Station(call=call.strip().upper(), country=country.name, name="op", qth="",
                       lat=lat, lon=lon, locator=(locator or maidenhead(lat, lon)).upper())
    country = best[1]
    places = [p for p in country.places if len(p) > 3 and str(p[3]) == digit] or list(country.places)
    if locator:
        lat, lon = locator_centre(locator)
        nearest = min(places, key=lambda p: distance_km((lat, lon), (p[1], p[2])))
        station = _station_at(country, nearest, call.strip().upper(), rng)
        loc = locator.strip().upper()
        if len(loc) == 4:
            loc = maidenhead(lat, lon)
        return Station(call=station.call, country=station.country, name=station.name,
                       qth=station.qth, lat=lat, lon=lon, locator=loc, zone=country.zone,
                       continent=country.continent)
    place = places[int(rng.integers(0, len(places)))]
    return _station_at(country, place, call.strip().upper(), rng)


def random_call(rng: np.random.Generator) -> str:
    """A callsign that could be real, from a country you would hear."""
    return draw_station(rng).call.lower()


# ---------------------------------------------------------------------------
# What they say
# ---------------------------------------------------------------------------

@dataclass
class Script:
    """A generated message: the text, who is in it, and what it needs."""

    kind: str                     # qso | beacon
    lines: list[str]              # one over per line; a beacon is one line
    two_stations: bool = False    # alternate lines are the other station
    wpm: float | None = None      # the speed this would be sent at, if the caller has none
    note: str = ""                # one line for the report
    detail: dict = field(default_factory=dict)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def band_class(band: str | None) -> str:
    """``lf``, ``hf``, ``vhf``, ``uhf`` or ``microwave`` for a band spec."""
    if not band:
        return "hf"
    hz = parse_band(band).hz
    if hz < 2e6:
        return "lf"
    if hz < 50e6:
        return "hf"
    if hz < 300e6:
        return "vhf"
    if hz < 1e9:
        return "uhf"
    return "microwave"


def rst(snr_db: float | None, rng: np.random.Generator, tone: str = "9") -> str:
    """A report that follows the conditions, with the usual optimism."""
    if snr_db is None:
        s = 9
    else:
        s = 9 if snr_db >= 18 else 8 if snr_db >= 13 else 7 if snr_db >= 8 else \
            6 if snr_db >= 4 else 5 if snr_db >= 1 else 4 if snr_db >= -3 else 3
    s = int(min(9, max(1, s + int(rng.integers(-1, 2)) * (rng.random() < 0.3))))
    r = 5 if s >= 5 else 4 if s == 4 else 3
    return f"{r}{s}{tone}"


def _reach(mode: str, band: str) -> dict:
    """How far the other station can be, for the path the signal takes."""
    if mode == "moon":
        return {}
    if mode == "aurora":
        return {"min_km": 300.0, "max_km": 2000.0, "min_lat": 50.0}
    if mode == "aircraft":
        return {"min_km": 150.0, "max_km": 800.0}
    if mode in ("rain", "snow"):
        return {"min_km": 60.0, "max_km": 500.0}
    if band in ("vhf", "uhf", "microwave"):
        return {"min_km": 30.0, "max_km": 700.0}
    if band == "lf":
        return {"max_km": 1500.0}
    return {}


def _greet(rng) -> str:
    return str(_pick(rng, [g for g, _ in GREETINGS], [w for _, w in GREETINGS]))


def _rep(text: str, n: int) -> str:
    return " ".join([text] * n)


def _cq(a: Station, rng, dx: bool, loc: bool) -> str:
    call = a.call.lower()
    if dx:
        return str(rng.choice([
            f"cq dx cq dx de {call} {call} k",
            f"cq dx cq dx cq dx de {call} {call} {call} pse k",
        ]))
    if loc:
        return str(rng.choice([
            f"cq cq de {call} {call} {a.square.lower()} k",
            f"cq cq cq de {call} {call} {call} {a.locator.lower()} k",
            f"cq cq de {call} {call} k",
        ]))
    return str(rng.choice([
        f"cq cq cq de {call} {call} {call} pse k",
        f"cq cq cq de {call} {call} {call} k",
        f"cq cq de {call} {call} k",
        f"cq cq cq de {call} {call} {call} <AR> k",
    ]))


def _answer(a: Station, b: Station, rng) -> str:
    x, y = a.call.lower(), b.call.lower()
    return str(rng.choice([
        f"{x} de {y} {y} {y} k",
        f"{x} de {y} {y} <AR>",
        f"{x} {x} de {y} {y} k",
        f"{x} de {y} {y} pse k",
    ]))


def ragchew(a: Station, b: Station, rng, snr_a: float | None, snr_b: float | None,
            qsb: bool, dx: bool, long: bool) -> list[str]:
    """A standard HF QSO: CQ, answer, report, name, QTH, perhaps the rig and
    the weather, and a proper ending."""
    x, y = a.call.lower(), b.call.lower()
    greet = _greet(rng)
    rst_a = rst(snr_a, rng)           # what B gives A: how A is heard
    rst_b = rst(snr_b, rng)           # what A gives B
    wid = " wid qsb" if qsb and rng.random() < 0.6 else ""
    lines = [_cq(a, rng, dx, loc=False), _answer(a, b, rng)]
    name_a = str(rng.choice([f"my name is {a.name} {a.name}", f"name {a.name} {a.name}",
                             f"op {a.name} {a.name}", f"name hr is {a.name} {a.name}"]))
    qth_a = str(rng.choice([f"my qth is {a.qth} {a.qth}", f"qth {a.qth} {a.qth}",
                            f"qth nr {a.qth} {a.qth}", f"qth {a.qth} {a.qth} loc {a.square.lower()}"]))
    lines.append(str(rng.choice([
        f"{y} de {x} = {greet} dr om tnx fer call = ur rst {rst_b} {rst_b}{wid} = {name_a} = "
        f"{qth_a} = hw? {y} de {x} <KN>",
        f"{y} de {x} = {greet} es tnx fer ur call = rst {rst_b} {rst_b} = {name_a} = {qth_a} = "
        f"hw cpy? {y} de {x} <KN>",
        f"{y} de {x} {greet} om tnx fer call = ur rst {rst_b} {rst_b}{wid} = {name_a} es {qth_a} "
        f"= hw? <BK>",
    ])))
    name_b = str(rng.choice([f"my name is {b.name} {b.name}", f"name {b.name} {b.name}",
                             f"op {b.name} {b.name}"]))
    qth_b = str(rng.choice([f"qth {b.qth} {b.qth}", f"my qth is {b.qth} {b.qth}",
                            f"qth nr {b.qth} {b.qth}"]))
    lines.append(str(rng.choice([
        f"{x} de {y} = r r {greet} dr {a.name} es tnx fer rprt = ur rst {rst_a} {rst_a} also = "
        f"{name_b} = {qth_b} = hw? {x} de {y} <KN>",
        f"{x} de {y} = ok dr {a.name} fb cpy = rst {rst_a} {rst_a} = {name_b} = {qth_b} = "
        f"hw? {x} de {y} <KN>",
        f"r r {x} de {y} = {greet} {a.name} tnx fer rprt = ur rst {rst_a} {rst_a} = {name_b} "
        f"= {qth_b} = <BK>",
    ])))
    if long:
        rig_a, rig_b = str(rng.choice(RIGS)), str(rng.choice(RIGS))
        pwr_a, pwr_b = str(rng.choice(POWERS)), str(rng.choice(POWERS))
        ant_a, ant_b = str(rng.choice(ANTENNAS)), str(rng.choice(ANTENNAS))
        wx_a, wx_b = str(rng.choice(WEATHER)), str(rng.choice(WEATHER))
        temp = int(rng.integers(-5, 29))
        lines.append(str(rng.choice([
            f"{y} de {x} = r fb {b.name} ur rprt {rst_a} ok = rig hr is {rig_a} pwr {pwr_a} es ant "
            f"{ant_a} up {int(rng.integers(6, 25))} m = wx {wx_a} temp {temp} c = hw? {y} de {x} <KN>",
            f"{y} de {x} = r r ok {b.name} = my rig is {rig_a} {pwr_a} ant {ant_a} = wx hr {wx_a} "
            f"= hw? {y} de {x} <KN>",
        ])))
        lines.append(str(rng.choice([
            f"{x} de {y} = r r ok {a.name} = rig {rig_b} {pwr_b} ant {ant_b} = wx hr {wx_b} = so "
            f"tnx fer nice qso es hpe cuagn = 73 73 es gl = {x} de {y} <SK>",
            f"{x} de {y} = r fb {a.name} = rig hr {rig_b} pwr {pwr_b} ant {ant_b} = wx {wx_b} = "
            f"mni tnx fer fb qso = 73 es gud dx = {x} de {y} <SK>",
        ])))
    else:
        lines.append(str(rng.choice([
            f"{y} de {x} = r r fb {b.name} tnx fer rprt = so tnx fer qso es hpe cuagn = 73 73 "
            f"{y} de {x} <SK>",
            f"{y} de {x} = ok {b.name} all cpd = tnx fer nice qso = 73 es gl = {y} de {x} <SK>",
        ])))
        lines.append(str(rng.choice([
            f"{x} de {y} = r tnx {a.name} fer fb qso = 73 es gud dx = {x} de {y} <SK> e e",
            f"r r {x} de {y} tnx {a.name} 73 73 <SK> e e",
            f"{x} de {y} = tu {a.name} 73 es cuagn = {x} de {y} <SK>",
        ])))
        return lines
    lines.append(str(rng.choice([
        f"{y} de {x} = r tnx {b.name} fer fb qso = 73 es gud dx = {y} de {x} <SK> e e",
        f"{y} de {x} = ok {b.name} tnx fer nice qso = 73 es cuagn = {y} de {x} <SK>",
        f"r r {y} de {x} tnx {b.name} 73 73 <SK> e e",
    ])))
    return lines


def vhf_qso(a: Station, b: Station, rng, snr_a: float | None, snr_b: float | None,
            tone: str, via: str = "") -> list[str]:
    """A VHF, UHF or microwave QSO: report and locator, repeated, and out."""
    x, y = a.call.lower(), b.call.lower()
    la, lb = a.locator.lower(), b.locator.lower()
    rst_a, rst_b = rst(snr_a, rng, tone), rst(snr_b, rng, tone)
    lines = [_cq(a, rng, dx=False, loc=True), _answer(a, b, rng)]
    lines.append(str(rng.choice([
        f"{y} de {x} ur {rst_b} {rst_b}{via} in {la} {la} hw? {y} de {x} <KN>",
        f"{y} de {x} r ur {rst_b} {rst_b} {rst_b}{via} {la} {la} {la} <KN>",
        f"{y} de {x} tnx ur {rst_b} {rst_b}{via} in {la} {la} k",
    ])))
    if rng.random() < 0.25:
        # The report did not make it: ask, and get it again.
        lines.append(str(rng.choice([f"{x} de {y} agn pse ur rprt agn <KN>",
                                     f"{x} de {y} nr agn? loc agn? <KN>"])))
        lines.append(f"{y} de {x} r ur {rst_b} {rst_b} {rst_b} {rst_b} in {la} {la} {la} k")
    lines.append(str(rng.choice([
        f"{x} de {y} r r ur {rst_a} {rst_a} {rst_a}{via} in {lb} {lb} {lb} hw? {x} de {y} <KN>",
        f"{x} de {y} r r tnx ur {rst_a} {rst_a}{via} {lb} {lb} hw? <KN>",
        f"r r {x} de {y} ur {rst_a} {rst_a} in {lb} {lb} {lb} k",
    ])))
    lines.append(str(rng.choice([
        f"{y} de {x} r r cfm all tnx fer qso 73 {y} de {x} <SK>",
        f"{y} de {x} r r qsl all tnx 73 <SK>",
        f"{y} de {x} rr cfm tnx fer nice qso 73 es gl {y} de {x} <SK>",
    ])))
    lines.append(str(rng.choice([
        f"{x} de {y} r r tnx 73 <SK>",
        f"r tnx 73 gl {x} de {y} <SK> e e",
        f"{x} de {y} qsl tnx fer qso 73 73 <SK>",
    ])))
    return lines


def _cut(number: int, rng) -> str:
    """A serial as it is sent: ``001``, or ``tt1`` with cut numbers."""
    text = f"{number:03d}"
    if rng.random() < 0.5:
        text = text.replace("0", "t").replace("9", "n")
    return text


def contest_qso(a: Station, b: Station, rng, band: str) -> list[str]:
    """A contest exchange: run station, caller, report and number, and out."""
    x, y = a.call.lower(), b.call.lower()
    if band in ("vhf", "uhf", "microwave"):
        # IARU VHF style: report, serial and locator.
        ex_a = f"5nn {_cut(int(rng.integers(1, 400)), rng)} {a.locator.lower()}"
        ex_b = f"5nn {_cut(int(rng.integers(1, 400)), rng)} {b.locator.lower()}"
    elif rng.random() < 0.5:
        ex_a, ex_b = f"5nn {a.zone}", f"5nn {b.zone}"
    else:
        ex_a = f"5nn {_cut(int(rng.integers(1, 1500)), rng)}"
        ex_b = f"5nn {_cut(int(rng.integers(1, 1500)), rng)}"
    lines = [str(rng.choice([f"cq test {x} {x} test", f"test {x} {x} test", f"cq {x} test",
                             f"cq test de {x} {x} test"]))]
    lines.append(str(rng.choice([y, f"{y} {y}", y])))
    lines.append(str(rng.choice([f"{y} {ex_a}", f"{y} {ex_a} {ex_a.split()[-1]}",
                                 f"{y} tu {ex_a}"])))
    if rng.random() < 0.2:
        lines.append(str(rng.choice(["nr?", "agn?", "nr agn"])))
        lines.append(f"{ex_a.split(' ', 1)[1]} {ex_a.split(' ', 1)[1]}")
    lines.append(str(rng.choice([f"r {ex_b} tu", f"tu {ex_b}", f"{ex_b} {ex_b.split()[-1]}",
                                 f"r r {ex_b}"])))
    lines.append(str(rng.choice([f"tu {x} test", f"tu {x}", f"{x} test", f"tu qrz {x}"])))
    return lines


def eme_qso(a: Station, b: Station, rng) -> list[str]:
    """The EME procedure: calls, then O, RO, RRR and 73, each sent for a period."""
    x, y = a.call.lower(), b.call.lower()
    report = str(rng.choice(["o", "o", "m"]))
    return [
        _rep(f"{y} {x}", 3) + " " + _rep(report * 3, 2),
        _rep("ro", 6) if report == "o" else _rep("rm", 6),
        _rep("rrr", 5),
        _rep("73", 4) + (" tnx" if rng.random() < 0.5 else ""),
    ]


def brief_qso(a: Station, b: Station, rng, snr_a, snr_b) -> list[str]:
    """Two overs, for a speed at which anything longer takes an afternoon."""
    x, y = a.call.lower(), b.call.lower()
    return [f"{y} de {x} {rst(snr_b, rng)} k", f"r {x} de {y} {rst(snr_a, rng)} 73"]


def qso(rng: np.random.Generator, band: str = "hf", mode: str = "none",
        contest: bool = False, qrss: bool = False, snr_db: float | None = 10.0,
        qsb_db: float = 0.0, other_db: float | None = None,
        me: Station | None = None) -> Script:
    """Both sides of a QSO the band and the path would carry.

    ``me`` is your own station, if you want to be in it; whether you call CQ
    or answer is drawn.  The other station is drawn within the reach of the
    path -- a rain-scatter QSO is a few hundred kilometres, a tropo QSO a few
    hundred more, an aurora QSO is between northern stations, an HF QSO is
    anywhere with Europe most likely, and the Moon does not care.
    """
    reach = _reach(mode, band)
    first = me or draw_station(rng, **({"min_lat": reach["min_lat"]} if "min_lat" in reach else {}))
    second = draw_station(rng, near=first, **reach)
    if me is not None and rng.random() < 0.5:
        a, b = second, first          # the other station calls, you answer
    else:
        a, b = first, second
    km = distance_km((a.lat, a.lon), (b.lat, b.lon))
    # The report B gives A is how A is heard, which is the S/N the render is
    # set to; the one A gives B follows B's level against it.
    snr_a = snr_db
    snr_b = None if snr_db is None else snr_db + float(other_db or 0.0)
    if qrss:
        lines, shape = brief_qso(a, b, rng, snr_a, snr_b), "two overs, QRSS"
    elif mode == "moon":
        lines, shape = eme_qso(a, b, rng), "EME procedure"
    elif contest:
        lines, shape = contest_qso(a, b, rng, band), "contest exchange"
    elif mode == "aurora":
        lines, shape = vhf_qso(a, b, rng, snr_a, snr_b, tone="a"), "aurora, A reports"
    elif mode in ("rain", "snow"):
        lines, shape = vhf_qso(a, b, rng, snr_a, snr_b, tone="s", via=" via rs"), \
            "scatter, S reports"
    elif band in ("vhf", "uhf", "microwave") or mode == "aircraft":
        lines, shape = vhf_qso(a, b, rng, snr_a, snr_b, tone="9"), "report and locator"
    else:
        long = rng.random() < 0.5
        lines = ragchew(a, b, rng, snr_a, snr_b, qsb=qsb_db >= 6.0,
                        dx=a.continent != b.continent, long=long)
        shape = "ragchew" + (", rig and weather" if long else "")
    who = ""
    if me is not None:
        who = f"; you {'call' if a is me else 'answer'}"
    note = (f"QSO {a.call} ({a.locator}, {a.qth}) with {b.call} ({b.locator}, {b.qth}), "
            f"{km:,.0f} km: {len(lines)} overs, {shape}{who}")
    return Script("qso", lines, two_stations=True, note=note, detail={
        "kind": "qso", "shape": shape, "overs": len(lines), "distance_km": round(km),
        "stations": [_station_dict(a), _station_dict(b)]})


def _station_dict(s: Station) -> dict:
    return {"call": s.call, "country": s.country, "name": s.name, "qth": s.qth,
            "locator": s.locator, "zone": s.zone}


def beacon(rng: np.random.Generator, band: str = "vhf", qrss: bool = False,
           me: Station | None = None, carrier: bool | None = None) -> Script:
    """A beacon's transmission: identification, locator and the long carrier.

    VHF and microwave beacons send callsign and locator at ten to fifteen
    words a minute and then hold the key down for tens of seconds -- the
    carrier is what the beacon is *for*, the identification only says whose it
    is -- and some key a carrier before the identification as well.  HF
    beacons sign ``/b`` and hold for less; a QRSS beacon on the low bands
    sends its callsign and perhaps a long dash, because at a dit of three
    seconds anything more takes an hour.
    """
    station = me or draw_station(rng, beacon=True, countries=EUROPE)
    call = station.call.lower()
    if me is not None and band == "hf" and not call.endswith("/b"):
        call += "/b"
    loc6, loc4 = station.locator.lower(), station.square.lower()
    if qrss:
        head = str(rng.choice([call, call, f"{call} {loc4}", f"{call} {call}", f"vvv de {call}"]))
        after = float(rng.choice([0.0, 0.0, 30.0, 60.0])) if carrier is None else (60.0 if carrier else 0.0)
        before = 0.0
        wpm = None
    elif band == "lf":
        head = str(rng.choice([f"{call} {call} {loc4}", f"vvv de {call} {call}", f"{call} {loc4}"]))
        after = float(rng.uniform(10.0, 30.0)) if (carrier is None and rng.random() < 0.7) or carrier else 0.0
        before = 0.0
        wpm = float(rng.uniform(8.0, 12.0))
    elif band == "hf":
        head = str(rng.choice([f"vvv de {call} {call} {loc4}", f"vvv vvv de {call} {call} {call} {loc4}",
                               f"de {call} {call} {loc4}", f"{call} {call} {loc4}"]))
        after = float(rng.uniform(8.0, 20.0)) if (carrier is None and rng.random() < 0.8) or carrier else 0.0
        before = 0.0
        wpm = float(rng.uniform(12.0, 16.0))
    else:
        head = str(rng.choice([f"{call} {loc6}", f"{call} {call} {loc6}",
                               f"vvv de {call} {loc6}", f"vvv vvv de {call} {call} {loc6}",
                               f"{call} {loc6}", f"de {call} {loc6}", f"{call} {loc4}"]))
        want = rng.random() < 0.85 if carrier is None else bool(carrier)
        after = float(rng.uniform(15.0, 60.0)) if want else 0.0
        before = float(rng.uniform(5.0, 20.0)) if want and rng.random() < 0.3 else 0.0
        if want and rng.random() < 0.15:
            before, after = after, 0.0        # the carrier first, then the ID
        wpm = float(rng.uniform(10.0, 15.0))
    parts = []
    if before:
        parts.append(f"[{before:.0f}s]")
    parts.append(head)
    if after:
        parts.append(f"[{after:.0f}s]")
    cycle = " ".join(parts)
    # Hear the structure: two cycles when they are short enough to sit through.
    cycles = 2 if (before + after) < 25.0 and not qrss else 1
    text = " [1s pause] ".join([cycle] * cycles) if cycles > 1 else cycle
    bits = []
    if before:
        bits.append(f"{before:.0f} s carrier before the ID")
    if after:
        bits.append(f"{after:.0f} s carrier after the ID")
    if not bits:
        bits.append("no carrier, ID only")
    if cycles > 1:
        bits.append(f"{cycles} cycles")
    note = f"beacon {station.call.upper()} in {station.locator} ({station.qth}): " + ", ".join(bits)
    return Script("beacon", [text], two_stations=False, wpm=wpm, note=note, detail={
        "kind": "beacon", "station": _station_dict(station), "carrier_before_s": before,
        "carrier_after_s": after, "cycles": cycles})


def compose(kind: str, cfg, rng: np.random.Generator, band_known: bool = True,
            my_call: str | None = None, my_loc: str | None = None,
            my_name: str | None = None, carrier: bool | None = None) -> Script:
    """A QSO or a beacon that fits ``cfg``: its band, its path, its speed.

    ``band_known`` is False for a profile that is about band conditions rather
    than a band, which is treated as HF because that is what crashes and a
    tilted noise floor are.  ``my_call`` puts you in the QSO, or on the
    beacon; ``my_loc`` says where you are if the callsign does not.
    """
    kind = str(kind).strip().lower()
    if kind not in ("qso", "beacon"):
        raise ValueError(f"nothing to generate called {kind!r}: qso or beacon")
    from .render import QRSS_DIT_S, mode_name     # local: render imports nothing here
    band = band_class(cfg.band) if band_known else "hf"
    mode = mode_name(cfg.scatter)
    qrss = (1.2 / max(float(cfg.wpm), 1e-6)) >= QRSS_DIT_S
    me = None
    loc = str(my_loc).strip() if my_loc and str(my_loc).strip() else None
    if my_call and str(my_call).strip():
        me = station_from_call(str(my_call), rng, loc, my_name)
    elif loc:
        me = station_from_call(draw_station(rng).call, rng, loc, my_name)
    if kind == "beacon":
        return beacon(rng, band=band, qrss=qrss, me=me, carrier=carrier)
    return qso(rng, band=band, mode=mode, contest=str(cfg.qrm_style) == "contest",
               qrss=qrss, snr_db=cfg.snr_db, qsb_db=float(cfg.qsb_db or 0.0),
               other_db=getattr(cfg, "other_db", None), me=me)
