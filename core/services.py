import uuid
from contextlib import contextmanager
from decimal import Decimal
from datetime import timedelta
from django.db import transaction
from django.db.models import Sum
from django.core.exceptions import ValidationError, PermissionDenied
from django.utils import timezone
from .models import Procurement, OrderItem, Invoice, Payment, AuditEvent, InvoiceProfile, InvoiceCounter, SupplierPrice, SALES_KINDS, INVOICE_KINDS, Wallet, LedgerEntry, FinancialEvidence, SupplierProduct, DOCUMENT_KINDS
from .permissions import is_owner, require_access
from .uploads import validate_evidence,prepare_evidence

CENT = Decimal('0.01')
def audit(user, action, target, **details):
    AuditEvent.objects.create(actor=user, action=action, target=str(target), details=details)
def amount(value):
    try: result = Decimal(str(value))
    except Exception: raise ValidationError('Nominal tidak valid.')
    if not result.is_finite() or result != result.quantize(CENT) or result <= 0:
        raise ValidationError('Nominal harus positif dengan maksimal dua angka desimal.')
    return result

@transaction.atomic
def save_item(user, order_id, form, item_id=None):
    require_access(user)
    order = Procurement.objects.select_for_update().get(pk=order_id)
    if order.status != Procurement.Status.DRAFT:
        raise ValidationError('Harga transaksi sudah dikunci. Barang tidak dapat diubah.')
    item = form.save(commit=False)
    item.procurement = order
    if item_id and (item.pk != item_id or not OrderItem.objects.filter(pk=item_id, procurement=order).exists()):
        raise ValidationError('Barang bukan bagian dari pengadaan ini.')
    if not item.supplier_quote_id and item.supplier_price > 0:
        quote = SupplierPrice.objects.create(product=item.product,supplier=item.supplier,price=item.supplier_price,unit=item.product.unit,effective_date=timezone.localdate(),created_by=user,note=f'Harga transaksi {order.code}')
        item.supplier_quote = quote
        audit(user,'supplier_price.created',quote.pk,source=order.code,price=str(quote.price))
    SupplierProduct.objects.get_or_create(product=item.product,supplier=item.supplier)
    item.full_clean()
    item.save()
    order.revision+=1;order.save(update_fields=['revision'])
    audit(user, 'item.updated' if item_id else 'item.created', order.code, item_id=item.pk)
    return item

@transaction.atomic
def delete_item(user, order_id, item_id):
    require_owner(user)
    order = Procurement.objects.select_for_update().get(pk=order_id)
    if order.status != Procurement.Status.DRAFT:
        raise ValidationError('Pengadaan dikunci.')
    item = OrderItem.objects.get(pk=item_id, procurement=order)
    item.delete()
    order.revision+=1;order.save(update_fields=['revision'])
    audit(user, 'item.deleted', order.code, item_id=item_id)

def invoice_profile(kind,partner=None):
    if kind not in DOCUMENT_KINDS:
        raise ValidationError('Jenis invoice tidak didukung.')
    profile, _ = InvoiceProfile.objects.get_or_create(kind=kind,partner=None,defaults={'title':('PENAWARAN HARGA' if kind=='procurement' else ('TAGIHAN SUPPLIER' if kind=='supplier' else 'INVOICE')),'prefix': {'supplier':'SUP','kms':'KMS','cooperative':'KOP','kitchen':'DPR','procurement':'PGD'}[kind]})
    if partner:
        return InvoiceProfile.objects.filter(kind=kind,partner=partner).first() or profile
    return profile


def issue_invoice(order, kind, issuer, recipient, total, today, supplier=None):
    # Called within confirm_order's transaction; lock the profile before its counter.
    base=invoice_profile(kind)
    InvoiceProfile.objects.select_for_update().get(pk=base.pk)
    partner=supplier if kind=='supplier' else (order.cooperative if kind=='cooperative' else (order.kitchen if kind=='kitchen' else None))
    profile=InvoiceProfile.objects.select_for_update().get(pk=invoice_profile(kind,partner).pk)
    profile.full_clean()
    period = today.strftime('%Y%m') if profile.reset == 'month' else (today.strftime('%Y') if profile.reset == 'year' else 'all')
    counter, _ = InvoiceCounter.objects.get_or_create(profile=profile, period=period)
    # Even if the numbering format is changed, skip existing numbers, never overwrite.
    while True:
        counter.value += 1
        number = profile.number_pattern.format(prefix=profile.prefix, year=today.strftime('%Y'), month=today.strftime('%m'), seq=f'{counter.value:05d}')
        if not Invoice.objects.filter(number=number).exists():
            break
    counter.save(update_fields=['value'])
    snapshot = {key: getattr(profile,key) for key in ['title','heading','address','bank_info','signature','footer','style']}
    snapshot.update(signers=profile.signers,logo_left=profile.logo_left.name,logo_right=profile.logo_right.name)
    return Invoice.objects.create(procurement=order,kind=kind,supplier=supplier,number=number,issuer_name=issuer,recipient_name=recipient,total=total,due_date=today+timedelta(days=profile.due_days),print_snapshot=snapshot)


@transaction.atomic
def confirm_order(user, order_id):
    if not is_owner(user): raise PermissionDenied('Konfirmasi harga oleh Owner / Super Admin.')
    order = Procurement.objects.select_for_update().select_related('cooperative','kitchen').get(pk=order_id)
    if order.status != Procurement.Status.DRAFT:
        raise ValidationError('Pengadaan sudah dikonfirmasi.')
    items = list(order.items.select_related('product','supplier'))
    if not items: raise ValidationError('Tambahkan minimal satu barang.')
    if any(i.kms_price <= 0 or i.cooperative_price <= 0 or i.kitchen_price <= 0 for i in items):
        raise ValidationError('Lengkapi harga KMS, koperasi, dan harga kantor dapur sebelum konfirmasi.')
    if any(i.kitchen_price < i.cooperative_price for i in items):
        raise ValidationError('Harga ke kantor dapur tidak boleh di bawah harga beli dapur.')
    for item in items:
        item.product_name, item.unit = item.product.name, item.product.unit
        item.save(update_fields=['product_name','unit'])
    today = timezone.localdate()
    suppliers={}
    for item in items:
        supplier,total=suppliers.get(item.supplier_id,(item.supplier,Decimal('0')))
        suppliers[item.supplier_id]=(supplier,total+item.purchase_total)
    for supplier,total in suppliers.values():
        issue_invoice(order,'supplier',supplier.name,'KMS',total,today,supplier=supplier)
    issue_invoice(order,'kms','KMS',order.cooperative.name,sum((i.kms_total for i in items),Decimal('0')),today)
    issue_invoice(order,'cooperative',order.cooperative.name,order.kitchen.name,sum((i.cooperative_total for i in items),Decimal('0')),today)
    issue_invoice(order,'kitchen',order.kitchen.name,order.office_name,sum((i.kitchen_total for i in items),Decimal('0')),today)
    order.report_snapshot = profile_snapshot(invoice_profile('procurement'))
    order.status, order.confirmed_at = Procurement.Status.CONFIRMED, timezone.now()
    order.save(update_fields=['status','confirmed_at','report_snapshot'])
    audit(user,'procurement.confirmed',order.code)
    return order


@transaction.atomic
def record_quote(user, form):
    require_access(user)
    quote = form.save(commit=False)
    quote.unit = quote.product.unit
    quote.created_by = user
    quote.full_clean()
    quote.save()
    SupplierProduct.objects.get_or_create(product=quote.product,supplier=quote.supplier)
    audit(user,'supplier_price.created',quote.pk,product=quote.product_id,supplier=quote.supplier_id,price=str(quote.price))
    return quote


def supplier_offers(product_id, date):
    # Latest eligible quote per supplier, then sort by price. Ties use newest entry.
    quotes = SupplierPrice.objects.filter(product_id=product_id,product__active=True,supplier__active=True,supplier__kind='supplier',effective_date__lte=date).select_related('supplier','product').order_by('supplier_id','-effective_date','-pk')
    latest = {}
    for quote in quotes:
        if quote.unit == quote.product.unit:
            latest.setdefault(quote.supplier_id,quote)
    return sorted(latest.values(),key=lambda q:(q.price,q.supplier.name))


@transaction.atomic
def advance_order(user, order_id):
    require_access(user)
    order = Procurement.objects.select_for_update().get(pk=order_id)
    transitions = {Procurement.Status.CONFIRMED:Procurement.Status.SHIPPED,Procurement.Status.SHIPPED:Procurement.Status.RECEIVED}
    if order.status not in transitions: raise ValidationError('Status tidak dapat dilanjutkan.')
    order.status=transitions[order.status]
    order.save(update_fields=['status'])
    audit(user,'procurement.status',order.code,status=order.status)

def kms_wallet():
    return Wallet.objects.get_or_create(name='KMS')[0]


def balance(wallet=None):
    wallet = wallet or kms_wallet()
    return LedgerEntry.objects.filter(wallet=wallet,cancelled_at__isnull=True).aggregate(value=Sum('amount'))['value'] or Decimal('0')


@contextmanager
def financial_transaction():
    written=[]
    try:
        with transaction.atomic():
            yield written
    except Exception:
        for file in written:
            file.delete(save=False)
        raise


def save_financial_evidence(user, file, written, payment=None, entry=None):
    if file is None: return None
    original=file.name[:200]
    optimized,thumbnail,suffix=prepare_evidence(file)
    proof=FinancialEvidence(payment=payment,ledger_entry=entry,original_name=original,uploaded_by=user)
    target=payment or entry
    date=target.date.isoformat()
    label=f'bayar-{payment.invoice.kind}-{payment.pk}' if payment else f'kas-{entry.pk}'
    proof.file.save(f'{date}-{label}-{uuid.uuid4().hex[:12]}{suffix}',optimized,save=False)
    written.append(proof.file)
    if thumbnail:
        proof.thumbnail.save(f'{uuid.uuid4().hex}.jpg',thumbnail,save=False)
        written.append(proof.thumbnail)
    proof.full_clean()
    proof.save()
    proof.original_name=evidence_filename(proof)
    proof.save(update_fields=['original_name'])
    audit(user,'financial_evidence.created',proof.pk,payment_id=payment.pk if payment else None,ledger_id=entry.pk if entry else None)
    return proof


def record_payment(user, invoice_id, value, date, reference, request_key, evidence=None):
    require_access(user)
    with financial_transaction() as written:
        # Lock procurement first: cancellation and payment use the same lock order.
        order_id=Invoice.objects.values_list('procurement_id',flat=True).get(pk=invoice_id)
        order=Procurement.objects.select_for_update().get(pk=order_id)
        invoice = Invoice.objects.select_for_update().get(pk=invoice_id)
        if order.status=='cancelled':raise ValidationError('Pengadaan dibatalkan. Pembayaran ditolak.')
        if invoice.kind not in INVOICE_KINDS: raise ValidationError('Jenis invoice tidak valid.')
        value = amount(value)
        existing=Payment.objects.filter(request_key=request_key).first()
        if existing:
            if existing.invoice_id != invoice.pk or existing.amount != value or existing.date != date or existing.reference != reference:
                raise ValidationError('Referensi permintaan telah digunakan untuk pembayaran berbeda.')
            if existing.cancelled_at:raise ValidationError('Permintaan pembayaran ini sudah dibatalkan. Gunakan form baru.')
            return existing
        if date > timezone.localdate(): raise ValidationError('Tanggal pembayaran tidak boleh di masa depan.')
        if value > invoice.remaining: raise ValidationError('Pembayaran melebihi sisa tagihan.')
        wallet=None
        if invoice.kind in ['supplier','kms']:
            wallet=Wallet.objects.select_for_update().get(pk=kms_wallet().pk)
            if invoice.kind=='supplier' and value>balance(wallet):
                raise ValidationError('Dana KMS belum mencukupi untuk pembayaran supplier. Hubungi Owner untuk pencatatan uang masuk.')
        validate_evidence(evidence)
        payment=Payment.objects.create(invoice=invoice,amount=value,date=date,reference=reference,request_key=request_key,created_by=user)
        if wallet:
            signed=-value if invoice.kind=='supplier' else value
            LedgerEntry.objects.create(wallet=wallet,payment=payment,amount=signed,date=date,description=f'{invoice.get_kind_display()} · {invoice.code}'[:200],created_by=user)
        save_financial_evidence(user,evidence,written,payment=payment)
        audit(user,'payment.created',invoice.code,payment_id=payment.pk,amount=str(value))
        return payment


def cash_movement(user,value,direction,date,description,request_key,evidence=None):
    require_access(user)
    with financial_transaction() as written:
        wallet=Wallet.objects.select_for_update().get(pk=kms_wallet().pk)
        value=amount(value)
        if direction not in ['income','expense']:raise ValidationError('Jenis mutasi tidak valid.')
        signed=-value if direction=='expense' else value
        existing=LedgerEntry.objects.filter(request_key=request_key).first()
        if existing:
            if existing.payment_id or existing.wallet_id!=wallet.pk or existing.amount!=signed or existing.date!=date or existing.description!=description:
                raise ValidationError('Referensi permintaan telah digunakan untuk mutasi berbeda.')
            if existing.cancelled_at:raise ValidationError('Mutasi ini sudah dibatalkan. Gunakan form baru.')
            return existing
        if date>timezone.localdate():raise ValidationError('Tanggal mutasi tidak boleh di masa depan.')
        if direction=='expense' and value>balance(wallet):raise ValidationError('Uang keluar melebihi saldo dana KMS.')
        validate_evidence(evidence)
        entry=LedgerEntry.objects.create(wallet=wallet,amount=signed,date=date,description=description,request_key=request_key,created_by=user)
        save_financial_evidence(user,evidence,written,entry=entry)
        audit(user,'cash.created',entry.pk,amount=str(signed))
        return entry


def attach_payment_evidence(user,payment_id,file):
    require_access(user)
    with financial_transaction() as written:
        payment=Payment.objects.select_for_update().get(pk=payment_id)
        return save_financial_evidence(user,file,written,payment=payment)


def attach_cash_evidence(user,entry_id,file):
    require_access(user)
    with financial_transaction() as written:
        entry=LedgerEntry.objects.select_for_update().get(pk=entry_id)
        return save_financial_evidence(user,file,written,entry=entry)


@transaction.atomic
def save_purchase_lines(user,order_id,formset,revision):
    require_access(user)
    order=Procurement.objects.select_for_update().get(pk=order_id)
    if order.status!='draft':raise ValidationError('Pengadaan sudah dikunci.')
    if order.revision!=revision:raise ValidationError('Pengadaan telah berubah di tab atau akun lain. Muat ulang sebelum menyimpan.')
    if not formset.is_valid():raise ValidationError('Periksa isian barang dan harga supplier.')
    existing={i.pk:i for i in order.items.select_related('product','supplier_quote')}
    submitted=[f.cleaned_data.get('id') for f in formset.forms if f.cleaned_data.get('id')]
    if len(submitted)!=len(set(submitted)) or set(submitted)!=set(existing):
        raise ValidationError('Daftar baris tidak sesuai pengadaan. Muat ulang halaman; hapus baris melalui tombol Hapus.')
    for form in formset:
        data=form.cleaned_data
        if not data:continue
        pk=data.get('id')
        if data.get('DELETE'):
            if pk:
                require_owner(user)
                existing[pk].delete()
            continue
        item=existing[pk] if pk else OrderItem(procurement=order,kms_price=0,cooperative_price=0,kitchen_price=0)
        product_changed=bool(pk and item.product_id!=data['product'].pk)
        same_purchase=bool(pk and item.product_id==data['product'].pk and item.supplier_id==data['supplier'].pk and item.supplier_price==data['supplier_price'])
        old_quote=item.supplier_quote if same_purchase and item.supplier_quote_id and item.supplier_quote.unit==data['product'].unit else None
        item.product=data['product'];item.supplier=data['supplier'];item.quantity=data['quantity'];item.supplier_price=data['supplier_price']
        item.supplier_quote=data.get('supplier_quote') or old_quote
        if not item.supplier_quote:
            item.supplier_quote=SupplierPrice.objects.create(product=item.product,supplier=item.supplier,price=item.supplier_price,unit=item.product.unit,effective_date=timezone.localdate(),created_by=user,note=f'Harga transaksi {order.code}')
            audit(user,'supplier_price.created',item.supplier_quote_id,source=order.code)
        if product_changed:item.kms_price=item.cooperative_price=item.kitchen_price=Decimal('0')
        item.full_clean();item.save()
        SupplierProduct.objects.get_or_create(product=item.product,supplier=item.supplier)
    order.revision+=1;order.save(update_fields=['revision'])
    audit(user,'procurement.purchase_lines_saved',order.code,revision=order.revision)
    return order


@transaction.atomic
def save_sales_lines(user,order_id,formset,revision):
    require_access(user)
    order=Procurement.objects.select_for_update().get(pk=order_id)
    if order.status!='draft':raise ValidationError('Pengadaan sudah dikunci.')
    if order.revision!=revision:raise ValidationError('Pengadaan telah berubah di tab atau akun lain. Muat ulang sebelum menyimpan.')
    if not formset.is_valid():raise ValidationError('Periksa harga jual seluruh barang.')
    items={i.pk:i for i in order.items.all()}
    ids=[f.cleaned_data.get('id') for f in formset]
    if len(ids)!=len(set(ids)) or set(ids)!=set(items):raise ValidationError('Daftar barang berubah. Muat ulang sebelum menyimpan harga.')
    for form in formset:
        data=form.cleaned_data;item=items[data['id']]
        item.kms_price=data['kms_price']
        item.cooperative_price=data['cooperative_price'];item.kitchen_price=data['kitchen_price']
        item.full_clean();item.save(update_fields=['kms_price','cooperative_price','kitchen_price'])
    order.revision+=1;order.save(update_fields=['revision'])
    audit(user,'procurement.sales_lines_saved',order.code,revision=order.revision)
    return order


def require_owner(user):
    if not is_owner(user):raise PermissionDenied('Pembatalan / hapus hanya untuk Owner atau Super Admin.')


def profile_snapshot(profile):
    data={key:getattr(profile,key) for key in ['title','heading','address','bank_info','signature','footer','style','signers']}
    data.update(logo_left=profile.logo_left.name,logo_right=profile.logo_right.name)
    return data


def evidence_filename(proof):
    from django.utils.text import slugify
    from pathlib import PurePath
    if proof.payment_id:
        payment=proof.payment; invoice=payment.invoice
        label=f'{invoice.procurement.code}-{invoice.kind}-{invoice.code}-bayar-{payment.pk}'
        date=payment.date
        cancelled=bool(payment.cancelled_at)
    else:
        entry=proof.ledger_entry
        label=f'kas-{entry.pk}-'+('masuk-' if entry.amount>0 else 'keluar-')+entry.description[:70]
        date=entry.date
        cancelled=bool(entry.cancelled_at)
    suffix=PurePath(proof.file.name).suffix.lower()
    return f'{date.isoformat()}-{slugify(label)[:150]}'+('-batal' if cancelled else '')+f'-bukti-{proof.pk}{suffix}'


def cancellation_reason(reason):
    reason=str(reason).strip()
    if not 5<=len(reason)<=300:raise ValidationError('Isi alasan pembatalan 5 sampai 300 karakter.')
    return reason


@transaction.atomic
def cancel_payment(user,payment_id,reason):
    require_owner(user);reason=cancellation_reason(reason)
    order_id=Payment.objects.values_list('invoice__procurement_id',flat=True).get(pk=payment_id)
    Procurement.objects.select_for_update().get(pk=order_id)
    invoice_id=Payment.objects.values_list('invoice_id',flat=True).get(pk=payment_id)
    Invoice.objects.select_for_update().get(pk=invoice_id)
    payment=Payment.objects.select_for_update().get(pk=payment_id)
    if payment.cancelled_at:return payment
    wallet=Wallet.objects.select_for_update().get(pk=kms_wallet().pk)
    entry=LedgerEntry.objects.filter(payment=payment,cancelled_at__isnull=True).first()
    if entry and balance(wallet)-entry.amount<0:
        raise ValidationError('Pembatalan membuat saldo negatif. Catat pengembalian / tambahan dana terlebih dahulu.')
    now=timezone.now()
    if entry:entry.cancelled_at=now;entry.cancellation_reason=reason;entry.save(update_fields=['cancelled_at','cancellation_reason'])
    payment.cancelled_at=now;payment.cancellation_reason=reason;payment.save(update_fields=['cancelled_at','cancellation_reason'])
    audit(user,'payment.cancelled',payment.invoice.code,payment_id=payment.pk,reason=reason,amount=str(payment.amount))
    return payment


@transaction.atomic
def cancel_cash(user,entry_id,reason):
    require_owner(user);reason=cancellation_reason(reason)
    wallet=Wallet.objects.select_for_update().get(pk=kms_wallet().pk)
    entry=LedgerEntry.objects.select_for_update().get(pk=entry_id,wallet=wallet)
    if entry.payment_id:raise ValidationError('Batalkan melalui pembayaran invoice agar kas dan tagihan tetap sesuai.')
    if entry.cancelled_at:return entry
    if balance(wallet)-entry.amount<0:raise ValidationError('Pembatalan membuat saldo negatif. Catat pengembalian / tambahan dana terlebih dahulu.')
    entry.cancelled_at=timezone.now();entry.cancellation_reason=reason;entry.save(update_fields=['cancelled_at','cancellation_reason'])
    audit(user,'cash.cancelled',entry.pk,reason=reason,amount=str(entry.amount))
    return entry


@transaction.atomic
def cancel_order(user,order_id,reason):
    require_owner(user);reason=cancellation_reason(reason)
    order=Procurement.objects.select_for_update().get(pk=order_id)
    if order.status=='cancelled':return order
    # Require explicit reconciliation of each payment before cancelling its documents.
    if Payment.objects.filter(invoice__procurement=order,cancelled_at__isnull=True).exists():
        raise ValidationError('Batalkan semua pembayaran pengadaan ini terlebih dahulu. Dana yang benar-benar berpindah harus diselesaikan sebelum membatalkan tagihannya.')
    order.status='cancelled';order.cancelled_at=timezone.now();order.cancellation_reason=reason;order.revision+=1
    order.save(update_fields=['status','cancelled_at','cancellation_reason','revision'])
    audit(user,'procurement.cancelled',order.code,reason=reason)
    return order
