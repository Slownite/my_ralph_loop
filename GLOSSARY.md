# Ralf

Ralf coordinates unattended implementation of a project-owned queue while keeping readiness and integration decisions outside the coding agent.

## Language

**Issue**:
A bounded unit of requested project work with acceptance criteria and a workflow status.
_Avoid_: Task, job, ticket

**Issue Queue**:
The ordered collection of Issues available to Ralf within one project.
_Avoid_: Backlog, task list

**Target**:
The project line into which completed Issue work is integrated.
_Avoid_: Main, base

**Harness**:
An external coding agent that receives one Issue attempt and may edit the assigned project state.
_Avoid_: Model, provider, orchestrator

**Attempt**:
One bounded opportunity for a Harness to produce an implementation that passes Ralf's checks. Infrastructure failures do not count as Attempts.
_Avoid_: Iteration, run

**Guard**:
A safety rule that rejects an ineligible change regardless of verification results.
_Avoid_: Check, test

**Gate**:
The complete set of Guards and project verification commands that determines whether implementation work is Ready.
_Avoid_: Test suite, agent verification

**Pending**:
An Issue available to begin.

**In Progress**:
An Issue with active or preserved implementation work that has not passed the Gate.
_Avoid_: Running

**Ready**:
An Issue whose implementation passed the Gate but has not been integrated into the Target.
_Avoid_: Done, complete

**Done**:
An Issue whose implementation was integrated into the Target successfully.
_Avoid_: Ready

**Blocked**:
An Issue that cannot proceed automatically and requires a deliberate retry or human intervention.
_Avoid_: Failed
