from django.db import migrations


def freeze(apps,schema_editor):
    Order=apps.get_model('core','Procurement')
    Invoice=apps.get_model('core','Invoice')
    for order in Order.objects.exclude(status='draft').filter(report_snapshot={}).iterator():
        invoice=Invoice.objects.filter(procurement=order,kind='kms').first()
        config=dict(invoice.print_snapshot) if invoice else {}
        config['title']='PENAWARAN HARGA'
        order.report_snapshot=config
        order.save(update_fields=['report_snapshot'])


class Migration(migrations.Migration):
    dependencies=[('core','0009_ledgerentry_cancellation_reason_and_more')]
    operations=[migrations.RunPython(freeze,migrations.RunPython.noop)]
