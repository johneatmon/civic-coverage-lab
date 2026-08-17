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
    max_grade: float | None = None  # steeper edges are impassable, not merely slow


# ADA maximum running slope for a ramp is 1:12 = 8.33%. Above that a route is not slow
# for a manual wheelchair user, it is unusable -- so the mobility profile drops those
# edges rather than penalising them.
ADA_MAX_GRADE = 0.0833

PROFILES = [
    Profile("adult", "Adult (planning standard)", 1.34,
            "3 mph; the 1/4-1/2-3/4 mile heuristic", "population"),
    Profile("older", "Older adult (65+)", 1.00,
            "gait-speed literature; MUTCD uses 1.07 m/s where older pedestrians are present",
            "pop_65plus"),
    Profile("mobility", "Ambulatory difficulty", 0.80,
            "manual wheelchair / walking-aid speeds; ADA 1:12 max running slope",
            "pop_ambulatory", ADA_MAX_GRADE),
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
    # Projected CRS in metres. Must match the city's UTM zone -- using Washington's
    # zone 10N for Phoenix would distort every distance in the pipeline.
    crs: str = "EPSG:32610"
    arcgis_service: str | None = None
    arcgis_url: str | None = None
    osm_filter: dict = field(default_factory=dict)


CITIES = {
    "seattle": City(
        key="seattle",
        place="Seattle, Washington, USA",
        state="53", county="033",  # King County
        pop_reference=755_000,
        facility_source="arcgis",
        crs="EPSG:32610",  # UTM 10N
        arcgis_service="Seattle_Public_Library",
    ),
    "tacoma": City(
        key="tacoma",
        place="Tacoma, Washington, USA",
        state="53", county="053",  # Pierce County
        pop_reference=222_000,
        facility_source="osm",
        crs="EPSG:32610",  # UTM 10N
        # OSM tags amenity=library indiscriminately: the 12 features in Tacoma include
        # two university libraries and a prep-school one. The operator website is the
        # reliable discriminator -- the 8 that match are locations/1..8, which is
        # exactly Tacoma Public Library's branch count.
        osm_filter={"tags": {"amenity": "library"}, "website_contains": "tacomalibrary.org"},
    ),
}


CITIES["phoenix"] = City(
    key="phoenix",
    place="Phoenix, Arizona, USA",
    state="04", county="013",  # Maricopa County
    pop_reference=1_650_000,
    facility_source="arcgis_url",
    crs="EPSG:32612",  # UTM 12N
    arcgis_url=("https://maps.phoenix.gov/pub/rest/services/Public/Libraries/"
                "MapServer/0/query"),
)


def get(key: str) -> City:
    if key not in CITIES:
        raise KeyError(f"unknown city {key!r}; known: {sorted(CITIES)}")
    return CITIES[key]
