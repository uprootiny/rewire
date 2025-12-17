# Contributing to Rewire

Thank you for considering contributing to Rewire.

## Ways to Contribute

### Bug Reports
Open an issue with:
- What you expected to happen
- What actually happened
- Steps to reproduce
- Your environment (Python version, OS)

### Feature Requests
Open an issue describing:
- The problem you're trying to solve
- Your proposed solution
- Why existing features don't solve it

### Code Contributions
1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Make your changes
4. Run tests (`PYTHONPATH=. python3 -m unittest discover -s tests -v`)
5. Run invariant checker (`python3 -m rewire.invariants --db test.db`)
6. Commit with clear messages
7. Open a pull request

## Code Standards

### Python
- Type hints required for all functions
- Docstrings for public functions
- Tests for new functionality
- Run `ruff check` before committing

### Clojure
- Specs for public functions where applicable
- Tests in `test/` directory

### Invariants
If you modify rule evaluation logic:
- Update `specs/rewire.qnt` if invariants change
- Ensure `rewire.invariants` still passes
- Add test cases for edge conditions

## Epistemic Contract
Rewire's core principle: **claim only what evidence supports**.

When adding features:
- Violations must include evidence
- No false positives from heuristics
- Document what the feature claims and refuses to claim

## Questions?
Open an issue or discussion on GitHub.
