"""Wolf game logic — no DB or UI dependencies."""

from courses import course_handicap, strokes_on_hole, net_score


# ── Wolf rotation ─────────────────────────────────────────────────────────────

def wolf_for_hole(players: list, hole: int, cumulative_after_16: dict | None = None) -> dict:
    """
    Return the wolf player dict for a given hole (1-18).
    players: list of wolf_player dicts sorted by wolf_order (ascending).
    cumulative_after_16: {player_id -> total points} — required for holes 17 & 18.
    """
    if hole <= 16:
        return players[(hole - 1) % 4]
    ranked = sorted(
        players,
        key=lambda p: (cumulative_after_16.get(p["id"], 0) if cumulative_after_16 else 0,
                       p["wolf_order"]),
    )
    return ranked[0] if hole == 17 else ranked[1]


# ── Points calculation ────────────────────────────────────────────────────────

def compute_hole_points(
    decision: str,
    wolf_id: int,
    partner_id: int | None,
    net_scores: dict,      # {player_id -> net_score | None}
    all_ids: list,
) -> tuple[dict, str]:
    """
    Return ({player_id -> pts_earned}, result_label).

    Points table:
      Blind Lone Wolf wins  → Wolf +6
      Blind Lone Wolf loses → Each of 3 others +6
      Lone Wolf wins        → Wolf +4
      Lone Wolf loses       → Each of 3 others +3
      Wolf+Partner win      → Wolf +2, Partner +2
      Wolf+Partner lose     → Each of other 2 +2
    """
    points = {pid: 0 for pid in all_ids}
    scored = {pid: ns for pid, ns in net_scores.items() if ns is not None and pid in all_ids}

    if len(scored) < 2:
        return points, "incomplete"

    wolf_net = scored.get(wolf_id)

    if decision in ("blind_lone", "lone"):
        pts_win  = 6 if decision == "blind_lone" else 4
        pts_lose = 6 if decision == "blind_lone" else 3
        others   = {pid: ns for pid, ns in scored.items() if pid != wolf_id}
        if wolf_net is None or not others:
            return points, "incomplete"
        best_other = min(others.values())
        if wolf_net < best_other:
            points[wolf_id] = pts_win
            return points, "wolf_wins"
        elif wolf_net > best_other:
            for pid in others:
                points[pid] = pts_lose
            return points, "others_win"
        else:
            return points, "push"

    elif decision == "partner" and partner_id is not None:
        wolf_team  = {pid for pid in (wolf_id, partner_id) if pid in scored}
        other_team = {pid for pid in all_ids if pid not in (wolf_id, partner_id) and pid in scored}
        if not wolf_team or not other_team:
            return points, "incomplete"
        best_wolf  = min(scored[pid] for pid in wolf_team)
        best_other = min(scored[pid] for pid in other_team)
        if best_wolf < best_other:
            for pid in (wolf_id, partner_id):
                if pid in all_ids:
                    points[pid] = 2
            return points, "wolf_wins"
        elif best_wolf > best_other:
            for pid in other_team:
                points[pid] = 2
            return points, "others_win"
        else:
            return points, "push"

    return points, "incomplete"


RESULT_LABELS = {
    "wolf_wins":  "🐺 Wolf wins!",
    "others_win": "💪 Others win!",
    "push":       "🤝 Push — no points",
    "incomplete": "⏳ Decision or scores missing",
}


# ── Full-round standings ──────────────────────────────────────────────────────

def compute_standings(players: list, scores_lkp: dict, decisions: dict, course_data: dict):
    """
    Compute wolf standings across all 18 holes.

    players:    list of wolf_player dicts (id, wolf_order, player_name, handicap, tee)
    scores_lkp: {(player_id, hole) -> gross}
    decisions:  {hole -> {decision, partner_id}}  (only holes where decision was set)
    course_data: COURSES[course_name]

    Returns:
        standings  - list of player-summary dicts sorted by points desc
        hole_pts   - {hole -> {player_id -> pts}}
        cum16      - {player_id -> pts} after 16 holes (for wolf 17/18 display)
    """
    all_ids    = [p["id"] for p in players]
    player_map = {p["id"]: p for p in players}
    par_total  = sum(course_data["par"])

    # Course handicap per player
    course_hcps = {}
    for p in players:
        ti = course_data["tees"].get(p["tee"], list(course_data["tees"].values())[0])
        course_hcps[p["id"]] = course_handicap(p["handicap"], ti["slope"], ti["rating"], par_total)

    cumulative = {pid: 0 for pid in all_ids}
    hole_pts   = {}
    cum16      = None

    for h in range(1, 19):
        wolf = wolf_for_hole(players, h, cumulative if h > 16 else None)
        dec  = decisions.get(h, {})
        decision   = dec.get("decision")
        partner_id = dec.get("partner_id")

        # Net scores this hole
        net_scores = {}
        for pid in all_ids:
            gross = scores_lkp.get((pid, h))
            if gross is not None:
                p  = player_map[pid]
                ti = course_data["tees"].get(p["tee"], list(course_data["tees"].values())[0])
                si = course_data[ti["si_key"]][h - 1]
                net_scores[pid] = net_score(gross, course_hcps[pid], si)
            else:
                net_scores[pid] = None

        if decision:
            pts, _ = compute_hole_points(decision, wolf["id"], partner_id, net_scores, all_ids)
        else:
            pts = {pid: 0 for pid in all_ids}

        hole_pts[h] = pts
        for pid in all_ids:
            cumulative[pid] += pts.get(pid, 0)

        if h == 16:
            cum16 = dict(cumulative)

    # Per-player summary
    standings = []
    for p in players:
        pid = p["id"]
        ti  = course_data["tees"].get(p["tee"], list(course_data["tees"].values())[0])
        si_key  = ti["si_key"]
        par_key = ti.get("par_key", "par")
        pars    = course_data.get(par_key, course_data["par"])

        gross_total = 0
        net_total   = 0
        par_played  = 0
        holes_played = 0

        for h in range(1, 19):
            gross = scores_lkp.get((pid, h))
            if gross is not None:
                holes_played += 1
                gross_total  += gross
                si    = course_data[si_key][h - 1]
                ns    = net_score(gross, course_hcps[pid], si)
                net_total  += ns
                par_played += pars[h - 1]

        vs_par = (net_total - par_played) if holes_played > 0 else None

        standings.append({
            "id":         pid,
            "name":       p["player_name"],
            "wolf_order": p["wolf_order"],
            "points":     cumulative[pid],
            "gross":      gross_total if holes_played > 0 else None,
            "net":        net_total   if holes_played > 0 else None,
            "vs_par":     vs_par,
            "holes":      holes_played,
            "course_hcp": course_hcps[pid],
        })

    standings.sort(key=lambda x: -x["points"])
    return standings, hole_pts, cum16 or dict(cumulative)
