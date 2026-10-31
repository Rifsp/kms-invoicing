from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group
from core.permissions import OWNER,OPERATOR
from core.models import Wallet
class Command(BaseCommand):
    help='Membuat role Owner dan Admin Operasional tanpa mengubah akun.'
    def handle(self,*args,**options):
        for name in [OWNER,OPERATOR]: Group.objects.get_or_create(name=name)
        Wallet.objects.get_or_create(name='KMS')
        self.stdout.write(self.style.SUCCESS('Role akses siap.'))
