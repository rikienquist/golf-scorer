import streamlit as st
from streamlit_autorefresh import st_autorefresh
import pandas as pd
from courses import (
    COURSES, FORMATS, PLAYERS, ADMIN_PASSWORD,
    course_handicap, strokes_on_hole, net_score, score_cell_html,
)
from database import (
    init_db, create_round, round_exists, get_round, finalize_round,
    add_team, get_teams, upsert_score, get_scores,
    list_active_rounds, list_completed_rounds,
)

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Golf Scorer",
    page_icon="⛳",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# Keep alive: ping every 25 s so Streamlit Cloud never idles out mid-round
st_autorefresh(interval=25_000, key="keepalive")

init_db()

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .stButton > button { min-height: 48px; font-size: 1rem; width: 100%; }
    .stSelectbox > div, .stNumberInput > div { font-size: 1rem; }
    div[data-testid="column"] .stNumberInput input { font-size:1.4rem; text-align:center; }

    /* Leaderboard */
    .lb-table { width:100%; border-collapse:collapse; font-size:0.9rem; }
    .lb-table th { background:#1a7a3c; color:white; padding:6px 8px; }
    .lb-table td { padding:5px 8px; border-bottom:1px solid #ddd; text-align:center; }
    .lb-table tr:nth-child(even) { background:#f5f5f5; }

    /* Scorecard */
    .sc-table { width:100%; border-collapse:collapse; font-size:0.82rem; }
    .sc-table th { background:#1a7a3c; color:white; padding:4px 6px; text-align:center; white-space:nowrap; }
    .sc-table td { padding:4px 6px; border:1px solid #ddd; text-align:center; white-space:nowrap; }
    .sc-table .row-label { background:#f0f0f0; font-weight:bold; text-align:left; }
    .sc-table .subtotal { background:#e8f4e8; font-weight:bold; }
    .sc-table .vspar-pos { color:#c00; font-weight:bold; }
    .sc-table .vspar-neg { color:#1a7a3c; font-weight:bold; }
    .sc-table .vspar-e   { font-weight:bold; }

    /* Hole status grid */
    .hole-grid { display:flex; flex-wrap:wrap; gap:4px; margin:8px 0; }
    .hole-btn  { width:36px; height:36px; border-radius:6px; border:none;
                 font-size:0.8rem; font-weight:bold; cursor:pointer; }
    .h-done    { background:#1a7a3c; color:white; }
    .h-partial { background:#f0a500; color:white; }
    .h-empty   { background:#e0e0e0; color:#555; }
    .h-active  { outline:3px solid #000; outline-offset:2px; }
</style>
""", unsafe_allow_html=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def go(page: str, **kw):
    st.query_params["page"] = page
    for k, v in kw.items():
        st.query_params[k] = str(v)
    st.rerun()


def home_btn():
    if st.button("🏠 Main Menu", key="home_top"):
        # Clear all params and go home
        st.query_params.clear()
        st.rerun()


def _tee_info(course_data: dict, tee: str) -> dict:
    return course_data["tees"].get(tee, list(course_data["tees"].values())[0])


def _player_course_hcp(team: dict, player_num: int, course_data: dict) -> int:
    """Calculate WHS course handicap for player 1 or 2."""
    if player_num == 1:
        idx = team["p1_handicap"]
        tee = team["p1_tee"]
    else:
        idx = team["p2_handicap"]
        tee = team["p2_tee"]
    ti = _tee_info(course_data, tee)
    par = sum(course_data["par"])
    return course_handicap(idx, ti["slope"], ti["rating"], par)


def _si_for_player(team: dict, player_num: int, course_data: dict, hole_idx: int) -> int:
    tee = team["p1_tee"] if player_num == 1 else team["p2_tee"]
    si_key = _tee_info(course_data, tee)["si_key"]
    return course_data[si_key][hole_idx]


def _par_for_tee(course_data: dict, tee: str) -> list[int]:
    """Return the 18-hole par list appropriate for this tee box."""
    par_key = _tee_info(course_data, tee).get("par_key", "par")
    return course_data.get(par_key, course_data["par"])


def build_score_lookup(scores: list[dict]) -> dict:
    """(team_id, player_num, hole) -> gross"""
    return {(s["team_id"], s["player_num"], s["hole"]): s["gross"] for s in scores}


def hole_status(score_lookup: dict, team_id: int) -> list[str]:
    """Return list of 18 statuses: 'done', 'partial', or 'empty'."""
    out = []
    for h in range(1, 19):
        g1 = score_lookup.get((team_id, 1, h))
        g2 = score_lookup.get((team_id, 2, h))
        if g1 is not None and g2 is not None:
            out.append("done")
        elif g1 is not None or g2 is not None:
            out.append("partial")
        else:
            out.append("empty")
    return out


def compute_leaderboard(round_id: str, course_data: dict) -> pd.DataFrame:
    teams = get_teams(round_id)
    all_scores = get_scores(round_id)
    lkp = build_score_lookup(all_scores)

    rows = []
    for team in teams:
        tid = team["id"]
        hcp1 = _player_course_hcp(team, 1, course_data)
        hcp2 = _player_course_hcp(team, 2, course_data)

        pars1 = _par_for_tee(course_data, team["p1_tee"])
        pars2 = _par_for_tee(course_data, team["p2_tee"])

        total_net_bb = 0
        par_played   = 0
        holes_counted = 0
        shotguns      = 0
        thru = 0

        for h in range(1, 19):
            g1 = lkp.get((tid, 1, h))
            g2 = lkp.get((tid, 2, h))
            if g1 is None and g2 is None:
                continue
            thru = h
            holes_counted += 1
            si1 = _si_for_player(team, 1, course_data, h - 1)
            si2 = _si_for_player(team, 2, course_data, h - 1)
            nets = []
            if g1 is not None:
                nets.append((net_score(g1, hcp1, si1), pars1[h - 1]))
            if g2 is not None:
                nets.append((net_score(g2, hcp2, si2), pars2[h - 1]))
            bb_net, bb_par = min(nets, key=lambda x: x[0])
            total_net_bb += bb_net
            par_played   += bb_par
            if bb_net > bb_par:
                shotguns += 1

        if holes_counted == 0:
            vs_par_str = "—"
            total_str  = "—"
            sort_key   = 9999
        else:
            diff = total_net_bb - par_played
            vs_par_str = f"+{diff}" if diff > 0 else ("E" if diff == 0 else str(diff))
            total_str  = str(total_net_bb)
            sort_key   = diff

        rows.append({
            "Pos":      "",
            "Team":     team["team_name"],
            "Players":  f"{team['p1_name']} / {team['p2_name']}",
            "Thru":     holes_counted if holes_counted > 0 else "—",
            "Net Tot":  total_str,
            "vs Par":   vs_par_str,
            "🍺 Shotguns": shotguns if holes_counted > 0 else "—",
            "_sort":    sort_key,
        })

    if not rows:
        return pd.DataFrame()

    df = (pd.DataFrame(rows)
          .sort_values("_sort")
          .drop(columns="_sort")
          .reset_index(drop=True))
    df["Pos"] = range(1, len(df) + 1)
    return df


def build_scorecard_html(round_id: str, team: dict, course_data: dict) -> str:
    """Build a horizontal scorecard HTML table with golf score symbols."""
    pars1 = _par_for_tee(course_data, team["p1_tee"])
    pars2 = _par_for_tee(course_data, team["p2_tee"])
    # Use p1's par for the header row (both are same except Woodside hole 4 edge case)
    pars = pars1
    all_scores = get_scores(round_id)
    lkp = build_score_lookup(all_scores)
    tid = team["id"]

    hcp1 = _player_course_hcp(team, 1, course_data)
    hcp2 = _player_course_hcp(team, 2, course_data)

    p1 = team["p1_name"]
    p2 = team["p2_name"]

    # Collect per-hole data
    holes_data = []  # list of dicts
    for h in range(1, 19):
        par1 = pars1[h - 1]
        par2 = pars2[h - 1]
        si1  = _si_for_player(team, 1, course_data, h - 1)
        si2  = _si_for_player(team, 2, course_data, h - 1)
        g1   = lkp.get((tid, 1, h))
        g2   = lkp.get((tid, 2, h))
        n1   = net_score(g1, hcp1, si1) if g1 is not None else None
        n2   = net_score(g2, hcp2, si2) if g2 is not None else None

        # Best net: pick lower net; use that player's par for vs-par
        if n1 is not None and n2 is not None:
            if n1 <= n2:
                bb, bb_par = n1, par1
            else:
                bb, bb_par = n2, par2
        elif n1 is not None:
            bb, bb_par = n1, par1
        elif n2 is not None:
            bb, bb_par = n2, par2
        else:
            bb, bb_par = None, par1

        vs = (bb - bb_par) if bb is not None else None
        stk1 = strokes_on_hole(hcp1, si1)
        stk2 = strokes_on_hole(hcp2, si2)
        holes_data.append(dict(
            par=par1, g1=g1, n1=n1, g2=g2, n2=n2, bb=bb, vs=vs,
            si1=si1, si2=si2, par1=par1, par2=par2, stk1=stk1, stk2=stk2
        ))

    def subtotal(lst):
        vals = [x for x in lst if x is not None]
        return sum(vals) if vals else None

    def vs_cell(val):
        if val is None:
            return '<td style="color:#aaa">—</td>'
        txt = f"+{val}" if val > 0 else ("E" if val == 0 else str(val))
        cls = "vspar-pos" if val > 0 else ("vspar-neg" if val < 0 else "vspar-e")
        return f'<td class="{cls}">{txt}</td>'

    def scored_cell(val, par, strokes=0):
        """Cell with golf symbols + handicap dot if strokes > 0."""
        if val is None:
            return '<td style="color:#aaa">—</td>'
        return f'<td style="text-align:center">{score_cell_html(val, par, strokes)}</td>'

    def plain_cell(val):
        return f'<td>{val}</td>' if val is not None else '<td style="color:#aaa">—</td>'


    front = holes_data[:9]
    back  = holes_data[9:]

    # Par sums
    par_out = sum(d["par1"] for d in front)
    par_in  = sum(d["par1"] for d in back)
    par_tot = par_out + par_in

    # Per-group value lists
    g1_front = [d["g1"] for d in front];  g1_back = [d["g1"] for d in back]
    n1_front = [d["n1"] for d in front];  n1_back = [d["n1"] for d in back]
    g2_front = [d["g2"] for d in front];  g2_back = [d["g2"] for d in back]
    n2_front = [d["n2"] for d in front];  n2_back = [d["n2"] for d in back]
    bb_front = [d["bb"] for d in front];  bb_back = [d["bb"] for d in back]
    si1_front = [d["si1"] for d in front]; si1_back = [d["si1"] for d in back]
    si2_front = [d["si2"] for d in front]; si2_back = [d["si2"] for d in back]
    pf  = [d["par1"] for d in front];  pb  = [d["par1"] for d in back]
    pf2 = [d["par2"] for d in front];  pb2 = [d["par2"] for d in back]
    stk1f = [d["stk1"] for d in front]; stk1b = [d["stk1"] for d in back]
    stk2f = [d["stk2"] for d in front]; stk2b = [d["stk2"] for d in back]

    # Subtotals (only sum holes that have a value — fixes the -29 bug)
    g1_out = subtotal(g1_front); g1_in = subtotal(g1_back); g1_tot = subtotal([g1_out, g1_in])
    n1_out = subtotal(n1_front); n1_in = subtotal(n1_back); n1_tot = subtotal([n1_out, n1_in])
    g2_out = subtotal(g2_front); g2_in = subtotal(g2_back); g2_tot = subtotal([g2_out, g2_in])
    n2_out = subtotal(n2_front); n2_in = subtotal(n2_back); n2_tot = subtotal([n2_out, n2_in])
    bb_out = subtotal(bb_front); bb_in = subtotal(bb_back); bb_tot = subtotal([bb_out, bb_in])

    # vs Par subtotals: sum only the per-hole vs-par values (not total_bb - total_par)
    # This way skipped holes don't drag the number down
    vs_out_val = subtotal([d["vs"] for d in front]) if any(d["vs"] is not None for d in front) else None
    vs_in_val  = subtotal([d["vs"] for d in back])  if any(d["vs"] is not None for d in back)  else None
    vs_tot_val = subtotal([v for v in [vs_out_val, vs_in_val] if v is not None]) if (vs_out_val is not None or vs_in_val is not None) else None

    # ── Build HTML ────────────────────────────────────────────────────────────

    def si_row(si_vals_front, si_vals_back):
        cells = "".join(f'<td style="color:#888;font-size:0.75rem">{s}</td>' for s in si_vals_front)
        cells += '<td class="subtotal">—</td>'
        cells += "".join(f'<td style="color:#888;font-size:0.75rem">{s}</td>' for s in si_vals_back)
        return cells + '<td class="subtotal">—</td><td class="subtotal">—</td>'

    def score_row(vals_f, vals_b, out, inp, tot, pars_f, pars_b,
                  with_symbols=False, strokes_f=None, strokes_b=None):
        """Render a data row; with_symbols adds golf circles/squares and handicap dots."""
        cells = ""
        for i, (v, p) in enumerate(zip(vals_f, pars_f)):
            stk = strokes_f[i] if strokes_f else 0
            cells += scored_cell(v, p, stk) if with_symbols else plain_cell(v)
        cells += f'<td class="subtotal">{out if out is not None else "—"}</td>'
        for i, (v, p) in enumerate(zip(vals_b, pars_b)):
            stk = strokes_b[i] if strokes_b else 0
            cells += scored_cell(v, p, stk) if with_symbols else plain_cell(v)
        cells += f'<td class="subtotal">{inp if inp is not None else "—"}</td>'
        cells += f'<td class="subtotal">{tot if tot is not None else "—"}</td>'
        return cells

    def shotgun_row(holes_f, holes_b):
        sg_out = sum(1 for d in holes_f if d["vs"] is not None and d["vs"] > 0)
        sg_in  = sum(1 for d in holes_b if d["vs"] is not None and d["vs"] > 0)
        sg_tot = sg_out + sg_in
        def sg_cell(d):
            if d["vs"] is None:
                return '<td style="color:#aaa">—</td>'
            return '<td style="font-size:1.1rem">🍺</td>' if d["vs"] > 0 else '<td></td>'
        cells = "".join(sg_cell(d) for d in holes_f)
        cells += f'<td class="subtotal">{sg_out or ""}</td>'
        cells += "".join(sg_cell(d) for d in holes_b)
        cells += f'<td class="subtotal">{sg_in or ""}</td>'
        cells += f'<td class="subtotal">{sg_tot or ""}</td>'
        return cells

    def vs_row(holes_f, holes_b, vs_out, vs_in, vs_tot):
        cells = "".join(vs_cell(d["vs"]) for d in holes_f)
        cells += vs_cell(vs_out)
        cells += "".join(vs_cell(d["vs"]) for d in holes_b)
        cells += vs_cell(vs_in)
        cells += vs_cell(vs_tot)
        return cells

    hole_headers = (
        "".join(f'<th>{i}</th>' for i in range(1, 10)) + '<th>OUT</th>' +
        "".join(f'<th>{i}</th>' for i in range(10, 19)) + '<th>IN</th><th>TOT</th>'
    )
    par_cells = (
        "".join(f'<td>{d["par"]}</td>' for d in front) +
        f'<td class="subtotal">{par_out}</td>' +
        "".join(f'<td>{d["par"]}</td>' for d in back) +
        f'<td class="subtotal">{par_in}</td><td class="subtotal">{par_tot}</td>'
    )

    html = f"""
    <div style="overflow-x:auto">
    <table class="sc-table">
      <thead>
        <tr><th class="row-label">Hole</th>{hole_headers}</tr>
      </thead>
      <tbody>
        <tr><td class="row-label">Par</td>{par_cells}</tr>
        <tr><td class="row-label">{p1} SI</td>{si_row(si1_front, si1_back)}</tr>
        <tr>
          <td class="row-label">{p1} Gross (hcp {hcp1})</td>
          {score_row(g1_front, g1_back, g1_out, g1_in, g1_tot, pf, pb,
                     with_symbols=True, strokes_f=stk1f, strokes_b=stk1b)}
        </tr>
        <tr>
          <td class="row-label">{p1} Net</td>
          {score_row(n1_front, n1_back, n1_out, n1_in, n1_tot, pf, pb, with_symbols=True)}
        </tr>
        <tr><td class="row-label">{p2} SI</td>{si_row(si2_front, si2_back)}</tr>
        <tr>
          <td class="row-label">{p2} Gross (hcp {hcp2})</td>
          {score_row(g2_front, g2_back, g2_out, g2_in, g2_tot, pf2, pb2,
                     with_symbols=True, strokes_f=stk2f, strokes_b=stk2b)}
        </tr>
        <tr>
          <td class="row-label">{p2} Net</td>
          {score_row(n2_front, n2_back, n2_out, n2_in, n2_tot, pf2, pb2, with_symbols=True)}
        </tr>
        <tr style="background:#e8f4e8">
          <td class="row-label">Best Net</td>
          {score_row(bb_front, bb_back, bb_out, bb_in, bb_tot, pf, pb, with_symbols=True)}
        </tr>
        <tr>
          <td class="row-label">vs Par</td>
          {vs_row(front, back, vs_out_val, vs_in_val, vs_tot_val)}
        </tr>
        <tr style="background:#fff3e0">
          <td class="row-label">🍺 Shotgun</td>
          {shotgun_row(front, back)}
        </tr>
      </tbody>
    </table>
    </div>
    """
    return html


# ── Routing ───────────────────────────────────────────────────────────────────
params = st.query_params
if "round" in params and "page" not in params:
    params["page"] = "score"

page = params.get("page", "home")

# ══════════════════════════════════════════════════════════════════════════════
# HOME
# ══════════════════════════════════════════════════════════════════════════════
if page == "home":
    st.title("⛳ Golf Scorer")
    st.caption("Live scoring · Net Best Ball")

    tab_new, tab_join, tab_past = st.tabs(["🆕 New Round", "🔗 Join Round", "📚 Past Rounds"])

    with tab_new:
        course = st.selectbox("Course", list(COURSES.keys()))
        fmt    = st.selectbox("Format", FORMATS)
        if st.button("Create Round", type="primary"):
            rid = create_round(course, fmt)
            go("setup", round=rid)

    with tab_join:
        code = st.text_input("Enter Round Code", placeholder="e.g. AB12CD", max_chars=6).upper().strip()
        if st.button("Join", type="primary"):
            if round_exists(code):
                go("score", round=code)
            else:
                st.error("Round not found — double-check the code.")
        st.divider()
        active = list_active_rounds()
        if active:
            st.caption("Active rounds:")
            for r in active:
                teams = get_teams(r["id"])
                if st.button(f"**{r['id']}** — {r['course']} · {len(teams)} team(s)", key=f"j_{r['id']}"):
                    go("score", round=r["id"])
        else:
            st.caption("No active rounds right now.")

    with tab_past:
        completed = list_completed_rounds()
        if not completed:
            st.info("No completed rounds yet.")
        else:
            for r in completed:
                label = f"🏁 {r['id']} — {r['course']}  ·  {r['created_at'][:10]}"
                with st.expander(label):
                    cd = COURSES[r["course"]]
                    lb = compute_leaderboard(r["id"], cd)
                    st.subheader("🏆 Final Leaderboard")
                    if lb.empty:
                        st.write("No scores recorded.")
                    else:
                        st.markdown(lb.to_html(index=False, classes="lb-table", border=0),
                                    unsafe_allow_html=True)
                    st.divider()
                    st.subheader("📋 Scorecards")
                    past_teams = get_teams(r["id"])
                    if past_teams:
                        sel = st.selectbox("Team", [t["team_name"] for t in past_teams],
                                           key=f"past_team_{r['id']}")
                        pt = next(t for t in past_teams if t["team_name"] == sel)
                        st.markdown(build_scorecard_html(r["id"], pt, cd),
                                    unsafe_allow_html=True)
                    else:
                        st.write("No teams.")

# ══════════════════════════════════════════════════════════════════════════════
# SETUP
# ══════════════════════════════════════════════════════════════════════════════
elif page == "setup":
    rid = params.get("round", "")
    rnd = get_round(rid)
    if not rnd:
        st.error("Round not found.")
        st.stop()

    home_btn()
    course_data = COURSES[rnd["course"]]
    tee_names   = list(course_data["tees"].keys())

    st.title(f"⚙️ Setup — {rnd['course']}")
    st.info(f"Round code: **{rid}** — share this with other teams to join on their phones")

    existing = get_teams(rid)
    if existing:
        st.success(f"{len(existing)} team(s) registered:")
        for t in existing:
            ti1 = _tee_info(course_data, t["p1_tee"])
            ti2 = _tee_info(course_data, t["p2_tee"])
            hcp1 = _player_course_hcp(t, 1, course_data)
            hcp2 = _player_course_hcp(t, 2, course_data)
            st.markdown(
                f"• **{t['team_name']}** (password = team name): "
                f"{t['p1_name']} (idx {t['p1_handicap']}, {t['p1_tee']} tee, course hcp **{hcp1}**) & "
                f"{t['p2_name']} (idx {t['p2_handicap']}, {t['p2_tee']} tee, course hcp **{hcp2}**)"
            )

    st.subheader("➕ Add a Team")

    player_options = [f"{name} (hcp {hcp})" for name, hcp in PLAYERS]

    with st.form("add_team"):
        team_name = st.text_input("Team Name", placeholder="e.g. Eagles")

        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Player 1**")
            p1_sel    = st.selectbox("Player", player_options, key="p1sel")
            p1_tee    = st.selectbox("Tee Box", tee_names, index=1, key="p1tee")
        with c2:
            st.markdown("**Player 2**")
            p2_sel    = st.selectbox("Player", player_options, key="p2sel")
            p2_tee    = st.selectbox("Tee Box", tee_names, index=1, key="p2tee")

        # Show computed course handicaps
        p1_idx = PLAYERS[player_options.index(p1_sel)][1]
        p2_idx = PLAYERS[player_options.index(p2_sel)][1]
        ti1 = _tee_info(course_data, p1_tee)
        ti2 = _tee_info(course_data, p2_tee)
        par = sum(course_data["par"])
        chcp1 = course_handicap(p1_idx, ti1["slope"], ti1["rating"], par)
        chcp2 = course_handicap(p2_idx, ti2["slope"], ti2["rating"], par)
        st.info(f"Slope-adjusted course handicaps: **{p1_sel.split('(')[0].strip()} → {chcp1}** · "
                f"**{p2_sel.split('(')[0].strip()} → {chcp2}**")

        submitted = st.form_submit_button("Add Team", type="primary")
        if submitted:
            if not team_name:
                st.error("Enter a team name.")
            else:
                p1_name = PLAYERS[player_options.index(p1_sel)][0]
                p2_name = PLAYERS[player_options.index(p2_sel)][0]
                add_team(rid, team_name, p1_name, p1_idx, p1_tee, p2_name, p2_idx, p2_tee)
                st.success(f"Team '{team_name}' added!")
                st.info(f"🔑 Your team's password is your **team name**: `{team_name}`")
                st.rerun()

    st.divider()
    if get_teams(rid):
        if st.button("▶ Start Scoring", type="primary"):
            go("score", round=rid)
    else:
        st.caption("Add at least one team before starting.")

# ══════════════════════════════════════════════════════════════════════════════
# SCORING
# ══════════════════════════════════════════════════════════════════════════════
elif page == "score":
    rid = params.get("round", "")
    rnd = get_round(rid)
    if not rnd:
        st.error("Round not found.")
        st.stop()

    course_data = COURSES[rnd["course"]]
    teams = get_teams(rid)
    pars  = course_data["par"]

    home_btn()
    st.title(f"⛳ {rnd['course']}")
    st.caption(f"Code: **{rid}** · {rnd['format']}"
               + (" · 🏁 **FINAL**" if rnd["status"] == "completed" else ""))

    if not teams:
        st.warning("No teams yet.")
        if st.button("Go to Setup"):
            go("setup", round=rid)
        st.stop()

    tab_score, tab_board, tab_card, tab_admin = st.tabs(
        ["📝 Scores", "🏆 Leaderboard", "📋 Scorecard", "🔒 Admin"]
    )

    all_scores = get_scores(rid)
    lkp        = build_score_lookup(all_scores)

    # ── Enter Scores ──────────────────────────────────────────────────────────
    with tab_score:
        if rnd["status"] == "completed":
            st.warning("🏁 This round has been finalised — scores are locked. View results in the Leaderboard and Scorecard tabs.")
        else:
            team_names = [t["team_name"] for t in teams]
            sel_name   = st.selectbox("Your Team", team_names, key="team_sel")
            team       = next(t for t in teams if t["team_name"] == sel_name)
            tid        = team["id"]

            # ── Team name gate ────────────────────────────────────────────────
            auth_key = f"auth_{rid}_{tid}"
            if not st.session_state.get(auth_key, False):
                st.info(f"Enter your **team name** to edit scores for **{sel_name}**.")
                pin_col, btn_col = st.columns([3, 1])
                with pin_col:
                    entered = st.text_input("Team Name", max_chars=50, key=f"pin_input_{tid}",
                                            placeholder="Your team name (case-insensitive)")
                with btn_col:
                    st.markdown("<br>", unsafe_allow_html=True)
                    if st.button("Unlock", key=f"pin_btn_{tid}", type="primary"):
                        if entered.lower() == team["team_name"].lower() or entered == ADMIN_PASSWORD:
                            st.session_state[auth_key] = True
                            st.rerun()
                        else:
                            st.error("Team name didn't match — check spelling.")
            else:
                st.caption(f"🔓 Editing scores for **{sel_name}**")

                hcp1 = _player_course_hcp(team, 1, course_data)
                hcp2 = _player_course_hcp(team, 2, course_data)

                statuses = hole_status(lkp, tid)

                # Hole status grid
                st.markdown("**Hole progress** — 🟢 complete · 🟡 partial · ⚪ not started")
                grid_html = '<div class="hole-grid">'
                for h in range(1, 19):
                    s = statuses[h - 1]
                    cls = "h-done" if s == "done" else ("h-partial" if s == "partial" else "h-empty")
                    icon = "✓" if s == "done" else ("½" if s == "partial" else str(h))
                    grid_html += f'<div class="hole-btn {cls}" title="Hole {h}">{icon}</div>'
                grid_html += "</div>"
                st.markdown(grid_html, unsafe_allow_html=True)

                st.divider()

                default_hole = next((h for h, s in enumerate(statuses, 1) if s != "done"), 18)
                h = st.select_slider("Select Hole", options=list(range(1, 19)), value=default_hole,
                                     format_func=lambda x: f"Hole {x}")

                status_now = statuses[h - 1]
                if status_now == "done":
                    st.success(f"✅ Hole {h} — both scores recorded")
                elif status_now == "partial":
                    st.warning(f"⚠️ Hole {h} — only one score recorded")
                else:
                    st.info(f"⬜ Hole {h} — no scores yet")

                # Shotgun popup — shown right after the status badge for visibility
                if st.session_state.pop(f"shotgun_{rid}_{tid}", False):
                    st.error("🍺🍺🍺  SHOTGUN TIME — YOU SUCK  🍺🍺🍺")

                par   = pars[h - 1]
                si1   = _si_for_player(team, 1, course_data, h - 1)
                si2   = _si_for_player(team, 2, course_data, h - 1)
                stk1  = strokes_on_hole(hcp1, si1)
                stk2  = strokes_on_hole(hcp2, si2)

                st.markdown(f"**Par {par}** &nbsp;·&nbsp; Hole SI — {team['p1_name']}: {si1} / {team['p2_name']}: {si2}")

                st.divider()
                c1, c2 = st.columns(2)

                existing_g1 = lkp.get((tid, 1, h))
                existing_g2 = lkp.get((tid, 2, h))

                with c1:
                    tee_info1 = _tee_info(course_data, team["p1_tee"])
                    tee_color = tee_info1["color"]
                    st.markdown(
                        f'<b>{team["p1_name"]}</b> '
                        f'<span style="background:{tee_color};color:white;border-radius:4px;padding:1px 6px;font-size:0.75rem">'
                        f'{team["p1_tee"]}</span> &nbsp; Course hcp <b>{hcp1}</b>'
                        + (f' · <b style="color:#1a7a3c">-{stk1} stroke{"s" if stk1!=1 else ""}</b>' if stk1 > 0 else ' · no stroke'),
                        unsafe_allow_html=True
                    )
                    p1_no_score = st.checkbox("Picked up / no score", key=f"p1_pu_{h}",
                                              value=(existing_g1 is None and status_now != "empty"))
                    if not p1_no_score:
                        g1 = st.number_input("Gross score", 1, 15,
                                             value=int(existing_g1) if existing_g1 else par,
                                             key=f"g1_{h}", label_visibility="collapsed")
                        n1 = net_score(g1, hcp1, si1)
                        st.caption(f"Net: **{n1}**")
                    else:
                        g1 = None
                        st.caption("No score for this hole")

                with c2:
                    tee_info2 = _tee_info(course_data, team["p2_tee"])
                    tee_color2 = tee_info2["color"]
                    st.markdown(
                        f'<b>{team["p2_name"]}</b> '
                        f'<span style="background:{tee_color2};color:white;border-radius:4px;padding:1px 6px;font-size:0.75rem">'
                        f'{team["p2_tee"]}</span> &nbsp; Course hcp <b>{hcp2}</b>'
                        + (f' · <b style="color:#1a7a3c">-{stk2} stroke{"s" if stk2!=1 else ""}</b>' if stk2 > 0 else ' · no stroke'),
                        unsafe_allow_html=True
                    )
                    p2_no_score = st.checkbox("Picked up / no score", key=f"p2_pu_{h}",
                                              value=(existing_g2 is None and status_now != "empty"))
                    if not p2_no_score:
                        g2 = st.number_input("Gross score", 1, 15,
                                             value=int(existing_g2) if existing_g2 else par,
                                             key=f"g2_{h}", label_visibility="collapsed")
                        n2 = net_score(g2, hcp2, si2)
                        st.caption(f"Net: **{n2}**")
                    else:
                        g2 = None
                        st.caption("No score for this hole")

                nets = []
                if g1 is not None:
                    nets.append(net_score(g1, hcp1, si1))
                if g2 is not None:
                    nets.append(net_score(g2, hcp2, si2))
                if nets:
                    bb  = min(nets)
                    vs  = bb - par
                    vs_str = f"+{vs}" if vs > 0 else ("E" if vs == 0 else str(vs))
                    st.info(f"Best Net Ball this hole: **{bb}** ({vs_str})")

                if st.button("💾 Save Hole", type="primary"):
                    upsert_score(rid, tid, 1, h, g1)
                    upsert_score(rid, tid, 2, h, g2)
                    if nets and min(nets) > par:
                        st.session_state[f"shotgun_{rid}_{tid}"] = True
                    st.rerun()

    # ── Leaderboard ───────────────────────────────────────────────────────────
    with tab_board:
        st.subheader("🏆 Leaderboard")
        st.caption("Auto-refreshes every 25 s — pull down or tap Refresh to update now")
        lb = compute_leaderboard(rid, course_data)
        if lb.empty:
            st.info("No scores entered yet.")
        else:
            st.markdown(lb.to_html(index=False, classes="lb-table", border=0),
                        unsafe_allow_html=True)
        if st.button("🔄 Refresh Now", key="lb_refresh"):
            st.rerun()
        st.divider()
        st.caption(f"Share code: **{rid}**")

    # ── Scorecard ─────────────────────────────────────────────────────────────
    with tab_card:
        st.subheader("📋 Full Scorecard")
        sel_card = st.selectbox("Team", [t["team_name"] for t in teams], key="card_sel")
        card_team = next(t for t in teams if t["team_name"] == sel_card)

        st.caption(
            "🟢 circle = birdie · 🟢🟢 double circle = eagle  |  "
            "⬛ square = bogey · ⬛⬛ double = double · 🔴🔴 red = triple+"
        )

        html = build_scorecard_html(rid, card_team, course_data)
        st.markdown(html, unsafe_allow_html=True)

    # ── Admin ─────────────────────────────────────────────────────────────────
    with tab_admin:
        st.subheader("🔒 Admin")
        pw = st.text_input("Admin password", type="password", key="admin_pw")
        if pw == ADMIN_PASSWORD:
            st.success("Authenticated ✓")
            if rnd["status"] == "active":
                st.write("Finalise the round to lock scores and move it to Past Rounds.")
                if st.button("🏁 Finalise Round", type="primary"):
                    finalize_round(rid)
                    st.success("Round finalised! Scores are now locked.")
                    st.rerun()
            else:
                st.info("This round is already finalised.")

            st.divider()
            if st.button("⚙️ Edit Teams / Add Team"):
                go("setup", round=rid)
        elif pw:
            st.error("Incorrect password.")

    # Footer
    st.divider()
    colA, colB = st.columns(2)
    with colA:
        if st.button("⚙️ Add Teams", key="add_teams_footer"):
            go("setup", round=rid)
    with colB:
        st.caption(f"Round: **{rid}**")
