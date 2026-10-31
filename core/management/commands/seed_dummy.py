"""Data dummy besar untuk uji tampilan. Jalankan:

    python manage.py seed_dummy --orders 40

Hanya menambah data; tidak menghapus apa pun. Idempoten untuk master (get_or_create),
dan menambah sejumlah pengadaan baru setiap kali dijalankan.
"""
import random
import uuid
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core.models import (
    Partner, Product, Procurement, OrderItem, SupplierPrice, SupplierProduct,
)
from core.services import confirm_order, record_payment, cash_movement, advance_order

SUPPLIER_NAMES = ['CV Sumber Rejeki', 'UD Berkah Jaya', 'PT Pangan Nusantara', 'Toko Sejahtera Abadi',
                  'CV Mitra Tani', 'UD Aneka Pangan', 'PT Boga Sentosa', 'CV Rasa Makmur',
                  'UD Sumber Protein', 'PT Segar Alami']
COOP_NAMES = ['Koperasi Merah Putih', 'KPRS Bangun Sejahtera', 'Koperasi Bersama Mandiri']
KITCHEN_NAMES = ['Dapur Bandung A', 'Dapur Bandung B', 'Dapur Cimahi 1', 'Dapur Soreang', 'Dapur Cileunyi']
CATALOG = [
    ('Daging', 'Ayam potong', 'kg', 12000), ('Daging', 'Ayam fillet', 'kg', 28000),
    ('Daging', 'Daging sapi sengkel', 'kg', 65000), ('Daging', 'Ikan nila', 'kg', 22000),
    ('Daging', 'Ikan kembung', 'kg', 25000), ('Daging', 'Telur ayam', 'kg', 11000),
    ('Protein', 'Tahu putih', 'kg', 6000), ('Protein', 'Tempe', 'kg', 7000),
    ('Sayur', 'Bayam', 'kg', 5000), ('Sayur', 'Kangkung', 'kg', 4500),
    ('Sayur', 'Wortel', 'kg', 9000), ('Sayur', 'Kentang', 'kg', 11000),
    ('Sayur', 'Tomat', 'kg', 8000), ('Sayur', 'Bawang merah', 'kg', 25000),
    ('Sayur', 'Bawang putih', 'kg', 22000), ('Sayur', 'Cabai merah', 'kg', 32000),
    ('Sayur', 'Sawi hijau', 'kg', 5500), ('Sayur', 'Kacang panjang', 'kg', 9500),
    ('Karbohidrat', 'Beras medium', 'kg', 10500), ('Karbohidrat', 'Beras premium', 'kg', 13500),
    ('Karbohidrat', 'Mie kering', 'kg', 12000), ('Karbohidrat', 'Tepung terigu', 'kg', 9000),
    ('Minuman', 'Susu UHT', 'liter', 16000), ('Minuman', 'Teh celup', 'kotak', 14000),
    ('Bumbu', 'Garam beryodium', 'kg', 3000), ('Bumbu', 'Gula pasir', 'kg', 13000),
    ('Bumbu', 'Kecap manis', 'liter', 15000), ('Bumbu', 'Saus sambal', 'liter', 14000),
    ('Bumbu', 'Minyak goreng', 'liter', 15500), ('Bumbu', 'Kemiri', 'kg', 35000),
]


class Command(BaseCommand):
    help = 'Buat data dummy (master + banyak pengadaan/invoice/pembayaran) untuk uji tampilan.'

    def add_arguments(self, parser):
        parser.add_argument('--orders', type=int, default=40, help='Banyak pengadaan baru yang dibuat.')
        parser.add_argument('--products', type=int, default=len(CATALOG), help='Banyak barang master.')
        parser.add_argument('--seed', type=int, default=2026, help='Seed acak agar data bisa direproduksi.')

    @transaction.atomic
    def handle(self, *args, **options):
        random.seed(options['seed'])
        User = get_user_model()
        admin, _ = User.objects.get_or_create(username='admin', defaults={'is_superuser': True, 'is_staff': True})
        if not admin.is_superuser:
            admin.is_superuser = admin.is_staff = True
            admin.save()
        owner_g, _ = Group.objects.get_or_create(name='Owner')
        op_g, _ = Group.objects.get_or_create(name='Admin Operasional')

        op_user, created = User.objects.get_or_create(username='operasional', defaults={'first_name': 'Operasional'})
        if created:
            op_user.set_unusable_password()
            op_user.save()
        op_user.groups.add(op_g)

        # ---- master ----
        suppliers = []
        for name in SUPPLIER_NAMES:
            p, _ = Partner.objects.get_or_create(name=name, kind='supplier',
                                                 defaults={'phone': f'0812{random.randint(1000000, 9999999)}',
                                                           'address': f'Jl. Industri No.{random.randint(1, 90)}, Bandung'})
            suppliers.append(p)
        coops = [Partner.objects.get_or_create(name=n, kind='cooperative')[0] for n in COOP_NAMES]
        kitchens = [Partner.objects.get_or_create(name=n, kind='kitchen')[0] for n in KITCHEN_NAMES]

        products = []
        for idx, (cat, name, unit, base) in enumerate(CATALOG[:options['products']], start=1):
            prod, _ = Product.objects.get_or_create(
                code=f'BRG-{idx:03d}',
                defaults={'name': name, 'category': cat, 'unit': unit})
            products.append((prod, unit, base))

        # ---- harga supplier historis (2 gelombang) ----
        today = timezone.localdate()
        for prod, unit, base in products:
            for sup in random.sample(suppliers, k=min(3, len(suppliers))):
                for wave, days in enumerate([45, 7]):
                    SupplierPrice.objects.get_or_create(
                        product=prod, supplier=sup, effective_date=today - timedelta(days=days),
                        defaults={'price': Decimal(base) + Decimal(random.randint(-500, 1500)),
                                  'unit': unit, 'created_by': admin,
                                  'note': f'Harga dummy gelombang {wave+1}'})
                SupplierProduct.objects.get_or_create(product=prod, supplier=sup)

        # saldo kas awal bila belum ada
        from core.services import balance
        if balance() == 0:
            cash_movement(admin, '50000000', 'income', today - timedelta(days=60), 'Modal awal (dummy)', uuid.uuid4())

        # ---- transaksi ----
        total_orders = options['orders']
        for i in range(total_orders):
            coop = random.choice(coops)
            kitchen = random.choice(kitchens)
            delivery = today - timedelta(days=random.randint(0, 55))
            order = Procurement.objects.create(
                cooperative=coop, kitchen=kitchen,
                office_name=f'Kantor {kitchen.name}',
                delivery_date=delivery, created_by=op_user,
                notes='DATA DUMMY — untuk uji tampilan, bukan transaksi nyata.')
            for prod, unit, base in random.sample(products, k=random.randint(1, 8)):
                quote = SupplierPrice.objects.filter(product=prod).order_by('-effective_date').first()
                supplier = quote.supplier if quote else random.choice(suppliers)
                purchase = Decimal(base) + Decimal(random.randint(-300, 800))
                kms = purchase + Decimal(random.randint(300, 900))
                coop_p = kms + Decimal(random.randint(300, 900))
                kitchen_p = coop_p + Decimal(random.randint(300, 1200))
                OrderItem.objects.create(
                    procurement=order, product=prod, supplier=supplier, supplier_quote=quote,
                    quantity=Decimal(random.choice([5, 10, 12.5, 15, 20, 25, 30, 50, 100])),
                    supplier_price=purchase, kms_price=kms,
                    cooperative_price=coop_p, kitchen_price=kitchen_p,
                    product_name=prod.name, unit=unit)
            # 80% dikonfirmasi; sisanya dibiarkan sebagai draf
            if random.random() < 0.8:
                confirm_order(admin, order.pk)
                # sebagian dimajukan ke shipped/received agar fitur ekspor & cetak bisa diuji
                roll2 = random.random()
                if roll2 < 0.25:
                    advance_order(op_user, order.pk)              # shipped
                elif roll2 < 0.45:
                    advance_order(op_user, order.pk)
                    advance_order(op_user, order.pk)              # received
                invoices = list(order.invoices.all())
                for inv in invoices:
                    roll = random.random()
                    if roll < 0.35:
                        continue                      # belum dibayar
                    if roll < 0.5:
                        nominal = (inv.total * Decimal('0.4')).quantize(Decimal('1'))
                    elif roll < 0.8:
                        nominal = inv.total                # lunas
                    else:
                        nominal = (inv.total * Decimal('0.75')).quantize(Decimal('1'))
                    if nominal <= 0:
                        continue
                    try:
                        record_payment(op_user if random.random() < 0.5 else admin, inv.pk,
                                       str(nominal), delivery + timedelta(days=random.randint(1, 10)),
                                       f'TRF-{uuid.uuid4().hex[:8].upper()}', uuid.uuid4())
                    except Exception:
                        pass  # lewati bila saldo kas kurang / aturan lain

        self.stdout.write(self.style.SUCCESS(
            f'Selesai. Pengadaan total={Procurement.objects.count()}, invoice={order_dummy_count()}, '
            f'produk={Product.objects.count()}, partner={Partner.objects.count()}.'))
        self.stdout.write('Data dummy siap untuk uji tampilan.')


def order_dummy_count():
    from core.models import Invoice
    return Invoice.objects.count()
