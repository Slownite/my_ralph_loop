# Fail closed at the Bubblewrap boundary

Agent and verification processes run in Bubblewrap on Linux with only the access each operation requires, and Ralf fails closed when isolation cannot start unless the user explicitly selects a loud per-run bypass. This limits accidental filesystem and process access, but it does not claim to prevent a networked Harness from transmitting source that the Harness must be able to read.
