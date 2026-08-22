"""Gemini narrative layer: commentary, post-match analysis, squad reports.

The Python engine is always the source of truth for every score, stat, and
event -- these functions only narrate structured data the caller already
computed. The model is never asked to invent a number; every prompt embeds
the exact facts it may cite and instructs it to use nothing else.

Every public function fails open: if GEMINI_API_KEY is unset, the package
isn't installed, or the API errors, they return None so callers fall back
to the existing rule-based output instead of breaking the page.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any

_MODEL = "gemini-3.6-flash"
_client = None
_client_checked = False


def _get_client():
    global _client, _client_checked
    if _client_checked:
        return _client
    _client_checked = True
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None
    try:
        from google import genai

        _client = genai.Client(api_key=api_key)
    except Exception:
        _client = None
    return _client


def is_available() -> bool:
    return _get_client() is not None


def _generate_json(prompt: str, *, temperature: float = 0.6, attempts: int = 2) -> dict[str, Any] | None:
    client = _get_client()
    if not client:
        return None
    from google.genai import types

    for attempt in range(attempts):
        try:
            resp = client.models.generate_content(
                model=_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=temperature,
                    response_mime_type="application/json",
                ),
            )
            text = (resp.text or "").strip()
            if not text:
                return None
            data = json.loads(text)
            return data if isinstance(data, dict) else None
        except Exception:
            if attempt + 1 >= attempts:
                return None
            time.sleep(1.5)
    return None


_GROUNDING_RULE = (
    "Only use the facts given below. Never invent a score, stat, player name, "
    "or event that isn't listed. If something isn't provided, don't mention it "
    "rather than guessing."
)


def generate_match_analysis(match_data: dict[str, Any]) -> dict[str, Any] | None:
    """Post-match narrative analysis grounded in the engine's own numbers.

    ``match_data`` should be a compact digest: home/away names, final score,
    expected xG, outcome probabilities, and the deterministic key_factors
    list already produced by analysis_explainer.build_matchup_analysis --
    NOT the raw simulation internals.
    """
    prompt = f"""You are a sharp football analyst writing a short post-match report.

{_GROUNDING_RULE}

MATCH DATA:
{json.dumps(match_data, indent=2, default=str)}

Return JSON with exactly these keys:
- "headline": a punchy one-line headline for the result (string)
- "verdict": 2-3 sentences on how the match went, grounded in the score and key_factors given (string)
- "turning_point": the single most decisive factor from key_factors, explained in 1-2 sentences (string)
- "tactical_analysis": 2-3 sentences on why the stronger side's edge translated (or didn't) into goals, citing only the given factors (string)
- "key_takeaways": an array of exactly 3 short bullet strings

Do not include any other keys. Write in a confident, magazine-style tone, not a stats dump."""
    return _generate_json(prompt)


def generate_squad_report(squad_data: dict[str, Any]) -> dict[str, Any] | None:
    """Narrative squad report grounded in the engine's own squad evaluation.

    ``squad_data`` should be a compact digest: team name, formation, unit
    ratings, team composites, tier labels (strengths/weaknesses), and bench
    info -- the same numbers already shown on the squad hub, not raw player
    season stats.
    """
    prompt = f"""You are a football analyst writing a squad report for a fantasy manager.

{_GROUNDING_RULE}

SQUAD DATA:
{json.dumps(squad_data, indent=2, default=str)}

Return JSON with exactly these keys:
- "overall_rating": a number 0-10, one decimal place, consistent with the strengths/weaknesses given
- "summary": 2-3 sentences on the squad's overall identity and biggest strength (string)
- "area_of_concern": the single most pressing weakness from the data given, 1 sentence (string)
- "tactical_recommendation": 1-2 sentences of concrete advice given the formation and unit ratings (string)

Do not include any other keys. Write for a manager who already knows their squad, not a beginner."""
    return _generate_json(prompt)


def generate_scout_game_plan(scout_data: dict[str, Any]) -> dict[str, Any] | None:
    """Manager's game plan grounded in a deterministic scout report.

    ``scout_data`` should be a compact digest: both teams' names/formations,
    the unit/team comparisons (advantage/disadvantage per area, with the
    actual values), the tactical_matchup synthesis (biggest advantage/
    concern), and key_battles (role matchups with a verdict) -- everything
    the scout report already computed deterministically. The model narrates
    what these numbers mean tactically; it never invents a stat, a player
    quality, or a score prediction.
    """
    prompt = f"""You are a football analyst writing a pre-match game plan for a fantasy manager, based entirely on a deterministic scout report comparing their squad to an opponent's.

{_GROUNDING_RULE}

SCOUT DATA:
{json.dumps(scout_data, indent=2, default=str)}

Return JSON with exactly these keys:
- "headline": one punchy line naming the single clearest tactical opportunity or concern (string)
- "in_possession": 1-2 sentences on how to attack this specific opponent, grounded in the comparisons/key_battles given (string)
- "out_of_possession": 1-2 sentences on how to defend against this specific opponent's strengths (string)
- "transitions": 1-2 sentences on transition moments (attacking or defensive) worth planning for, only if the data supports it -- otherwise a short "Nothing notable in the data" (string)
- "biggest_danger": 1 sentence on the single biggest risk this matchup poses, grounded in the data (string)

Do not include any other keys, a scoreline, a win probability, or any stat not present in the data given. Write for a manager who already knows football, not a beginner — be specific about which unit/area/player battle you're referencing."""
    return _generate_json(prompt)


def generate_match_commentary(
    home: str, away: str, events: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Batch commentary for a completed (or partial) sequence of match events.

    ``events`` is a list of dicts like {"minute": 68, "type": "goal",
    "team": "home"|"away", "player": "...", "detail": "..."}, already sorted
    by minute -- the same event log the tactic board already records.
    """
    if not events:
        return None
    prompt = f"""You are a live football commentator writing recap blocks for a match.

{_GROUNDING_RULE}

HOME TEAM: {home}
AWAY TEAM: {away}
EVENTS (chronological):
{json.dumps(events, indent=2, default=str)}

Return JSON with exactly one key, "blocks", an array of objects -- one per
goal (skip non-goal events unless they directly set up a goal), each with:
- "minute": the event's minute (number)
- "headline": a short punchy headline, e.g. "GOAL! {home} strike again!" (string)
- "text": 1-2 vivid sentences describing the passage of play, using only the given event data (string)

Do not include any other keys or events without a listed goal."""
    return _generate_json(prompt)
