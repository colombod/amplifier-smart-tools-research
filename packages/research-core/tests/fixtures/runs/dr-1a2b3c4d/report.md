# What convergence guarantees do state-based CRDTs actually provide?

## 1. Scope of the question

The question asks what state-based CRDTs guarantee, not what they are advertised to
guarantee. Those differ, and the gap is where most of the useful evidence sits.

Three sub-questions were worth separating: what the formal result says [s1][s2], what
the result requires of an implementation, and what is observed when those requirements
are not met [s3].

## 2. What the formal result says

A state-based CRDT is a join-semilattice with a merge operation that is associative,
commutative and idempotent. Given those three properties, replicas that have received
the same set of updates converge to the same state, in any order, with any number of
duplicates [s1].

This is strong eventual consistency. It is strictly weaker than linearizability and it
says nothing about the state being one a user would call correct -- only that every
replica agrees on it [s2].

The original presentation is careful about this distinction; secondary material
frequently is not [s4].

## 3. What it requires of an implementation

The guarantee is conditional on merge genuinely being a join. Three ways that is lost
in practice appear repeatedly in the sources:

Merge that reads the clock. A merge consulting wall time is not idempotent, because
re-merging the same state later produces a different result [s3].

Merge that is not total. A merge that rejects some pairs of states leaves replicas that
cannot converge at all, and the failure is silent until the two replicas meet [s3][s5].

Validation applied after merge. Application-level checks that run on the merged value
are not part of the lattice, and are typically not commutative [s5].

## 4. Where the evidence disagrees

The academic sources treat the guarantee as settled and the implementation burden as an
engineering matter [s1][s2]. The practitioner sources treat the implementation burden as
the whole problem [s5][s6].

Kleppmann is the sharpest dissent: the guarantee is real but routinely overstated,
because systems described as CRDT-based have validation and garbage collection outside
the lattice, and neither preserves the properties the proof depends on [s5].

No source contradicts the formal result. The disagreement is entirely about how much of
a real system the result actually covers.

## 5. What would settle the remaining uncertainty

Two things this run could not establish:

How often the failure modes above occur in deployed systems. No source surveys
implementations; the practitioner claims are drawn from individual cases [s5][s6].

Whether the post-merge validation problem has a principled fix, or is inherent. It is
named in the dissent but not resolved there [s5].
