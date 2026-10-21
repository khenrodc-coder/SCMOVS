"""Places used in address fields. The province is fixed: SCMOVS is used in Nueva Ecija.

The 5 cities and 27 municipalities of Nueva Ecija. Barangays and puroks/streets are typed by the user
(there are hundreds, and they change), but the city or municipality must come from this list.
"""
PROVINCE = "Nueva Ecija"

CITIES = ("Cabanatuan City", "Gapan City", "Palayan City", "San Jose City", "Science City of Mu\u00f1oz")
MUNICIPALITIES = (
    "Aliaga", "Bongabon", "Cabiao", "Carranglan", "Cuyapo", "Gabaldon", "General Mamerto Natividad", "General Tinio",
    "Guimba", "Jaen", "Laur", "Licab", "Llanera", "Lupao", "Nampicuan", "Pantabangan", "Pe\u00f1aranda", "Quezon", "Rizal",
    "San Antonio", "San Isidro", "San Leonardo", "Santa Rosa", "Santo Domingo", "Talavera", "Talugtug", "Zaragoza",
)
# (value, label) pairs sorted A-Z; the value is what is stored
PLACES = tuple(sorted(CITIES + MUNICIPALITIES, key=lambda n: n.lower()))


def match_place(text):
    """Return the official spelling of a city/municipality (case-insensitive), or None.

    Also accepts a few common short forms, e.g. 'Cabanatuan', 'Munoz', 'Penaranda'.
    """
    wanted = _key(text)
    if not wanted:
        return None
    for name in PLACES:
        if _key(name) == wanted:
            return name
    aliases = {"cabanatuan": "Cabanatuan City", "gapan": "Gapan City", "palayan": "Palayan City",
               "san jose": "San Jose City", "munoz": "Science City of Mu\u00f1oz", "science city": "Science City of Mu\u00f1oz",
               "science city of munoz": "Science City of Mu\u00f1oz", "penaranda": "Pe\u00f1aranda"}
    return aliases.get(wanted)


def _key(text):
    table = str.maketrans({"\u00f1": "n", "\u00d1": "n"})
    return " ".join((text or "").translate(table).lower().replace(".", " ").split())
