# Project Constitution: Scrapy Distributed Crawler

## Core Principles

### I. Specification First

Every implementation decision must trace back to a documented requirement, assumption, or clarification in `specs/`.

### II. Operational Safety

The crawler must include explicit rate limits, host-level controls, retry bounds, blacklisting, and observability before scale-out.

### III. Data Durability

HTML persistence, metadata delivery, and downstream parse task publication must define failure behavior and replay semantics before implementation.

### IV. Incremental Delivery

The system must be delivered in independently verifiable phases: single-node PoC, distributed crawl path, storage path, analytics path, and automated deployment.

### V. Measurable Acceptance

Performance, cost, reliability, and operational goals must be expressed as measurable criteria with validation steps.

## Governance

- Requirements marked `NEEDS CLARIFICATION` block detailed planning.
- Technical plans must document simpler alternatives considered and rejected.
- Tasks must include exact file paths once implementation begins.
- Production scale-out must not proceed until the PoC acceptance criteria are met.

