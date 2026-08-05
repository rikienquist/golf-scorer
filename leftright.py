"""Left-Right game logic — no DB or UI dependencies."""

from courses import course_handicap, strokes_on_hole, net_score


def make_lr_decision(left_ids: list) -> str:
    """Encode the two left-team player IDs as a decision string."""
    s = sorted(left_ids)
    return f"lr_{s[0]}_{s[1]}"


def parse_lr_left_ids(decision: str) -> list:
    """Decode 'lr_PID1_PID2' → [pid1, pid2], or [] if not set."""
    if not decision or not decision.startswith("lr_"):
        return []
    try:
        parts = decision.split("_")
        return [int(parts[1]), int(parts[2])]
    except (IndexError, ValueError):
        return []


def compute_hole_result(left_ids: list, right_ids: list, net_scores: dict) -> tuple:
    """
    Returns ({player_id -> pts}, result_label).
    result_label: 'left_wins' | 'right_wins' | 'tie' | 'incomplete'
    """
    points = {pid: 0 for pid in left_ids + right_ids}

    left_nets  = [net_scores.get(pid) for pid in left_ids]
    right_nets = [net_scores.get(pid) for pid in right_ids]

    if any(n is None for n in left_nets + right_nets):
        return points, "incomplete"

    left_agg  = sum(left_nets)
    right_agg = sum(right_nets)

    if left_agg < right_agg:
        for pid in left_ids:
            points[pid] = 1
        return points, "left_wins"
    elif right_agg < left_agg:
        for pid in right_ids:
            points[pid] = 1
        return points, "right_wins"
    else:
        return points, "tie"


def compute_lr_standings(players: list, scores_lkp: dict, decisions: dict, course_data: dict):
    """
    Returns:
        standings  - list of player-summary dicts sorted by points desc
        hole_pts   - {hole -> {player_id -> pts}}
    """
    all_ids    = [p["id"] for p in players]
    player_map = {p["id"]: p for p in players}
    par_total  = sum(course_data["par"])

    course_hcps = {}
    for p in players:
        ti = course_data["tees"].get(p["tee"], list(course_data["tees"].values())[0])
        course_hcps[p["id"]] = course_handicap(p["handicap"], ti["slope"], ti["rating"], par_total)

    cumulative = {pid: 0 for pid in all_ids}
    hole_pts   = {}

    for h in range(1, 19):
        dec      = decisions.get(h, {})
        decision = dec.get("decision", "")
        left_ids = parse_lr_left_ids(decision)
        right_ids = [pid for pid in all_ids if pid not in left_ids] if len(left_ids) == 2 else []

        net_h = {}
        for pid in all_ids:
            gross = scores_lkp.get((pid, h))
            p  = player_map[pid]
            ti = course_data["tees"].get(p["tee"], list(course_data["tees"].values())[0])
            si = course_data[ti["si_key"]][h - 1]
            net_h[pid] = net_score(gross, course_hcps[pid], si) if gross is not None else None

        if len(left_ids) == 2 and len(right_ids) == 2:
            pts, _ = compute_hole_result(left_ids, right_ids, net_h)
        else:
            pts = {pid: 0 for pid in all_ids}

        hole_pts[h] = pts
        for pid in all_ids:
            cumulative[pid] += pts.get(pid, 0)

    standings = []
    for p in players:
        pid     = p["id"]
        ti      = course_data["tees"].get(p["tee"], list(course_data["tees"].values())[0])
        si_key  = ti["si_key"]
        par_key = ti.get("par_key", "par")
        pars    = course_data.get(par_key, course_data["par"])

        gross_total = net_total = par_played = holes_played = 0

        for h in range(1, 19):
            gross = scores_lkp.get((pid, h))
            if gross is not None:
                holes_played += 1
                gross_total  += gross
                si  = course_data[si_key][h - 1]
                ns  = net_score(gross, course_hcps[pid], si)
                net_total  += ns
                par_played += pars[h - 1]

        vs_par = (net_total - par_played) if holes_played > 0 else None

        standings.append({
            "id":         pid,
            "name":       p["player_name"],
            "order":      p["wolf_order"],
            "points":     cumulative[pid],
            "gross":      gross_total  if holes_played > 0 else None,
            "net":        net_total    if holes_played > 0 else None,
            "vs_par":     vs_par,
            "holes":      holes_played,
            "course_hcp": course_hcps[pid],
        })

    standings.sort(key=lambda x: -x["points"])
    return standings, hole_pts


RESULT_LABELS = {
    "left_wins":  "⬅️ Left wins!",
    "right_wins": "➡️ Right wins!",
    "tie":        "🤝 Tie",
    "incomplete": "⏳ Scores missing",
}
