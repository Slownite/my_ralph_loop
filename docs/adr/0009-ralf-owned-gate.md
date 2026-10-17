# Ralf owns an independent gate

Only Ralf's own guard and verification gate authorizes Ready and Done. A Harness may run commands for feedback, but its prose and exit status never decide the outcome. Ralf reruns the protected-path and test-deletion Guards after verification, because a formatter or checker may mutate the tree, and commits exactly the tree that passed.

This supersedes the earlier split-gate decision and makes it stricter: the gate is executed by Ralf outside the Harness, through the same process boundary, with verification networking disabled by default.
