# FQNM technology overview — revised edition

Source: older FQNM Overview v2.0, retained and reconciled with Portfolio v1.4 and R01. This edited derivative preserves conservation and reconstruction concepts while retiring old product-routing assumptions.

## The continuum and digital-state problem
Physical laws are often written as smooth fields and continuous fluxes; digital machines execute finite-state operations. The older overview asks whether selected conservation-sensitive dynamics can be represented as state-to-state transfer before continuum observables are reconstructed. This does not mean continuum mathematics is wrong or that every continuous model should be replaced.

Potential symptoms include long-run numerical drift, precision sensitivity, artificial diffusion or dispersion, fragile conservation and hardware-dependent results. The assessment identifies the conserved quantity, transfer structure, boundary conditions and observable before proposing a route. Only a conservation-sensitive component of a larger simulation or scientific ML system may be relevant.

The retained high-level method is to identify an eligible workload, establish an appropriate transfer representation, execute within its validity conditions, reconstruct the required observable, and compare conservation, error, stability, runtime and reproducibility against agreed baselines. Source code, detailed update rules, quantisation, proof assumptions and reconstruction maps are not disclosed by this public summary.

## Scope and proof
Conservation, transport, flux, shocks, waves and state transfer are relevance signals rather than automatic eligibility. Selected CAE, CFD, energy, electromagnetic or physical-system workloads may warrant investigation. Industrial scale, dimensionality, boundary behavior and reconstruction error require separate validation. Do not infer universal PDE support, zero numerical error or equal results across all hardware.

R01 studies continuum reconstruction under stated assumptions. The older FQNM paper and NDA comparison remain dated technical evidence. Their existence does not make FQNM a commercially released training runtime, a universal substitute for other compression methods, or a demonstrated customer outcome. Measured runtime and power claims need the specified implementation and environment.

## Current portfolio boundary
FQNM is a research asset. AXIOM Compute software validation and planned AXIOM Core hardware/IP are separately scoped offerings; testing an FQNM hypothesis in a solver is not proof that AXIOM Core is deployed. QNTA Runtime has its own architecture and feasibility evidence. No mandatory AXIOM–CRE–FQNM product sequence follows from these conceptual relationships.
