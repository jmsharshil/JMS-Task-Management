from .models import OrganizationSettings

def org_settings(request):
    """Context processor to inject org settings into all templates."""
    try:
        return {'org': OrganizationSettings.get()}
    except Exception:
        return {'org': None}
