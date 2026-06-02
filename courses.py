COURSES = {
    "Springbank Links": {
        "holes": 18,
        "par": [4, 4, 5, 4, 3, 4, 4, 3, 5,  3, 4, 4, 4, 4, 4, 3, 5, 4],
        "si_mens":   [11, 7, 5, 15, 13, 1, 3, 17, 9,  16, 4, 8, 12, 2, 18, 14, 10, 6],
        "si_ladies": [11, 5, 7, 15, 13, 1, 3, 17, 9,  14, 6, 10, 12, 2, 18, 16,  8, 4],
    }
}

FORMATS = ["2-Person Net Best Ball"]


def get_strokes_on_hole(handicap: int, stroke_index: int) -> int:
    """Return extra strokes a player receives on a given hole."""
    full_strokes = handicap // 18
    remainder = handicap % 18
    return full_strokes + (1 if stroke_index <= remainder else 0)


def net_score(gross: int, handicap: int, stroke_index: int) -> int:
    return gross - get_strokes_on_hole(handicap, stroke_index)
