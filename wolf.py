"""Wolf game logic — no DB or UI dependencies."""

from courses import course_handicap, strokes_on_hole, net_score


# ── Wolf rotation ─────────────────────────────────────────────────────────────

def wolf_for_hole(players: list, hole: int, cumulative_after_16: dict | None = None) -> dict:
    if hole <= 16:
        return players[(hole - 1) % 4]
    ranked = sorted(
        players,
        key=lambda p: (cumulative_after_16.get(p["id"], 0) if cumulative_after_16 else 0,
                       p["wolf_order"]),
    )
    return ranked[0] if hole == 17 else ranked[1]


# ── Per-player score multiplier (birdie / eagle) ──────────────────────────────

def _score_mult(pid: int, gross_scores: dict, hole_pars: dict) -> int:
    """Return 3 for eagle-or-better, 2 for birdie, 1 for par-or-worse."""
    g = gross_scores.get(pid)
    p = hole_pars.get(pid, 4)
    if g is None:
        return 1
    if g <= p - 2:
        return 3   # eagle or better
    if g == p - 1:
        return 2   # birdie
    return 1


# ── Points calculation ────────────────────────────────────────────────────────

def compute_hole_points(
    decision: str,
    wolf_id: int,
    partner_id: int | None,
    net_scores: dict,    # {player_id -> net_score | None}
    gross_scores: dict,  # {player_id -> gross | None}
    hole_pars: dict,     # {player_id -> par for their tee on this hole}
    all_ids: list,
    carry_mult: int = 1,
) -> tuple[dict, str, int]:
    """
    Returns ({player_id -> pts_earned}, result_label, next_carry_mult).

    Base points (before multipliers):
      Blind Lone Wolf wins  → Wolf 6
      Blind Lone Wolf loses → each other 3
      Lone Wolf wins        → Wolf 4
      Lone Wolf loses       → each other 2
      Wolf+Partner win      → each 2
      Wolf+Partner lose     → each of other 2 get 3

    Multipliers applied to each winning player's points:
      carry_mult  — doubles on every push (1 → 2 → 4 → 8 …), resets to 1 on win
      score_mult  — birdie ×2, eagle ×3  (per-player, only affects that player's points)
      combined    — carry_mult × score_mult(player)

    Examples on a ×2 carry hole:
      Wolf wins lone wolf with a birdie → 4 × 2 × 2 = 16 pts
      Opponent wins vs lone wolf with a birdie → 2 × 2 × 2 = 8 pts each
    """
    points = {pid: 0 for pid in all_ids}
    scored = {pid: ns for pid, ns in net_scores.items() if ns is not None and pid in all_ids}

    if len(scored) < 2:
        return points, "incomplete", carry_mult

    wolf_net = scored.get(wolf_id)

    if decision in ("blind_lone", "lone"):
        base_win  = 6 if decision == "blind_lone" else 4
        base_lose = 3 if decision == "blind_lone" else 2
        others = {pid: ns for pid, ns in scored.items() if pid != wolf_id}
        if wolf_net is None or not others:
            return points, "incomplete", carry_mult
        best_other = min(others.values())

        if wolf_net < best_other:
            sm = _score_mult(wolf_id, gross_scores, hole_pars)
            points[wolf_id] = base_win * carry_mult * sm
            return points, "wolf_wins", 1
        elif wolf_net > best_other:
            for pid in others:
                sm = _score_mult(pid, gross_scores, hole_pars)
                points[pid] = base_lose * carry_mult * sm
            return points, "others_win", 1
        else:
            return points, "push", carry_mult * 2

    elif decision == "partner" and partner_id is not None:
        wolf_team  = {pid for pid in (wolf_id, partner_id) if pid in scored}
        other_team = {pid for pid in all_ids if pid not in (wolf_id, partner_id) and pid in scored}
        if not wolf_team or not other_team:
            return points, "incomplete", carry_mult
        best_wolf  = min(scored[pid] for pid in wolf_team)
        best_other = min(scored[pid] for pid in other_team)

        if best_wolf < best_other:
            for pid in (wolf_id, partner_id):
                if pid in all_ids:
                    sm = _score_mult(pid, gross_scores, hole_pars)
                    points[pid] = 2 * carry_mult * sm
            return points, "wolf_wins", 1
        elif best_wolf > best_other:
            for pid in other_team:
                sm = _score_mult(pid, gross_scores, hole_pars)
                points[pid] = 3 * carry_mult * sm
            return points, "others_win", 1
        else:
            return points, "push", carry_mult * 2

    return points, "incomplete", carry_mult


RESULT_LABELS = {
    "wolf_wins":  "🐺 Wolf wins!",
    "others_win": "💪 Others win!",
    "push":       "🤝 Push — carries over!",
    "incomplete": "⏳ Decision or scores missing",
}


# ── Full-round standings ──────────────────────────────────────────────────────

def compute_standings(players: list, scores_lkp: dict, decisions: dict, course_data: dict):
    """
    Returns:
        standings   - list of player-summary dicts sorted by points desc
        hole_pts    - {hole -> {player_id -> pts}}
        cum16       - {player_id -> pts} after 16 holes (for wolf 17/18)
        hole_carry  - {hole -> carry_mult that was in effect on that hole}
    """
    all_ids    = [p["id"] for p in players]
    player_map = {p["id"]: p for p in players}
    par_total  = sum(course_data["par"])

    course_hcps = {}
    for p in players:
        ti = course_data["tees"].get(p["tee"], list(course_data["tees"].values())[0])
        course_hcps[p["id"]] = course_handicap(p["handicap"], ti["slope"], ti["rating"], par_total)

    cumulative  = {pid: 0 for pid in all_ids}
    hole_pts    = {}
    hole_carry  = {}
    cum16       = None
    carry_mult  = 1   # tracks running carry across holes

    for h in range(1, 19):
        hole_carry[h] = carry_mult   # record what carry was in effect THIS hole
        wolf = wolf_for_hole(players, h, cumulative if h > 16 else None)
        dec  = decisions.get(h, {})
        decision   = dec.get("decision")
        partner_id = dec.get("partner_id")

        # Gross and net scores this hole, plus per-player par
        gross_h = {}
        net_h   = {}
        par_h   = {}
        for pid in all_ids:
            gross = scores_lkp.get((pid, h))
            p     = player_map[pid]
            ti    = course_data["tees"].get(p["tee"], list(course_data["tees"].values())[0])
            si    = course_data[ti["si_key"]][h - 1]
            pk    = ti.get("par_key", "par")
            par_h[pid] = course_data.get(pk, course_data["par"])[h - 1]
            gross_h[pid] = gross
            net_h[pid]   = net_score(gross, course_hcps[pid], si) if gross is not None else None

        if decision:
            pts, result, carry_mult = compute_hole_points(
                decision, wolf["id"], partner_id,
                net_h, gross_h, par_h, all_ids, carry_mult
            )
        else:
            pts = {pid: 0 for pid in all_ids}
            # No decision yet — carry doesn't advance or reset

        hole_pts[h] = pts
        for pid in all_ids:
            cumulative[pid] += pts.get(pid, 0)

        if h == 16:
            cum16 = dict(cumulative)

    # Per-player totals
    standings = []
    for p in players:
        pid = p["id"]
        ti  = course_data["tees"].get(p["tee"], list(course_data["tees"].values())[0])
        si_key  = ti["si_key"]
        par_key = ti.get("par_key", "par")
        pars    = course_data.get(par_key, course_data["par"])

        gross_total  = 0
        net_total    = 0
        par_played   = 0
        holes_played = 0

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
            "wolf_order": p["wolf_order"],
            "points":     cumulative[pid],
            "gross":      gross_total if holes_played > 0 else None,
            "net":        net_total   if holes_played > 0 else None,
            "vs_par":     vs_par,
            "holes":      holes_played,
            "course_hcp": course_hcps[pid],
        })

    standings.sort(key=lambda x: -x["points"])
    return standings, hole_pts, cum16 or dict(cumulative), hole_carry
