import streamlit as st
from streamlit_autorefresh import st_autorefresh
import pandas as pd
from courses import COURSES, FORMATS, get_strokes_on_hole, net_score
from database import (
    init_db, create_round, round_exists, get_round,
    add_team, get_teams, upsert_score, get_scores, list_active_rounds,
)

# ── page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Golf Scorer",
    page_icon="⛳",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# Keep-alive: auto-refresh every 25 seconds to prevent Streamlit Cloud timeout
st_autorefresh(interval=25_000, key="keepalive")

init_db()

# ── shared CSS for mobile feel ────────────────────────────────────────────────
st.markdown("""
<style>
    /* larger tap targets */
    .stButton > button { min-height: 48px; font-size: 1rem; width: 100%; }
    .stSelectbox > div, .stNumberInput > div { font-size: 1rem; }
    /* score input grid */
    div[data-testid="column"] .stNumberInput input { font-size: 1.4rem; text-align: center; }
    /* leaderboard table */
    .lb-table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
    .lb-table th { background: #1a7a3c; color: white; padding: 6px 8px; }
    .lb-table td { padding: 5px 8px; border-bottom: 1px solid #ddd; text-align: center; }
    .lb-table tr:nth-child(even) { background: #f5f5f5; }
    .hole-badge { background:#1a7a3c; color:white; border-radius:50%;
                  width:32px; height:32px; display:inline-flex;
                  align-items:center; justify-content:center; font-weight:bold; }
</style>
""", unsafe_allow_html=True)


# ── helpers ──────────────────────────────────────────────────────────────────

def compute_leaderboard(round_id: str, course_data: dict) -> pd.DataFrame:
    teams = get_teams(round_id)
    all_scores = get_scores(round_id)
    pars = course_data["par"]

    score_lookup: dict[tuple, int] = {}
    for s in all_scores:
        score_lookup[(s["team_id"], s["player_num"], s["hole"])] = s["gross"]

    rows = []
    for team in teams:
        tid = team["id"]
        si_p1 = course_data[f"si_{team['p1_gender']}"]
        si_p2 = course_data[f"si_{team['p2_gender']}"]

        holes_played = 0
        total_net_bb = 0
        thru = 0

        for h in range(1, 19):
            g1 = score_lookup.get((tid, 1, h))
            g2 = score_lookup.get((tid, 2, h))
            if g1 is None and g2 is None:
                continue
            thru = h
            holes_played += 1
            nets = []
            if g1 is not None:
                nets.append(net_score(g1, team["p1_handicap"], si_p1[h - 1]))
            if g2 is not None:
                nets.append(net_score(g2, team["p2_handicap"], si_p2[h - 1]))
            best_net = min(nets)
            total_net_bb += best_net

        if holes_played == 0:
            vs_par = "-"
            total_str = "-"
        else:
            par_thru = sum(pars[:thru])
            diff = total_net_bb - par_thru
            vs_par = f"+{diff}" if diff > 0 else str(diff)
            total_str = str(total_net_bb)

        rows.append({
            "Team": team["team_name"],
            "Players": f"{team['p1_name']} / {team['p2_name']}",
            "Thru": thru if holes_played > 0 else "-",
            "Net Total": total_str,
            "vs Par": vs_par,
            "_sort": total_net_bb if holes_played > 0 else 9999,
        })

    if rows:
        df = pd.DataFrame(rows).sort_values("_sort").drop(columns="_sort").reset_index(drop=True)
        df.index += 1
    else:
        df = pd.DataFrame(rows)
    return df


def hole_summary_for_team(round_id: str, team: dict, course_data: dict) -> pd.DataFrame:
    all_scores = get_scores(round_id)
    score_lookup: dict[tuple, int] = {}
    for s in all_scores:
        if s["team_id"] == team["id"]:
            score_lookup[(s["player_num"], s["hole"])] = s["gross"]

    si_p1 = course_data[f"si_{team['p1_gender']}"]
    si_p2 = course_data[f"si_{team['p2_gender']}"]
    pars = course_data["par"]

    rows = []
    for h in range(1, 19):
        g1 = score_lookup.get((1, h))
        g2 = score_lookup.get((2, h))
        n1 = net_score(g1, team["p1_handicap"], si_p1[h - 1]) if g1 else "-"
        n2 = net_score(g2, team["p2_handicap"], si_p2[h - 1]) if g2 else "-"
        if g1 is not None and g2 is not None:
            bb = min(n1, n2)
            vs = bb - pars[h - 1]
            vs_str = f"+{vs}" if vs > 0 else str(vs)
        else:
            bb = "-"
            vs_str = "-"
        rows.append({
            "Hole": h,
            "Par": pars[h - 1],
            f"{team['p1_name']} gross": g1 if g1 else "-",
            f"{team['p1_name']} net": n1,
            f"{team['p2_name']} gross": g2 if g2 else "-",
            f"{team['p2_name']} net": n2,
            "Best Net": bb,
            "vs Par": vs_str,
        })
    return pd.DataFrame(rows)


# ── routing via query params ──────────────────────────────────────────────────
params = st.query_params

# If URL has ?round=XXXX, jump straight into that round
if "round" in params and "page" not in params:
    params["page"] = "score"


def go(page: str, **kw):
    params["page"] = page
    for k, v in kw.items():
        params[k] = v
    st.rerun()


page = params.get("page", "home")

# ── HOME ─────────────────────────────────────────────────────────────────────
if page == "home":
    st.title("⛳ Golf Scorer")
    st.caption("Real-time scoring for your round")

    tab_new, tab_join = st.tabs(["🆕 New Round", "🔗 Join Round"])

    with tab_new:
        course = st.selectbox("Course", list(COURSES.keys()))
        fmt = st.selectbox("Format", FORMATS)
        if st.button("Create Round", type="primary"):
            rid = create_round(course, fmt)
            go("setup", round=rid)

    with tab_join:
        code = st.text_input("Round Code", placeholder="e.g. AB12CD", max_chars=6).upper()
        if st.button("Join", type="primary"):
            if round_exists(code):
                go("score", round=code)
            else:
                st.error("Round not found — check the code.")

        st.divider()
        st.caption("Recent active rounds")
        active = list_active_rounds()
        for r in active:
            teams = get_teams(r["id"])
            label = f"**{r['id']}** — {r['course']} ({len(teams)} teams)"
            if st.button(label, key=f"join_{r['id']}"):
                go("score", round=r["id"])

# ── SETUP: add teams ──────────────────────────────────────────────────────────
elif page == "setup":
    rid = params.get("round", "")
    rnd = get_round(rid)
    if not rnd:
        st.error("Round not found.")
        st.stop()

    course_data = COURSES[rnd["course"]]
    st.title(f"Setup — {rnd['course']}")
    st.info(f"Round code: **{rid}** — share this with other teams to join")

    existing = get_teams(rid)
    if existing:
        st.success(f"{len(existing)} team(s) already added.")
        for t in existing:
            st.write(f"• **{t['team_name']}**: {t['p1_name']} (hcp {t['p1_handicap']}) & {t['p2_name']} (hcp {t['p2_handicap']})")

    st.subheader("Add a Team")
    with st.form("add_team"):
        team_name = st.text_input("Team Name", placeholder="e.g. Eagles")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Player 1**")
            p1_name = st.text_input("Name", key="p1n")
            p1_hcp = st.number_input("Handicap", 0, 54, 18, key="p1h")
            p1_gender = st.radio("Tee", ["mens", "ladies"], key="p1g", horizontal=True)
        with c2:
            st.markdown("**Player 2**")
            p2_name = st.text_input("Name", key="p2n")
            p2_hcp = st.number_input("Handicap", 0, 54, 18, key="p2h")
            p2_gender = st.radio("Tee", ["mens", "ladies"], key="p2g", horizontal=True)

        submitted = st.form_submit_button("Add Team", type="primary")
        if submitted:
            if not team_name or not p1_name or not p2_name:
                st.error("Please fill in all name fields.")
            else:
                add_team(rid, team_name, p1_name, p1_hcp, p1_gender, p2_name, p2_hcp, p2_gender)
                st.success(f"Team '{team_name}' added!")
                st.rerun()

    st.divider()
    teams = get_teams(rid)
    if teams:
        if st.button("▶ Start Scoring", type="primary"):
            go("score", round=rid)
    else:
        st.caption("Add at least one team to start scoring.")

# ── SCORING ───────────────────────────────────────────────────────────────────
elif page == "score":
    rid = params.get("round", "")
    rnd = get_round(rid)
    if not rnd:
        st.error("Round not found.")
        st.stop()

    course_data = COURSES[rnd["course"]]
    teams = get_teams(rid)
    pars = course_data["par"]

    st.title(f"⛳ {rnd['course']}")
    st.caption(f"Round: **{rid}** · {rnd['format']}")

    if not teams:
        st.warning("No teams yet. Go back to setup.")
        if st.button("Back to Setup"):
            go("setup", round=rid)
        st.stop()

    tab_score, tab_board, tab_card = st.tabs(["📝 Enter Scores", "🏆 Leaderboard", "📋 Scorecard"])

    # ── Enter Scores tab ─────────────────────────────────────────────────────
    with tab_score:
        team_names = [t["team_name"] for t in teams]
        selected_team_name = st.selectbox("Your Team", team_names)
        team = next(t for t in teams if t["team_name"] == selected_team_name)
        tid = team["id"]

        # Load existing scores for this team
        all_scores = get_scores(rid)
        score_lookup: dict[tuple, int] = {}
        for s in all_scores:
            if s["team_id"] == tid:
                score_lookup[(s["player_num"], s["hole"])] = s["gross"]

        # Determine current hole (first without both scores)
        current_hole = 18
        for h in range(1, 19):
            if (1, h) not in score_lookup or (2, h) not in score_lookup:
                current_hole = h
                break

        st.divider()

        # Hole navigator
        hole_nums = list(range(1, 19))
        hole_idx = st.select_slider(
            "Hole", options=hole_nums, value=current_hole,
            format_func=lambda h: f"Hole {h}"
        )

        h = hole_idx
        par = pars[h - 1]
        si_p1 = course_data[f"si_{team['p1_gender']}"][h - 1]
        si_p2 = course_data[f"si_{team['p2_gender']}"][h - 1]
        strokes_p1 = get_strokes_on_hole(team["p1_handicap"], si_p1)
        strokes_p2 = get_strokes_on_hole(team["p2_handicap"], si_p2)

        # Hole header
        col_badge, col_info = st.columns([1, 4])
        with col_badge:
            st.markdown(f'<div class="hole-badge">{h}</div>', unsafe_allow_html=True)
        with col_info:
            st.markdown(f"**Par {par}** &nbsp;·&nbsp; SI Men's: {si_p1} / Ladies': {si_p2}")

        st.divider()

        c1, c2 = st.columns(2)

        with c1:
            st.markdown(f"**{team['p1_name']}**")
            st.caption(f"Hcp {team['p1_handicap']} · +{strokes_p1} stroke(s) this hole")
            default1 = score_lookup.get((1, h), par)
            g1 = st.number_input(
                "Gross", min_value=1, max_value=15, value=int(default1),
                key=f"g1_{h}", label_visibility="collapsed"
            )
            n1 = net_score(g1, team["p1_handicap"], si_p1)
            st.caption(f"Net: **{n1}**")

        with c2:
            st.markdown(f"**{team['p2_name']}**")
            st.caption(f"Hcp {team['p2_handicap']} · +{strokes_p2} stroke(s) this hole")
            default2 = score_lookup.get((2, h), par)
            g2 = st.number_input(
                "Gross", min_value=1, max_value=15, value=int(default2),
                key=f"g2_{h}", label_visibility="collapsed"
            )
            n2 = net_score(g2, team["p2_handicap"], si_p2)
            st.caption(f"Net: **{n2}**")

        best = min(n1, n2)
        vs = best - par
        vs_str = f"+{vs}" if vs > 0 else ("E" if vs == 0 else str(vs))
        st.info(f"Best Net Ball: **{best}** ({vs_str})")

        if st.button("💾 Save Hole", type="primary"):
            upsert_score(rid, tid, 1, h, g1)
            upsert_score(rid, tid, 2, h, g2)
            st.success(f"Hole {h} saved!")
            # Auto-advance
            if h < 18:
                st.query_params["page"] = "score"
                st.rerun()

    # ── Leaderboard tab ──────────────────────────────────────────────────────
    with tab_board:
        st.subheader("🏆 Leaderboard")
        st.caption("Auto-refreshes every 25 seconds")
        lb = compute_leaderboard(rid, course_data)
        if lb.empty:
            st.info("No scores yet.")
        else:
            # Render as styled HTML table
            html = lb.to_html(index=True, classes="lb-table", border=0)
            st.markdown(html, unsafe_allow_html=True)

        if st.button("🔄 Refresh Now"):
            st.rerun()

        st.divider()
        st.caption(f"Share code: **{rid}**")

    # ── Scorecard tab ────────────────────────────────────────────────────────
    with tab_card:
        st.subheader("Full Scorecard")
        selected_card_team = st.selectbox("Team", [t["team_name"] for t in teams], key="card_team")
        card_team = next(t for t in teams if t["team_name"] == selected_card_team)
        df_card = hole_summary_for_team(rid, card_team, course_data)
        st.dataframe(df_card, use_container_width=True, hide_index=True)

    # ── Bottom: share/setup links ─────────────────────────────────────────────
    st.divider()
    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("⚙️ Add More Teams"):
            go("setup", round=rid)
    with col_b:
        st.caption(f"Round code: **{rid}**")
