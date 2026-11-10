"""Acceptance gate for a mission report produced by Hermes from get_mission_state. Pure, offline.

A report is VALIDATED only when the consumer itself OBSERVED exactly one successful call of the
intended tool with the intended arguments, holds the result that call returned, and the answer
matches that result under the answer contract. Anything else is NOT_VALIDATED with explicit
reasons; matching fields never compensate for a missing or wrong query.

``observed_calls`` must come from the runtime (e.g. Hermes' in-process ``post_tool_call`` hook:
tool_name, args, status, result), never from the model's own text. Not connected to any vehicle
control; it only labels a report. Integration point: a Hermes plugin that keeps the turn's
``post_tool_call`` observations per ``turn_id`` and calls ``validate_mission_report`` from
``post_llm_call`` (``assistant_response``). The trial review (``hermes_capture_run.assess_tool_trial``)
applies the same rule offline to captured metadata.
"""
from __future__ import annotations

import json

from observability import mission_query_cases as cases

TOOL = "mcp__tfg_mission_control__get_mission_state"
VALIDATED = "VALIDATED"
NOT_VALIDATED = "NOT_VALIDATED"


def _result_document(result):
    """The tool's external-view dict from an observed result (dict, or Hermes' MCP JSON envelope)."""
    if isinstance(result, dict) and "view" in result:
        return result
    try:
        outer = json.loads(result) if isinstance(result, str) else result
        inner = outer.get("structuredContent") or outer.get("result")
        return json.loads(inner) if isinstance(inner, str) else inner
    except (ValueError, AttributeError, TypeError):
        return None


def validate_mission_report(*, answer_text: str, intended_run_id: str, observed_calls: list,
                            contract: str = "v3", parsed_answer=None) -> dict:
    """Return {status, reasons, answer} where answer holds per-key outcomes only (no values).

    ``parsed_answer`` is the ``(object, parse_status)`` pair from ``parse_answer(answer_text)`` when
    the caller already read it, so the answer is interpreted once, with one rule."""
    parsed, parse_status = parsed_answer if parsed_answer is not None else cases.parse_answer(answer_text)
    reasons = []
    calls = [c for c in observed_calls if isinstance(c, dict)]
    document = None
    if not calls:
        reasons.append("NO_TOOL_EXECUTED")
    elif len(calls) > 1:
        reasons.append("MORE_THAN_ONE_TOOL_CALL")
    else:
        call = calls[0]
        args = call.get("args") if isinstance(call.get("args"), dict) else {}
        if call.get("tool_name") != TOOL:
            reasons.append("WRONG_TOOL")
        elif call.get("status") != "ok":
            reasons.append("TOOL_NOT_SUCCESSFUL")
        if args.get("run_id") != intended_run_id or args.get("view") != "external":
            reasons.append("ARGUMENTS_NOT_AS_INTENDED")
        document = _result_document(call.get("result"))
    if calls and document is None:
        reasons.append("RESULT_NOT_AVAILABLE")
    elif document is not None:
        queried = (document.get("queried") or {}).get("run_id")
        first = ((document.get("preflights") or [{}])[0].get("identity") or {}).get("run_id")
        if document.get("view") != "external" or document.get("external_schema_version") != 2:
            reasons.append("RESULT_NOT_EXTERNAL_SCHEMA_2")
        elif queried != intended_run_id or first != intended_run_id:
            reasons.append("RESULT_NOT_FOR_INTENDED_RUN")
        elif document.get("rejected_fields"):
            reasons.append("RESULT_HAS_REJECTED_FIELDS")
    if document is not None and not reasons:
        answer = cases.evaluate_parsed(parsed, parse_status, cases.answer_from_external_view(document, contract),
                                       contract)
        if answer["verdict"] != "ALL_FIELDS_CORRECT":
            reasons.append("ANSWER_NOT_VALID" if answer["verdict"] == "FIELDS_INCORRECT" else "ANSWER_NOT_PARSEABLE")
    else:
        # Without a usable observed query there is nothing to compare with: the answer is only
        # parsed, so a coincidentally matching answer cannot turn the result into a success.
        answer = {"verdict": "NOT_COMPARED_NO_VALID_QUERY", "parse_status": parse_status, "contract": contract}
    return {"status": NOT_VALIDATED if reasons else VALIDATED, "reasons": reasons, "answer": answer,
            "contract": contract}
