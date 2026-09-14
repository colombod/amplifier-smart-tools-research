# What is known about the performance cost of CRDTs?

## 1. The sources disagree, substantially

Two peer-reviewed measurements of the same property report different results. [s1] measures
roughly 3x memory overhead versus a last-write-wins register. [s2] measures under 1.2x, and
explicitly attributes the higher earlier figures to an unoptimised encoding rather than to
anything inherent in the data type.

These are not compatible readings of one number. [s2] is the later paper and offers an
explanation for the discrepancy; [s1] does not address encoding choice at all. Neither has
been independently replicated in the material gathered here.

## 2. One production account, not a measurement

[s3] is a single team's engineering blog describing reverting a CRDT-based feature after
memory growth in production. It reports no figures and does not say which CRDT or encoding
was used. It is an experience report, not a measurement, and one team's outcome.

## 3. Sources present but uninformative on this question

[s4] documents that Redis offers active-active geo-distribution built on CRDTs. It says
nothing about performance cost. [s5] is a newsletter mentioning CRDTs among other topics
and carries no measurements at all.

## 4. What the evidence does not establish

Nothing here gives a figure for CPU cost, network bandwidth, or latency. Nothing addresses
delta-state encodings specifically. No source states a general overhead figure that holds
across implementations.
