from decimal import Decimal
from datetime import timedelta
from django.test import TestCase,TransactionTestCase
from django.urls import reverse
from django.core.exceptions import ValidationError
from django.utils import timezone
from .tests import FixtureMixin
from .models import Product,Partner,OrderItem,Invoice,SupplierPrice,SupplierProduct,Procurement
from .forms import PurchaseFormSet,SalesFormSet
from .services import save_purchase_lines,save_sales_lines,record_quote


class BulkEntryTests(FixtureMixin,TestCase):
    def purchase_data(self,rows,revision=0):
        data={'revision':revision,'items-TOTAL_FORMS':len(rows),'items-INITIAL_FORMS':1,'items-MIN_NUM_FORMS':1,'items-MAX_NUM_FORMS':200,'action':'next'}
        for index,row in enumerate(rows):
            for key,value in row.items():data[f'items-{index}-{key}']=str(value) if value is not None else ''
        return data
    def purchase_row(self,**changes):
        row={'id':self.item.pk,'product':self.product.pk,'supplier':self.supplier.pk,'quantity':'100','supplier_price':'13000'}
        row.update(changes);return row
    def sales_data(self,items,revision=0,action='review'):
        data={'revision':revision,'prices-TOTAL_FORMS':len(items),'prices-INITIAL_FORMS':len(items),'prices-MIN_NUM_FORMS':1,'prices-MAX_NUM_FORMS':200,'action':action}
        for index,item in enumerate(items):
            for name,value in {'id':item.pk,'kms_price':'13500','cooperative_price':'14000','kitchen_price':'14500'}.items():data[f'prices-{index}-{name}']=str(value)
        return data
    def test_bulk_two_stages_preserve_existing_invoice_flow(self):
        self.client.force_login(self.owner)
        product=Product.objects.create(code='P2',name='Ayam potong',category='Protein',unit='kg')
        supplier=Partner.objects.create(name='Supplier B',kind='supplier')
        data=self.purchase_data([self.purchase_row(),self.purchase_row(id=None,product=product.pk,supplier=supplier.pk,quantity='20',supplier_price='35000')])
        response=self.client.post(reverse('purchase_lines',args=[self.order.pk]),data)
        self.assertRedirects(response,reverse('sales_lines',args=[self.order.pk]))
        self.assertEqual(self.order.items.count(),2);self.assertEqual(Invoice.objects.count(),0)
        self.order.refresh_from_db();items=list(self.order.items.order_by('pk'))
        self.assertEqual(items[1].kms_price,0)
        data=self.sales_data(items,self.order.revision)
        response=self.client.post(reverse('sales_lines',args=[self.order.pk]),data)
        self.assertRedirects(response,reverse('order_detail',args=[self.order.pk]))
        self.assertEqual(Invoice.objects.count(),0)
        self.confirm()
        self.assertEqual(self.order.invoices.count(),5)
        self.assertEqual(self.order.invoices.filter(kind='supplier').count(),2)
    def test_back_saves_partial_prices_without_losing_buyer_details(self):
        self.client.force_login(self.owner)
        data=self.sales_data([self.item],action='back')
        data['prices-0-kitchen_price']=''
        response=self.client.post(reverse('sales_lines',args=[self.order.pk]),data)
        self.assertRedirects(response,reverse('purchase_lines',args=[self.order.pk]))
        self.item.refresh_from_db();self.assertEqual(self.item.cooperative_price,Decimal('14000'));self.assertEqual(self.item.kitchen_price,0)
        self.assertEqual(self.item.quantity,Decimal('100'));self.assertEqual(self.item.supplier_id,self.supplier.pk)
        self.assertContains(self.client.get(reverse('sales_lines',args=[self.order.pk])),'14000')
    def test_invalid_later_purchase_row_rolls_back_entire_batch(self):
        data=self.purchase_data([self.purchase_row(quantity='999'),self.purchase_row(id=None,quantity='-2')])
        formset=PurchaseFormSet(data,prefix='items')
        with self.assertRaises(ValidationError):save_purchase_lines(self.owner,self.order.pk,formset,0)
        self.item.refresh_from_db();self.assertEqual(self.item.quantity,Decimal('100'))
        self.assertEqual(SupplierPrice.objects.count(),0)
    def test_forged_and_duplicate_line_ids_cannot_modify_another_order(self):
        other=Procurement.objects.create(cooperative=self.coop,kitchen=self.kitchen,delivery_date=timezone.localdate(),created_by=self.owner)
        foreign=OrderItem.objects.create(procurement=other,product=self.product,supplier=self.supplier,quantity=1,supplier_price=1,kms_price=2,cooperative_price=3,kitchen_price=4)
        for rows in [[self.purchase_row(id=foreign.pk)],[self.purchase_row(),self.purchase_row()]]:
            formset=PurchaseFormSet(self.purchase_data(rows),prefix='items')
            with self.assertRaises(ValidationError):save_purchase_lines(self.owner,self.order.pk,formset,0)
        foreign.refresh_from_db();self.assertEqual(foreign.quantity,1)
    def test_stale_revision_and_confirmed_order_cannot_be_overwritten(self):
        data=self.purchase_data([self.purchase_row(quantity='120')])
        save_purchase_lines(self.owner,self.order.pk,PurchaseFormSet(data,prefix='items'),0)
        with self.assertRaises(ValidationError):save_purchase_lines(self.owner,self.order.pk,PurchaseFormSet(data,prefix='items'),0)
        self.order.refresh_from_db();self.confirm()
        with self.assertRaises(ValidationError):save_purchase_lines(self.owner,self.order.pk,PurchaseFormSet(data,prefix='items'),self.order.revision)
    def test_operator_can_set_kms_price_in_sales_stage(self):
        data=self.purchase_data([self.purchase_row()]);data['items-0-kms_price']='999999'
        save_purchase_lines(self.operator,self.order.pk,PurchaseFormSet(data,prefix='items'),0)
        self.order.refresh_from_db();self.item.refresh_from_db()
        data=self.sales_data([self.item],self.order.revision);data['prices-0-kms_price']='999999'
        initial=[{'id':self.item.pk,'kms_price':self.item.kms_price}]
        formset=SalesFormSet(data,initial=initial,prefix='prices',form_kwargs={'user':self.operator})
        save_sales_lines(self.operator,self.order.pk,formset,self.order.revision)
        self.item.refresh_from_db();self.assertEqual(self.item.kms_price,Decimal('999999'))
    def test_explicit_delete_and_product_change_reset_sales_prices(self):
        data=self.purchase_data([self.purchase_row(DELETE='on'),self.purchase_row(id=None,quantity='3')])
        save_purchase_lines(self.owner,self.order.pk,PurchaseFormSet(data,prefix='items'),0)
        self.assertFalse(OrderItem.objects.filter(pk=self.item.pk).exists())
        new=self.order.items.get();self.assertEqual(new.kms_price,0)
    def test_purchase_next_does_not_duplicate_unchanged_price_history(self):
        data=self.purchase_data([self.purchase_row()])
        save_purchase_lines(self.owner,self.order.pk,PurchaseFormSet(data,prefix='items'),0)
        self.order.refresh_from_db();self.item.refresh_from_db()
        data=self.purchase_data([self.purchase_row()],revision=self.order.revision)
        save_purchase_lines(self.owner,self.order.pk,PurchaseFormSet(data,prefix='items'),self.order.revision)
        self.assertEqual(SupplierPrice.objects.count(),1)
    def test_sales_review_requires_all_prices_and_exact_item_set(self):
        self.client.force_login(self.owner)
        data=self.sales_data([self.item]);data['prices-0-cooperative_price']=''
        response=self.client.post(reverse('sales_lines',args=[self.order.pk]),data)
        self.assertEqual(response.status_code,200);self.assertTrue(response.context['formset'].errors)
        self.item.refresh_from_db();self.assertEqual(self.item.cooperative_price,Decimal('14000'))
        self.assertEqual(Invoice.objects.count(),0)
    def test_bulk_pages_render_and_server_limits_rows(self):
        self.client.force_login(self.owner)
        self.assertContains(self.client.get(reverse('purchase_lines',args=[self.order.pk])),'Lanjut ke semua harga jual')
        self.assertContains(self.client.get(reverse('sales_lines',args=[self.order.pk])),'Simpan & kembali ke barang')
        data={'items-TOTAL_FORMS':'9999','items-INITIAL_FORMS':'0'}
        formset=PurchaseFormSet(data,prefix='items')
        self.assertFalse(formset.is_valid());self.assertEqual(len(formset.forms),220)


    def test_operator_can_complete_kms_price_before_owner_confirmation(self):
        self.item.kms_price=0;self.item.save()
        self.client.force_login(self.operator)
        data=self.sales_data([self.item]);data['prices-0-kms_price']='99999'
        response=self.client.post(reverse('sales_lines',args=[self.order.pk]),data)
        self.assertRedirects(response,reverse('order_detail',args=[self.order.pk]))
        self.item.refresh_from_db();self.assertEqual(self.item.kms_price,Decimal('99999'))
        self.assertEqual(self.item.cooperative_price,Decimal('14000'))
        self.confirm()
    def test_small_decimal_quantity_and_price_are_accepted_exactly(self):
        data=self.purchase_data([self.purchase_row(quantity='0.01',supplier_price='0.01')])
        formset=PurchaseFormSet(data,prefix='items')
        self.assertTrue(formset.is_valid(),formset.errors)
        save_purchase_lines(self.owner,self.order.pk,formset,0)
        self.item.refresh_from_db();self.assertEqual(self.item.quantity,Decimal('0.01'))


class CatalogTests(FixtureMixin,TestCase):
    def setUp(self):
        super().setUp();self.client.force_login(self.owner)
    def quote(self,product,supplier,price,days=0):
        return SupplierPrice.objects.create(product=product,supplier=supplier,price=price,unit=product.unit,effective_date=timezone.localdate()+timedelta(days=days),created_by=self.owner)
    def test_by_product_shows_all_suppliers_latest_current_prices_and_history(self):
        b=Partner.objects.create(name='Supplier B',kind='supplier')
        a_link=SupplierProduct.objects.create(product=self.product,supplier=self.supplier)
        SupplierProduct.objects.create(product=self.product,supplier=b)
        self.quote(self.product,self.supplier,12000,-2);self.quote(self.product,self.supplier,13000);self.quote(self.product,self.supplier,9999,2);self.quote(self.product,b,13500)
        page=self.client.get(reverse('catalog'),{'product':self.product.pk})
        rows=list(page.context['page']);self.assertEqual(len(rows),2)
        self.assertEqual(sorted(row.latest_price for row in rows),[Decimal('13000'),Decimal('13500')])
        page=self.client.get(reverse('catalog_history',args=[a_link.pk]))
        self.assertEqual(page.context['page'].paginator.count,3);self.assertContains(page,'Belum berlaku')
    def test_supplier_can_list_products_without_price_or_purchase(self):
        other=Product.objects.create(code='N',name='Barang belum dibeli',unit='dus',category='Tes')
        SupplierProduct.objects.create(product=other,supplier=self.supplier)
        page=self.client.get(reverse('catalog'),{'mode':'supplier','supplier':self.supplier.pk})
        self.assertEqual(len(page.context['page']),1)
        self.assertContains(page,'Barang belum dibeli');self.assertContains(page,'Belum ada harga')
    def test_register_supply_without_price_and_keyword_search(self):
        response=self.client.post(reverse('catalog_create'),{'product':self.product.pk,'supplier':self.supplier.pk,'note':'Tersedia harian','active':'on'})
        self.assertEqual(response.status_code,302);self.assertEqual(SupplierProduct.objects.count(),1)
        page=self.client.get(reverse('catalog'),{'q':'P001'})
        self.assertEqual(page.context['page'].paginator.count,1)
        self.client.logout();self.assertEqual(self.client.get(reverse('catalog')).status_code,302)
class CatalogMigrationTests(TransactionTestCase):
    def test_existing_quotes_and_purchases_populate_catalog_without_duplicates(self):
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor
        before=('core','0007_procurement_revision_supplierproduct');target=('core','0008_import_supplier_catalog')
        try:
            executor=MigrationExecutor(connection);executor.migrate([before]);apps=executor.loader.project_state([before]).apps
            User=apps.get_model('auth','User');Partner=apps.get_model('core','Partner');Product=apps.get_model('core','Product')
            Quote=apps.get_model('core','SupplierPrice');Order=apps.get_model('core','Procurement');Item=apps.get_model('core','OrderItem')
            user=User.objects.create(username='catalog-migration')
            supplier=Partner.objects.create(name='Supplier',kind='supplier');coop=Partner.objects.create(name='Koperasi',kind='cooperative');kitchen=Partner.objects.create(name='Dapur',kind='kitchen')
            product=Product.objects.create(code='Q',name='Produk penawaran',category='Tes',unit='kg')
            other=Product.objects.create(code='P',name='Produk pembelian',category='Tes',unit='kg')
            for price in [100,120]:Quote.objects.create(product=product,supplier=supplier,price=price,unit='kg',effective_date=timezone.localdate(),created_by=user)
            order=Order.objects.create(cooperative=coop,kitchen=kitchen,delivery_date=timezone.localdate(),created_by=user)
            Item.objects.create(procurement=order,product=other,supplier=supplier,quantity=1,supplier_price=100,kms_price=120,cooperative_price=130,kitchen_price=140)
            executor=MigrationExecutor(connection);executor.migrate([target]);apps=executor.loader.project_state([target]).apps
            self.assertEqual(apps.get_model('core','SupplierProduct').objects.count(),2)
            self.assertEqual(apps.get_model('core','SupplierPrice').objects.count(),2)
            self.assertEqual(apps.get_model('core','OrderItem').objects.get().supplier_price,Decimal('100'))
        finally:MigrationExecutor(connection).migrate([('core','0010_freeze_existing_procurement_reports')])
