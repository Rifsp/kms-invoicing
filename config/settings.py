import os
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')
DEBUG = os.getenv('DEBUG', '0') == '1'
SECRET_KEY = os.getenv('SECRET_KEY', '')
if not SECRET_KEY:
    raise ImproperlyConfigured('Set SECRET_KEY di .env. Lihat .env.example.')
ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')
CSRF_TRUSTED_ORIGINS = [x for x in os.getenv('CSRF_TRUSTED_ORIGINS', '').split(',') if x]
INSTALLED_APPS = ['django.contrib.admin', 'django.contrib.auth', 'django.contrib.contenttypes', 'django.contrib.sessions', 'django.contrib.messages', 'django.contrib.staticfiles', 'django.contrib.humanize', 'core']
MIDDLEWARE = ['django.middleware.security.SecurityMiddleware', 'whitenoise.middleware.WhiteNoiseMiddleware', 'django.contrib.sessions.middleware.SessionMiddleware', 'django.middleware.common.CommonMiddleware', 'django.middleware.csrf.CsrfViewMiddleware', 'django.contrib.auth.middleware.AuthenticationMiddleware', 'django.contrib.messages.middleware.MessageMiddleware', 'django.middleware.clickjacking.XFrameOptionsMiddleware']
ROOT_URLCONF = 'config.urls'
TEMPLATES = [{'BACKEND': 'django.template.backends.django.DjangoTemplates', 'DIRS': [BASE_DIR / 'templates'], 'APP_DIRS': True, 'OPTIONS': {'builtins':['core.templatetags.ui'],'context_processors': ['django.template.context_processors.debug','django.template.context_processors.request','django.contrib.auth.context_processors.auth','django.contrib.messages.context_processors.messages','core.permissions.context']}}]
WSGI_APPLICATION = 'config.wsgi.application'
DATABASES = {'default': {'ENGINE': 'django.db.backends.postgresql', 'NAME': os.getenv('POSTGRES_DB', 'kms'), 'USER': os.getenv('POSTGRES_USER', 'kms'), 'PASSWORD': os.getenv('POSTGRES_PASSWORD', ''), 'HOST': os.getenv('POSTGRES_HOST', '127.0.0.1'), 'PORT': os.getenv('POSTGRES_PORT', '5432'), 'CONN_MAX_AGE': int(os.getenv('CONN_MAX_AGE', '60'))}}
AUTH_PASSWORD_VALIDATORS = [{'NAME':'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},{'NAME':'django.contrib.auth.password_validation.MinimumLengthValidator'},{'NAME':'django.contrib.auth.password_validation.CommonPasswordValidator'},{'NAME':'django.contrib.auth.password_validation.NumericPasswordValidator'}]
LANGUAGE_CODE = 'id'
TIME_ZONE = 'Asia/Jakarta'
USE_I18N = True
USE_TZ = True
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']
STORAGES = {'default': {'BACKEND':'django.core.files.storage.FileSystemStorage'}, 'staticfiles': {'BACKEND':'whitenoise.storage.CompressedManifestStaticFilesStorage'}}
MEDIA_ROOT = BASE_DIR / 'private_uploads'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'dashboard'
LOGOUT_REDIRECT_URL = 'login'
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_AGE = 28800
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
DATA_UPLOAD_MAX_MEMORY_SIZE = 12 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
if not DEBUG:
    # Default aman: cookie Secure + HSTS aktif. Untuk deploy TANPA TLS (mis. akses
    # lewat IP/HTTP di jaringan internal), matikan eksplisit via .env:
    #   SESSION_COOKIE_SECURE=0, CSRF_COOKIE_SECURE=0, SECURE_SSL_REDIRECT=0,
    #   SECURE_HSTS_SECONDS=0
    # Catatan: dengan cookie tidak-Secure, kredensial dikirim tanpa enkripsi —
    # hanya layak di jaringan tepercaya / di belakang reverse proxy TLS.
    SESSION_COOKIE_SECURE = os.getenv('SESSION_COOKIE_SECURE', '1') == '1'
    CSRF_COOKIE_SECURE = os.getenv('CSRF_COOKIE_SECURE', '1') == '1'
    SECURE_SSL_REDIRECT = os.getenv('SECURE_SSL_REDIRECT', '1') == '1'
    SECURE_HSTS_SECONDS = int(os.getenv('SECURE_HSTS_SECONDS', '31536000'))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = os.getenv('SECURE_HSTS_INCLUDE_SUBDOMAINS', '1') == '1'
    SECURE_HSTS_PRELOAD = os.getenv('SECURE_HSTS_PRELOAD', '1') == '1'

# Bound bulk formsets allow up to 200 purchase rows.
DATA_UPLOAD_MAX_NUMBER_FIELDS = 2500
