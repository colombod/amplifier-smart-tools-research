# Should evidence acquisition and reasoning share one abstraction?

**Status:** decided, with the smaller change adopted and the larger one declined.
**Written against:** `research_core.backends.base.ResearchBackend`,
`research_core.reasoning.Reasoner`, and the two live implementations behind each.

---

## The question

We have two seams that look nearly identical at arm's length.

```python
class ResearchBackend(Protocol):
    name: str

    def preflight(self) -> str: ...
    def gather(self, query: str, budget: Budget) -> Evidence: ...


class Reasoner(Protocol):
    name: str

    def preflight(self) -> str: ...
    def think(self, prompt: str, *, on_event=None) -> Thought: ...
```

Both take an intent, go away and do work nobody supervises, and come back with a result
and an account of what it cost. That is the smart-tool definition applied one level down.
The obvious move is to collapse them into one `Agent` abstraction with a capability
declaration — `can_search: bool` — and several implementations behind it.

There is already evidence the split leaks. `deep_research.research._gather` inspects each
backend's signature at runtime to decide which extras it accepts:

```python
parameters = inspect.signature(engine.gather).parameters
if "scope" in parameters:
    extra["scope"] = ...
if "on_event" in parameters:
    extra["on_event"] = on_event
```

That is a special case wearing a polite hat, and its existence is a fair argument that the
abstraction is wrong.

## The recommendation

**Do not unify the two protocols. Do unify the machinery underneath them, and delete the
special case.**

Concretely, three changes, in order of confidence:

1. **Widen `ResearchBackend.gather` to `gather(query, budget, *, scope="", on_event=None)`
   for every implementation**, and delete the `inspect.signature` hack. An implementation
   that has no use for `scope` ignores the argument. This is the change the leak was
   actually pointing at: the problem was never that there are two protocols, it was that
   one of them had two different signatures.
2. **Name the shared machinery and keep it in one place.** `research_core.engine.run_turn`
   is already this: preflight, provider selection, budget, mount-plan control, usage
   accounting, progress plumbing. Both `AgentBackend` and `AgentReasoner` call it and
   differ by exactly one argument — `tools=WEB_TOOLS` versus `tools=()`. That is the
   unification worth having, and we already have it.
3. **Write the invariant down in the protocols themselves**, because it is the reason for
   the split and nothing currently says so out loud.

## Why not unify: the distinction is authority, not shape

The two seams do not differ in shape. They differ in **what they are permitted to
introduce into a run.**

- A **backend is authorised to bring new evidence into the run.** Its return type carries
  `sources`, and everything downstream — id assignment, categorisation, the sources file —
  exists to record what it brought.
- A **reasoner is authorised only to reason over evidence already recorded.** Its return
  type carries no sources, and `AgentReasoner` mounts **no tools at all**, deliberately.

That is not an implementation detail. It is the premise the citation check rests on: every
marker in a synthesis must resolve to a source id the run already has, and a synthesis that
cites `s9` when the run defines `s1`–`s3` is rejected and repaired. The check is only
meaningful because the synthesising turn **cannot** have found `s9` itself.

Unify the protocols and the merged result type needs an optional `sources` field —
populated by a searching implementation, empty for a reasoning one. "Optional sources on
the reasoning result" is precisely the shape through which a synthesis quietly introduces a
citation nobody gathered. The type system currently makes that unrepresentable. A unified
`Agent` with `can_search: bool` makes it a configuration mistake, and configuration
mistakes are the ones that ship.

## What a merged abstraction would have to hide, and must not

| | Perplexity backend | Agent backend / reasoner |
|---|---|---|
| **Who owns the search loop** | the service does; we hand over a question and see no steps | we do; we choose the mounted tools and see each call |
| **Is cost reportable?** | **no** — measured: `cost_usd` came back `null` on live runs, the service does not tell us | **yes** — measured: `$0.041082` for a live run, real token accounting |
| **Turn-level control** | `depth` maps to a step ceiling, and that is the whole lever | mounted tools, per-turn timeout, approval policy, filtered mount plan |
| **Progress during the call** | none; one blocking request | tool events mid-turn, in principle |
| **What it may introduce** | new sources | nothing — reasons over what it is given |

A single abstraction would have to express all five as optional capabilities. At that point
the abstraction is a union of two things with a flag for each difference, which is a longer
way of writing two types.

The first two rows are the ones that would hurt most if hidden. A caller that cannot tell
whether `cost_usd: null` means *free* or *unreported* has been misled about its own
spending — and our answer to that today is that `null` means unreported, said out loud,
which only works because the tool knows which implementation ran.

## The strongest argument against this recommendation

**Two protocols make a third implementation homeless.** Something that both searches *and*
reasons — a local RAG service, a competitor's research API with a synthesis endpoint, a
future Perplexity that exposes its steps — has to pick a side or be split unnaturally
across both. If that arrives, we will wish we had one seam with capabilities.

Two further points on the same side, both fair:

- **The leak is real.** `inspect.signature` in a hot path is a bad smell, and I am treating
  it as a signature bug rather than as evidence about the abstraction. A reader could
  reasonably read it the other way.
- **Two near-identical protocols invite a well-meaning cleanup.** The next person sees
  `preflight` twice and merges them, and the invariant dies quietly because nothing in the
  code says why they were apart. This is a real maintenance risk and the reason change (3)
  above is not optional.

**Why I am not persuaded:** the homeless-third-implementation problem is *hypothetical* and
the citation invariant is *load-bearing today*. A thing that searches and reasons can
implement both protocols — nothing forbids one class satisfying two `Protocol`s — so the
cost of being wrong here is smaller than it first appears.

## What adoption costs, and how reversible it is

**Adoption:** small. Widen one signature across two implementations, delete about eight
lines of `inspect` code, add docstring paragraphs naming the invariant. Under an hour, no
behaviour change, existing tests cover it.

**Reversal — and this asymmetry is the strongest single argument for the decision:**

- **Split now, unify later:** a mechanical merge. Two protocols with a shared machinery
  layer already underneath them collapse cleanly whenever a genuine both-at-once
  implementation arrives.
- **Unify now, split later:** not mechanical. Once a result type carries optional
  `sources`, code starts reading it on the reasoning path, and re-establishing "a reasoner
  cannot introduce a source" means auditing every caller rather than changing one type.

Reversibility runs in one direction. Take the reversible option.

## Demonstration: both implementations, no special case

With change (1), every implementation satisfies one signature and the caller stops
adapting:

```python
class PerplexityBackend:
    name = "perplexity"
    def preflight(self) -> str: ...
    def gather(self, query, budget, *, scope="", on_event=None) -> Evidence:
        # Ignores scope: the service takes a question and owns its own loop.
        # Ignores on_event: one blocking request, nothing to report mid-flight.
        # Both are honest no-ops, not stubs -- there is nothing to pass on.

class AgentBackend:
    name = "agent"
    def preflight(self) -> str: ...
    def gather(self, query, budget, *, scope="", on_event=None) -> Evidence:
        # Uses both: scope sharpens the prompt, on_event forwards tool progress.
        return parse_agent_reply(run_turn(prompt, tools=WEB_TOOLS, on_event=on_event, ...))
```

```python
# the caller, afterwards
evidence = engine.gather(sharpened, budget, scope=scope_text, on_event=progress)
```

And the shared machinery, which is where the real unification already lives:

```python
run_turn(prompt, tools=WEB_TOOLS, ...)   # AgentBackend  — may introduce sources
run_turn(prompt, tools=(), ...)          # AgentReasoner — may not
```

One argument apart. That single argument is the authority boundary, and keeping it as an
argument to shared machinery — rather than as a capability flag on a merged public type —
is the whole of this note's recommendation.

## What this says to the specification

Relevant to ROADMAP #2 (how intelligence gets integrated) and #4 (an AI provider interface).

The useful finding is not the protocol shape. It is that **a smart tool integrating more
than one kind of intelligence will find that the interesting differences are about
authority rather than interface** — what an implementation is permitted to introduce into
the caller's world, not what arguments it takes. An interface specification that describes
only the call shape will produce tools that compile and lie.

Our second finding is narrower and concrete: **cost is not uniformly reportable.** One of
our two implementations cannot tell us what a call cost. Any provider interface should make
"unknown" a first-class value rather than letting `0.00` stand in for it, and should let a
caller discover which it is dealing with before spending.
