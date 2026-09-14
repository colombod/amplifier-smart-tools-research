# Claims about state-based CRDTs

## 1. Supported

Convergence regardless of arrival order follows directly from the algebraic
properties of merge [s1][s2].

## 2. Refuted

Convergence is agreement, not correctness [s2][s5]. This is the claim most often
repeated and it does not hold.

## 3. Unverifiable

Whether most production implementations validate outside the lattice is checked and
not established: one source argues it from individual cases, none surveys the field
[s5]. Unverifiable is not refuted.
