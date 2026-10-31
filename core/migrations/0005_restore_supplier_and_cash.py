"""Restore missing supplier bills and cash postings without duplicating V1 records."""
from datetime import timedelta
from decimal import Decimal
from django.db import migrations
from django.utils import timezone


def restore(apps,schema_editor):
    db=schema_editor.connection.alias
    Order=apps.get_model('core','Procurement')
    Invoice=apps.get_model('core','Invoice')
    Payment=apps.get_model('core','Payment')
    Wallet=apps.get_model('core','Wallet')
    Entry=apps.get_model('core','LedgerEntry')
    wallet,_=Wallet.objects.using(db).get_or_create(name='KMS')
    for order in Order.objects.using(db).exclude(status='draft').iterator():
        grouped={}
        for item in order.items.using(db).select_related('supplier').order_by('supplier_id','pk'):
            supplier,total=grouped.get(item.supplier_id,(item.supplier,Decimal('0')))
            grouped[item.supplier_id]=(supplier,total+(item.quantity*item.supplier_price).quantize(Decimal('0.01')))
        for supplier,total in grouped.values():
            if Invoice.objects.using(db).filter(procurement_id=order.pk,kind='supplier',supplier_id=supplier.pk).exists():continue
            invoice=Invoice.objects.using(db).create(procurement_id=order.pk,kind='supplier',supplier_id=supplier.pk,issuer_name=supplier.name,recipient_name='KMS',total=total,due_date=order.delivery_date+timedelta(days=14),print_snapshot={'title':'TAGIHAN SUPPLIER','style':'classic','footer':'Dipulihkan dari harga beli pada pengadaan. Cocokkan dengan tagihan supplier sebelum pembayaran.'})
            base=f'SUP-REC-{invoice.pk:05d}';number=base;suffix=1
            while Invoice.objects.using(db).filter(number=number).exists():
                number=f'{base}-{suffix}';suffix+=1
            Invoice.objects.using(db).filter(pk=invoice.pk).update(number=number,created_at=order.confirmed_at or order.created_at)
    for payment in Payment.objects.using(db).filter(invoice__kind__in=['kms','supplier']).select_related('invoice').iterator():
        if Entry.objects.using(db).filter(payment_id=payment.pk).exists():continue
        signed=-payment.amount if payment.invoice.kind=='supplier' else payment.amount
        entry=Entry.objects.using(db).create(wallet_id=wallet.pk,payment_id=payment.pk,amount=signed,date=payment.date,description=f'Rekonsiliasi pembayaran {payment.invoice.number or payment.invoice.pk}'[:200],created_by_id=payment.created_by_id)
        Entry.objects.using(db).filter(pk=entry.pk).update(created_at=payment.created_at)
    for entry in Entry.objects.using(db).select_related('payment').iterator():
        date=entry.payment.date if entry.payment_id else timezone.localtime(entry.created_at).date()
        Entry.objects.using(db).filter(pk=entry.pk).update(date=date)


class Migration(migrations.Migration):
    dependencies=[('core','0004_ledgerentry_date_alter_invoice_kind_and_more')]
    operations=[migrations.RunPython(restore,migrations.RunPython.noop)]
