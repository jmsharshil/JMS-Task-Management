import sys
import logging

file_path = r'c:\Users\Admin\Downloads\jms-delivery-hub\jms-delivery-hub\backend\core\views.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Edit 1: project_type and category
old_create = """        project = Project.objects.create(
            name=data["name"], client_id=data.get("client") or None,
            ref=data.get("ref", ""), start_date=data["start_date"],
            weeks=int(data.get("weeks", 8)),
            brief_summary=brief_data.get("summary", ""),"""

new_create = """        project = Project.objects.create(
            name=data["name"], client_id=data.get("client") or None,
            ref=data.get("ref", ""), start_date=data["start_date"],
            weeks=int(data.get("weeks", 8)),
            category=data.get("category", "JMS"),
            project_type=data.get("project_type", "SOFTWARE"),
            brief_summary=brief_data.get("summary", ""),"""

if old_create not in content:
    print('Failed to find first edit target!')
else:
    content = content.replace(old_create, new_create)
    print('Applied first edit')

# Edit 2: documents upload auto process
old_doc = """            doc = ProjectDocument.objects.create(
                project=project, title=title, file=file, uploaded_by=request.user
            )
            return Response(
                ProjectDocumentSerializer(doc, context={"request": request}).data,
                status=201,
            )
        docs = project.documents.all()"""

new_doc = """            doc = ProjectDocument.objects.create(
                project=project, title=title, file=file, uploaded_by=request.user
            )
            
            # Auto-process the uploaded document
            try:
                file_ext = (file.name or "").lower().split(".")[-1]
                file.seek(0)
                file_bytes = file.read()
                doc_text = ""
                
                if file_ext in ("docx", "doc"):
                    try:
                        import io
                        from docx import Document
                        document = Document(io.BytesIO(file_bytes))
                        doc_text = "\\n".join(paragraph.text for paragraph in document.paragraphs)
                    except Exception as e:
                        import logging
                        logging.getLogger(__name__).warning(f"DOCX extraction failed for auto-process: {e}")
                elif file_ext == "pdf":
                    try:
                        import io
                        from pypdf import PdfReader
                        reader = PdfReader(io.BytesIO(file_bytes))
                        doc_text = "\\n".join(page.extract_text() or "" for page in reader.pages)
                    except Exception as e:
                        import logging
                        logging.getLogger(__name__).warning(f"PDF extraction failed for auto-process: {e}")
                elif file_ext in ("txt", "md", "csv"):
                    try:
                        doc_text = file_bytes.decode("utf-8")
                    except Exception:
                        pass
                
                if doc_text.strip():
                    from .services import auto_process_document
                    auto_process_document(project, doc_text, request.user)
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"Error auto-processing document: {e}")

            return Response(
                ProjectDocumentSerializer(doc, context={"request": request}).data,
                status=201,
            )
        docs = project.documents.all()"""

if old_doc not in content:
    print('Failed to find second edit target!')
else:
    content = content.replace(old_doc, new_doc)
    print('Applied second edit')

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)

print('Success')
