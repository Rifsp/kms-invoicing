"""Isolated portable tests only; normal settings always use PostgreSQL."""
import os
os.environ.setdefault('SECRET_KEY','test-only-not-for-production')
os.environ.setdefault('DEBUG','1')
from .settings import *
DATABASES={'default':{'ENGINE':'django.db.backends.sqlite3','NAME':':memory:'}}
STORAGES={'default':{'BACKEND':'django.core.files.storage.FileSystemStorage'},'staticfiles':{'BACKEND':'django.contrib.staticfiles.storage.StaticFilesStorage'}}
PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher']
