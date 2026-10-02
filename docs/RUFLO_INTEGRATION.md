# Ruflo Integration

## Status

Ruflo is the next external integration for Night Files. The first stage is deliberately lightweight.

The production generator and publisher remain the source of execution truth. Ruflo is not installed or started by the normal GitHub Actions production run.

## Why

Ruflo provides agent orchestration around Claude Code/Codex, including agents, swarms, memory, hooks, and workflows. Night Files can use those ideas to coordinate research, story writing, visual planning, QA, and packaging.

The first Night Files implementation therefore records the orchestration contract without introducing another required runtime.

## Current integration

- `pipeline/ruflo_plan.json` describes the canonical Night Files stages and role ownership.
- `pipeline/ruflo_check.py` validates the plan and prints the delegation graph.
- No existing production Python stage imports Ruflo.
- No new secret is required.
- No Anthropic API key is added to GitHub Actions for Ruflo.
- No Ruflo daemon or swarm is started by production.
- Existing publishing behavior is unchanged.

## Future activation path

1. Use the manifest with Claude Code/Ruflo during non-production development tasks.
2. Add selected agents for research, story review, visual review, or packaging review.
3. Persist only useful patterns/memory that Night Files can safely reuse.
4. Keep production tasks deterministic until Ruflo has been separately validated.
5. Only then consider optional delegation of a specific stage.

## Role contract

### Planner
Maps a task into existing Night Files stages and dependencies. It does not rewrite the production architecture.

### Researcher
Finds source material and verifies claims. For true stories, evidence must remain traceable to the existing research/source system.

### Writer
Produces or revises the story while respecting the existing hook, fact-lock, tone, and duration rules.

### Visual planner
Maps narration to shots, characters, locations, and continuity constraints. It must not weaken the visual QA rules.

### QA reviewer
Reviews the rendered output and diagnostic signals. QA remains report-only in the current production design.

### Packaging reviewer
Reviews captions, titles, hashtags, pinned comments, and platform metadata without changing the actual posting transport.

## Safety boundary

Do not copy Ruflo's full runtime, MCP server, plugin tree, or agent database into Night Files.

Do not make production depend on an external agent swarm.

Do not add Ruflo credentials to the repository.

Do not let an orchestration failure discard a generated video.

## Validation

Run:

```bash
python pipeline/ruflo_check.py
```

Expected:

```
RUFLO CHECK: PASS
```

Official project:
https://github.com/ruvnet/ruflo


## Task contract implementation, 2026-10-02

The first practical Ruflo layer has now been implemented as **local task contracts**, while Ruflo itself remains optional and is not installed or executed by production.

### Added files

- `docs/ruflo_tasks/planner.md`: decomposes Night Files work into the existing pipeline stages without replacing the pipeline.
- `docs/ruflo_tasks/researcher.md`: defines source-backed research, evidence tracing, and fact/folklore/speculation separation.
- `docs/ruflo_tasks/story_writer.md`: defines story drafting/revision while preserving hook, fact-lock, duration, fiction, and channel rules.
- `docs/ruflo_tasks/visual_planner.md`: defines narration-to-shot planning, story-bible continuity, visual specificity, and existing visual safety rules.
- `docs/ruflo_tasks/qa_reviewer.md`: defines diagnostic review and failure reporting without silently overriding quality gates.
- `docs/ruflo_tasks/packaging_reviewer.md`: defines title/caption/hashtag/pinned-comment/platform metadata review while leaving transport to the existing publisher.
- `pipeline/ruflo_task_check.py`: dependency-free contract validator.

### Validator behavior

The validator checks that every required role contract exists, contains the five required sections (Purpose, Inputs, Outputs, Responsibilities, Constraints), and corresponds to a role declared by `pipeline/ruflo_plan.json`.

It prints:

```
RUFLO TASK CHECK: PASS
Production execution: unchanged
Ruflo runtime required: no
Agent/swarm execution: disabled
```

The validator does not import Ruflo and does not perform network operations, agent execution, swarm execution, MCP startup, or publishing.

### Current activation state

Ruflo is **documented and contract-ready, but not production-active**. The real Night Files Python pipeline remains the execution source of truth. The task contracts are deliberately reusable definitions that can later be consumed by Ruflo/Claude Code for non-production work.

The implementation does not add a secret, API key, daemon, service, model, or new production dependency.

### Production boundary

No change was made to the production publisher, TikTok authentication, YouTube authentication, buffer semantics, render path, or daily workflow. An orchestration failure cannot currently discard a generated video because Ruflo is not in the production execution path.

### Verification performed

The repository now has both validators:

- `python pipeline/ruflo_check.py` validates the stage/dependency manifest.
- `python pipeline/ruflo_task_check.py` validates the role contracts.

Both must pass before the next Ruflo activation stage is considered complete.

### Next implementation stage

After these contracts are validated, the next step is **non-production Ruflo execution against one isolated task**, preferably research or review. That stage should produce an artifact for comparison with the existing Night Files output before any production delegation is considered.
