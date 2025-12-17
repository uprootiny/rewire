# Provenance

## What I (the human) did

- Provided the initial specification and design constraints
- Requested implementation in both Python and Clojure
- Reviewed generated code structure
- Decided on project direction

## What LLMs helped with

- Claude Code (Opus 4.5) generated the full implementation from the specification
- Code structure, module organization, and test design were LLM-generated
- This README and documentation were LLM-assisted

## What remains uncertain

- Edge cases in rule evaluation logic (especially overlap detection)
- Thread safety of SQLite operations under concurrent load
- Whether the Clojure notify.clj actually compiles (depends on javax.mail availability)
- Performance characteristics with large observation histories
- Whether all violation codes close correctly after recovery

## Maintenance expectations

**Experimental / Dormant**

This is a single-session extraction. I may use it, fork it, or abandon it. No commitment to maintenance, support, or further development.
