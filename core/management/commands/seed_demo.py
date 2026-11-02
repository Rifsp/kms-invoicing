import os
import uuid
from datetime import timedelta
from django.core.management.base import BaseCommand,CommandError
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.db import transaction
from django.utils import timezone
from core.models import Partner,Product,Procurement,OrderItem,SupplierPrice,SupplierProduct
from core.services import confirm_order,record_payment,cash_movement

class Command(BaseCommand):
    help='Data contoh invoicing; hanya untuk database tanpa pengadaan. Wajib KMS_DEMO_PASSWORD.'
    @transaction.atomic
    def handle(self,*args,**options):
        password=os.getenv('KMS_DEMO_PASSWORD','')
        if len(password)<12: raise CommandError('Set KMS_DEMO_PASSWORD minimal 12 karakter.')
        if Procurement.objects.exists(): raise CommandError('Database sudah memiliki pengadaan; demo tidak ditambahkan.')
        call_command('setup_roles')
        User=get_user_model()
        if User.objects.filter(username__in=['owner','operasional']).exists(): raise CommandError('Akun demo sudah ada; gunakan database demo kosong.')
        owner=User.objects.create_user('owner',password=password,first_name='Owner')
        owner.groups.add(Group.objects.get(name='Owner'))
        operator=User.objects.create_user('operasional',password=password,first_name='Operasional')
        operator.groups.add(Group.objects.get(name='Admin Operasional'))
        coop=Partner.objects.get_or_create(name='Koperasi Contoh',kind='cooperative')[0]
        kitchen=Partner.objects.get_or_create(name='Dapur Bandung A',kind='kitchen')[0]
        suppliers=[Partner.objects.get_or_create(name=f'Supplier {letter}',kind='supplier')[0] for letter in ['A','B','C']]
        egg=Product.objects.get_or_create(code='BRG-001',defaults={'name':'Telur ayam','category':'Protein','unit':'kg'})[0]
        today=timezone.localdate()
        old=SupplierPrice.objects.create(product=egg,supplier=suppliers[0],price=11500,unit='kg',effective_date=today-timedelta(days=7),created_by=owner,note='Harga minggu lalu — DEMO')
        quotes=[SupplierPrice.objects.create(product=egg,supplier=supplier,price=price,unit='kg',effective_date=today,created_by=owner,note='Penawaran DEMO') for supplier,price in zip(suppliers,[12000,13000,13500])]
        for supplier in suppliers:SupplierProduct.objects.get_or_create(product=egg,supplier=supplier)
        cash_movement(owner,'5000000','income',today,'Modal awal DEMO',uuid.uuid4())
        for idx in range(3):
            order=Procurement.objects.create(cooperative=coop,kitchen=kitchen,delivery_date=today+timedelta(days=idx),created_by=operator,notes='DATA CONTOH — bukan transaksi sebenarnya.')
            OrderItem.objects.create(procurement=order,product=egg,supplier=suppliers[0],supplier_quote=quotes[0],quantity=100+idx*50,supplier_price=12000,kms_price=12500,cooperative_price=13000)
            if idx<2:
                confirm_order(owner,order.pk)
                supplier_invoice=order.invoices.get(kind='supplier')
                record_payment(operator,supplier_invoice.pk,'200000',today,'BAYAR-SUPPLIER-DEMO',uuid.uuid4())
                inv=order.invoices.get(kind='kms')
                record_payment(operator,inv.pk,'500000',today,'TRANSFER-DEMO',uuid.uuid4())
        self.stdout.write(self.style.SUCCESS('Data contoh siap: owner dan operasional. Password dari KMS_DEMO_PASSWORD.'))
