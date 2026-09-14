# What is known about state-based CRDT convergence and adoption?

## 1. Convergence

State-based CRDTs converge when replicas form a join-semilattice and every update is
monotonic with respect to that lattice's partial order [s1]. Convergence under those
conditions is proved, not merely observed [s1]. The proof requires only that merges are
associative, commutative and idempotent; it does not require any ordering of message
delivery [s1].

Delta-state CRDTs transmit only the parts of the state that changed, which reduces message
size relative to shipping the full state on every update [s2]. The convergence guarantee is
unchanged by that optimisation [s2].

## 2. Adoption

Redis offers active-active geo-distribution built on conflict-free replicated data types
[s3]. Several teams have adopted CRDTs for collaborative editing [s4]. The most common
complaint reported by adopters is memory overhead [s4].

## 3. What the evidence does not establish

None of the sources here gives a date for when CRDTs were first described, names a specific
company's production deployment, compares CRDTs against operational transformation on any
measured axis, or addresses whether CRDTs are suitable for financial ledgers.
