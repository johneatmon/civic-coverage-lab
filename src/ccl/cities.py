"""City configuration and walking-speed standards.

The service standards here follow the US planning heuristic a Tacoma city engineer
described: 5 min = 1/4 mile, 10 min = 1/2 mile, 15 min = 3/4 mile. That implies a walking
speed of 3 mph (1.34 m/s), and it reproduces the two thresholds practitioners actually
cite -- 15 min = 1,207 m (0.75 mi) and 10 min = 804 m (0.50 mi).

The point of the profiles is that a time-based standard is not one distance. "A 10 minute
walk" means 804 m to a fit adult and 480 m to someone using a wheelchair, so the same
policy sentence describes very different catchments -- and each profile has its own
relevant population, not a share of the whole city.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Profile:
    key: str
    label: str
    speed_mps: float
    basis: str
    pop_field: str  # which demand raster counts as this profile's population


PROFILES = [
    Profile("adult", "Adult (planning standard)", 1.34,
            "3 mph; the 1/4-1/2-3/4 mile heuristic", "population"),
    Profile("older", "Older adult (65+)", 1.00,
            "gait-speed literature; MUTCD uses 1.07 m/s where older pedestrians are present",
            "pop_65plus"),
    Profile("mobility", "Ambulatory difficulty", 0.80,
            "manual wheelchair / walking-aid speeds", "pop_ambulatory"),
]

TIME_BUDGETS_MIN = [10, 15]


def distance_m(profile: Profile, minutes: float) -> float:
    return profile.speed_mps * minutes * 60.0


@dataclass(frozen=True)
class City:
    key: str
    place: str
    state: str
    county: str
    pop_reference: int  # published city population, for validating the raster
    facility_source: str  # "arcgis" or "osm"
    arcgis_service: str | None = None
    osm_filter: dict = field(default_factory=dict)


CITIES = {
    "seattle": City(
        key="seattle",
        place="Seattle, Washington, USA",
        state="53", county="033",  # King County
        pop_reference=755_000,
        facility_source="arcgis",
        arcgis_service="Seattle_Public_Library",
    ),
    "tacoma": City(
        key="tacoma",
        place="Tacoma, Washington, USA",
        state="53", county="053",  # Pierce County
        pop_reference=222_000,
        facility_source="osm",
        # OSM tags amenity=library indiscriminately: the 12 features in Tacoma include
        # two university libraries and a prep-school one. The operator website is the
        # reliable discriminator -- the 8 that match are locations/1..8, which is
        # exactly Tacoma Public Library's branch count.
        osm_filter={"tags": {"amenity": "library"}, "website_contains": "tacomalibrary.org"},
    ),
}


def get(key: str) -> City:
    if key not in CITIES:
        raise KeyError(f"unknown city {key!r}; known: {sorted(CITIES)}")
    return CITIES[key]
