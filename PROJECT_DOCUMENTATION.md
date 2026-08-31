# JMS Delivery Hub - Project Documentation

## System Architecture

The system is a Django REST Framework backend with React frontend for managing software delivery projects at JMS Tech.

### Core Models
- **Project**: Central entity with name, client, timeline (start_date, weeks), team (M2M User), brief_summary, sow_pdf, and linked `architecture`.
- **ProjectArchitecture**: OneToOne with Project. Stores AI-generated structured architecture (JSON with overview, tech_stack, key_components, mermaid_diagrams, etc.), status (DRAFT/APPROVED/REJECTED), approval metadata.
- **Task**: Day-level tasks (day_num, date, week, developer, module, title, status).
- **ProjectDocument**, **Update**, **AdHocTask**, **BackgroundJob**.

### Two-Stage Gated AI Workflow (Key Feature)
1. **Architecture Generation** (`POST /api/projects/generate-architecture/`):
   - Takes SOW/FDD (PDF or text).
   - Uses `gpt-4o-mini` via Azure OpenAI to produce structured architecture document.
   - Returns draft for review.

2. **Architecture Approval** (`POST /api/projects/approve-architecture/`):
   - Admin reviews/edits, approves. Creates `ProjectArchitecture` record with `status=APPROVED`.

3. **Plan Generation** (`POST /api/projects/generate-plan/`):
   - **Blocked** until `architecture_id` (approved) is provided.
   - Planner functions now incorporate architecture context in prompts for aligned weekly/daily tasks.
   - Returns draft rows.

4. **Project Creation** (`POST /api/projects/`):
   - Requires approved `architecture_id`.
   - Creates Project, links architecture, bulk creates Tasks from rows, sends notifications.
   - Hard gate enforced in `create()` and `generate_plan()`.

### AI Planner (`ai/planner.py`)
- `generate_architecture()`: Detailed prompt for technical architecture, components, data flows, Mermaid diagrams, NFRs, risks.
- `extract_brief()`, `weekly_plan()`, `daily_tasks()`: Enhanced to consume architecture context from brief dict.
- Uses structured JSON output parsing with fallback.

### Services & Background
- `core/services.py`: `build_plan_rows()` now receives architecture-enriched brief.
- Reports (weekly, daily, Gantt, PDF via WeasyPrint/xhtml2pdf).
- `background.py` + `scheduler.py`: Celery-like job queue for notifications, AI tasks.
- Notifications via email/SMS using templates.

### Other Features
- Gantt chart (per-dev module segments).
- Ad-hoc tasks with attachments.
- Dashboard stats.
- Document upload with Azure blob URL resolution.
- Update history and real-time plan adjustment (preserves DONE tasks).

### Deployment
- Azure Web Apps, Azure Storage for blobs/PDFs.
- Azure OpenAI for AI features.
- SQLite for dev, scalable to Postgres.
- Requirements include pypdf, python-docx, openai, weasyprint (or xhtml2pdf).

**Backward Compatibility**: Existing projects without architecture are supported but new projects enforce the gate.

**Frontend Integration** (now complete):
- `NewProject` component implements phased flow: form → architecture generation/review/approval → plan generation/review → create.
- `generateArchitecture` / `approveArchitecture` / `generatePlan` (with `architecture_id`) calls.
- `ArchitectureView` renders structured content, tech stack tags, key components, Mermaid code blocks (copy to mermaid.live), NFRs, risks, etc.
- `ProjectDetail` adds conditional "Architecture" tab showing approved doc with approval metadata.
- Updated `api.js` with new endpoints.
- UI emphasizes the "two-stage gated" process with clear messaging.

See `ARCHITECTURE_APPROVAL_WORKFLOW.md` for process details.
