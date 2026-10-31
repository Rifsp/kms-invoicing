import uuid
from decimal import Decimal
from django.conf import settings
from django.db import models
from django.db.models import Q
from django.core.validators import MinValueValidator
from django.utils import timezone

ZERO = Decimal('0')
class Stamp(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        abstract = True

class Partner(Stamp):
    class Kind(models.TextChoices):
        SUPPLIER = 'supplier', 'Supplier'
        COOPERATIVE = 'cooperative', 'Koperasi'
        KITCHEN = 'kitchen', 'Dapur'
    name = models.CharField('Nama', max_length=140)
    kind = models.CharField('Jenis', max_length=20, choices=Kind.choices)
    phone = models.CharField('Telepon', max_length=30, blank=True)
    address = models.TextField('Alamat', blank=True)
    active = models.BooleanField('Aktif', default=True)
    class Meta:
        ordering = ['name']
        constraints = [models.UniqueConstraint(fields=['name','kind'], name='partner_name_kind_unique')]
    def __str__(self): return self.name

class Product(Stamp):
    code = models.CharField('Kode barang', max_length=30, unique=True)
    name = models.CharField('Nama barang', max_length=140)
    category = models.CharField('Kategori', max_length=80)
    unit = models.CharField('Satuan', max_length=20, default='kg')
    active = models.BooleanField('Aktif', default=True)
    class Meta: ordering = ['name']
    def __str__(self): return f'{self.code} · {self.name} · {self.unit}'

class Procurement(Stamp):
    class Status(models.TextChoices):
        DRAFT = 'draft', 'Draf'
        CONFIRMED = 'confirmed', 'Dikonfirmasi'
        SHIPPED = 'shipped', 'Dalam pengiriman'
        RECEIVED = 'received', 'Diterima dapur'
        CANCELLED = 'cancelled', 'Dibatalkan'
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.CharField(max_length=300, blank=True)
    report_snapshot = models.JSONField(default=dict, blank=True)
    revision = models.PositiveIntegerField(default=0)
    reference = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    cooperative = models.ForeignKey(Partner, on_delete=models.PROTECT, related_name='cooperative_orders', limit_choices_to={'kind':'cooperative'})
    kitchen = models.ForeignKey(Partner, on_delete=models.PROTECT, related_name='kitchen_orders', limit_choices_to={'kind':'kitchen'})
    office_name = models.CharField('Nama kantor dapur / penerima invoice', max_length=140, default='Kantor dapur')
    delivery_date = models.DateField('Tanggal pengiriman')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    notes = models.TextField('Catatan', blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    class Meta: ordering = ['-created_at']
    @property
    def code(self): return f'PGD-{self.pk:05d}'
    def __str__(self): return self.code

class OrderItem(models.Model):
    procurement = models.ForeignKey(Procurement, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    supplier = models.ForeignKey(Partner, on_delete=models.PROTECT, limit_choices_to={'kind':'supplier'})
    quantity = models.DecimalField('Jumlah', max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    supplier_price = models.DecimalField('Supplier → KMS (Rp/satuan)', max_digits=15, decimal_places=2, validators=[MinValueValidator(ZERO)])
    kms_price = models.DecimalField('KMS → Koperasi (Rp/satuan)', max_digits=15, decimal_places=2, validators=[MinValueValidator(ZERO)], default=ZERO)
    cooperative_price = models.DecimalField('Koperasi → Dapur (Rp/satuan)', max_digits=15, decimal_places=2, validators=[MinValueValidator(ZERO)])
    recommended_price = models.DecimalField('Harga rekomendasi lama', max_digits=15, decimal_places=2, validators=[MinValueValidator(ZERO)], default=ZERO)
    kitchen_price = models.DecimalField('Dapur → Kantor dapur (Rp/satuan)', max_digits=15, decimal_places=2, validators=[MinValueValidator(ZERO)], default=ZERO)
    supplier_quote = models.ForeignKey('SupplierPrice', null=True, blank=True, on_delete=models.PROTECT)
    product_name = models.CharField(max_length=140, blank=True)
    unit = models.CharField(max_length=20, blank=True)
    class Meta:
        constraints = [models.CheckConstraint(condition=Q(quantity__gt=0), name='item_positive_quantity')] + [models.CheckConstraint(condition=Q(**{f'{f}__gte':0}), name=f'item_nonnegative_{f}') for f in ['supplier_price','kms_price','cooperative_price','recommended_price','kitchen_price']]
    @property
    def purchase_total(self): return (self.quantity*self.supplier_price).quantize(Decimal('0.01'))
    @property
    def kms_total(self): return (self.quantity*self.kms_price).quantize(Decimal('0.01'))
    @property
    def cooperative_total(self): return (self.quantity*self.cooperative_price).quantize(Decimal('0.01'))

    @property
    def kitchen_total(self): return (self.quantity*self.kitchen_price).quantize(Decimal('0.01'))

class Invoice(Stamp):
    class Kind(models.TextChoices):
        SUPPLIER = 'supplier', 'Tagihan supplier → KMS'
        KMS = 'kms', 'KMS → Koperasi'
        COOPERATIVE = 'cooperative', 'Koperasi → Dapur (harga beli dapur)'
        KITCHEN = 'kitchen', 'Dapur → Kantor Dapur'
    procurement = models.ForeignKey(Procurement, on_delete=models.PROTECT, related_name='invoices')
    kind = models.CharField(max_length=20, choices=Kind.choices)
    supplier = models.ForeignKey(Partner, null=True, blank=True, on_delete=models.PROTECT)
    number = models.CharField(max_length=100, unique=True, null=True, blank=True)
    print_snapshot = models.JSONField(default=dict, blank=True)
    issuer_name = models.CharField(max_length=140)
    recipient_name = models.CharField(max_length=140)
    total = models.DecimalField(max_digits=18, decimal_places=2)
    due_date = models.DateField()
    class Meta:
        ordering = ['-created_at']
        constraints = [models.UniqueConstraint(fields=['procurement','supplier'], condition=Q(kind='supplier'), name='unique_supplier_invoice'), models.UniqueConstraint(fields=['procurement','kind'], condition=~Q(kind='supplier'), name='unique_sales_invoice'), models.CheckConstraint(condition=Q(total__gte=0), name='invoice_nonnegative_total'), models.CheckConstraint(condition=(Q(kind='supplier',supplier__isnull=False)|(~Q(kind='supplier')&Q(supplier__isnull=True))), name='invoice_supplier_required')]
    @property
    def code(self): return self.number or f'INV-{self.pk:05d}'
    @property
    def paid(self): return sum((p.amount for p in self.payments.all() if not p.cancelled_at), ZERO)
    @property
    def remaining(self): return self.total-self.paid
    @property
    def payment_status_key(self):
        if self.procurement.status=='cancelled':return 'cancelled'
        return 'paid' if self.remaining==0 else ('partial' if self.paid else 'unpaid')
    @property
    def payment_status(self):
        if self.procurement.status == 'cancelled': return 'Dibatalkan'
        return 'Lunas' if self.remaining == 0 else ('Dibayar sebagian' if self.paid else 'Belum dibayar')

class Payment(Stamp):
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.CharField(max_length=300, blank=True)
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name='payments')
    amount = models.DecimalField('Nominal pembayaran (Rp)', max_digits=18, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    date = models.DateField('Tanggal pembayaran')
    reference = models.CharField('Referensi transfer / bukti', max_length=120)
    request_key = models.UUIDField(default=uuid.uuid4, unique=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    class Meta:
        ordering = ['-date','-pk']
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0),name='payment_positive')]

class Wallet(models.Model):
    name = models.CharField(max_length=40, unique=True, default='KMS')

class LedgerEntry(Stamp):
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.CharField(max_length=300, blank=True)
    date = models.DateField('Tanggal mutasi', default=timezone.localdate)
    wallet = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name='entries')
    payment = models.OneToOneField(Payment, null=True, blank=True, on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    description = models.CharField(max_length=200)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    request_key = models.UUIDField(default=uuid.uuid4, unique=True)
    class Meta:
        ordering = ['-created_at']
        constraints = [models.CheckConstraint(condition=~Q(amount=0), name='ledger_nonzero')]

class KitchenEntry(Stamp):
    class Kind(models.TextChoices):
        REVENUE='revenue','Pendapatan dapur'
        EXPENSE='expense','Biaya operasional dapur'
        COOP_EXPENSE='coop_expense','Biaya operasional koperasi'
    procurement = models.ForeignKey(Procurement, on_delete=models.PROTECT, related_name='kitchen_entries')
    kind = models.CharField('Jenis pencatatan',max_length=20,choices=Kind.choices)
    amount = models.DecimalField('Nominal (Rp)',max_digits=18,decimal_places=2,validators=[MinValueValidator(Decimal('0.01'))])
    date = models.DateField('Tanggal')
    description = models.CharField('Keterangan',max_length=200)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    class Meta:
        constraints=[models.CheckConstraint(condition=Q(amount__gt=0),name='kitchen_entry_positive')]

class Attachment(Stamp):
    procurement = models.ForeignKey(Procurement, on_delete=models.PROTECT, related_name='attachments')
    file = models.FileField(upload_to='evidence/%Y/%m/')
    thumbnail = models.FileField(upload_to='thumbnails/%Y/%m/',blank=True)
    original_name = models.CharField(max_length=200)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

class AuditEvent(Stamp):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    action = models.CharField(max_length=80)
    target = models.CharField(max_length=120)
    details = models.JSONField(default=dict)
    class Meta: ordering = ['-created_at']


SALES_KINDS = ['kms', 'cooperative', 'kitchen']
INVOICE_KINDS = ['supplier'] + SALES_KINDS
DOCUMENT_KINDS = INVOICE_KINDS + ['procurement']
def document_label(kind):
    return 'Laporan pengadaan' if kind == 'procurement' else Invoice.Kind(kind).label

class SupplierPrice(Stamp):
    """Append-only price offers; transaction prices are independent snapshots."""
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='supplier_prices')
    supplier = models.ForeignKey(Partner, on_delete=models.PROTECT, limit_choices_to={'kind': 'supplier'})
    price = models.DecimalField('Harga per satuan (Rp)', max_digits=15, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    unit = models.CharField(max_length=20)
    effective_date = models.DateField('Tanggal berlaku')
    note = models.CharField('Catatan / sumber harga', max_length=200, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    class Meta:
        ordering = ['-effective_date', '-pk']
        indexes = [models.Index(fields=['product', 'supplier', '-effective_date'], name='quote_lookup_idx')]
        constraints = [models.CheckConstraint(condition=Q(price__gt=0), name='quote_price_positive')]
    def __str__(self): return f'{self.supplier} · {self.price}/{self.unit} · {self.effective_date}'


class InvoiceProfile(models.Model):
    kind = models.CharField(max_length=20, choices=[(k, document_label(k)) for k in DOCUMENT_KINDS])
    partner = models.ForeignKey(Partner,null=True,blank=True,on_delete=models.PROTECT,related_name='invoice_profiles')
    logo_left = models.FileField('Logo kiri',upload_to='invoice_logos/',blank=True)
    logo_right = models.FileField('Logo kanan',upload_to='invoice_logos/',blank=True)
    signers = models.JSONField(default=list,blank=True)
    prefix = models.CharField('Awalan nomor', max_length=20)
    number_pattern = models.CharField('Format nomor', max_length=80, default='{prefix}/{year}/{month}/{seq}', help_text='Token: {prefix}, {year}, {month}, {seq}. Nomor urut otomatis 5 digit. Wajib memuat {seq}.')
    reset = models.CharField('Reset nomor urut', max_length=10, choices=[('never','Tidak direset'),('year','Setiap tahun'),('month','Setiap bulan')], default='month')
    title = models.CharField('Judul dokumen', max_length=80, default='INVOICE')
    heading = models.CharField('Kop tambahan', max_length=140, blank=True)
    address = models.TextField('Alamat / kontak pada kop', blank=True)
    bank_info = models.TextField('Informasi rekening', blank=True)
    signature = models.CharField('Nama penanda tangan', max_length=140, blank=True)
    footer = models.TextField('Catatan kaki', blank=True)
    style = models.CharField('Template cetak', max_length=20, choices=[('classic','Klasik'),('compact','Ringkas')], default='classic')
    due_days = models.PositiveSmallIntegerField('Jatuh tempo (hari sejak terbit)', default=14)

    class Meta:
        constraints=[models.UniqueConstraint(fields=['kind'],condition=Q(partner__isnull=True),name='invoice_default_profile_unique'),models.UniqueConstraint(fields=['kind','partner'],condition=Q(partner__isnull=False),name='invoice_partner_profile_unique')]

    def clean(self):
        from django.core.exceptions import ValidationError
        import re
        pattern = self.number_pattern
        tokens = re.findall(r'\{([^{}]+)\}', pattern)
        residue = re.sub(r'\{(?:prefix|year|month|seq)\}', '', pattern)
        if '{seq}' not in pattern or any(t not in ['prefix','year','month','seq'] for t in tokens) or '{' in residue or '}' in residue:
            raise ValidationError({'number_pattern': 'Gunakan token yang tersedia dan sertakan {seq}.'})
        if self.reset == 'year' and '{year}' not in pattern:
            raise ValidationError({'number_pattern': 'Reset tahunan memerlukan {year}.'})
        if self.reset == 'month' and not all(t in pattern for t in ['{year}', '{month}']):
            raise ValidationError({'number_pattern': 'Reset bulanan memerlukan {year} dan {month}.'})
        example = pattern.format(prefix=self.prefix, year='2026', month='10', seq='00001')
        if len(example) > 100:
            raise ValidationError({'number_pattern': 'Nomor invoice maksimal 100 karakter.'})

class InvoiceCounter(models.Model):
    profile = models.ForeignKey(InvoiceProfile, on_delete=models.PROTECT)
    period = models.CharField(max_length=6)
    value = models.PositiveIntegerField(default=0)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['profile', 'period'], name='invoice_counter_period_unique')]


class FinancialEvidence(Stamp):
    payment = models.ForeignKey(Payment, null=True, blank=True, on_delete=models.PROTECT, related_name='evidences')
    ledger_entry = models.ForeignKey(LedgerEntry, null=True, blank=True, on_delete=models.PROTECT, related_name='evidences')
    file = models.FileField(upload_to='financial_evidence/%Y/%m/')
    thumbnail = models.FileField(upload_to='thumbnails/%Y/%m/',blank=True)
    original_name = models.CharField(max_length=200)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    class Meta:
        constraints = [models.CheckConstraint(condition=(Q(payment__isnull=False,ledger_entry__isnull=True)|Q(payment__isnull=True,ledger_entry__isnull=False)),name='evidence_single_financial_target')]


class SupplierProduct(Stamp):
    product=models.ForeignKey(Product,on_delete=models.PROTECT,related_name='supplier_catalog')
    supplier=models.ForeignKey(Partner,on_delete=models.PROTECT,related_name='product_catalog',limit_choices_to={'kind':'supplier'})
    note=models.CharField('Catatan ketersediaan',max_length=200,blank=True)
    active=models.BooleanField('Aktif',default=True)
    class Meta:
        ordering=['product__name','supplier__name']
        constraints=[models.UniqueConstraint(fields=['product','supplier'],name='supplier_product_pair_unique')]
    def __str__(self):return f'{self.product} / {self.supplier}'
