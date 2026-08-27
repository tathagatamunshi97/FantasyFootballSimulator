if (!requireAuthOrAdmin()) throw new Error("auth");

document.getElementById("userLabel").textContent = getUser() || (getAdminToken() ? "admin" : "");
if (isAdminUser() || getAdminToken()) {
  document.getElementById("adminLinks").hidden = false;
}

document.getElementById("logoutBtn").addEventListener("click", async () => {
  try {
    await api("/api/logout", { method: "POST" });
  } catch (_) {}
  clearSession();
  window.location.href = "/login";
});

let _lastMatchdayKey = "";
let _liveBoard = null;
let _liveBoardFixtureId = null;
let _hosting = false;
let _lastFrameSeq = -1;
let _savingFt = false;
let _publishQueue = null;
let _publishBusy = false;
let _refreshInFlight = false;

function destroyLiveBoard() {
  if (_liveBoard && typeof _liveBoard.destroy === "function") {
    _liveBoard.destroy();
  }
  _liveBoard = null;
  _liveBoardFixtureId = null;
  _hosting = false;
  _lastFrameSeq = -1;
  _publishQueue = null;
}

function wireMatchdayActions(session) {
  const runBtn = document.getElementById("matchdayRunBtn");
  if (runBtn) {
    runBtn.addEventListener("click", async () => {
      runBtn.disabled = true;
      try {
        await api("/api/matchday/kickoff", { method: "POST" });
        await refresh({ force: true });
      } catch (e) {
        alert(e.message);
        runBtn.disabled = false;
      }
    });
  }
  const dismissBtn = document.getElementById("matchdayDismissBtn");
  if (dismissBtn) {
    dismissBtn.addEventListener("click", async () => {
      try {
        destroyLiveBoard();
        await api("/api/matchday/dismiss", { method: "POST" });
        await refresh({ force: true });
      } catch (e) {
        alert(e.message);
      }
    });
  }
  const analysisBtn = document.getElementById("matchdaySeeAnalysisBtn");
  if (analysisBtn && session?.result) {
    analysisBtn.addEventListener("click", async () => {
      const panel = document.getElementById("matchdayAnalysisPanel");
      if (!panel) return;
      const r = session.result;
      const tid = session.tournament_id || r.tournament_id;
      const mid = r.match_id || session.fixture_id;

      const showReport = (report) => {
        const analysis = report?.analysis || r.analysis;
        const squad = report?.squad_analysis || r.squad_analysis;
        const matchup = report?.matchup || r.matchup;
        const aiVerdict = report?.ai_verdict || r.ai_verdict;
        const aiCommentary = report?.ai_commentary || r.ai_commentary;
        panel.hidden = false;
        let html = "";
        if (typeof renderAnalysis === "function" && analysis) {
          html += renderAnalysis(analysis);
        }
        if (typeof renderAiVerdict === "function" && aiVerdict) {
          html += renderAiVerdict(aiVerdict);
        }
        if (typeof renderAiCommentary === "function" && aiCommentary) {
          html += renderAiCommentary(aiCommentary);
        }
        if (typeof renderSquadAnalysis === "function" && squad) {
          html += renderSquadAnalysis(squad, matchup);
        }
        if (!html && analysis) {
          html = `<div class="card"><pre style="white-space:pre-wrap;font-size:0.85rem">${esc(
            JSON.stringify(analysis, null, 2)
          )}</pre></div>`;
        }
        panel.innerHTML = html || `<p class="muted">No analysis text.</p>`;
        analysisBtn.textContent = "See analysis";
        panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
      };

      const existing = r.report || {
        analysis: r.analysis,
        squad_analysis: r.squad_analysis,
        matchup: r.matchup,
        ai_verdict: r.ai_verdict,
        ai_commentary: r.ai_commentary,
      };
      if (existing.analysis || r.analysis || existing.ai_commentary || r.ai_commentary) {
        showReport(existing);
        return;
      }

      // A League + Cup friendly never gets a deterministic analysis report
      // -- commentary (attached at completion time, above) is the whole
      // report for a friendly. Don't fall through to a generate-analysis
      // fetch, which has no equivalent for friendlies and would 404.
      if (session?.stage === "friendly") {
        panel.hidden = false;
        panel.innerHTML = `<p class="muted">No commentary available for this match.</p>`;
        return;
      }

      if (!tid || !mid) {
        alert("Analysis is not available yet.");
        return;
      }

      // League/cup matches (not friendlies) do get a real analysis report,
      // same as groups+knockout, just via the league-cup-specific endpoint.
      const isLeagueCupMatch = ["league", "cup"].includes(session?.stage);
      const apiBase = isLeagueCupMatch ? "/api/league-cup" : "/api/tournament";

      analysisBtn.disabled = true;
      const prevLabel = analysisBtn.textContent;
      analysisBtn.textContent = "Generating…";
      panel.hidden = false;
      panel.innerHTML = `<p class="muted">Generating analysis…</p>`;
      try {
        const data = await fetchTournamentMatchAnalysis(tid, mid, { apiBase });
        if (session.result) {
          session.result.has_analysis = Boolean(data?.analysis);
          session.result.analysis = data.analysis;
          session.result.squad_analysis = data.squad_analysis;
          session.result.matchup = data.matchup;
          session.result.ai_verdict = data.ai_verdict;
          session.result.ai_commentary = data.ai_commentary;
          session.result.report = {
            analysis: data.analysis,
            squad_analysis: data.squad_analysis,
            matchup: data.matchup,
            ai_verdict: data.ai_verdict,
            ai_commentary: data.ai_commentary,
          };
        }
        showReport(data);
      } catch (e) {
        panel.innerHTML = `<p class="error-msg">${esc(e.message)}</p>`;
        analysisBtn.textContent = prevLabel;
      } finally {
        analysisBtn.disabled = false;
      }
    });
  }
}

async function flushPublish() {
  // Same bug class as saveFullTime below: this gate only ever checked the
  // raw getAdminToken(), so a host signed in as a normal session-based admin
  // (password login, no raw token ever entered) had every single broadcast
  // frame silently dropped here -- the host's own local board kept animating
  // fine (it's a fully independent simulation), but the server's frame_seq
  // never advanced, so every viewer was stuck watching kickoff (0') forever.
  const hasAdminAuth = Boolean(getAdminToken()) || isAdminUser();
  if (_publishBusy || !_publishQueue || !hasAdminAuth) return;
  _publishBusy = true;
  const frame = _publishQueue;
  _publishQueue = null;
  try {
    await api("/api/matchday/board-state", { method: "POST", json: { frame } });
  } catch (_) {
    /* ignore */
  } finally {
    _publishBusy = false;
    if (_publishQueue) flushPublish();
  }
}

function queueBroadcast(frame) {
  if (!_hosting || !frame) return;
  _publishQueue = frame;
  flushPublish();
}

async function saveFullTime(score, session) {
  // Bug fix — real user report: friendlies (and presumably every other
  // match type) got permanently stuck at "saving..." for any admin logged
  // in the normal way (username + password session), not just the raw
  // SIM_ADMIN_TOKEN. api() already correctly sends BOTH X-Session-Token
  // and X-Admin-Token on every request, and the backend's own
  // _require_admin is session-first by design ("the raw token remains
  // valid too, as the recovery path if it's lost") -- but this gate only
  // ever checked getAdminToken(), so a session-only admin silently failed
  // this check on literally every match, every time, with zero feedback.
  const hasAdminAuth = Boolean(getAdminToken()) || isAdminUser();
  if (_savingFt) return;
  if (!hasAdminAuth || !session) {
    // Surface it instead of hanging on "saving..." forever with no
    // explanation -- if this ever fires again (a genuine non-admin viewer,
    // or a fully logged-out tab), at least it's visible, not silent.
    if (!hasAdminAuth) {
      alert("Not signed in as admin on this tab, so the result can't be saved yet. Log in as admin, then click Resume/refresh to retry.");
    }
    return;
  }
  _savingFt = true;
  const home = session.home;
  const away = session.away;
  const hg = Number(score.homeGoals) || 0;
  const ag = Number(score.awayGoals) || 0;
  let winner = score.winner || null;
  const legCtx = session.agg_context || null;
  const isLeg1OfTwo = legCtx && legCtx.twoLegged && legCtx.leg === 1;
  if (session.is_knockout && !winner && !isLeg1OfTwo) {
    if (legCtx && legCtx.twoLegged && legCtx.leg === 2) {
      // Aggregate-aware fallback (the board should normally already resolve
      // this correctly — see tactic_board.js's resolveMatchWinner()).
      const aggHome = hg + (legCtx.enteringAggHome || 0);
      const aggAway = ag + (legCtx.enteringAggAway || 0);
      if (aggHome > aggAway) winner = home;
      else if (aggAway > aggHome) winner = away;
      else {
        const homeAwayGoals = legCtx.enteringAggHome || 0; // fixed, from leg 1
        const awayAwayGoals = ag; // this leg's own away-side goals, live
        if (homeAwayGoals > awayAwayGoals) winner = home;
        else if (awayAwayGoals > homeAwayGoals) winner = away;
        else if (score.decided_by === "pens") {
          const ph = Number(score.pens_home);
          const pa = Number(score.pens_away);
          if (Number.isFinite(ph) && Number.isFinite(pa) && ph !== pa) {
            winner = ph > pa ? home : away;
          }
        }
      }
    } else if (hg > ag) winner = home;
    else if (ag > hg) winner = away;
    else if (score.decided_by === "pens") {
      const ph = Number(score.pens_home);
      const pa = Number(score.pens_away);
      if (Number.isFinite(ph) && Number.isFinite(pa) && ph !== pa) {
        winner = ph > pa ? home : away;
      }
    }
  }
  const boardLog =
    score.match_log ||
    (typeof _liveBoard?.getMatchLog === "function" ? _liveBoard.getMatchLog() : null);
  try {
    await api("/api/matchday/complete", {
      method: "POST",
      json: {
        home_goals: hg,
        away_goals: ag,
        winner,
        decided_by: score.decided_by || null,
        ft_home_goals: score.ft_home_goals ?? null,
        ft_away_goals: score.ft_away_goals ?? null,
        pens_home: score.pens_home ?? null,
        pens_away: score.pens_away ?? null,
        score_display: score.score_display || null,
        board_events: score.board_events || boardLog?.events || null,
        match_log: boardLog,
      },
    });
    _hosting = false;
    await refresh({ force: true });
  } catch (e) {
    _savingFt = false;
    alert(`Could not save pin score: ${e.message}`);
  }
}

async function startHostBoard(session) {
  if (!session) return;
  const mount = document.querySelector("[data-tactic-mount]");
  if (!mount || typeof TacticBoard === "undefined") return;
  if (_liveBoard && _hosting) return;

  destroyLiveBoard();
  const board = session.board;
  if (!board) return;

  _hosting = true;
  _savingFt = false;
  _liveBoardFixtureId = session.fixture_id;
  _liveBoard = await TacticBoard.openTournamentWatch(
    mount,
    {
      matchId: session.fixture_id,
      home: session.home,
      away: session.away,
      boardPayload: board,
      showPrematch: false,
      autoplay: true,
      hostMode: true,
      isKnockout: Boolean(session.is_knockout),
      isFinal: Boolean(session.is_final),
      aggContext: session.agg_context || null,
      broadcastIntervalMs: 220,
      onBroadcast: (frame) => queueBroadcast(frame),
      onFullTime: (score) => saveFullTime(score, session),
      // Matchday defaults to the FM Mobile commentary-first presentation —
      // purely a rendering choice: getMatchLog() (see saveFullTime above)
      // is unaffected, so everything sent to /api/matchday/complete stays
      // exactly as accurate as before.
      mobileBroadcast: true,
    },
    { apiFetch: api }
  );
}

async function startViewerBoard(session) {
  if (!session) return;
  const mount = document.querySelector("[data-tactic-mount]");
  if (!mount || typeof TacticBoard === "undefined") return;
  const board = session.board;
  if (!board) return;

  // Bug fix — real user report: the admin and other viewers ended up
  // watching two completely different matches. refresh()'s cleanup only
  // calls destroyLiveBoard() when phase leaves "live"/"running" -- if the
  // active fixture changed (one match finished, a new one started hosting)
  // while phase stayed "live" continuously across this tab's poll (missing
  // the brief "result" phase in between), the OLD board never got torn
  // down. `if (!_liveBoard)` below then skipped creating a new one and just
  // kept applying the NEW match's frames onto the OLD match's board --
  // wrong teams/lineups/kits, with live-looking movement on top. Force a
  // rebuild whenever the fixture actually changed, not just when no board
  // exists yet.
  if (_liveBoard && _liveBoardFixtureId !== session.fixture_id) {
    destroyLiveBoard();
  }

  if (!_liveBoard) {
    _liveBoard = TacticBoard.createBoard(mount, {
      home: board.home,
      away: board.away,
      unitHome: board.unit_home || board.unitHome || {},
      unitAway: board.unit_away || board.unitAway || {},
      live: false,
      viewerMode: true,
      hideControls: true,
      autoplay: false,
      showPrematch: false,
      mobileBroadcast: true,
    });
    _liveBoardFixtureId = session.fixture_id;
  }

  const frame = session.frame || session.board_state;
  const seq = frame?.seq ?? session.frame_seq ?? 0;
  // Strictly-greater, not "different": overlapping polls (see refresh()) can
  // resolve out of order, so a late-arriving older frame must never overwrite
  // a newer one already applied — that's what caused the score to visibly
  // flicker/regress for viewers.
  if (frame && seq > _lastFrameSeq) {
    _lastFrameSeq = seq;
    if (typeof _liveBoard.applyBroadcastState === "function") {
      _liveBoard.applyBroadcastState(frame);
    } else if (typeof _liveBoard.applyFrame === "function") {
      _liveBoard.applyFrame(frame);
    }
  }
}

function hideResumeHostPrompt() {
  const el = document.getElementById("matchdayHostTakeover");
  if (el) {
    el.hidden = true;
    el.innerHTML = "";
  }
}

function showResumeHostPrompt(session) {
  const el = document.getElementById("matchdayHostTakeover");
  if (!el) return;
  el.hidden = false;
  el.innerHTML = `
    <div class="badge" style="display:block;padding:0.6rem 0.75rem">
      A live match is already in progress on another tab/device (or this tab
      reconnected mid-match). You're watching it read-only.
      <button type="button" id="matchdayResumeHostBtn" class="btn-primary btn-sm" style="margin-left:0.5rem">Resume hosting</button>
      <span class="muted" style="display:block;margin-top:0.35rem;font-size:0.8rem">
        This restarts the simulation from kickoff — only use it if the original host is gone for good.
      </span>
    </div>`;
  const btn = document.getElementById("matchdayResumeHostBtn");
  if (btn) {
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      hideResumeHostPrompt();
      destroyLiveBoard();
      await startHostBoard(session);
    });
  }
}

async function ensureLiveBoard(session, { isAdmin }) {
  if (!session) return;
  const phase = session.phase;
  if (phase !== "live" && phase !== "running") return;
  if (!(session.board || session.engine === "tactic_board")) return;

  const canHost = Boolean(isAdmin || getAdminToken());
  if (canHost) {
    // A page reload/reconnect resets this tab's local state, but the server
    // session may already have a live match in progress (frames already
    // broadcast). Auto-hosting here would spin up a second, independent
    // simulation and silently overwrite the real one for every viewer — so
    // only auto-host when nothing has been broadcast yet (a genuine first
    // start); otherwise watch read-only until the admin explicitly takes over.
    const alreadyBroadcasting = Boolean(session.frame_seq) || Boolean(session.board_state);
    if (alreadyBroadcasting && !_hosting) {
      await startViewerBoard(session);
      showResumeHostPrompt(session);
      return;
    }
    hideResumeHostPrompt();
    await startHostBoard(session);
  } else {
    await startViewerBoard(session);
  }
}

function showIdleMatchday(data, { isAdmin, force = false } = {}) {
  if (!force && _lastMatchdayKey === "idle") return;
  destroyLiveBoard();
  _lastMatchdayKey = "idle";
  const app = document.getElementById("app");
  if (app) {
    app.innerHTML = renderMatchdaySession(data || { active: false, session: null }, { isAdmin });
  }
}

async function refresh({ force = false } = {}) {
  // setInterval doesn't wait for the previous call to finish — on a slow poll
  // (>900ms round trip) this let two requests run concurrently, and if they
  // resolved out of order the older one would win, appearing to viewers as
  // the live score randomly regressing. Skip rather than overlap.
  if (_refreshInFlight) return;
  _refreshInFlight = true;
  try {
    const data = await api("/api/matchday");
    const isAdmin = isAdminUser() || Boolean(getAdminToken());
    const session = data && typeof data === "object" ? data.session ?? null : null;

    // No active session — empty state, never read session.phase
    if (!data?.active || !session) {
      showIdleMatchday(data, { isAdmin, force });
      return;
    }

    const phase = session.phase;
    const frameSeq = session.frame_seq ?? session.frame?.seq ?? "";
    const key = `${session.fixture_id}|${phase}|${session.result?.score || ""}|${session.message || ""}|${frameSeq}`;

    const liveMounted = Boolean(_liveBoard) && (phase === "live" || phase === "running");
    const samePhaseLive =
      !force && liveMounted && _lastMatchdayKey.startsWith(`${session.fixture_id}|${phase}|`);

    if (samePhaseLive && !_hosting) {
      _lastMatchdayKey = key;
      await startViewerBoard(session);
      return;
    }

    if (!force && key === _lastMatchdayKey && (liveMounted || phase === "result")) {
      return;
    }

    const phaseChanged =
      !_lastMatchdayKey || !_lastMatchdayKey.startsWith(`${session.fixture_id}|${phase}|`);

    if (phaseChanged || force || phase === "setup" || phase === "result") {
      if (phase !== "live" && phase !== "running") {
        destroyLiveBoard();
      }
      _lastMatchdayKey = key;
      const app = document.getElementById("app");
      app.innerHTML = renderMatchdaySession(data, { isAdmin });
      wireMatchdayActions(session);
      if (typeof TacticBoard !== "undefined" && phase === "result") {
        TacticBoard.wireMatchdayWatch(app, session);
      }
      await ensureLiveBoard(session, { isAdmin });
    } else if (!_hosting) {
      _lastMatchdayKey = key;
      await startViewerBoard(session);
    } else {
      _lastMatchdayKey = key;
    }
  } catch (e) {
    if (
      e.message.includes("401") ||
      e.message.includes("Login") ||
      e.message.includes("admin token")
    ) {
      clearSession();
      window.location.href = "/login?next=/matchday";
      return;
    }
    const app = document.getElementById("app");
    if (app) app.innerHTML = `<div class="empty">Failed to load: ${esc(e.message)}</div>`;
  } finally {
    _refreshInFlight = false;
  }
}

refresh();
setInterval(() => refresh(), 900);
