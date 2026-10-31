"""Keep existing transactions intact; import their supplier prices as dated history."""
from django.db import migrations
from django.utils import timezone


def import_history(apps, schema_editor):
    Item = apps.get_model('core', 'OrderItem')
    Price = apps.get_model('core', 'SupplierPrice')
    Invoice = apps.get_model('core', 'Invoice')
    db = schema_editor.connection.alias
    for invoice in Invoice.objects.using(db).filter(number__isnull=True).iterator():
        Invoice.objects.using(db).filter(pk=invoice.pk).update(number=f'INV-{invoice.pk:05d}')
    for item in Item.objects.using(db).select_related('procurement', 'product').filter(supplier_quote__isnull=True, supplier_price__gt=0).order_by('procurement__created_at', 'pk').iterator():
        created = timezone.localtime(item.procurement.created_at).date()
        quote = Price.objects.using(db).create(
            product_id=item.product_id, supplier_id=item.supplier_id,
            price=item.supplier_price, unit=item.unit or item.product.unit,
            effective_date=created, created_by_id=item.procurement.created_by_id,
            note=f'Impor harga transaksi V1 #{item.procurement_id}',
        )
        Item.objects.using(db).filter(pk=item.pk).update(supplier_quote_id=quote.pk)


class Migration(migrations.Migration):
    dependencies = [('core', '0002_invoiceprofile_invoice_number_invoice_print_snapshot_and_more')]
    operations = [migrations.RunPython(import_history, migrations.RunPython.noop)]
