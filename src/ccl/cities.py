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


# Accessible-route grade. Under the 2010 ADA Standards a walking surface on an accessible
# route is limited to 1:20 (5%); anything steeper is a *ramp*, which additionally requires
# handrails, landings, edge protection and rise limits. PROWAG R302.4.1 sets the same 5%
# limit on a pedestrian access route in the right-of-way.
#
# 1:12 (8.3%) is the maximum for a *ramp* (ADA) or a *curb ramp* (PROWAG R304.2.1) -- not a
# general limit for walking a city block, which is what this models.
#
# PROWAG grants an exception: where the adjacent street exceeds 5%, the route may match the
# street's grade. So a sidewalk up a steep hill can be fully compliant. 5% is therefore the
# grade an accessible route is *designed* to, not a guarantee that steeper is unlawful --
# which is exactly why it is the right usability threshold and why the label below avoids
# the word "compliant".
PAR_MAX_GRADE = 0.05
ADA_RAMP_MAX_GRADE = 0.0833  # ramps and curb ramps only
ADA_MAX_CROSS_SLOPE = 0.021  # 1:48; not modelled -- no sidewalk cross-slope data

PROFILES = [
    Profile("adult", "Adult (planning standard)", 1.34,
            "3 mph; the 1/4-1/2-3/4 mile heuristic", "population"),
    Profile("older", "Older adult (65+)", 1.00,
            "gait-speed literature; MUTCD uses 1.07 m/s where older pedestrians are present",
            "pop_65plus"),
    Profile("mobility", "Ambulatory difficulty", 0.80,
            "manual wheelchair / walking-aid speeds; 1:20 accessible-route grade",
            "pop_ambulatory", PAR_MAX_GRADE),
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
    # Projected CRS in metres. Must match the city's UTM zone -- using Washington's
    # zone 10N for Phoenix would distort every distance in the pipeline.
    crs: str = "EPSG:32610"


CITIES = {
    "seattle": City(
        key="seattle",
        place="Seattle, Washington, USA",
        state="53", county="033",  # King County
        pop_reference=755_000,
        crs="EPSG:32610",  # UTM 10N
    ),
    "tacoma": City(
        key="tacoma",
        place="Tacoma, Washington, USA",
        state="53", county="053",  # Pierce County
        pop_reference=222_000,
        crs="EPSG:32610",  # UTM 10N
    ),
}


CITIES["phoenix"] = City(
    key="phoenix",
    place="Phoenix, Arizona, USA",
    state="04", county="013",  # Maricopa County
    pop_reference=1_650_000,
    crs="EPSG:32612",  # UTM 12N
)


def get(key: str) -> City:
    if key not in CITIES:
        raise KeyError(f"unknown city {key!r}; known: {sorted(CITIES)}")
    return CITIES[key]


# --------------------------------------------------------------------- amenities


@dataclass(frozen=True)
class Amenity:
    """What is being measured access *to*.

    `geometry` is the load-bearing field. A library is a door: a point. A park is an area
    you enter at its edge, so collapsing it to a centroid puts the access point hundreds of
    metres from where anyone actually walks in -- for a 275 ha park that is a bigger error
    than the thing being measured.
    """

    key: str
    noun: str            # singular, for prose
    label: str           # plural, for headings
    geometry: str        # "point" | "polygon"
    headline_min: int    # the time budget this amenity's standard is written in
    standard_note: str
    sources: dict        # city key -> source spec


# Trust for Public Land's 10-minute-walk methodology, and Metro Parks Tacoma's own
# standard, both count publicly accessible park land and exclude golf courses, cemeteries
# and paid-admission attractions. Seattle's layer is parcel-level, so it is dissolved by
# name first: 2,000 polygons are roughly 500 parks.
_PARK_MIN_AREA_M2 = 1_000.0
_PARK_EXCLUDE = ("GOLF", "ZOO", "CEMETERY")

AMENITIES = {
    "libraries": Amenity(
        key="libraries", noun="library", label="library branches",
        geometry="point", headline_min=15,
        standard_note="15-minute neighbourhood goal; 3 mph on the flat = 0.75 mi",
        sources={
            "seattle": {"kind": "arcgis_service", "service": "Seattle_Public_Library"},
            "tacoma": {"kind": "osm", "tags": {"amenity": "library"},
                       "website_contains": "tacomalibrary.org"},
            "phoenix": {"kind": "arcgis_url",
                        "url": "https://maps.phoenix.gov/pub/rest/services/Public/"
                               "Libraries/MapServer/0/query"},
        },
    ),
    "parks": Amenity(
        key="parks", noun="park", label="parks",
        geometry="polygon", headline_min=10,
        standard_note="10-minute walk to a park (Metro Parks Tacoma; Trust for Public Land)",
        sources={
            "seattle": {"kind": "arcgis_url",
                        "url": "https://services.arcgis.com/ZOyb2t4B0UYuYNYH/arcgis/rest/"
                               "services/Park_Boundary_%28details%29/FeatureServer/2/query",
                        "dissolve": "NAME", "exclude_name": _PARK_EXCLUDE,
                        "min_area_m2": _PARK_MIN_AREA_M2},
            # Metro Parks Tacoma's own layer, filtered to their own analysis set.
            # Anlyss_Lyr is their classification tier: 0 is excluded, 1-4 are
            # Neighborhood / Community / Regional Park and Natural Area. Using their
            # inclusion criteria is what makes the result comparable to the 10-minute
            # walkshed they publish themselves.
            "tacoma": {"kind": "arcgis_url",
                       "url": "https://services1.arcgis.com/WGzzp37bqYMLyzDR/arcgis/rest/"
                              "services/MPT_Parks_Properties_System_and_Strategic_Plan/"
                              "FeatureServer/0/query",
                       "where": "Anlyss_Lyr > 0",
                       "min_area_m2": _PARK_MIN_AREA_M2},
        },
    ),
}


def amenity(key: str) -> Amenity:
    if key not in AMENITIES:
        raise KeyError(f"unknown amenity {key!r}; known: {sorted(AMENITIES)}")
    return AMENITIES[key]
