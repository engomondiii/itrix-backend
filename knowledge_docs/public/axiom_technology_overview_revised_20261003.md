# AXIOM technology overview — revised edition

Source: older AXIOM Overview v2.0, retained and reconciled with Portfolio v1.4 and R03. This is an edited derivative preserving useful explanation; original mathematical research is not rewritten. Product identity and maturity follow the October portfolio.

## State, observation and reconstruction
AXIOM means Algebraic eXtension by Index-Ordered Multiplication. The earlier overview explains algebraic computation through state, transitions, projected observation, preservation of hidden structure and reconstruction. A visible output need not describe all the internal state that produced it. A zero observation alone does not establish a zero internal state. Conversely, hidden state cannot always be recovered: the relevant structure must be preserved and the reconstruction conditions established.

The useful assessment questions remain: what state exists, what transition occurs, which part is observed, what information is retained, and whether the original algebraic meaning can be reconstructed. Symptoms worth investigating include projection being mistaken for full state, early flattening into arrays/kernels that discards useful structure, reconstruction failure, and special-case arithmetic burden. These are hypotheses to investigate, not diagnoses established by a visitor using an algebra keyword.

## Distinct technology roles
AXIOM addresses algebraic state and operations. CRE concerns structure-preserving real representation of eligible operators. FQNM concerns conservative transfer and continuum reconstruction. Their relationship does not prove that all three must be installed together or that every workload should follow them in sequence. AXIOM-TENSOR and QNTA have separate evidence scopes.

The new R03 paper provides bounded evidence about signed-XOR, table-free basis multiplication. That result is narrower than a claim to reconstruct arbitrary states or accelerate whole models. Report the operation and algebra involved, terms stored, sign conventions, precision and workload. Table-free basis support does not eliminate the scaling cost of a sparse bilinear product.

## Product and evaluation boundaries
AXIOM Compute is the software offering in validation. AXIOM Core is planned dedicated hardware/IP; it is not the generic name for all runtime, solver or PoC execution. Assess a representation hypothesis on an agreed environment without implying an available hardware product or mandatory migration. Research relevance does not establish licensing readiness or deployment compatibility.

Public explanations may discuss the problem and high-level role. Detailed reconstruction, eligibility, basis/sign mechanisms, implementation, partner mappings and unpublished performance require appropriate content authorization in addition to any applicable NDA. Neither a paper nor a confidentiality agreement grants unrestricted implementation disclosure. Patent applications are not grants, and coauthorship is not inventorship.
