"""Generate local Docker configuration without overwriting existing settings."""
from pathlib import Path
import secrets

path = Path(__file__).resolve().parent / '.env'
if path.exists():
    raise SystemExit('.env sudah ada; konfigurasi tidak diubah.')
text = '\n'.join([
    'DEBUG=1',
    'SECRET_KEY=' + secrets.token_urlsafe(48),
    'POSTGRES_PASSWORD=' + secrets.token_urlsafe(32),
    'POSTGRES_DB=kms', 'POSTGRES_USER=kms',
    'POSTGRES_HOST=127.0.0.1', 'POSTGRES_PORT=5432',
    'ALLOWED_HOSTS=localhost,127.0.0.1', 'CSRF_TRUSTED_ORIGINS=', '',
])
with path.open('x', encoding='utf-8') as stream:
    stream.write(text)
try:
    path.chmod(0o600)
except OSError:
    pass
print('Konfigurasi lokal siap. Lanjutkan langkah Docker di README.md.')
