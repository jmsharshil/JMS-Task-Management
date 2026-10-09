"""
Fixed task templates for Naavya AI project types.
Each template returns a list of task dicts: {day_num, module, title}
These are used instead of AI-generated plans for Naavya projects.
"""

WHATSAPP_TASKS = [
    # Day 1 — Document Collection
    {"day_num": 1, "module": "Document Collection", "title": "Collect GST certificate from client"},
    {"day_num": 1, "module": "Document Collection", "title": "Collect PAN card of authorized person"},
    {"day_num": 1, "module": "Document Collection", "title": "Collect phone number details (new or existing WhatsApp number)"},
    {"day_num": 1, "module": "Document Collection", "title": "Collect Meta/Facebook account credentials (email & password)"},
    {"day_num": 1, "module": "Document Collection", "title": "Collect international debit/credit card details for Meta billing"},
    {"day_num": 1, "module": "Document Collection", "title": "Collect bot use case brief (FAQ, lead gen, product menu, order updates, etc.)"},
    {"day_num": 1, "module": "Document Collection", "title": "Collect WhatsApp profile assets: Logo, Description, Address, Email, Website"},

    # Day 2 — Meta Business Portfolio Access & Verification Check
    {"day_num": 2, "module": "Meta Business Setup", "title": "Log in to Meta Business Suite / Business Manager with client credentials"},
    {"day_num": 2, "module": "Meta Business Setup", "title": "Verify admin-level access to client's business portfolio"},
    {"day_num": 2, "module": "Meta Business Setup", "title": "Go to Settings → Business Info and check verification status"},

    # Day 3 — Business Verification (if needed)
    {"day_num": 3, "module": "Business Verification", "title": "Start verification: Security Center → Business Verification"},
    {"day_num": 3, "module": "Business Verification", "title": "Enter legal business name, address, phone, website (must match GST certificate exactly)"},
    {"day_num": 3, "module": "Business Verification", "title": "Upload GST certificate for verification"},
    {"day_num": 3, "module": "Business Verification", "title": "Complete contact verification (email, phone, or domain)"},
    {"day_num": 3, "module": "Business Verification", "title": "Submit verification and monitor status"},

    # Day 4 — Verification Follow-up & Number Preparation
    {"day_num": 4, "module": "Business Verification", "title": "Check verification approval status"},
    {"day_num": 4, "module": "Business Verification", "title": "If GST rejected: re-verify with alternate document (CoI, PAN, utility bill, bank statement)"},
    {"day_num": 4, "module": "Number Preparation", "title": "Confirm phone number is NOT connected to any existing WhatsApp/WA Business app"},
    {"day_num": 4, "module": "Number Preparation", "title": "If existing WA number: delete account or initiate migration"},

    # Day 5 — Embedded Signup & Number Connection
    {"day_num": 5, "module": "Embedded Signup", "title": "Launch Embedded Signup flow from platform/BSP"},
    {"day_num": 5, "module": "Embedded Signup", "title": "Log in with Facebook and select verified business portfolio"},
    {"day_num": 5, "module": "Embedded Signup", "title": "Create or select WhatsApp Business Account (WABA)"},
    {"day_num": 5, "module": "Embedded Signup", "title": "Enter phone number and verify with OTP (SMS or voice call)"},
    {"day_num": 5, "module": "Embedded Signup", "title": "Set display name and submit for Meta approval"},

    # Day 6 — Confirmation & Profile Setup
    {"day_num": 6, "module": "Confirmation", "title": "Confirm number shows as Connected in WhatsApp Manager"},
    {"day_num": 6, "module": "Confirmation", "title": "Confirm WABA is linked to verified portfolio"},
    {"day_num": 6, "module": "Confirmation", "title": "Confirm display name is approved by Meta"},
    {"day_num": 6, "module": "Profile Setup", "title": "Upload business logo to WhatsApp profile"},
    {"day_num": 6, "module": "Profile Setup", "title": "Set business description on WhatsApp profile"},
    {"day_num": 6, "module": "Profile Setup", "title": "Set address, email, and website on WhatsApp profile"},

    # Day 7 — Bot Configuration
    {"day_num": 7, "module": "Bot Setup", "title": "Configure chatbot flow based on client's use case brief"},
    {"day_num": 7, "module": "Bot Setup", "title": "Set up automated greeting and away messages"},
    {"day_num": 7, "module": "Bot Setup", "title": "Configure quick reply buttons and interactive message templates"},

    # Day 8 — Testing & Handover
    {"day_num": 8, "module": "Testing", "title": "Test end-to-end message flow (send & receive)"},
    {"day_num": 8, "module": "Testing", "title": "Test bot responses and interactive elements"},
    {"day_num": 8, "module": "Testing", "title": "Verify billing and payment method is active"},
    {"day_num": 8, "module": "Handover", "title": "Client walkthrough and handover documentation"},
    {"day_num": 8, "module": "Handover", "title": "Share access credentials and admin guide with client"},
]


VOICE_TASKS = [
    # Day 1
    {"day_num": 1, "module": "Requirement Analysis", "title": "Analyze client requirements and prepare voice-agent script"},
    # Day 2
    {"day_num": 2, "module": "Voice Agent Development", "title": "Develop voice agent based on approved script and client requirements"},
    # Day 3
    {"day_num": 3, "module": "Feature Implementation", "title": "Identify and implement any additional features or mechanisms required"},
    # Day 4
    {"day_num": 4, "module": "Frontend Integration", "title": "Integrate the developed voice agent with the frontend"},
    # Day 5
    {"day_num": 5, "module": "Dashboard Customization", "title": "Customize the dashboard according to client's specific requirements"},
    # Day 6
    {"day_num": 6, "module": "Testing Readiness", "title": "Prepare the dashboard for testing once development and customization are complete"},
    # Day 7
    {"day_num": 7, "module": "Final Testing and Handover", "title": "Perform end-to-end testing, resolve issues, validate system, and handover"},
]


VOICE_WHATSAPP_TASKS = VOICE_TASKS + WHATSAPP_TASKS


def get_fixed_tasks(project_type):
    """Return the fixed task template list for a given Naavya project type."""
    templates = {
        "WHATSAPP": WHATSAPP_TASKS,
        "VOICE": VOICE_TASKS,
        "VOICE_WHATSAPP": VOICE_WHATSAPP_TASKS,
    }
    return templates.get(project_type, [])
