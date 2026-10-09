import sys

file_path = r'c:\Users\Admin\Downloads\jms-delivery-hub\jms-delivery-hub\backend\core\services.py'

append_code = """
def auto_process_document(project, text, user):
    \"\"\"
    Intelligently create MOMs, milestones, or ad-hoc tasks based on uploaded document text.
    Uses AI to analyze the text and extract actionable items.
    \"\"\"
    from ai import planner
    from .models import MeetingMinutes, ProjectMilestone, AdHocTask
    from django.utils import timezone
    import json

    prompt = (
        "Analyze the following document text and extract any meetings, milestones, or ad-hoc tasks. "
        "Respond ONLY in JSON format, like this:\\n"
        "{\\n"
        '  "moms": [{"title": "Kickoff", "meeting_date": "2026-10-01", "decisions": "...", "action_items": "..."}],\\n'
        '  "milestones": [{"title": "Phase 1 completion", "status": "ON_TRACK", "committed_date": "2026-11-01"}],\\n'
        '  "tasks": [{"title": "Setup server", "description": "AWS EC2 instance"}]\\n'
        "}\\n\\n"
        "If there are none, return empty lists. Text:\\n"
        f"{text[:10000]}"
    )
    
    actions = []
    try:
        result_text = planner._ask(prompt, max_tokens=1500)
        data = planner._parse_json(result_text)
        
        if "moms" in data and isinstance(data["moms"], list):
            for m_data in data["moms"]:
                date_str = m_data.get("meeting_date")
                if date_str:
                    try:
                        from django.utils.dateparse import parse_date
                        date_val = parse_date(date_str)
                    except:
                        date_val = timezone.localdate()
                else:
                    date_val = timezone.localdate()
                    
                mom = MeetingMinutes.objects.create(
                    project=project,
                    title=m_data.get("title", "Document Extracted MOM")[:255],
                    meeting_date=date_val or timezone.localdate(),
                    meeting_time="10:00:00",
                    decisions=m_data.get("decisions", ""),
                    action_items=m_data.get("action_items", ""),
                    created_by=user
                )
                actions.append(f"Created MOM: {mom.title}")
                
        if "milestones" in data and isinstance(data["milestones"], list):
            for m_data in data["milestones"]:
                date_str = m_data.get("committed_date")
                try:
                    from django.utils.dateparse import parse_date
                    date_val = parse_date(date_str) if date_str else None
                except:
                    date_val = None
                    
                milestone = ProjectMilestone.objects.create(
                    project=project,
                    title=m_data.get("title", "Extracted Milestone")[:255],
                    status=m_data.get("status", "ON_TRACK") if m_data.get("status") in ["COMPLETED", "ON_TRACK", "AT_RISK", "DELAYED"] else "ON_TRACK",
                    committed_date=date_val,
                    owner=user.get_full_name()
                )
                actions.append(f"Created Milestone: {milestone.title}")
                
        if "tasks" in data and isinstance(data["tasks"], list):
            for t_data in data["tasks"]:
                task = AdHocTask.objects.create(
                    title=t_data.get("title", "Extracted Task")[:255],
                    description=t_data.get("description", ""),
                    created_by=user,
                    status="TODO"
                )
                task.assignees.add(user)
                actions.append(f"Created Ad-hoc Task: {task.title}")
                
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Failed to auto-process document text: {e}")
        
    return {"actions": actions}
"""

with open(file_path, 'a', encoding='utf-8') as f:
    f.write(append_code)

print('Success')
