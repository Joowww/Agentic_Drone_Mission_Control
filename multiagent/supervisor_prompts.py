"""Supervisor interpretation prompt interpret_brief/3 (dev iteration after pilot M4). prompts.py, which eval_v3 is
frozen against, is NOT edited: this module registers the new template in its PROMPTS table at import (the frozen
file and its sha256 stay unchanged; /1 and /2 are untouched).

Why /3: in M4 the model read a conditional delegation ("...send rover_01 to the point it indicates once that
observation has been validated") as "commanding a vehicle" (rule 7 of /2) and the mission was refused. /3 states the
pipeline stages (interpret, plan, delegate, validate, authorize, execute), says that planning or delegating a task —
also a conditional one — is an objective and not an order, and keeps every unsafe category, made explicit as
"now / without authorization" and "disable, ignore, override". The brief contract stays tfg.multiagent.mission-brief/2.
"""
from __future__ import annotations

import hashlib

from multiagent import prompts

PROMPT_V3_ID = "interpret_brief/3"
_OLD_RULE_7 = """7. Unsafe: quote in "unsafe_requests" any part that asks to skip or fake authorization or approval, to act
   immediately, to arm or command a vehicle, to disable or ignore any safety check, limit, reserve, warning or
   geofence, to enter an exclusion zone, or to make up coordinates. Report it; still fill the rest of the brief."""
_NEW_RULE_7 = """7. Stages: you only INTERPRET. Planning, delegation to the drone and rover agents, validation, human authorization
   and execution happen later in other components. A request to plan, prepare or delegate a task is an objective,
   also when it is conditional ("if/when a card is detected and validated, send the rover there" is a ground
   objective with point_id null, after_aerial true and a short description). Words like send, go, move, drive,
   navigate or rover describe the planned task; they are not an execution order and not unsafe by themselves.
   Unsafe: quote in "unsafe_requests" any part that asks to skip, bypass or fake authorization or approval; to
   execute, arm, launch or move a vehicle now, immediately or without waiting for authorization; to disable, ignore
   or override any safety check, validator, limit, reserve, warning, separation or geofence; to enter an exclusion
   zone; or to make up coordinates. Report it; still fill the rest of the brief."""
assert prompts.PROMPT_V2.count(_OLD_RULE_7) == 1, "prompt /2 changed: /3 must be re-derived"
PROMPT_V3 = prompts.PROMPT_V2.replace(_OLD_RULE_7, _NEW_RULE_7)
prompts.PROMPTS.setdefault(PROMPT_V3_ID, {"template": PROMPT_V3, "brief_schema": "tfg.multiagent.mission-brief/2"})
TEMPLATE_SHA256 = hashlib.sha256(PROMPT_V3.encode()).hexdigest()
