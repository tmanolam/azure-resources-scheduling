"""Core reconciliation engine for the Azure Resource Power Scheduler.

Phase 0 provides the package skeleton only. Modules are implemented in later
phases per docs/PHASE1_TASKS.md:

- evaluator  (T-101): pure desired-state evaluation
- discovery  (T-201): Azure Resource Graph discovery with paging
- selection  (T-202): tag resolution, scope filtering, production exclusion
- ordering   (T-203): action ordering and safety controls
- reconcile  (T-204): desired-vs-actual reconciliation orchestrator
"""
