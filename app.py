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
    pars = course_data["par"]
    lkp = build_score_lookup(all_scores)

    rows = []
    for team in teams:
        tid = team["id"]
        hcp1 = _player_course_hcp(team, 1, course_data)
        hcp2 = _player_course_hcp(team, 2, course_data)

        total_net_bb = 0
        holes_counted = 0
        thru = 0

        for h in range(1, 19):
            g1 = lkp.get((tid, 1, h))
            g2 = lkp.get((tid, 2, h))
            if g1 is None and g2 is None:
                continue
            thru = h
            holes_counted += 1
            nets = []
            si1 = _si_for_player(team, 1, course_data, h - 1)
            si2 = _si_for_player(team, 2, course_data, h - 1)
            if g1 is not None:
                nets.append(net_score(g1, hcp1, si1))
            if g2 is not None:
                nets.append(net_score(g2, hcp2, si2))
            total_net_bb += min(nets)

        if holes_counted == 0:
            vs_par_str = "—"
            total_str  = "—"
            sort_key   = 9999
        else:
            par_thru = sum(pars[:thru])
            diff = total_net_bb - par_thru
            vs_par_str = f"+{diff}" if diff > 0 else ("E" if diff == 0 else str(diff))
            total_str  = str(total_net_bb)
            sort_key   = diff

        rows.append({
            "Pos":      "",
            "Team":     team["team_name"],
            "Players":  f"{team['p1_name']} / {team['p2_name']}",
            "Thru":     thru if holes_counted > 0 else "—",
            "Net Tot":  total_str,
            "vs Par":   vs_par_str,
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
    pars = course_data["par"]
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
        par  = pars[h - 1]
        si1  = _si_for_player(team, 1, course_data, h - 1)
        si2  = _si_for_player(team, 2, course_data, h - 1)
        g1   = lkp.get((tid, 1, h))
        g2   = lkp.get((tid, 2, h))
        n1   = net_score(g1, hcp1, si1) if g1 is not None else None
        n2   = net_score(g2, hcp2, si2) if g2 is not None else None

        nets = [x for x in [n1, n2] if x is not None]
        bb   = min(nets) if nets else None
        vs   = (bb - par) if bb is not None else None

        holes_data.append(dict(
            par=par, g1=g1, n1=n1, g2=g2, n2=n2, bb=bb, vs=vs, si1=si1, si2=si2
        ))

    def subtotal(lst):
        vals = [x for x in lst if x is not None]
        return sum(vals) if vals else None

    def vs_cell(val):
        if val is None:
            return '<td>—</td>'
        txt = f"+{val}" if val > 0 else ("E" if val == 0 else str(val))
        cls = "vspar-pos" if val > 0 else ("vspar-neg" if val < 0 else "vspar-e")
        return f'<td class="{cls}">{txt}</td>'

    def net_cell(val):
        return f'<td>{val}</td>' if val is not None else '<td style="color:#aaa">—</td>'

    # Build column groups: front 9 (idx 0-8), subtotal OUT, back 9 (idx 9-17), subtotal IN, total TOT
    def row_cells(values_front, out_val, values_back, in_val, tot_val, is_gross=False, pars_front=None, pars_back=None):
        cells = ""
        for i, v in enumerate(values_front):
            if is_gross and pars_front:
                cells += f'<td>{score_cell_html(v, pars_front[i])}</td>'
            else:
                cells += net_cell(v)
        cells += f'<td class="subtotal">{out_val if out_val is not None else "—"}</td>'
        for i, v in enumerate(values_back):
            if is_gross and pars_back:
                cells += f'<td>{score_cell_html(v, pars_back[i])}</td>'
            else:
                cells += net_cell(v)
        cells += f'<td class="subtotal">{in_val if in_val is not None else "—"}</td>'
        cells += f'<td class="subtotal">{tot_val if tot_val is not None else "—"}</td>'
        return cells

    front = holes_data[:9]
    back  = holes_data[9:]

    # Par sums
    par_out = sum(d["par"] for d in front)
    par_in  = sum(d["par"] for d in back)
    par_tot = par_out + par_in

    # Player 1 gross
    g1_front = [d["g1"] for d in front]; g1_back = [d["g1"] for d in back]
    g1_out = subtotal(g1_front); g1_in = subtotal(g1_back)
    g1_tot = subtotal([g1_out, g1_in])

    # Player 1 net
    n1_front = [d["n1"] for d in front]; n1_back = [d["n1"] for d in back]
    n1_out = subtotal(n1_front); n1_in = subtotal(n1_back); n1_tot = subtotal([n1_out, n1_in])

    # Player 2 gross
    g2_front = [d["g2"] for d in front]; g2_back = [d["g2"] for d in back]
    g2_out = subtotal(g2_front); g2_in = subtotal(g2_back); g2_tot = subtotal([g2_out, g2_in])

    # Player 2 net
    n2_front = [d["n2"] for d in front]; n2_back = [d["n2"] for d in back]
    n2_out = subtotal(n2_front); n2_in = subtotal(n2_back); n2_tot = subtotal([n2_out, n2_in])

    # Best net
    bb_front = [d["bb"] for d in front]; bb_back = [d["bb"] for d in back]
    bb_out = subtotal(bb_front); bb_in = subtotal(bb_back); bb_tot = subtotal([bb_out, bb_in])

    # vs par (cumulative for subtotals)
    vs_out = (bb_out - par_out) if bb_out is not None else None
    vs_in  = (bb_in  - par_in)  if bb_in  is not None else None
    vs_tot = (bb_tot - par_tot) if bb_tot is not None else None

    # SI rows
    si1_front = [d["si1"] for d in front]; si1_back = [d["si1"] for d in back]
    si2_front = [d["si2"] for d in front]; si2_back = [d["si2"] for d in back]

    # Header row
    hole_headers = "".join(f'<th>{i}</th>' for i in range(1, 10))
    hole_headers += '<th>OUT</th>'
    hole_headers += "".join(f'<th>{i}</th>' for i in range(10, 19))
    hole_headers += '<th>IN</th><th>TOT</th>'

    par_cells = "".join(f'<td>{d["par"]}</td>' for d in front)
    par_cells += f'<td class="subtotal">{par_out}</td>'
    par_cells += "".join(f'<td>{d["par"]}</td>' for d in back)
    par_cells += f'<td class="subtotal">{par_in}</td><td class="subtotal">{par_tot}</td>'

    si1_cells = "".join(f'<td style="color:#888;font-size:0.75rem">{s}</td>' for s in si1_front)
    si1_cells += '<td class="subtotal">—</td>'
    si1_cells += "".join(f'<td style="color:#888;font-size:0.75rem">{s}</td>' for s in si1_back)
    si1_cells += '<td class="subtotal">—</td><td class="subtotal">—</td>'

    si2_cells = "".join(f'<td style="color:#888;font-size:0.75rem">{s}</td>' for s in si2_front)
    si2_cells += '<td class="subtotal">—</td>'
    si2_cells += "".join(f'<td style="color:#888;font-size:0.75rem">{s}</td>' for s in si2_back)
    si2_cells += '<td class="subtotal">—</td><td class="subtotal">—</td>'

    # Best net vs par per hole cells
    vs_cells = ""
    for d in front:
        vs_cells += vs_cell(d["vs"])
    vs_cells += vs_cell(vs_out)
    for d in back:
        vs_cells += vs_cell(d["vs"])
    vs_cells += vs_cell(vs_in)
    vs_cells += vs_cell(vs_tot)

    html = f"""
    <div style="overflow-x:auto">
    <table class="sc-table">
      <thead>
        <tr><th class="row-label">Hole</th>{hole_headers}</tr>
      </thead>
      <tbody>
        <tr>
          <td class="row-label">Par</td>{par_cells}
        </tr>
        <tr>
          <td class="row-label">{p1} SI</td>{si1_cells}
        </tr>
        <tr>
          <td class="row-label">{p1} Gross (hcp {hcp1})</td>
          {row_cells(g1_front, g1_out, g1_back, g1_in, g1_tot, is_gross=True,
                     pars_front=[d["par"] for d in front],
                     pars_back=[d["par"] for d in back])}
        </tr>
        <tr>
          <td class="row-label">{p1} Net</td>
          {row_cells(n1_front, n1_out, n1_back, n1_in, n1_tot)}
        </tr>
        <tr>
          <td class="row-label">{p2} SI</td>{si2_cells}
        </tr>
        <tr>
          <td class="row-label">{p2} Gross (hcp {hcp2})</td>
          {row_cells(g2_front, g2_out, g2_back, g2_in, g2_tot, is_gross=True,
                     pars_front=[d["par"] for d in front],
                     pars_back=[d["par"] for d in back])}
        </tr>
        <tr>
          <td class="row-label">{p2} Net</td>
          {row_cells(n2_front, n2_out, n2_back, n2_in, n2_tot)}
        </tr>
        <tr style="background:#e8f4e8">
          <td class="row-label">Best Net</td>
          {row_cells(bb_front, bb_out, bb_back, bb_in, bb_tot)}
        </tr>
        <tr>
          <td class="row-label">vs Par</td>{vs_cells}
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
                with st.expander(f"🏁 {r['id']} — {r['course']}  ·  {r['created_at'][:10]}"):
                    course_data = COURSES[r["course"]]
                    lb = compute_leaderboard(r["id"], course_data)
                    if lb.empty:
                        st.write("No scores recorded.")
                    else:
                        st.markdown(lb.to_html(index=False, classes="lb-table", border=0),
                                    unsafe_allow_html=True)
                    if st.button("View full scorecard", key=f"past_{r['id']}"):
                        go("score", round=r["id"])

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
                f"• **{t['team_name']}**: "
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
            st.warning("This round has been finalised — scores are locked.")
            st.stop()

        team_names = [t["team_name"] for t in teams]
        sel_name   = st.selectbox("Your Team", team_names, key="team_sel")
        team       = next(t for t in teams if t["team_name"] == sel_name)
        tid        = team["id"]

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

        # Find first incomplete hole as default
        default_hole = next((h for h, s in enumerate(statuses, 1) if s != "done"), 18)
        h = st.select_slider("Select Hole", options=list(range(1, 19)), value=default_hole,
                             format_func=lambda x: f"Hole {x}")

        # Completion badge
        status_now = statuses[h - 1]
        if status_now == "done":
            st.success(f"✅ Hole {h} — both scores recorded")
        elif status_now == "partial":
            st.warning(f"⚠️ Hole {h} — only one score recorded")
        else:
            st.info(f"⬜ Hole {h} — no scores yet")

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
                f'{team["p1_tee"]}</span> &nbsp; Course hcp <b>{hcp1}</b> · +{stk1} here',
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
                f'{team["p2_tee"]}</span> &nbsp; Course hcp <b>{hcp2}</b> · +{stk2} here',
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

        # Best net summary
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
            st.success(f"Hole {h} saved!")
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
