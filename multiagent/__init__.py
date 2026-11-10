"""Offline prototype of a three-agent architecture: Mission Orchestrator, Drone/Swarm Agent and Rover Agent.

Everything here PROPOSES. No agent authorizes, arms, uploads or commands a vehicle; the result of a run is a
global proposal whose tasks stay pending a human authorization, to be handed to the EXISTING planning,
export and coordination entries (planning.scenario_instance, tools.scenario_package, the R1 coordinator).

Modules:
- contracts: the messages exchanged between agents (mission brief, task requests, agent results);
- interpreters: natural language -> mission brief (deterministic rules, or a model adapter);
- swarm: deterministic reference allocation of aerial objectives among several drones;
- drone_agent, rover_agent, orchestrator: the three agents (the orchestrator is a LangGraph graph);
- models: adapters for the models to compare (Ollama, AIDA HPC Qwen and Clef, OpenAI-compatible, doubles);
- tracing: local structured trace and a dry-run Opik payload;
- benchmark: cases, metrics and runner;
- demo: the reproducible offline example.
"""
