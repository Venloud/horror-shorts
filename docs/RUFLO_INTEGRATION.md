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


## Ruflo implementation ledger, 2026-10-02

This section is cumulative. Every Ruflo-related commit made so far is recorded here so the repository remains self-documenting and the next implementation can start from a known state.

### Commits completed

1. `55dba71653467bce61c0e72867f5d189e2977548` - Add concrete Ruflo first-stage integration design. Established the first-stage architecture and explicitly kept Ruflo outside production.
2. `157a9875aa0945d0dfe8fc0fcaaeaa5ff3a6cbb9` - Document Ruflo integration plan and safety constraints. Recorded the activation sequence, production boundary, and safety rules.
3. `767242e1f811885ee513a7a3c2ea4359f6527e64` - Add Ruflo integration `pipeline/ruflo_plan.json`. Added the declarative stage/dependency/role map for research through publishing.
4. `9ff04cfce6cc7338525bc0efa49131fd6850f1b6` - Add Ruflo integration `pipeline/ruflo_check.py`. Added the zero-dependency manifest validator and delegation-graph check.
5. `a24cd4f27bc0789dd14b83850bf6ffd79561a93f` - Add Ruflo integration docs. Added the dedicated integration reference and activation boundaries.
6. `4879e18f0a60cdebcdddd1c3b4c1f7fa2cf74481` - Add planner task contract. Defined how Ruflo planning maps onto existing Night Files stages without replacing them.
7. `01cd3726fe82ff8de6663e3777f897daec2cb6bf` - Add researcher task contract. Defined source-backed research, evidence tracing, and folklore/speculation separation.
8. `9f3bda761e04662b2ddee12e5e58277612fdc55f` - Add story-writer task contract. Defined narration generation/revision under fact-lock, hook, duration, and fiction rules.
9. `a2b1bd4bb8775f97dd39c6725fb8fdaf8c8416b3` - Add visual-planner task contract. Defined shot planning, continuity, and visual safety requirements.
10. `f4099b098e1f32e8ea85af0f30a8114caa8ff01e` - Add QA-reviewer task contract. Defined diagnostic review and failure reporting without bypassing gates.
11. `4d05bc1c3d7efdb8ba362ade2e075125bd50af3f` - Add packaging-reviewer task contract. Defined metadata review while leaving TikTok/YouTube transport untouched.
12. `b7c6a6d9c8cf2737f7fcdc23c0244631cd561210` - Add Ruflo task-contract validator. Added `pipeline/ruflo_task_check.py` to verify all six contracts and their required sections.
13. `e4b61ac216553a1ce0501b16e5274db587aeb216` - Document implemented Ruflo task contracts. Expanded `docs/RUFLO_INTEGRATION.md` with exact files, validator behavior, and current activation state.
14. `0242173df1e81a52e07640c8716a8bce501f7f9b` - Record implemented Ruflo task contracts. Added the cumulative implementation update to `NIGHT_FILES_UPDATE.md`.
15. `6f6d428eb5396b1a1fac34ea2ee53f38262353eb` - Mark Ruflo contract layer implemented. Updated `CLAUDE.md` so future sessions treat the contract layer as implemented, production-disabled.

### Validation state before the next implementation

The repository state has been statically checked from the current GitHub files. The manifest and task-contract definitions are internally consistent. The validators are dependency-free and are designed not to start agents, swarms, MCP, daemons, or publishing.

### Ready state

**Current Ruflo state: contract-ready, production-disabled.**

**Next implementation:** isolated non-production Ruflo execution of exactly one task, with captured output and comparison against the existing Night Files result. Do not connect that execution to `daily.yml`, publishing, TikTok auth, YouTube auth, or the production buffer yet.

The next implementation is considered ready only if it preserves these properties:
- no new production secret unless a verified runtime requirement is discovered;
- no production workflow dependency;
- no automatic publishing;
- no bypass of research, fact-lock, visual QA, duration QA, or packaging safeguards;
- clear artifact/output location for comparison;
- failure of Ruflo remains non-fatal to production.
