# ── Player roster (sorted lowest to highest handicap) ─────────────────────────
PLAYERS = [
    ("Braeden", 12),
    ("Riki",    15),
    ("Kyle",    15),
    ("Jake",    16),
    ("Ben",     17),
    ("Aidan",   20),
    ("Ryan",    22),
    ("Broden",  24),
    ("Sean",    24),
    ("Connor",  24),
    ("Tyler",   27),
    ("Kenzie",  27),
    ("Kelso",  30),  
    ("Joel",  30),
    ("Gemma",  30),  
]

# ── Course data ───────────────────────────────────────────────────────────────
# Slope / Course Rating are estimates — confirm with Springbank Links pro shop.
# SI = Stroke Index (handicap hole order). Slope/Rating determine how many
# total strokes a player receives when adjusted for each tee box.

COURSES = {
    "Woodside Golf Course": {
        "holes": 18,
        # Hole 4 is par 4 (men) / par 5 (ladies) — using men's par here
        "par":      [4, 4, 3, 4, 4, 4, 3, 4, 5,   4, 4, 3, 5, 3, 4, 4, 4, 4],
        "par_ladies": [4, 4, 3, 5, 4, 4, 3, 4, 5, 4, 4, 3, 5, 3, 4, 4, 4, 4],
        "si_mens":   [13, 1, 11, 3, 15, 7, 17, 9, 5,  16, 2, 14, 6, 18, 12, 10, 4, 8],
        "si_ladies": [13, 3, 15, 7,  9, 5, 17,11, 1,  16, 6, 14, 2, 18, 12,  8, 4,10],
        "tees": {
            "Black":        {"color": "#222222", "text": "white", "slope": 122, "rating": 68.9, "si_key": "si_mens",   "par_key": "par"},
            "Blue":         {"color": "#1a3a8a", "text": "white", "slope": 117, "rating": 67.3, "si_key": "si_mens",   "par_key": "par"},
            "Blue|White":   {"color": "#4a6fa5", "text": "white", "slope": 114, "rating": 67.3, "si_key": "si_mens",   "par_key": "par"},
            "White":        {"color": "#f0f0f0", "text": "black", "slope": 110, "rating": 64.8, "si_key": "si_mens",   "par_key": "par"},
            "White|Silver": {"color": "#b0b0b0", "text": "white", "slope": 120, "rating": 67, "si_key": "si_ladies", "par_key": "par_ladies"},
            "Silver":       {"color": "#888888", "text": "white", "slope": 110, "rating": 63.6, "si_key": "si_ladies", "par_key": "par_ladies"},
        },
    },
    "Springbank Links": {
        "holes": 18,
        "par": [4, 4, 5, 4, 3, 4, 4, 3, 5,   3, 4, 4, 4, 4, 4, 3, 5, 4],
        "si_mens":   [11, 7, 5, 15, 13, 1, 3, 17, 9,  16, 4, 8, 12, 2, 18, 14, 10, 6],
        "si_ladies": [11, 5, 7, 15, 13, 1, 3, 17, 9,  14, 6, 10, 12, 2, 18, 16,  8, 4],
        "tees": {
            "Emerald":            {"color": "#2d5a27", "text": "white", "slope": 129, "rating": 71.6, "si_key": "si_mens",   "par_key": "par"},
            "Blue":               {"color": "#1a3a8a", "text": "white", "slope": 127, "rating": 69.8, "si_key": "si_mens",   "par_key": "par"},
            "Blue/Silver":        {"color": "#4a6fa5", "text": "white", "slope": 123, "rating": 67.8, "si_key": "si_mens",   "par_key": "par"},
            "Silver":             {"color": "#888888", "text": "white", "slope": 120, "rating": 66.2, "si_key": "si_mens",   "par_key": "par"},
            "Silver/Gold Senior": {"color": "#b8a040", "text": "white", "slope": 115, "rating": 64.6, "si_key": "si_mens",   "par_key": "par"},
            "Gold":               {"color": "#c8a000", "text": "white", "slope": 119, "rating": 68.0, "si_key": "si_ladies", "par_key": "par"},
            "Red":                {"color": "#c83020", "text": "white", "slope": 111, "rating": 65.1, "si_key": "si_ladies", "par_key": "par"},
        },
    }
}

FORMATS = ["2-Person Net Best Ball", "Wolf"]

ADMIN_PASSWORD = "chigga"


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

def score_cell_html(gross, par, strokes: int = 0) -> str:
    """Return gross score wrapped in golf-standard symbols, with handicap dot(s) if strokes > 0."""
    if gross is None or gross == "":
        return '<span style="color:#aaa">—</span>'
    try:
        gross = int(gross)
        par   = int(par)
    except (TypeError, ValueError):
        return str(gross)

    diff = gross - par

    if diff <= -2:   # Eagle or better — double circle
        inner = (f'<span style="display:inline-block;border:2px solid #1a7a3c;border-radius:50%;'
                 f'box-shadow:0 0 0 4px #1a7a3c;padding:1px 5px;color:#1a7a3c;">{gross}</span>')
    elif diff == -1: # Birdie — single circle
        inner = (f'<span style="display:inline-block;border:2px solid #1a7a3c;border-radius:50%;'
                 f'padding:1px 5px;color:#1a7a3c;">{gross}</span>')
    elif diff == 0:  # Par — plain
        inner = str(gross)
    elif diff == 1:  # Bogey — single square
        inner = (f'<span style="display:inline-block;border:2px solid #333;'
                 f'padding:1px 5px;">{gross}</span>')
    elif diff == 2:  # Double bogey — double square
        inner = (f'<span style="display:inline-block;border:2px solid #333;'
                 f'outline:2px solid #333;outline-offset:3px;padding:1px 5px;">{gross}</span>')
    else:            # Triple+ — red double square
        inner = (f'<span style="display:inline-block;border:2px solid #c00;'
                 f'outline:2px solid #c00;outline-offset:3px;'
                 f'padding:1px 5px;color:#c00;font-weight:bold;">{gross}</span>')

    if strokes > 0:
        dots = '•' * strokes
        # Wrap in a relative-positioned span so the dot sits in the top-right corner
        return (f'<span style="position:relative;display:inline-block">'
                f'<span style="position:absolute;top:-4px;right:-5px;font-size:0.85rem;'
                f'color:#111;line-height:1;font-weight:bold">{dots}</span>'
                f'{inner}</span>')
    return inner
