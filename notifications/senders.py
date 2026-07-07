import requests
from django.conf import settings
from django.core.mail import send_mail


def email(to, subject, body):
    if not to:
        return
    send_mail(subject, body, settings.DEFAULT_FROM_EMAIL,
              [to] if isinstance(to, str) else list(to), fail_silently=False)


def whatsapp(phone, text):
    """Optional: Meta Cloud API text message. Silently no-ops when not configured."""
    if not (settings.WHATSAPP_TOKEN and settings.WHATSAPP_PHONE_ID and phone):
        return
    try:
        requests.post(
            f"https://graph.facebook.com/v21.0/{settings.WHATSAPP_PHONE_ID}/messages",
            headers={"Authorization": f"Bearer {settings.WHATSAPP_TOKEN}"},
            json={"messaging_product": "whatsapp", "to": phone.lstrip("+"),
                  "type": "text", "text": {"body": text[:4000]}},
            timeout=15,
        )
    except requests.RequestException:
        pass  # never let a WhatsApp failure break the flow
