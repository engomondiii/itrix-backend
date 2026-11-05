# ASTOP observation and access
Sources: ASTOP White Paper v3.0 and Round 7 (November 5, 2026) for current availability boundaries. Historical accepted agreements remain unchanged.

## How it works
ASTOP is an Observation Layer for AI agents and long-running computational systems. Acquire evidence from logs, APIs, files, counters and process state; detect decision-relevant semantic change; deliver sufficient observations to reasoning. Low-level sensing continues outside expensive reasoning. ASTOP does not replace the runtime, scheduler, tool contract or reasoning policy.
Strong fits have long-running work, redundant state and sparse required events. Short jobs, event-dense work, ambiguous telemetry and costly observation logic can be weak fits. Required events and correct decisions must be preserved before any efficiency claim.

## Current benchmark evidence
White Paper v3.0 and the supplied R07 PRISM manuscript report finite-panel reductions of 58.8–69.2% in observation-induced tokens, 23.1–30.1% in model calls and 88.1–90.0% in delivered bytes. The local Qwen3.5 panel uses 9B, 27B and 35B models; all 360 reported episodes succeeded. These are descriptive benchmark observations, not population claims or guarantees for a customer's workload.
ML training used more calls under PRISM despite fewer tokens. Controlled durations of 30, 60, 120 and 300 seconds illustrate finite trends, not proof of an asymptotic limit or 24-hour endurance. An additional 18-episode LLM-free panel covers SGD, Rust compilation and numerical simulation. Observer CPU, memory, I/O, classification cost and latency count against net value.
The older 51.9–84.5% band belongs to earlier evidence and must not be presented as the latest benchmark. Do not add benchmark percentages to SoL-Pi, caching or other tools' reported savings.

## Current access
The website explains ASTOP and accepts PoC applications through the approved language-specific Google Forms. Round 7's download page is a review draft. Confirmed release date, installer URL, supported system requirements and installation guide have not been supplied; do not invent them or offer launch-alert registration. See astop_availability_20261105.md for current routes and boundaries.
