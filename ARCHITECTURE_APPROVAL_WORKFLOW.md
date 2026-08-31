# Architecture Approval Workflow (Two-Stage Gated Process)

## Overview
To ensure technical soundness before committing to detailed delivery plans, all new projects must go through an **AI-generated Architecture Document** that is **explicitly approved** by an admin before a detailed weekly plan can be generated or project created.

This implements the "generate AI Architecture Document from SOW/FDD *before* detailed project plan" requirement.

## Process Steps

1. **Upload SOW/FDD & Generate Architecture**
   - Endpoint: `POST /api/projects/generate-architecture/`
   - Payload: `name`, `team`, `sow_pdf` or `doc_text`
   - AI (`generate_architecture()` in `ai/planner.py` using gpt-4o-mini):
     - Produces structured JSON: overview, tech_stack, key_components, data_flow, mermaid_diagrams (architecture + sequence), non_functional, risks_assumptions, implementation_approach.
   - Frontend shows the draft (with Mermaid render for diagrams) for review.

2. **Review & Approve/Reject**
   - Admin reviews the architecture document.
   - Can add notes, edit content if needed.
   - Endpoint: `POST /api/projects/approve-architecture/`
     - Saves `ProjectArchitecture` record with `status=APPROVED`, `approved_by`, `approved_at`.
     - Returns `id` to use in next steps.
   - If rejected, can regenerate with updated SOW.

3. **Generate Detailed Plan (Gated)**
   - Endpoint: `POST /api/projects/generate-plan/`
   - **Requires** `architecture_id` (must be APPROVED).
   - `generate_plan()` in views validates the architecture exists and is approved.
   - Planner receives architecture context in `brief["architecture"]` → prompts in `weekly_plan()` and `daily_tasks()` explicitly reference the approved tech, components, approach to ensure alignment.
   - Returns draft `{brief, rows}`.

4. **Create Project**
   - `POST /api/projects/`
   - Requires `architecture_id`, `rows` (from step 3, possibly edited), `brief`.
   - Creates `Project`, links the `ProjectArchitecture` (OneToOne), bulk_creates `Task`s.
   - Sets initial status, creates kickoff `Update`, triggers notifications.
   - Architecture is now permanently associated with the project (accessible via `project.architecture`).

## Enforcement
- **Hard gates** in `ProjectViewSet.create()` and `generate_plan()`.
- `ProjectSerializer` includes full `architecture` nested serializer.
- `ProjectArchitecture` model tracks version, status, approval audit trail.
- Update/replan flows can reference existing architecture.

## Benefits
- Ensures architectural thinking happens *before* tactical task breakdown.
- AI architecture provides consistent technical baseline (diagrams, NFRs, risks).
- Audit trail for approvals.
- Reduces risk of misaligned delivery plans.
- Reusable for future SOW changes (regenerate architecture).

## Frontend Integration Notes
- New UI flow: SOW upload → Architecture Review screen (with approve button) → Plan confirmation.
- Display Mermaid diagrams from `content.mermaid_diagrams`.
- Show approval status on project cards.

## Future Enhancements
- Versioning of architecture docs.
- AI review/feedback on proposed changes vs architecture.
- Auto-generate initial Mermaid from SOW.
- Integration with requirements traceability.

**Implemented in:** models.py, ai/planner.py, core/services.py, core/views.py, core/serializers.py, migrations.

This completes the two-stage gated workflow.
