# itriX — Company and Technology Overview

**Disclosure tier: PUBLIC.** Everything in this document may be said to an
anonymous visitor with no NDA in place. It contains no construction detail, no
benchmark figures and no performance guarantees.

---

## What is itriX?

itriX is a computational infrastructure company. It commercialises patented
mathematics that changes **the form a computation is expressed in before that
computation is executed**.

The one-sentence version: **don't scale inefficient computation — make computation
worth scaling first.**

itriX is not a chip company, not a cloud provider, and not a model company. It sits
one level below all three, at the layer where a workload is *represented*. The same
arithmetic can be written in more than one form, and the form decides how well it
fits the hardware it will eventually run on. itriX works on that choice of form.

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

## The Knowledge Core: three patented technologies

itriX holds three granted Korean patents. They are separate inventions with one
shared thesis: **representation before execution.**

### AXIOM — rearranging algebra

**Patent P260-07KR.**

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

**Patent P253-84KR.**

CRE concerns operators that are naturally expressed over complex numbers. It embeds
them into a real-valued form in a way that preserves their structure rather than
approximating it — two values travelling together as one bundle with a rotation,
instead of two separately-tracked quantities.

CRE supports AXIOM's thesis; it does not replace it. The two are distinct patents
with distinct claims and should not be collapsed into one name.

### FQNM — conservation as counting

**Patent P253-18KR.** Published as arXiv:2604.06947 (math.NA).

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

### Where the two branches meet

FQNM re-asks a question about the derivative: is floating point something we bear out
of necessity, or something we chose? AXIOM re-asks a question about algebra: is
large repetitive computation an unavoidable form, or a chosen form?

Both arrive in the same place. The performance and stability of a computation are not
settled by the name of the chip alone. They depend on the form the numbers and the
operations are expressed in.

---

## The products

### ALPHA Compute — representation diagnosis

ALPHA Compute is the entry point and the adoption wedge. It is a **diagnostic**: it
examines whether a workload carries structural overhead in how it is represented,
and where the highest-leverage opportunities for change might lie.

It produces a transformation hypothesis, not a promise. Any quantitative claim has
to be validated against the specific workload through evaluation.

### ALPHA Core — runtime and execution

ALPHA Core is the execution and validation layer: the runtime that applies a
transformation, and the proof-of-concept apparatus that measures whether it did what
the hypothesis said it would.

The division is worth stating plainly, because it is easy to blur: **ALPHA Compute
diagnoses and proposes a transformation. ALPHA Core executes and validates it.**

*(Some older itriX material describes ALPHA Core as hardware-facing intellectual
property for future silicon. The current approved position is the one above: ALPHA
Core is the runtime and validation layer. If asked, describe it that way.)*

---

## How itriX engages commercially

### One-Third Value Participation

itriX prices on **one-third value participation**: itriX participates in one third
of the validated value created, rather than charging a licence fee up front against
an unproven benefit.

The reason is structural rather than generous. If the claim is that representation
can be improved and that any improvement must be validated rather than promised, then
the commercial model has to sit on the same side of that claim. Value participation
means itriX is paid when the evaluation shows something, and not before.

### The typical path

1. **A non-confidential conversation.** A description of where computational
   pressure is being felt — cost, latency, energy, stability, memory movement,
   hardware utilisation, or an architectural ceiling. No confidential technical
   detail is needed or wanted at this stage.
2. **A representation review.** ALPHA Compute looks at whether the pressure appears
   structural rather than cyclical, and where representation might be the leverage.
3. **An NDA, where the conversation needs to go deeper.** Construction detail,
   methodology and evaluation design sit behind an NDA — not as a sales gate, but
   because that is where the patented specifics live.
4. **A scoped proof of concept.** A defined workload, agreed measurements, and a
   result that either supports the hypothesis or does not.
5. **Licensing and integration,** where the PoC supports it.

### Licensing pathways

Non-exclusive, exclusive, and strategic. Which is appropriate depends on the
workload, the industry, and how central the technology would become to the partner's
own roadmap.

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
- No quantitative performance figure outside a validated proof of concept.

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
Two products. ALPHA Compute, a representation diagnostic that identifies whether a
workload carries structural overhead. ALPHA Core, the runtime that applies a
transformation and the apparatus that validates it.

**Is this a chip, a compiler, or a library?**
None of those exactly. It is mathematics about the form a computation takes,
delivered as a diagnostic and a runtime. The principle can be implemented on both
CPU and GPU; part of the diagnosis is which suits a given shape of work.

**Do I need to share confidential information to start?**
No. The first conversation is a non-confidential description of where computational
pressure is being felt. Construction detail and evaluation methodology sit behind an
NDA, and nothing requires you to disclose a workload to have that first
conversation.

**How much faster will my workload run?**
That question cannot be answered honestly before an evaluation. itriX does not
publish or promise figures outside a validated proof of concept — which is also why
pricing is value participation rather than an up-front fee.

**Is the technology proven?**
The mathematics is published and patented: three granted Korean patents, a
peer-reviewable arXiv paper, and a master's thesis. Whether it produces a benefit on
*your* workload is exactly what a proof of concept is for. itriX separates those two
statements deliberately and does not let them share a sentence.

**Which industries does this apply to?**
The technology is domain-general, because representation is domain-general. It is
most relevant where compute pressure is structural: AI training and inference at
scale, physics and engineering simulation, semiconductor and memory design,
autonomy, aerospace, climate and energy modelling, and constrained edge deployment.

**Where do I start?**
Describe where computation is limiting you, in non-confidential terms. That is
enough to begin a representation review.
