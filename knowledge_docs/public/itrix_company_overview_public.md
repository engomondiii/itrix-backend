# itriX — Company and Technology Overview

**Disclosure tier: PUBLIC.** Everything in this document may be said to an
anonymous visitor with no NDA in place. It contains no construction detail, no
benchmark figures and no performance guarantees.

---

## What is itriX?

itriX is a computational infrastructure company. Its current product architecture works across two distinct intervention domains: **observation before reasoning** and **representation before execution**. The supplied source set identifies Korean patent applications for several computational technology families; it does not verify granted-patent status.

The one-sentence version: **reduce avoidable computational work before simply scaling more of it.**

In the observation domain, PRISM structures decision-relevant system evidence before expensive reasoning, and ASTOP operationalizes that observation domain as a product. In the computational domain, ALPHA Compute applies eligible computational technologies to suitable workloads before execution, while ALPHA Core is a separate optional hardware product considered only when validated software-layer evidence supports deeper hardware implementation.

itriX is not a chip company, cloud provider or model vendor. Its products can sit alongside those layers while changing what information or computation reaches them.

---

## The problem itriX exists to address

For roughly a century, a set of costs in computing have been treated as facts of
life:

- Floating point holds a value like 0.1 only as an approximation.
- Training the same model on the same input twice can produce subtly different
  results — a loss of reproducibility.
- Long-running simulations drift as small errors accumulate.
- Enormous compute is spent on repetitive work whose shape never changes.

The itriX question is not "how do we tolerate these better?" It is: **how much of
this is an unavoidable cost, and how much is the consequence of a representation we
happened to choose?**

Modern infrastructure has answered rising demand by adding capacity — more cores,
wider memory bandwidth, larger accelerators, more power and cooling. That approach
genuinely opened the AI era. But the cost of AI infrastructure does not come from
arithmetic volume alone. It comes together from data movement, memory bandwidth,
power, cooling and orchestration. Beyond a certain point, adding capacity multiplies
an inefficiency rather than removing it.

### Why this is getting worse, not better

Accelerators are strongest on regular, dense, aligned work: many numbers moving
under the same rule, fed in order, not colliding with each other. Where a workload
has that shape, throughput is overwhelming.

Two well-understood things happen when it does not:

- **Serialisation.** Parallel workers that must combine results into one shared
  place stop being parallel and start queuing. Ten thousand workers and one
  chalkboard is not ten thousand times the work.
- **Poor memory locality.** Compute cores are fast, but a fast calculator with no
  data to work on waits. When the values a computation needs are scattered rather
  than adjacent, a wide memory path is largely wasted.

Neither is fixed by buying more of the same hardware, because neither is caused by a
shortage of it. Both are consequences of the shape of the work.

---

## The technology architecture

The supplied authoritative source set identifies three Korean patent applications across the AXIOM, CRE and FQNM technology families. Grant status is not represented as verified in the public Knowledge Core. They share one thesis: **representation before execution.**


### PRISM — observation before reasoning

PRISM is the observation technology/architecture behind ASTOP. It projects and structures system evidence before an expensive AI controller reasons over it. PRISM is a technology, not a separately sold product.

### AXIOM — rearranging algebra

AXIOM is a mathematical framework for changing the *representation and placement* of
a computation so that its fit with hardware changes. It works in three movements:
an algebraic state, a projected observation of that state, and a reconstruction.

The plain-language version: instead of asking the hardware to travel the same road
faster, AXIOM asks whether the computation can travel a different road. Some shapes
of computation suit an accelerator's way of working; some suit a CPU's more
naturally. AXIOM is about deliberately choosing which.

AXIOM should not be described as *only* a faster way of doing multiplication. It is
a framework about representation, and the multiplication case is one consequence of
it rather than its definition.

### CRE — structure-preserving real embedding

CRE concerns operators that are naturally expressed over complex numbers. It embeds
them into a real-valued form in a way that preserves their structure rather than
approximating it — two values travelling together as one bundle with a rotation,
instead of two separately-tracked quantities.

CRE supports AXIOM's thesis; it does not replace it. The two are distinct method families and should not be collapsed into one name.

### FQNM — conservation as counting

FQNM is also described in arXiv:2604.06947 (math.NA), an arXiv preprint.

FQNM stands for Fast Quantized Numerical Method. It re-poses conservation-type
computation as movement between integer states rather than as arithmetic on
approximated continuous values.

The intuition the authors use: imagine measuring a sandcastle eroding in the wind.
You can try to measure a continuously changing weight — or you can count blocks of
sand and track the rules by which they move. The second is a counting problem, and
counting is what integer arithmetic does exactly.

Why that matters: in numerical analysis and physics simulation, the long-standing
central problem is how far error accumulation can be delayed and managed. The
conventional answers are periodic correction, higher-precision floating point, and
more compute. FQNM asks whether the constraint can be viewed one level differently —
whether some of what we call rounding accident is a consequence of the chosen
representation rather than of the machine.

### AXIOM-TENSOR and QNTA

AXIOM-TENSOR and QNTA are additional technologies in the current itriX technical taxonomy. Their applicability is workload-specific. They are not separately sold products, and mentioning them does not establish that they apply to a particular workload or that a performance advantage has been validated.

### Where the two branches meet

FQNM re-asks a question about the derivative: is floating point something we bear out
of necessity, or something we chose? AXIOM re-asks a question about algebra: is
large repetitive computation an unavoidable form, or a chosen form?

Both arrive in the same place. The performance and stability of a computation are not
settled by the name of the chip alone. They depend on the form the numbers and the
operations are expressed in.

---

## The products

itriX currently has three products. Product identity is separate from evidence status: being a product does not imply that a particular workload is eligible, validated, value-verified or licensable.

### ASTOP — observation product

ASTOP (A System Trans-Observation Projector) is the observation product. It operationalizes the PRISM observation domain for computational systems and agentic AI workflows. Public visitors may learn that ASTOP exists and may receive public-safe explanation and approved scoped evidence. ASTOP is not a public self-service download or fixed-price SaaS purchase; controlled evaluation and production rights remain governed separately.

### ALPHA Compute — independent software computational infrastructure

ALPHA Compute is the independent software product. For an eligible workload it can apply appropriate computational technologies to transform representation before execution, with correctness and advantage assessed against an agreed baseline. It can be useful on existing software and hardware paths without ALPHA Core.

### ALPHA Core — separate optional hardware product

ALPHA Core is the separate optional hardware product. It is considered only when validated software-layer evidence justifies deeper implementation or acceleration in hardware. It is not an automatic upgrade, a prerequisite for ALPHA Compute, or a consequence of merely discussing hardware.

### Products versus technologies

**Products:** ASTOP, ALPHA Compute, ALPHA Core.

**Technologies:** PRISM, AXIOM, AXIOM-TENSOR, CRE, FQNM, QNTA.

The technologies are not separate catalogue products. ASTOP and ALPHA are also technically independent; the current commercial sequence may use ASTOP as a controlled proof point before a separate ALPHA Compute qualification, but that sequencing does not make one product technically dependent on another.

## How a strategic evaluation can progress

A visitor can remain in public or controlled technical evaluation without entering a commercial path. When a person explicitly asks itriX to evaluate a concrete organizational workload or decision, the system can offer a Strategic Customer transition and, if accepted, reflect the problem before recommending a next action.

Possible later actions are independent decisions rather than a mandatory funnel. Depending on the selected action, evidence and authorization, they may include a controlled evaluation, an agreement-protected technical exchange, a proof of concept, integration work, or a commercial discussion. An NDA protects information that has separately been authorized for disclosure; signing one does not itself create disclosure entitlement. A controlled evaluation is not a PoC unless the customer explicitly chooses a PoC. Commercial terms and rights are established only through the applicable approved or executed agreement.

---

## Where itriX is most relevant

itriX is worth a conversation where the pressure looks **structural** rather than
cyclical — where adding capacity has bought headroom without changing the cost of a
unit of work:

- **Training and inference cost growing faster than the value produced.** Scaling
  compounds an inefficiency in representation rather than resolving it.
- **Energy, power and thermal ceilings.** More chips can be bought; power, cooling
  and floor space often cannot. Reducing what the hardware is asked to do is a
  different lever from supplying more of it.
- **Data-movement-bound runtime.** Where the accelerator is waiting on memory rather
  than computing, arithmetic throughput is not the constraint.
- **Reproducibility and numerical stability.** Where results drift over long runs, or
  the same input does not reliably give the same output.
- **Conservation-heavy simulation.** Physics, fluids, climate, and other domains
  where a conserved quantity must stay conserved.
- **Edge and constrained deployment.** Where there is no more power, memory or
  thermal budget to give.

---

## What itriX will and will not claim

This distinction is load-bearing, and itriX states it in its own materials.

### Stated strongly

- The cost of modern AI infrastructure arises from data movement, memory bandwidth,
  power, cooling and orchestration together — not from arithmetic volume alone.
- Accelerators are strong at regular, dense tensor computation, and there exist
  computations whose form and grain differ from that.
- AXIOM is a mathematical framework showing that changing the representation and
  placement of a computation can change its fit with the hardware.
- FQNM is the idea of re-placing conservation-type computation as a movement
  structure between integer states.

### Never claimed

- No guaranteed savings, speedups or accuracy improvements.
- No absolutes: not "always", not "every workload", not "replaces your hardware".
- No competitor comparisons.
- No quantitative performance figure without workload-specific validated evidence against an appropriate frozen baseline.

The honest framing is conditional throughout: *may*, *in eligible cases*, *subject
to validation*. This is not hedging for its own sake — a company whose thesis is
"validate rather than promise" cannot promise.

---

## People and provenance

- **AXIOM-CRE** originates in the master's thesis of **Junhu Park** (Department of
  Mathematical Sciences, Seoul National University; advisor **Myungjoo Kang**).
- **FQNM** is published as **arXiv:2604.06947** [math.NA], by **Junhu Park**,
  **Youngsoo Ha** and **Myungjoo Kang**.
- **Haneol Kim**, Principal Researcher at itriX and a PhD candidate in Mathematical
  Sciences at Seoul National University, authored *Redefining Computation*, the
  public explainer that translates AXIOM-CRE and FQNM for non-specialist readers.

*Redefining Computation* is deliberately built out of questions rather than promises
or demos. Its own framing: before asking whether the calculator is fast enough, ask
whether we are expressing the thing we need to compute in the right form.

---

## Frequently asked questions

**What does itriX actually sell?**
itriX currently has three products: ASTOP, ALPHA Compute and ALPHA Core. ASTOP is the observation product. ALPHA Compute is the independent software computational infrastructure product. ALPHA Core is the separate optional hardware product. PRISM, AXIOM, AXIOM-TENSOR, CRE, FQNM and QNTA are technologies rather than separately sold products.

**Is this a chip, a compiler, or a library?**
No single label covers the portfolio. ASTOP is an observation product. ALPHA Compute is software computational infrastructure that can work with existing libraries, solvers, compilers, vendor kernels and hardware. ALPHA Core is a separate optional hardware-layer product when deeper implementation is justified.

**Do I need to share confidential information to start?**
No. The first conversation is a non-confidential description of where computational
pressure is being felt. Construction detail and evaluation methodology are shared only when the applicable disclosure is separately authorized and any required agreement protection is in place. An NDA by itself does not create access, and nothing requires you to disclose a workload to have that first conversation.

**How much faster will my workload run?**
That question cannot be answered honestly before workload-specific validation against a frozen baseline. itriX does not publish or promise workload-specific performance figures without supporting evidence. The appropriate validation form may be a controlled evaluation or, if explicitly selected, a proof of concept; commercial terms are handled separately.

**Is the technology proven?**
The supplied evidence includes three Korean patent applications, an arXiv preprint and a master's thesis. Those facts do not establish performance on a particular workload. Workload-specific advantage requires an appropriately scoped validation against an agreed baseline; that validation is not automatically a proof of concept.

**Which industries does this apply to?**
The technology is domain-general, because representation is domain-general. It is
most relevant where compute pressure is structural: AI training and inference at
scale, physics and engineering simulation, semiconductor and memory design,
autonomy, aerospace, climate and energy modelling, and constrained edge deployment.

**Where do I start?**
You can begin by asking any public question or, if you want itriX to evaluate a concrete workload, describe the computational pressure in non-confidential terms. The system will not assume a commercial path from that alone.
