import os
from pathlib import Path
from datetime import timedelta
import dj_database_url
from dotenv import load_dotenv

load_dotenv()
BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-secret")
DEBUG = False
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "accounts",
    "core",
    "notifications",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

ROOT_URLCONF = "hub.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [], "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]
WSGI_APPLICATION = "hub.wsgi.application"

CONNECTION_STRING = os.environ.get('AZURE_POSTGRESQL_CONNECTIONSTRING')

if not CONNECTION_STRING:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }
else:
    conn_str_params = {pair.split('=')[0]: pair.split('=')[1] for pair in CONNECTION_STRING.split(' ')}
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': conn_str_params['dbname'],
            'HOST': conn_str_params['host'],
            'USER': conn_str_params['user'],
            'PASSWORD': conn_str_params['password'],
        }
    }


AUTH_USER_MODEL = "accounts.User"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ("rest_framework_simplejwt.authentication.JWTAuthentication",),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
}
SIMPLE_JWT = {"ACCESS_TOKEN_LIFETIME": timedelta(days=36500), "REFRESH_TOKEN_LIFETIME": timedelta(days=3000)}

CORS_ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "https://yellow-hill-086abe100.7.azurestaticapps.net",
    "https://deliveryhub.jmstech.co",
]
CORS_ALLOW_CREDENTIALS = True

CSRF_TRUSTED_ORIGINS = ["https://jms-task-management-f2e2hzcthnhteveh.centralindia-01.azurewebsites.net","http://localhost:8000"]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = os.getenv("EMAIL_HOST", "")
EMAIL_PORT = 587
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS=1
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "JMS Delivery Hub <no-reply@jmstech.co>")
ADMIN_REPORT_EMAIL = os.getenv("ADMIN_REPORT_EMAIL", "japan@jmstech.co")

AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY", "")

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID", "")

if not DEBUG:
    LOGGING = {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'verbose': {
                'format': '{levelname} {asctime} {module} {message}',
                'style': '{',
            },
        },
        'handlers': {
            'file': {
                'level': 'ERROR',
                'class': 'logging.FileHandler',
                'filename': os.getenv('DJANGO_LOG_FILE', os.path.join(BASE_DIR, 'django_errors.log')),
                'formatter': 'verbose',
            },
        },
        'loggers': {
            'django': {
                'handlers': ['file'],
                'level': 'ERROR',
                'propagate': False,
            },
        },
    }

CSRF_COOKIE_SECURE = True      # Only valid if using HTTPS
SESSION_COOKIE_SECURE = True   # Only valid if using HTTPS

USE_AZURE_MEDIA = os.environ.get("USE_AZURE_MEDIA", "0") in ("1", "true", "True")

if USE_AZURE_MEDIA:
    AZURE_ACCOUNT_NAME = os.environ["AZURE_ACCOUNT_NAME"]
    AZURE_ACCOUNT_KEY  = os.environ["AZURE_ACCOUNT_KEY"]
    AZURE_CONTAINER    = os.environ.get("AZURE_MEDIA_CONTAINER")
    AZURE_ACCOUNT_URL  = f"https://{AZURE_ACCOUNT_NAME}.blob.core.windows.net"
    AZURE_CUSTOM_DOMAIN = os.environ.get(
        "AZURE_CUSTOM_DOMAIN",
        f"{AZURE_ACCOUNT_NAME}.blob.core.windows.net",
    )
    AZURE_URL_EXPIRATION_SECS = int(os.environ.get("AZURE_URL_EXPIRATION_SECS", "3600"))
    AZURE_OVERWRITE_FILES = False

    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.azure_storage.AzureStorage",
            "OPTIONS": {
                "account_name": AZURE_ACCOUNT_NAME,
                "account_key": AZURE_ACCOUNT_KEY,
                "azure_container": AZURE_CONTAINER,
                "overwrite_files": AZURE_OVERWRITE_FILES,
                "expiration_secs": None,
            }
        },
        "staticfiles": {
            # keep whatever you use for static files (example with WhiteNoise)
            "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
        },
    }

    WHITENOISE_USE_FINDERS = True

    MEDIA_URL = f"https://{AZURE_CUSTOM_DOMAIN}/{AZURE_CONTAINER}/"
else:
    MEDIA_URL  = "/media/"
    MEDIA_ROOT = os.path.join(BASE_DIR, "media")
