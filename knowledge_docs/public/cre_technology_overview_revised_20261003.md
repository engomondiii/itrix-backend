# CRE technology overview — revised edition

Source: older CRE Overview v2.0, retained and reconciled with Portfolio v1.4 and R02. This edited derivative preserves the operator-focused explanation and disclosure boundaries. It replaces the old assumption that runtime testing is itself an AXIOM Core product.

## What CRE addresses
CRE means Conjugation-Real Embedding. It explores whether selected complex or tensor-valued operator workloads can be represented in a real structured form while preserving the mathematical meaning needed for computation and recovery. It is more specific than a general promise to make complex arithmetic faster.

Representation costs may include repeated real/complex conversion, tensor layout movement, operator-to-solver conversion, duplicate intermediate storage, cache/memory traffic and device transfers. A representation hypothesis asks whether some of those boundaries can be reduced without changing the required operation. Symptoms such as memory pressure or conversion churn are reasons to investigate eligibility, not proof that CRE will improve the workload.

Relevant properties depend on the route and conditions: multiplication relations, adjoints, invertibility, spectra, norms, conditioning and recoverability. Do not promise that every property is preserved for every operator. Execution cost, transformation/recovery overhead, precision, numerical error and data movement must all be measured against the actual baseline.

## Preserved distinctions and evidence limits
AXIOM focuses on algebraic state and operations; CRE focuses on eligible operator representations; FQNM focuses on conservation-sensitive transfer. CRE is an enabling technology in the October portfolio, not an extra sold product or mandatory dependency for AXIOM-TENSOR/QNTA.

R02 concerns structured Cholesky/inverse reconstruction for admissible operators. It does not remove worst-case cubic complexity of dense operations. Report admissibility, matrix dimensions, structure, precision, conditioning, reconstruction error and runtime separately. A smaller or real-valued representation does not establish net energy, whole-model or universal solver speed benefits.

## Product and disclosure boundaries
An eligible CRE hypothesis can be evaluated in the relevant software environment. AXIOM Compute is in software validation; AXIOM Core is planned dedicated hardware/IP and is not a required general runtime-validation stage. Commercial scope and support require separate agreement.

Public material may explain selected structure-preserving representation and why repeated boundaries matter. Detailed embedding maps, operator/SPD eligibility, solver orchestration, recovery logic, implementation and partner-specific crossover evidence remain controlled and require explicit authorization. An NDA alone never unlocks those details. No private patent-file identifiers or implied grant status are carried into this edition.
