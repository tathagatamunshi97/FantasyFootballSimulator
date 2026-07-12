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
let _hosting = false;
let _lastFrameSeq = -1;
let _savingFt = false;
let _publishQueue = null;
let _publishBusy = false;

function destroyLiveBoard() {
  if (_liveBoard && typeof _liveBoard.destroy === "function") {
    _liveBoard.destroy();
  }
  _liveBoard = null;
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
        panel.hidden = false;
        let html = "";
        if (typeof renderAnalysis === "function" && analysis) {
          html += renderAnalysis(analysis);
        }
        if (typeof renderSquadAnalysis === "function" && squad) {
          html += renderSquadAnalysis(squad);
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
      };
      if (existing.analysis || r.analysis) {
        showReport(existing);
        return;
      }

      if (!tid || !mid) {
        alert("Analysis is not available yet.");
        return;
      }

      analysisBtn.disabled = true;
      const prevLabel = analysisBtn.textContent;
      analysisBtn.textContent = "Generating…";
      panel.hidden = false;
      panel.innerHTML = `<p class="muted">Generating analysis…</p>`;
      try {
        const data = await fetchTournamentMatchAnalysis(tid, mid);
        if (session.result) {
          session.result.has_analysis = Boolean(data?.analysis);
          session.result.analysis = data.analysis;
          session.result.squad_analysis = data.squad_analysis;
          session.result.matchup = data.matchup;
          session.result.report = {
            analysis: data.analysis,
            squad_analysis: data.squad_analysis,
            matchup: data.matchup,
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
  if (_publishBusy || !_publishQueue || !getAdminToken()) return;
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
  if (_savingFt || !getAdminToken() || !session) return;
  _savingFt = true;
  const home = session.home;
  const away = session.away;
  const hg = Number(score.homeGoals) || 0;
  const ag = Number(score.awayGoals) || 0;
  let winner = score.winner || null;
  if (session.is_knockout && !winner) {
    if (hg > ag) winner = home;
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
      broadcastIntervalMs: 220,
      onBroadcast: (frame) => queueBroadcast(frame),
      onFullTime: (score) => saveFullTime(score, session),
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
    });
  }

  const frame = session.frame || session.board_state;
  const seq = frame?.seq ?? session.frame_seq ?? 0;
  if (frame && seq !== _lastFrameSeq) {
    _lastFrameSeq = seq;
    if (typeof _liveBoard.applyBroadcastState === "function") {
      _liveBoard.applyBroadcastState(frame);
    } else if (typeof _liveBoard.applyFrame === "function") {
      _liveBoard.applyFrame(frame);
    }
  }
}

async function ensureLiveBoard(session, { isAdmin }) {
  if (!session) return;
  const phase = session.phase;
  if (phase !== "live" && phase !== "running") return;
  if (!(session.board || session.engine === "tactic_board")) return;

  const canHost = Boolean(isAdmin || getAdminToken());
  if (canHost) {
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
  }
}

refresh();
setInterval(() => refresh(), 900);
