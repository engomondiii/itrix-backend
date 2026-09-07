# ASTOP technical capabilities — current controlled synthesis

Source basis: current ASTOP technical README supplied for September 2026 implementation. Distribution/install instructions in that README are NOT governing commercialization authority; ASTOP GTM v2.3 governs access and License-Out.

ASTOP (A System Trans-Observation Projector) is a cross-platform observability instrument for computational systems and long-running research workloads. It projects heterogeneous host, accelerator, process, and experiment state into consistent human, machine-readable, and event-driven views. Acquisition and interpretation are separated: collectors obtain the strongest available evidence, shared models normalize it without inventing unavailable quantities, and presentation layers expose the same state to humans, scripts, and agents.

A measured zero is evidence. An unavailable quantity remains N/A or null and must not be fabricated as zero.

Implemented/technical capabilities described by the source include CPU, memory, pressure, swap, process and multi-GPU observation across platform-specific collectors; programmatic JSON/CSV/record output; an event-driven service; job/watch state; semantic progress/events; blocking waits; durable terminal events and acknowledgement; and platform-specific GPU telemetry. Metric availability depends on hardware, OS/kernel, permissions and installed drivers, and unsupported values remain explicitly unavailable.

Commercial boundary: this source does not authorize public executable download, anonymous evaluation, self-service purchase, public fixed pricing, or production use. Current access is controlled and production rights require an executed License-Out under ASTOP GTM v2.3.
