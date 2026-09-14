State-based CRDTs guarantee strong eventual consistency, not linearizability: any two
replicas that have received the same set of updates are in the same state, regardless of
order or duplication [s1][s2]. The guarantee holds only while the merge operation really
is a join on a semilattice, and the literature is unanimous that the property is easy to
state and easy to violate in implementation [s3][s4].

One dissent worth carrying: Kleppmann argues the guarantee is routinely overstated in
practice, because real systems apply application-level validation after merge, which is
not itself commutative [s5].
