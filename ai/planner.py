"""
AI planning service — turns a SOW/FDD into a day-wise, developer-wise plan
(the same structure as JMS Tech's delivery sheets: D1..Dn, one task per
developer per working day, module-tagged, weekends excluded).
"""
import base64
import json
import re
from django.conf import settings
from openai import AzureOpenAI

MODEL = "gpt-4o-mini"


def _client():
    if not settings.AZURE_OPENAI_API_KEY:
        raise RuntimeError("AZURE_OPENAI_API_KEY is not configured.")
    if not settings.AZURE_OPENAI_ENDPOINT:
        raise RuntimeError("AZURE_OPENAI_ENDPOINT is not configured.")
    return AzureOpenAI(api_key=settings.AZURE_OPENAI_API_KEY,api_version="2024-05-01-preview",azure_endpoint=settings.AZURE_OPENAI_ENDPOINT)


def _ask(content, max_tokens=3000):
    msg = _client().chat.completions.create(model=MODEL, max_completion_tokens=max_tokens,
                                    messages=[{"role": "user", "content": content}])
    return msg.choices[0].message.content


def _parse_json(text):
    clean = re.sub(r"```json|```", "", text).strip()
    start = min([i for i in (clean.find("["), clean.find("{")) if i != -1], default=0)
    return json.loads(clean[start:])


def extract_brief(file_bytes=None, filename="", doc_text=""):
    """Condense a SOW/FDD (PDF, DOCX, or pasted text) into {summary, modules[]}."""
    ask = ('Extract a concise scope brief from this SOW/FDD. Respond ONLY with JSON, '
           'no markdown: {"summary":"<max 150 words>","modules":["<short module names '
           "like 'M1 Users', max 12>\"]}")
    if file_bytes:
        import io
        filename = (filename or "").lower()
        if filename.endswith(".docx") or filename.endswith(".doc"):
            try:
                from docx import Document
                document = Document(io.BytesIO(file_bytes))
                doc_text = "\n".join(paragraph.text for paragraph in document.paragraphs)
            except Exception as e:
                doc_text = f"[DOCX Extraction Failed: {e}]"
        else:
            from pypdf import PdfReader
            try:
                reader = PdfReader(io.BytesIO(file_bytes))
                doc_text = "\n".join(page.extract_text() or "" for page in reader.pages)
            except Exception as e:
                doc_text = f"[PDF Extraction Failed: {e}]"
            
    content = f"{ask}\n\nDOCUMENT TEXT:\n{doc_text[:12000]}"
    return _parse_json(_ask(content, max_tokens=800))


def weekly_plan(name, weeks, devs, brief, week_from=1, change_note="", done_titles=None):
    """devs: list of (name, designation). Returns [{week, focus, modules[]}]."""
    dev_line = "; ".join(f"{n} ({d})" for n, d in devs)
    prompt = (
        f"Project: {name}. Total {weeks} weeks; plan weeks {week_from}-{weeks}. Team: {dev_line}.\n"
        f"Scope: {brief.get('summary','')}\nModules: {', '.join(brief.get('modules', []))}\n"
    )
    if change_note:
        prompt += f"IMPORTANT SCOPE CHANGE (adjust remaining work): {change_note}\n"
    if done_titles:
        prompt += f"Already completed (do not repeat): {'; '.join(done_titles[:30])}\n"
    prompt += (
        "Create a weekly delivery plan (build first, then integrate, hardening, UAT, launch last). "
        f"Respond ONLY JSON array, no markdown: "
        f'[{{"week":{week_from},"focus":"<max 12 words>","modules":["..."]}}] '
        f"with exactly {weeks - week_from + 1} items for weeks {week_from} to {weeks}."
    )
    return _parse_json(_ask(prompt, max_tokens=1500))


def daily_tasks(name, weeks, week, focus, modules, devs, day_labels, change_note=""):
    """One task per developer per working day of the given week.
    day_labels: like ['D6 (17 Jul)', ...]. Returns [{day, dev, module, task}]."""
    dev_line = "; ".join(f"{n} ({d})" for n, d in devs)
    prompt = (
        f'Project "{name}" week {week}/{weeks}. Focus: {focus}. '
        f"Modules this week: {', '.join(modules)}.\n"
        + (f"Scope change in effect: {change_note}\n" if change_note else "")
        + f"Team: {dev_line}. Working days: {', '.join(day_labels)}.\n"
        "Assign exactly ONE task per developer per day, matching each developer's designation. "
        "Tasks concrete, under 12 words. Module names short (e.g. 'M1 Users', 'Setup', 'UAT').\n"
        'Respond ONLY JSON array, no markdown: [{"day":"D6","dev":"<name>","module":"<short>","task":"<short>"}]'
    )
    return _parse_json(_ask(prompt, max_tokens=3000))


def executive_summary(stats_text):
    """On-demand founder summary from live plan stats."""
    return _ask(
        "You are reporting to the founder of JMS Tech. Based on the data below, write a crisp "
        "executive status summary (under 180 words): overall health in one line, what's on track, "
        "what's at risk (name the developers and overdue items), and 2-3 recommended actions. "
        f"Plain text, no markdown headings.\n\n{stats_text}",
        max_tokens=600,
    )
