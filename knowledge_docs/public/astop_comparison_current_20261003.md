# ASTOP comparison and evidence boundaries

Sources: itriX ASTOP Comparative Knowledge Core v1.1, 16 September 2026; newer ASTOP White Paper v2.3 and R07 PRISM. This curated edition preserves comparison distinctions and replaces unqualified older benchmark presentation. Competitor descriptions retain the comparative source's date; current availability or integrations require separate verification.

## Different layers of efficiency
Anthropic request/model mechanisms, including prompt caching and request design, can affect the cost of model use. SoL-Pi concerns agent harness and trajectory behavior. ASTOP and PRISM concern observation and supervision: which state is collected, represented and delivered before reasoning is invoked. These layers overlap and may complement each other. Do not claim competitors never observe state, that ASTOP alone changes behavior, or that ASTOP inherently improves model intelligence.

ASTOP is not just prompt caching. Caching changes how suitable repeated input is handled; observation can avoid unnecessary supervision calls or reduce the decision-relevant information that must be delivered. A caching benefit does not demonstrate preserved observation fidelity, and a smaller observation does not prove a lower bill after all costs. Neither makes the other universally unnecessary.

## Evidence and comparisons
The newer finite test panel reports 58.8–69.2% fewer observation-induced tokens,23.1–30.1% fewer model calls and 88.1–90.0% fewer delivered bytes. It concerns Qwen3.5 models and 360 episodes with 30/60/120/300-second durations, not a 24-hour endurance study or universal customer saving. Some training workloads made more calls despite fewer tokens. Preserve the experiment's task and decision-fidelity conditions.

The earlier 51.9–84.5% range belongs to the September comparative material's older experiment. It must not be presented as the current range, a guaranteed ASTOP saving or a price advantage over SoL-Pi. Never add or multiply ASTOP, SoL-Pi and Anthropic percentages to invent combined savings. Run the combined system against a comparable baseline and report cost, quality, latency and uncertainty.

## When ASTOP may help or add overhead
Repeated polling, long-running supervision, meaningful state transitions and expensive downstream reasoning are candidate use cases. Simple one-shot inference, cheap local checks or webhooks that already provide sufficient events can be weak fits. With sufficient webhooks, justify incremental benefit through better representation, evidence preservation, missing coverage or decision quality; do not replace a working event feed without measured reason.

ASTOP itself consumes compute. Subtract observer CPU/GPU work, memory, storage, integration and failure-handling overhead from avoided model work. Preserve required failure/completion events and acknowledgements, and measure missed events, false alarms and delay. A token reduction alone is not a net monetary or energy saving.

The comparative source discusses local session archives such as ObservationPack and Evidence-Preserving Reducer. Retention and deletion behavior must be checked explicitly; archived copies are not presumed automatically deleted. Compatibility or an example configuration is not a validated ASTOP/SoL-Pi integration, and SoL-Pi must not be described as an official Pi distribution on this evidence. PRISM research and the shipped ASTOP implementation are related but not legally or functionally identical in every respect.
