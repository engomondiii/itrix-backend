# itriX Product Canonical — ALPHA Compute & ALPHA Core v2.4 (HISTORICAL)

**Status: SUPERSEDED / NONCURRENT. Retained only for historical source traceability.**
**Superseded by:** `itrix_product_canonical_v3_5.md` and the September 2026 White Paper v3.5 taxonomy.
**Retrieval rule:** this source must not govern current visitor answers.
**Source:** ALPHA Compute & ALPHA Core — Computational Infrastructure for the Age of AI, White Paper v2.4, August 2026.

## Core thesis

Representation before execution. Execution that preserves the representation.

itriX treats the representation of mathematical work as an engineering surface. The question is not only how quickly existing operations can be executed, but whether an eligible workload can be expressed through a structurally better computational route while preserving the mathematical or application-specific meaning that matters.

## ALPHA Compute

ALPHA Compute is the independent software computational infrastructure product.

It can:

- diagnose structural inefficiency and computational boundaries;
- determine mathematical eligibility;
- select and apply an appropriate ALPHA method route;
- transform eligible workloads into validated computational representations;
- execute or route the transformed structure through existing software libraries, solvers, compilers, vendor kernels and runtimes;
- reconstruct and verify the intended result;
- measure technical and economic advantage against an agreed baseline; and
- remain deployed in production on existing hardware without ALPHA Core.

ALPHA Compute is not merely a diagnostic pre-stage for hardware and is not merely a qualification step for ALPHA Core. Diagnosis and assessment are modules within the software product, not the product's complete identity.

## ALPHA Core

ALPHA Core is the separate hardware-layer computational infrastructure product.

It implements or accelerates already validated ALPHA computational structures more deeply in hardware architectures when additional hardware-level value is justified. Examples include FPGA, ASIC, NPU, accelerator, memory/data-path, SoC or other chip/system architectures.

ALPHA Core is not a required runtime or SDK stage after ALPHA Compute and is not a prerequisite for production software value.

## Relationship between the products

ALPHA Compute and ALPHA Core are complementary but independent.

The software-only path is valid and complete:

ALPHA Compute → diagnose → determine eligibility → transform → execute/route in software → verify/reconstruct → measure → production software deployment.

The optional hardware-extension path is:

validated ALPHA Compute evidence → ALPHA Core hardware evaluation → prototype/co-design → hardware integration → validation → hardware licensing or metering.

Failure to adopt ALPHA Core does not make an ALPHA Compute deployment incomplete.

## Method families underneath the products

AXIOM / AXIOM-TENSOR, CRE and FQNM are method families underneath the ALPHA products. They are not three separate ALPHA products and they are not a mandatory sequential pipeline.

- AXIOM concerns algebraic state, observation/projection and reconstruction, with high-dimensional algebraic structure as a technical route.
- CRE is a structure-preserving real embedding route for eligible complex/Hermitian operator problems; the validated HPD case can expose a structured real SPD execution path.
- FQNM is a quantised integer-transfer route for validated conservative dynamics, with exact discrete conservation within its stated scope.

No method family is universally applicable. Mathematical eligibility comes before any performance claim.

## Evidence discipline

Mathematical equivalence does not by itself prove runtime, memory, power or economic benefit. Runtime, memory, energy and commercial claims require workload-specific measurement against a frozen baseline, including transformation and reconstruction overhead.

## Evaluation and deployment progression

ALPHA Compute can support assessment, controlled evaluation or proof work, and production software deployment when each step is explicitly selected and evidence supports it. A controlled evaluation is not automatically a PoC, and success at one stage does not create consent to a later stage. Commercial terms are agreed separately in the applicable commercial process and are not part of public technical guidance. ALPHA Core is considered only when deeper hardware implementation is expected to add incremental verified value beyond the software-only ALPHA Compute baseline.
