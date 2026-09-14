# Vision

## The problem

Hard-won research judgment tends to stay where it was built. Someone works out how to
research a question properly — how to pick sources, what a weak citation looks like, when
a single dissenting paper matters more than four agreeing blog posts, what to do when the
evidence is thin — and that judgment ends up encoded in one harness, reachable only from
inside it, and only with the right context loaded.

That is what happened here. This judgment currently lives in an Amplifier bundle. It is
real and it works, and it is unreachable from a CI job, a Python service, a shell script,
Copilot, or Claude Code. The expertise is fine. Its packaging is the problem.

## Who this is for

Anyone who needs evidence and does not want to become a researcher to get it:

- **An agent** that needs to know something before it can act, and cannot afford to load
  a domain's worth of context and run the search itself.
- **Code** — a service, a scheduled job, a CI step — that wants a structured result it
  can branch on, with no model involved on its side at all.
- **A person** at a terminal who wants an answer and the sources behind it.

The caller states an intent. It does not learn how research works. That is the whole
idea.

## Why two tools

**`deep-research`** answers "what is known about X?". **`fact-check`** answers "is this
claim true?".

These look adjacent and are not. Research starts from a question and converges on a
synthesis; fact-checking starts from claims, fans out over them independently, and
converges on a verdict per claim. Different inputs, different shape of work, different
answer. The Amplifier bundle they come from already had them as two separate workflows —
the boundary was drawn by whoever built it, and we are reading it rather than inventing
it.

They share everything that is not the workflow: the evidence store, the source format,
the result shape. One library, two tools.

## What good looks like

- A caller with no research expertise gets an answer it can act on, and can see what the
  answer rests on.
- A caller that never touches a smart capability never needs credentials for anything.
- An answer too large to hold is still usable, because the caller can navigate it instead
  of swallowing it.
- An expensive answer is paid for once. Reshaping it, filtering it, or citing it later
  costs nothing.
- Evidence accumulates. A question answered last week is available to whoever asks
  something adjacent this week.
- Nothing is claimed that is not shown. A partial view says it is partial; an
  unverifiable claim is reported as unverifiable and not as refuted; a run that failed
  says where.

## What this is not

- **Not a search engine.** It answers questions with evidence; it does not index the web.
- **Not a citation manager.** It produces bibliographies; it does not maintain a library.
- **Not an oracle.** It reports what the evidence supports, including when the evidence
  disagrees with itself or runs out. Confidence is stated, never implied.
- **Not a wrapper around one vendor.** Where the evidence comes from is an implementation
  detail and is expected to change.

## The constraints that shape everything

Three, and they are not negotiable:

1. **The deterministic paths run with no AI provider configured.** A caller who only
   wants to read, filter, or reshape an existing result needs no credentials of any kind.
   Not a nice-to-have — a verified property with a test attached.
2. **It is callable from anywhere.** An ordinary library, installed from git, with a thin
   CLI over the top. Every other surface is an optional adapter over the same library,
   and no capability exists only in a wrapper.
3. **The expertise stays inside the tool.** The caller sends an intent and receives a
   result. It does not send a methodology, and it does not have to know one.

## The bet

That the useful unit is not "a model that can search" but **a durable, addressable piece
of evidence** — something that outlives the call that produced it, that several callers
can share, and that costs nothing to consult again. If that is right, the research run
stops being a transaction and becomes an asset.

See `docs/ARCHITECTURE.md` for how this is built, and `tools/*/contracts/cli.v1.md` for
what callers may rely on.
