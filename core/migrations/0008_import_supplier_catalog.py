from django.db import migrations


def import_catalog(apps,schema_editor):
    db=schema_editor.connection.alias
    Link=apps.get_model('core','SupplierProduct')
    for model in ['SupplierPrice','OrderItem']:
        Source=apps.get_model('core',model)
        for product,supplier in Source.objects.using(db).order_by().values_list('product_id','supplier_id').distinct().iterator():
            Link.objects.using(db).get_or_create(product_id=product,supplier_id=supplier)


class Migration(migrations.Migration):
    dependencies=[('core','0007_procurement_revision_supplierproduct')]
    operations=[migrations.RunPython(import_catalog,migrations.RunPython.noop)]
