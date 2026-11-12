"""How graduate admission and funding usually work per country, used for scoring and drafting.

`contact_first` is how much a prior email to a prospective supervisor matters:
  required   - admission or the scholarship route needs a supervisor's acceptance/consent
  expected   - supervisors usually admit (and often fund) students directly
  encouraged - central admissions, but a supervisor's interest helps
  optional   - mostly advertised positions; email about a specific posting

These are general patterns, not deadlines. The profiler records the actual posting and
deadline it finds on a page (open_positions), and drafts should prefer that evidence.
"""
from gradlead.normalize import name_key

RULES = {
    "canada": {
        "region": "Canada", "contact_first": "expected",
        "routes": ["supervisor-funded thesis-based MSc or PhD (stipend from the supervisor's grants plus university awards)"],
        "programme": "a funded thesis-based MSc (or a PhD position)",
    },
    "australia": {
        "region": "Australia", "contact_first": "expected",
        "routes": ["Research Training Program (RTP) or university research scholarships, applied for with a supervisor's support"],
        "programme": "an MPhil (research Master's) or PhD place with an RTP or university research scholarship",
    },
    "china": {
        "region": "China", "contact_first": "required",
        "routes": ["Chinese Government Scholarship (CSC); many routes ask for a supervisor's pre-admission or acceptance letter",
                   "university and provincial scholarships for international students"],
        "programme": "a research Master's (or PhD) place under the Chinese Government (CSC) Scholarship",
    },
    "hong kong": {
        "region": "China", "contact_first": "encouraged",
        "routes": ["Hong Kong PhD Fellowship Scheme (HKPFS), whose application window usually closes in early December",
                   "university postgraduate studentships"],
        "programme": "a funded MPhil (or a PhD place through the Hong Kong PhD Fellowship Scheme)",
    },
    "united kingdom": {
        "region": "Europe", "contact_first": "encouraged",
        "routes": ["funded studentships (doctoral training partnerships / centres for doctoral training)",
                   "supervisor-advertised funded projects"],
        "programme": "a funded MSc by Research or MRes (or a PhD studentship)",
    },
    "germany": {
        "region": "Europe", "contact_first": "encouraged",
        "routes": ["salaried research-assistant PhD positions hired directly by professors", "graduate schools (e.g. IMPRS, ELLIS)"],
        "programme": "an MSc with a research thesis in your group (or a PhD position)",
    },
    "switzerland": {
        "region": "Europe", "contact_first": "encouraged",
        "routes": ["salaried doctoral positions; at ETH Zurich a professor must agree to supervise, EPFL also runs a central EDIC admission"],
        "programme": "an MSc with a research thesis in your group (or a PhD position)",
    },
    "netherlands": {
        "region": "Europe", "contact_first": "optional",
        "routes": ["salaried PhD positions advertised as vacancies"],
        "programme": "an MSc with a research thesis in your group (or a PhD position)",
    },
    "belgium": {"region": "Europe", "contact_first": "optional",
                "routes": ["salaried PhD positions and FWO fellowships"], "programme": "an MSc with a research thesis in your group (or a PhD position)"},
    "sweden": {"region": "Europe", "contact_first": "optional",
               "routes": ["salaried doctoral student positions advertised as vacancies (often WASP-funded in AI)"],
               "programme": "an MSc with a research thesis in your group (or a PhD position)"},
    "denmark": {"region": "Europe", "contact_first": "optional",
                "routes": ["salaried PhD positions advertised as vacancies"], "programme": "an MSc with a research thesis in your group (or a PhD position)"},
    "finland": {"region": "Europe", "contact_first": "optional",
                "routes": ["salaried doctoral researcher positions (e.g. FCAI calls)"], "programme": "an MSc with a research thesis in your group (or a PhD position)"},
    "norway": {"region": "Europe", "contact_first": "optional",
               "routes": ["salaried PhD research fellowships advertised as vacancies"], "programme": "an MSc with a research thesis in your group (or a PhD position)"},
    "ireland": {"region": "Europe", "contact_first": "encouraged",
                "routes": ["funded PhD studentships (e.g. Research Ireland centres)"], "programme": "an MSc with a research thesis in your group (or a PhD position)"},
    "france": {"region": "Europe", "contact_first": "encouraged",
               "routes": ["funded thesis contracts tied to a supervisor's project"], "programme": "an MSc with a research thesis in your group (or a PhD position)"},
    "austria": {"region": "Europe", "contact_first": "encouraged",
                "routes": ["salaried PhD positions on professors' projects"], "programme": "an MSc with a research thesis in your group (or a PhD position)"},
    "italy": {"region": "Europe", "contact_first": "optional",
              "routes": ["national PhD calls with scholarships"], "programme": "an MSc with a research thesis in your group (or a PhD position)"},
    "spain": {"region": "Europe", "contact_first": "encouraged",
              "routes": ["FPI/FPU contracts and project-funded PhD positions"], "programme": "an MSc with a research thesis in your group (or a PhD position)"},
    "united arab emirates": {
        "region": "Middle East", "contact_first": "encouraged",
        "routes": ["fully funded MSc/PhD through central admission (e.g. MBZUAI, Khalifa University, NYU Abu Dhabi)"],
        "programme": "a fully funded MSc (or PhD)",
    },
    "saudi arabia": {
        "region": "Middle East", "contact_first": "encouraged",
        "routes": ["fully funded MS/PhD fellowships through central admission (e.g. KAUST)"],
        "programme": "a fully funded MS (or PhD)",
    },
    "qatar": {
        "region": "Middle East", "contact_first": "encouraged",
        "routes": ["funded graduate scholarships (e.g. Hamad Bin Khalifa University)"],
        "programme": "a funded MSc (or PhD)",
    },
    "turkey": {
        "region": "Turkey", "contact_first": "encouraged",
        "routes": ["fully funded PhD/MSc scholarships through central admission (e.g. Koç, Sabancı, Bilkent)",
                   "TÜBİTAK 2215 graduate scholarship for international students"],
        "programme": "a fully funded MSc (or PhD)",
    },
    "united states": {
        "region": "USA", "contact_first": "encouraged",
        "routes": ["funded PhD admission straight from a BSc (tuition waiver plus RA/TA stipend), through a department committee; "
                   "Fall 2027 deadlines are mostly 1-15 December 2026",
                   "funded MS places are rare; an RA on a professor's grant is the usual route"],
        "programme": "a funded PhD place for Fall 2027 (or a funded MS with a research assistantship)",
    },
}

# Countries we never target: targets, adverts and exports skip them.
EXCLUDED_COUNTRIES = {"israel"}

ALIASES = {
    "uk": "united kingdom", "england": "united kingdom", "scotland": "united kingdom", "wales": "united kingdom",
    "great britain": "united kingdom", "uae": "united arab emirates", "ksa": "saudi arabia",
    "hong kong sar": "hong kong", "hk": "hong kong", "prc": "china", "mainland china": "china",
    "the netherlands": "netherlands", "holland": "netherlands", "türkiye": "turkey", "turkiye": "turkey",
    "usa": "united states", "us": "united states", "united states of america": "united states", "u.s.": "united states",
}

CONTACT_POINTS = {"required": 5, "expected": 5, "encouraged": 3, "optional": 1}
DEFAULT = {"region": "Other", "contact_first": "optional", "routes": [], "programme": "a funded research MSc (or PhD)"}


def country_key(country: str | None) -> str:
    key = name_key(country or "")
    return ALIASES.get(key, key)


def info(country: str | None) -> dict:
    key = country_key(country)
    return {"country": key, **RULES.get(key, DEFAULT)}


def is_excluded(country: str | None) -> bool:
    return country_key(country) in EXCLUDED_COUNTRIES


def region(country: str | None) -> str:
    return info(country)["region"]


def region_points(country: str | None) -> int:
    return CONTACT_POINTS[info(country)["contact_first"]]
