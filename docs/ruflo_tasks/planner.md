# Ruflo Task Contract: Planner

## Purpose
Decompose a Night Files task into the existing pipeline stages without replacing production architecture.

## Inputs
- `pipeline/ruflo_plan.json`
- Existing Night Files pipeline stage names
- Current task objective

## Outputs
- A proposed delegation sequence using existing stage IDs
- Dependencies between proposed tasks
- A list of stages that should remain deterministic

## Responsibilities
- Use the existing Night Files pipeline as the source of truth.
- Identify which role should handle each requested task.
- Preserve stage dependencies.
- Keep production execution owned by the existing Python pipeline.
- Flag work that requires human review.

## Constraints
- Never invent a replacement pipeline.
- Never activate a Ruflo swarm.
- Never modify production configuration.
- Never bypass QA, fact locks, or publishing safeguards.
