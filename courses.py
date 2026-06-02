# ── Player roster (sorted lowest to highest handicap) ─────────────────────────
PLAYERS = [
    ("Braeden", 12),
    ("Riki",    15),
    ("Kyle",    15),
    ("Jake",    16),
    ("Ben",     17),
    ("Aidan",   20),
    ("Ryan",    20),
    ("Broden",  24),
    ("Sean",    24),
    ("Tyler",   27),
    ("Kenzie",  27),
]

# ── Course data ───────────────────────────────────────────────────────────────
# Slope / Course Rating are estimates — confirm with Springbank Links pro shop.
# SI = Stroke Index (handicap hole order). Slope/Rating determine how many
# total strokes a player receives when adjusted for each tee box.

COURSES = {
    "Springbank Links": {
        "holes": 18,
        "par": [4, 4, 5, 4, 3, 4, 4, 3, 5,   3, 4, 4, 4, 4, 4, 3, 5, 4],
        "si_mens":   [11, 7, 5, 15, 13, 1, 3, 17, 9,  16, 4, 8, 12, 2, 18, 14, 10, 6],
        "si_ladies": [11, 5, 7, 15, 13, 1, 3, 17, 9,  14, 6, 10, 12, 2, 18, 16,  8, 4],
        "tees": {
            "Emerald":            {"color": "#2d5a27", "text": "white",  "slope": 133, "rating": 72.1, "si_key": "si_mens"},
            "Blue":               {"color": "#1a3a8a", "text": "white",  "slope": 128, "rating": 70.4, "si_key": "si_mens"},
            "Blue/Silver":        {"color": "#4a6fa5", "text": "white",  "slope": 122, "rating": 68.5, "si_key": "si_mens"},
            "Silver":             {"color": "#888888", "text": "white",  "slope": 117, "rating": 66.8, "si_key": "si_mens"},
            "Silver/Gold Senior": {"color": "#b8a040", "text": "white",  "slope": 113, "rating": 65.3, "si_key": "si_mens"},
            "Gold":               {"color": "#c8a000", "text": "white",  "slope": 107, "rating": 63.0, "si_key": "si_ladies"},
            "Red":                {"color": "#c83020", "text": "white",  "slope": 101, "rating": 60.5, "si_key": "si_ladies"},
        },
    }
}

FORMATS = ["2-Person Net Best Ball"]

ADMIN_PASSWORD = "springbank"   # change this to whatever you like


# ── Handicap maths ────────────────────────────────────────────────────────────

def course_handicap(handicap_index: float, slope: int, rating: float, par: int) -> int:
    """World Handicap System course handicap formula."""
    return round(handicap_index * (slope / 113) + (rating - par))


def strokes_on_hole(course_hcp: int, si: int) -> int:
    """How many extra strokes a player receives on a hole given their course handicap."""
    full = course_hcp // 18
    remainder = course_hcp % 18
    return full + (1 if si <= remainder else 0)


def net_score(gross: int, course_hcp: int, si: int) -> int:
    return gross - strokes_on_hole(course_hcp, si)


# ── Scorecard cell HTML ───────────────────────────────────────────────────────

def score_cell_html(gross, par) -> str:
    """Return gross score wrapped in golf-standard symbols."""
    if gross is None or gross == "":
        return '<span style="color:#aaa">—</span>'
    try:
        gross = int(gross)
        par   = int(par)
    except (TypeError, ValueError):
        return str(gross)

    diff = gross - par

    base = f'<b>{gross}</b>'

    if diff <= -2:   # Eagle or better — double circle
        return (f'<span style="display:inline-block;border:2px solid #1a7a3c;border-radius:50%;'
                f'box-shadow:0 0 0 4px #1a7a3c;padding:1px 5px;color:#1a7a3c;">{gross}</span>')
    elif diff == -1: # Birdie — single circle
        return (f'<span style="display:inline-block;border:2px solid #1a7a3c;border-radius:50%;'
                f'padding:1px 5px;color:#1a7a3c;">{gross}</span>')
    elif diff == 0:  # Par — plain
        return str(gross)
    elif diff == 1:  # Bogey — single square
        return (f'<span style="display:inline-block;border:2px solid #333;'
                f'padding:1px 5px;">{gross}</span>')
    elif diff == 2:  # Double bogey — double square
        return (f'<span style="display:inline-block;border:2px solid #333;'
                f'outline:2px solid #333;outline-offset:3px;padding:1px 5px;">{gross}</span>')
    else:            # Triple+ — red double square
        return (f'<span style="display:inline-block;border:2px solid #c00;'
                f'outline:2px solid #c00;outline-offset:3px;'
                f'padding:1px 5px;color:#c00;font-weight:bold;">{gross}</span>')
