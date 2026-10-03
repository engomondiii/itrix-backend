# Workload and bottleneck guide — revised edition

Sources: Computational Workload and Platform Materials v2.0 and AI-Aggravated Bottleneck Materials v2.0, retained with October product boundaries. These examples identify questions to investigate; they do not establish qualification, compatibility or guaranteed savings.

## Begin with the workload
Ask what task runs, where it runs, what is becoming costly and what must remain correct. Identify the owner, representative data, hardware/software environment, baseline, precision, failure cases and acceptance criteria. A platform name alone is insufficient to choose an itriX technology. Public discovery can remain anonymous; protected data transfer and commercial access have their own authorization gates.

## Keep different pressures separate
- Cost: distinguish compute time, model traffic, memory, orchestration, integration and operational cost. Lower observation tokens are not automatically lower total cost.
- Speed: distinguish latency, throughput, time-to-solution, queueing and observation delay. A faster kernel or representation step is not a faster complete workflow.
- Energy: measure power and elapsed work under comparable task quality. Memory movement or utilization is a hypothesis, not a substitute for energy measurement.
- Stability and accuracy: record residual/error, conservation, precision, reconstruction quality and failure behavior separately from runtime.
- Memory and bandwidth: measure allocation, intermediate materialization, layout conversions and transfers; a smaller representation can have transformation overhead.
- Hardware utilization: verify the intended CPU/GPU/accelerator path and contention, thermal limits, unsupported operations and synchronization costs. More utilization alone is not more useful work.
- Architecture pressure: determine whether the present representation or interfaces discard useful structure before execution. Avoid redesigning a whole system from a generic symptom.

## Preserve platform-specific questions
Numerical platforms such as MATLAB, Mathematica, Maple and Julia may expose matrix, symbolic-to-numeric, operator or simulation workloads. Scientific/HPC and CAE/CFD environments require solver, conservation, scaling and baseline detail. AI training and inference require model, task quality, batch/sequence dimensions, precision, memory and actual backend information. Signal processing, robotics and edge systems add latency, reliability and power constraints. Cloud/data-center workflows add orchestration, transfer and shared-resource costs. Chip/SDK partnerships require compatibility, implementation feasibility and explicit intellectual-property scope. These are examples, not certified integrations.

## Choose a bounded next step
Repeated expensive observation with sparse meaningful events may support an ASTOP comparison. A representation hypothesis may justify AXIOM Compute software validation. Planned AXIOM Core dedicated hardware/IP requires its own feasibility discussion and cannot be described as an available generic runtime or required PoC stage. QNTA Runtime has separate feasibility evidence and should not be inferred from any mention of training. CRE, FQNM and other research routes are considered only when their mathematical conditions and workload evidence are relevant.

A scoped assessment states the hypothesis, the transformation/observation costs, recovery or decision-fidelity requirements, baseline and stop criteria. It may end with no fit. Do not force a product, evaluation, NDA, PoC or license merely because a visitor is technical. Retail ASTOP follows the specific LO route; enterprise evaluation and expanded rights remain separately agreed.
