import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied,ValidationError
from django.test import TestCase,TransactionTestCase,Client
from django.urls import reverse
from django.utils import timezone
from django.db import close_old_connections,connection
from .models import Partner,Product,Procurement,OrderItem,Invoice,Wallet,Payment,AuditEvent,LedgerEntry,SupplierPrice,InvoiceProfile,InvoiceCounter,FinancialEvidence
from .forms import ItemForm,AttachmentForm,SupplierPriceForm,InvoiceProfileForm
from .services import confirm_order,record_payment,save_item,delete_item,supplier_offers,record_quote,cash_movement,balance

class FixtureMixin:
    def setUp(self):
        self.owner=get_user_model().objects.create_user('owner',password='Unit-test-secret-932!')
        self.operator=get_user_model().objects.create_user('operator',password='Unit-test-secret-932!')
        self.owner.groups.add(Group.objects.create(name='Owner'))
        self.operator.groups.add(Group.objects.create(name='Admin Operasional'))
        Wallet.objects.get_or_create(name='KMS')
        self.coop=Partner.objects.create(name='Koperasi',kind='cooperative')
        self.kitchen=Partner.objects.create(name='Dapur',kind='kitchen')
        self.supplier=Partner.objects.create(name='Supplier',kind='supplier')
        self.product=Product.objects.create(code='P001',name='Beras',category='Sembako',unit='kg')
        self.order=Procurement.objects.create(cooperative=self.coop,kitchen=self.kitchen,delivery_date=timezone.localdate(),created_by=self.operator)
        self.item=OrderItem.objects.create(procurement=self.order,product=self.product,supplier=self.supplier,quantity='100',supplier_price='13000',kms_price='13500',cooperative_price='14000',kitchen_price='14500')
    def fund(self,value='10000000'):
        return cash_movement(self.owner,value,'income',timezone.localdate(),'Modal awal',uuid.uuid4())
    def confirm(self): confirm_order(self.owner,self.order.pk)
    def pay(self,invoice,value,key=None):return record_payment(self.operator,invoice.pk,value,timezone.localdate(),'TEST',key or uuid.uuid4())

class BusinessTests(FixtureMixin,TestCase):
    def test_confirmation_generates_sales_invoices_and_separate_supplier_bills(self):
        supplier2=Partner.objects.create(name='Supplier B',kind='supplier')
        OrderItem.objects.create(procurement=self.order,product=self.product,supplier=supplier2,quantity='0.25',supplier_price='13000.02',kms_price='13500.02',cooperative_price='14000.02',kitchen_price='14500')
        self.confirm()
        self.assertEqual(self.order.invoices.count(),5)
        self.assertEqual(self.order.invoices.filter(kind="supplier").count(),2)
        self.assertEqual(self.order.invoices.get(kind="supplier",supplier=self.supplier).total,Decimal("1300000"))
        self.assertEqual(self.order.invoices.get(kind="kitchen").total,Decimal("1453625"))
        self.item.refresh_from_db();self.assertEqual(self.item.product_name,'Beras')
        self.assertEqual(self.order.invoices.get(kind='kms').total,Decimal('1353375.00'))
        self.product.name='Beras diubah';self.product.save()
        self.assertEqual(self.item.product_name,'Beras')
        with self.assertRaises(ValidationError):self.confirm()
    def test_locked_item_cannot_be_deleted(self):
        self.confirm()
        with self.assertRaises(ValidationError):delete_item(self.owner,self.order.pk,self.item.pk)
    def test_locked_item_cannot_be_saved_with_prevalidated_form(self):
        data={'product':self.product.pk,'supplier':self.supplier.pk,'quantity':10,'supplier_price':1,'kms_price':2,'cooperative_price':3,'kitchen_price':4}
        form=ItemForm(data,user=self.owner,instance=self.item);self.assertTrue(form.is_valid())
        self.confirm()
        with self.assertRaises(ValidationError):save_item(self.owner,self.order.pk,form,self.item.pk)
    def test_operator_can_set_kms_price_but_cannot_confirm(self):
        data={'product':self.product.pk,'supplier':self.supplier.pk,'quantity':100,'supplier_price':13000,'kms_price':99999,'cooperative_price':14000,'kitchen_price':14500}
        form=ItemForm(data,user=self.operator,instance=self.item);self.assertTrue(form.is_valid())
        save_item(self.operator,self.order.pk,form,self.item.pk)
        self.item.refresh_from_db();self.assertEqual(self.item.kms_price,Decimal('99999'))
        with self.assertRaises(PermissionDenied):confirm_order(self.operator,self.order.pk)
    def test_partial_payments_for_all_three_invoices(self):
        self.confirm()
        for kind in ['kms','cooperative','kitchen']:
            inv=self.order.invoices.get(kind=kind)
            self.pay(inv,'500000')
            self.assertEqual(inv.remaining,inv.total-Decimal('500000'))
            self.assertEqual(inv.payment_status,'Dibayar sebagian')
        self.assertEqual(LedgerEntry.objects.count(),1)
    def test_overpayment_is_atomic_without_wallet_requirement(self):
        self.confirm();Wallet.objects.all().delete()
        inv=self.order.invoices.get(kind='kitchen')
        with self.assertRaises(ValidationError):self.pay(inv,inv.total+1)
        self.assertEqual(Payment.objects.count(),0)
        self.pay(inv,inv.total)
        self.assertEqual(inv.remaining,0)
    def test_payment_retry_is_idempotent_and_rejects_changed_payload(self):
        self.confirm();inv=self.order.invoices.get(kind='kms');key=uuid.uuid4()
        one=self.pay(inv,'100000',key);two=self.pay(inv,'100000',key)
        self.assertEqual(one.pk,two.pk);self.assertEqual(Payment.objects.count(),1)
        with self.assertRaises(ValidationError):self.pay(inv,'200000',key)
    def test_owner_only_routes_and_report_data(self):
        self.confirm();self.client.force_login(self.operator)
        self.assertEqual(self.client.get(reverse('invoice_settings',args=['kms'])).status_code,403)
        self.assertEqual(self.client.get(reverse('audit')).status_code,403)
        report=self.client.get(reverse('reports'))
        self.assertNotContains(report,'Margin kotor KMS')
        self.assertNotIn('kms_margin',report.context['rows'][0])
        self.assertContains(report,'Koperasi');self.assertContains(report,'Dapur')
        dashboard=self.client.get(reverse('dashboard'))
        self.assertNotIn('balance',dashboard.context)
    def test_pages_render_and_owner_has_financial_access(self):
        self.confirm();self.client.force_login(self.owner)
        urls=['dashboard','products','partners','orders','order_create','invoices','supplier_prices','reports','audit']
        for name in urls:
            with self.subTest(name=name):self.assertEqual(self.client.get(reverse(name)).status_code,200)
        for inv in self.order.invoices.all():self.assertEqual(self.client.get(reverse('invoice_detail',args=[inv.pk])).status_code,200)
        self.assertEqual(self.client.get(reverse('order_detail',args=[self.order.pk])).status_code,200)
    def test_unauthenticated_and_unassigned_accounts_denied(self):
        self.assertEqual(self.client.get(reverse('dashboard')).status_code,302)
        user=get_user_model().objects.create_user('unassigned',password='test')
        self.client.force_login(user);self.assertEqual(self.client.get(reverse('dashboard')).status_code,403)
    def test_csrf_protection(self):
        client=Client(enforce_csrf_checks=True);client.force_login(self.owner)
        self.assertEqual(client.post(reverse('order_confirm',args=[self.order.pk])).status_code,403)
    def test_get_cannot_confirm(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse('order_confirm',args=[self.order.pk])).status_code,405)
    def test_negative_and_nonfinite_payment_rejected(self):
        self.confirm();inv=self.order.invoices.get(kind='kms')
        for value in ['-1','0','NaN','Infinity','0.001']:
            with self.subTest(value=value),self.assertRaises(ValidationError): self.pay(inv,value)
    def test_master_edits_do_not_change_invoice_identity(self):
        self.confirm();self.coop.name='Nama baru';self.coop.save()
        self.assertEqual(self.order.invoices.get(kind='kms').recipient_name,'Koperasi')
    def test_private_attachment_requires_login_and_rejects_script(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        bad=SimpleUploadedFile('evil.pdf',b'<script>alert(1)</script>',content_type='application/pdf')
        self.assertFalse(AttachmentForm(files={'file':bad}).is_valid())
        self.assertEqual(self.client.get('/evidence/1/').status_code,302)

class ConcurrencyTests(FixtureMixin,TransactionTestCase):
    def test_concurrent_payments_do_not_overpay(self):
        if connection.vendor!='postgresql':self.skipTest('PostgreSQL required')
        self.confirm();inv=self.order.invoices.get(kind='kms');uid=self.operator.pk
        def worker():
            close_old_connections()
            try:
                record_payment(get_user_model().objects.get(pk=uid),inv.pk,1000000,timezone.localdate(),'CONCURRENT',uuid.uuid4())
                return True
            except ValidationError:return False
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:worker(),range(2)))
        self.assertEqual(results.count(True),1)
        inv.refresh_from_db();self.assertEqual(inv.paid,Decimal('1000000'))

class WorkflowTests(FixtureMixin, TestCase):
    def test_operator_draft_owner_confirmation_and_payment_through_forms(self):
        self.client.force_login(self.operator)
        response = self.client.post(reverse('order_create'), {
            'cooperative': self.coop.pk, 'kitchen': self.kitchen.pk,
            'office_name':'Kantor Dapur A', 'delivery_date': timezone.localdate().isoformat(), 'notes': 'Uji alur form',
        })
        order = Procurement.objects.exclude(pk=self.order.pk).get()
        self.assertRedirects(response, reverse('purchase_lines', args=[order.pk]))
        response = self.client.post(reverse('item_create', args=[order.pk]), {
            'product': self.product.pk, 'supplier': self.supplier.pk,
            'quantity': '2', 'supplier_price': '13000', 'kms_price': '999999',
            'cooperative_price': '14000', 'kitchen_price': '14500',
        })
        self.assertEqual(response.status_code, 302)
        item = order.items.get()
        self.assertEqual(item.kms_price, Decimal("999999"))
        self.assertEqual(self.client.post(reverse('order_confirm', args=[order.pk])).status_code, 403)
        self.client.force_login(self.owner)
        self.client.post(reverse('item_edit', args=[order.pk, item.pk]), {
            'product': self.product.pk, 'supplier': self.supplier.pk,
            'quantity': '2', 'supplier_price': '13000', 'kms_price': '13500',
            'cooperative_price': '14000', 'kitchen_price': '14500',
        })
        response = self.client.post(reverse('order_confirm', args=[order.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(order.invoices.count(), 4)
        invoice = order.invoices.get(kind='kms')
        self.assertEqual(invoice.total, Decimal('27000'))
        self.client.force_login(self.operator)
        payload = {'amount': '10000', 'date': timezone.localdate().isoformat(),
                   'reference': 'Transfer percobaan', 'request_key': str(uuid.uuid4())}
        for _ in range(2):
            response = self.client.post(reverse('payment_create', args=[invoice.pk]), payload)
            self.assertEqual(response.status_code, 302)
        self.assertEqual(invoice.payments.count(), 1)
        self.assertEqual(invoice.remaining, Decimal('17000'))
        self.assertEqual(LedgerEntry.objects.count(), 1)
        for expected in ['shipped', 'received']:
            self.client.post(reverse('order_advance', args=[order.pk]))
            order.refresh_from_db()
            self.assertEqual(order.status, expected)


class PricingAndReportTests(FixtureMixin,TestCase):
    def quote(self,supplier,price,date=None,unit='kg'):
        return SupplierPrice.objects.create(product=self.product,supplier=supplier,price=price,unit=unit,effective_date=date or timezone.localdate(),created_by=self.owner)
    def test_supplier_comparison_uses_latest_eligible_quote_per_supplier(self):
        from datetime import timedelta
        today=timezone.localdate()
        b=Partner.objects.create(name='Supplier B',kind='supplier')
        c=Partner.objects.create(name='Supplier C',kind='supplier')
        self.quote(self.supplier,'11000',today-timedelta(days=3))
        chosen=self.quote(self.supplier,'12000')
        self.quote(self.supplier,'9999',today+timedelta(days=1))
        self.quote(b,'13000');self.quote(c,'13500')
        offers=supplier_offers(self.product.pk,today)
        self.assertEqual([q.price for q in offers],[Decimal('12000'),Decimal('13000'),Decimal('13500')])
        self.assertEqual(offers[0].pk,chosen.pk)
        self.assertEqual(SupplierPrice.objects.count(),5)
        b.active=False;b.save()
        self.assertEqual(len(supplier_offers(self.product.pk,today)),2)
    def test_quote_selection_is_validated_and_snapshotted(self):
        quote=self.quote(self.supplier,'12000')
        data={'product':self.product.pk,'supplier':self.supplier.pk,'quantity':100,'supplier_price':'12000','kms_price':'13500','cooperative_price':'14000','kitchen_price':'14500','supplier_quote':quote.pk}
        form=ItemForm(data,user=self.owner,instance=self.item)
        self.assertTrue(form.is_valid(),form.errors)
        save_item(self.owner,self.order.pk,form,self.item.pk)
        self.confirm()
        self.quote(self.supplier,'20000')
        self.item.refresh_from_db()
        self.assertEqual(self.item.supplier_price,Decimal('12000'))
        self.assertEqual(self.item.supplier_quote_id,quote.pk)
        self.assertEqual(self.order.invoices.get(kind='kms').total,Decimal('1350000'))
    def test_forged_quote_price_supplier_product_and_unit_rejected(self):
        quote=self.quote(self.supplier,'12000')
        other=Partner.objects.create(name='Autre',kind='supplier')
        data={'product':self.product.pk,'supplier':self.supplier.pk,'quantity':1,'supplier_price':'12000','kms_price':13500,'cooperative_price':14000,'kitchen_price':14500,'supplier_quote':quote.pk}
        for changes in [{'supplier_price':'1'},{'supplier':other.pk}]:
            form=ItemForm(dict(data,**changes),user=self.owner)
            self.assertFalse(form.is_valid())
        self.product.unit='dus';self.product.save()
        self.assertFalse(ItemForm(data,user=self.owner).is_valid())
        self.assertEqual(supplier_offers(self.product.pk,timezone.localdate()),[])
    def test_quote_form_appends_history_with_unit_and_author(self):
        self.client.force_login(self.operator)
        data={'product':self.product.pk,'supplier':self.supplier.pk,'price':'12000','effective_date':timezone.localdate().isoformat(),'note':'Penawaran'}
        for _ in range(2):self.assertEqual(self.client.post(reverse('supplier_prices'),data).status_code,302)
        self.assertEqual(SupplierPrice.objects.count(),2)
        quote=SupplierPrice.objects.first()
        self.assertEqual(quote.unit,'kg');self.assertEqual(quote.created_by,self.operator)
        self.assertEqual(self.client.get(reverse('supplier_offers'),{'product':self.product.pk}).json()['offers'][0]['price'],'12000.00')
    def test_missing_office_price_blocks_confirmation_and_rolls_back(self):
        self.item.kitchen_price=0;self.item.save()
        with self.assertRaises(ValidationError):self.confirm()
        self.assertEqual(Invoice.objects.count(),0)
        self.item.refresh_from_db();self.assertEqual(self.item.product_name,'')
    def test_office_price_below_purchase_is_rejected(self):
        self.item.kitchen_price=13000;self.item.save()
        with self.assertRaises(ValidationError):self.confirm()
    def test_omzet_profit_and_date_filters_use_invoice_values(self):
        self.confirm();self.client.force_login(self.owner)
        report=self.client.get(reverse('reports'))
        self.assertEqual(report.context['totals'],{'kms_sales':Decimal('1350000'),'kms_margin':Decimal('50000'),'coop_sales':Decimal('1400000'),'coop_margin':Decimal('50000'),'kitchen_sales':Decimal('1450000'),'kitchen_margin':Decimal('50000')})
        self.pay(self.order.invoices.get(kind='kitchen'),'10000')
        self.assertEqual(self.client.get(reverse('reports')).context['totals'],report.context['totals'])
        empty=self.client.get(reverse('reports'),{'start':'2099-01-01'})
        self.assertEqual(empty.context['rows'],[])
        invalid=self.client.get(reverse('reports'),{'start':'2026-02-02','end':'2026-01-01'})
        self.assertTrue(invalid.context['filter_form'].errors)
        self.client.force_login(self.operator)
        response=self.client.get(reverse('reports'))
        self.assertNotIn('kms_sales',response.context['totals'])
        self.assertNotIn('kms_margin',response.context['rows'][0])
        self.assertNotIn('kms_sales',self.client.get(reverse('dashboard')).context['totals'])
    def test_legacy_supplier_invoice_is_visible_and_payable_again(self):
        inv=Invoice.objects.create(procurement=self.order,kind='supplier',supplier=self.supplier,issuer_name='Supplier',recipient_name='KMS',total=10,due_date=timezone.localdate())
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse('invoice_detail',args=[inv.pk])).status_code,200)
        self.assertEqual(len(self.client.get(reverse('supplier_invoices')).context['page']),1)
        self.fund('100')
        self.pay(inv,'1')
        self.assertEqual(balance(),Decimal('99'))
    def test_removed_operational_routes_and_ui(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.post(f'/orders/{self.order.pk}/operating-entry/').status_code,404)
        self.assertEqual(self.client.get('/finance/').status_code,200)
        self.assertNotContains(self.client.get(reverse('order_detail',args=[self.order.pk])),'Realisasi koperasi')

class InvoiceNumberTests(FixtureMixin,TestCase):
    def test_number_and_print_settings_are_frozen_per_invoice(self):
        from .services import invoice_profile
        profile=invoice_profile('kitchen');profile.prefix='DAPUR';profile.heading='Kop Dapur';profile.bank_info='Bank ABC 123';profile.style='compact';profile.save()
        self.confirm()
        inv=self.order.invoices.get(kind='kitchen')
        self.assertTrue(inv.code.startswith('DAPUR/'))
        self.assertEqual(inv.recipient_name,'Kantor dapur')
        profile.heading='Kop baru';profile.prefix='BARU';profile.save()
        inv.refresh_from_db()
        self.assertEqual(inv.print_snapshot['heading'],'Kop Dapur')
        self.assertTrue(inv.code.startswith('DAPUR/'))
        self.client.force_login(self.owner)
        page=self.client.get(reverse('invoice_detail',args=[inv.pk]))
        self.assertContains(page,'Kop Dapur');self.assertContains(page,'Bank ABC 123');self.assertNotContains(page,'Kop baru')
    def test_settings_validate_format_and_reset_tokens(self):
        from django.core.exceptions import ValidationError
        for pattern,reset in [('{seq}','month'),('{prefix}/{seq}','year'),('{prefix}/{unknown}/{seq}','never'),('{prefix}/{year}','year'),('{prefix}/{seq.__class__}','never')]:
            profile=InvoiceProfile(kind='kms',prefix='KMS',number_pattern=pattern,reset=reset)
            with self.subTest(pattern=pattern),self.assertRaises(ValidationError):profile.full_clean()
    def test_number_counter_rolls_back_if_later_invoice_profile_invalid(self):
        from .services import invoice_profile
        profile=invoice_profile('kitchen');profile.number_pattern='{bad}';profile.save()
        with self.assertRaises(ValidationError):self.confirm()
        self.assertEqual(Invoice.objects.count(),0)
        self.assertEqual(InvoiceCounter.objects.count(),0)
        self.order.refresh_from_db();self.assertEqual(self.order.status,'draft')
    def test_number_sequence_continues_for_new_orders(self):
        self.confirm()
        first=self.order.invoices.get(kind='kms')
        order=Procurement.objects.create(cooperative=self.coop,kitchen=self.kitchen,delivery_date=timezone.localdate(),created_by=self.owner)
        OrderItem.objects.create(procurement=order,product=self.product,supplier=self.supplier,quantity=1,supplier_price=1,kms_price=2,cooperative_price=3,kitchen_price=4)
        confirm_order(self.owner,order.pk)
        self.assertTrue(first.code.endswith('00001'))
        self.assertTrue(order.invoices.get(kind='kms').code.endswith('00002'))
    def test_owner_can_edit_profile_operator_cannot(self):
        from .services import invoice_profile
        profile=invoice_profile('kms')
        fields=['prefix','number_pattern','reset','title','heading','address','bank_info','signature','footer','style','due_days']
        data={name:getattr(profile,name) for name in fields};data['prefix']='CUSTOM'
        self.client.force_login(self.operator)
        self.assertEqual(self.client.post(reverse('invoice_settings',args=['kms']),data).status_code,403)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.post(reverse('invoice_settings',args=['kms']),data).status_code,302)
        profile.refresh_from_db();self.assertEqual(profile.prefix,'CUSTOM')

class UpgradeMigrationTests(TransactionTestCase):
    def test_v1_data_is_preserved_and_supplier_history_imported(self):
        from django.db.migrations.executor import MigrationExecutor
        target=('core','0003_import_supplier_history')
        try:
            executor=MigrationExecutor(connection)
            executor.migrate([('core','0001_initial')])
            apps=executor.loader.project_state([('core','0001_initial')]).apps
            User=apps.get_model('auth','User')
            Partner=apps.get_model('core','Partner')
            Product=apps.get_model('core','Product')
            Procurement=apps.get_model('core','Procurement')
            Item=apps.get_model('core','OrderItem')
            Invoice=apps.get_model('core','Invoice')
            Expense=apps.get_model('core','KitchenEntry')
            user=User.objects.create(username='migration-owner')
            supplier=Partner.objects.create(name='Supplier lama',kind='supplier')
            coop=Partner.objects.create(name='Koperasi lama',kind='cooperative')
            kitchen=Partner.objects.create(name='Dapur lama',kind='kitchen')
            product=Product.objects.create(code='OLD',name='Telur',unit='kg',category='Protein')
            order=Procurement.objects.create(cooperative=coop,kitchen=kitchen,delivery_date=timezone.localdate(),status='confirmed',created_by=user,confirmed_at=timezone.now())
            item=Item.objects.create(procurement=order,product=product,supplier=supplier,quantity=1,supplier_price=12000,kms_price=12500,cooperative_price=13000,recommended_price=13500,product_name='Telur',unit='kg')
            invoice=Invoice.objects.create(procurement=order,kind='supplier',supplier=supplier,issuer_name='Supplier lama',recipient_name='KMS',total=12000,due_date=timezone.localdate())
            expense=Expense.objects.create(procurement=order,kind='expense',amount=100,date=timezone.localdate(),description='Arsip',created_by=user)
            executor=MigrationExecutor(connection);executor.migrate([target])
            apps=executor.loader.project_state([target]).apps
            updated=apps.get_model('core','OrderItem').objects.get(pk=item.pk)
            quote=apps.get_model('core','SupplierPrice').objects.get(pk=updated.supplier_quote_id)
            self.assertEqual(quote.price,Decimal('12000'))
            self.assertEqual(updated.recommended_price,Decimal('13500'))
            self.assertEqual(updated.kitchen_price,0)
            self.assertEqual(apps.get_model('core','Invoice').objects.get(pk=invoice.pk).number,f'INV-{invoice.pk:05d}')
            self.assertEqual(apps.get_model('core','Invoice').objects.filter(kind='kitchen').count(),0)
            self.assertTrue(apps.get_model('core','KitchenEntry').objects.filter(pk=expense.pk).exists())
        finally:
            MigrationExecutor(connection).migrate([('core','0010_freeze_existing_procurement_reports')])

class FinanceTests(FixtureMixin,TestCase):
    def setUp(self):
        super().setUp()
        import tempfile
        from django.test import override_settings
        self.media=tempfile.TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        override=override_settings(MEDIA_ROOT=self.media.name)
        override.enable();self.addCleanup(override.disable)
    def proof(self,name='transfer.pdf'):
        from django.core.files.uploadedfile import SimpleUploadedFile
        return SimpleUploadedFile(name,b'%PDF-1.4\n%%EOF',content_type='application/pdf')
    def test_supplier_partial_payment_decreases_kms_and_uses_its_invoice_only(self):
        self.confirm();self.fund('2000000')
        inv=self.order.invoices.get(kind='supplier')
        payment=record_payment(self.operator,inv.pk,'500000',timezone.localdate(),'TRF-SUP',uuid.uuid4(),evidence=self.proof())
        self.assertEqual(inv.remaining,Decimal('800000'))
        self.assertEqual(balance(),Decimal('1500000'))
        self.assertEqual(LedgerEntry.objects.get(payment=payment).amount,Decimal('-500000'))
        self.assertEqual(payment.evidences.count(),1)
        self.assertEqual(self.order.invoices.get(kind='kms').paid,0)
    def test_insufficient_funds_and_overpayment_leave_no_payment_or_proof(self):
        from pathlib import Path
        self.confirm();inv=self.order.invoices.get(kind='supplier')
        for value in ['100','1300001']:
            with self.assertRaises(ValidationError):
                record_payment(self.operator,inv.pk,value,timezone.localdate(),'FAIL',uuid.uuid4(),evidence=self.proof())
        self.assertEqual(Payment.objects.count(),0)
        self.assertEqual(FinancialEvidence.objects.count(),0)
        self.assertEqual([p for p in Path(self.media.name).rglob('*') if p.is_file()],[])
    def test_receipt_changes_kms_but_cooperative_and_kitchen_payments_do_not(self):
        self.confirm()
        self.pay(self.order.invoices.get(kind='kms'),'200000')
        self.pay(self.order.invoices.get(kind='cooperative'),'300000')
        self.pay(self.order.invoices.get(kind='kitchen'),'400000')
        self.assertEqual(balance(),Decimal('200000'))
        self.assertEqual(LedgerEntry.objects.count(),1)
    def test_supplier_retry_does_not_duplicate_payment_cash_or_proof(self):
        self.confirm();self.fund('1000');inv=self.order.invoices.get(kind='supplier');key=uuid.uuid4()
        for _ in range(2):record_payment(self.operator,inv.pk,'100',timezone.localdate(),'RETRY',key,evidence=self.proof())
        self.assertEqual(Payment.objects.count(),1)
        self.assertEqual(LedgerEntry.objects.count(),2)
        self.assertEqual(FinancialEvidence.objects.count(),1)
        self.assertEqual(balance(),Decimal('900'))
    def test_owner_manual_cash_and_proof_retry_and_operator_denied(self):
        key=uuid.uuid4()
        for _ in range(2):cash_movement(self.owner,'1000','income',timezone.localdate(),'Tambahan modal',key,evidence=self.proof('modal.pdf'))
        cash_movement(self.owner,'250','expense',timezone.localdate(),'Transport KMS',uuid.uuid4())
        self.assertEqual(balance(),Decimal('750'))
        self.assertEqual(FinancialEvidence.objects.count(),1)
        with self.assertRaises(ValidationError):cash_movement(self.owner,'1000','expense',timezone.localdate(),'Berlebih',uuid.uuid4())
        cash_movement(self.operator,'100','income',timezone.localdate(),'Tambahan admin',uuid.uuid4())
        self.client.force_login(self.operator)
        self.assertEqual(self.client.get(reverse('finance')).status_code,200)
        self.assertNotIn('balance',self.client.get(reverse('dashboard')).context)
        self.client.force_login(self.owner)
        page=self.client.get(reverse('finance'))
        self.assertEqual(page.context['income'],Decimal('1100'))
        self.assertEqual(page.context['expense'],Decimal('250'))
        self.assertEqual(page.context['balance'],Decimal('850'))
    def test_proof_upload_through_payment_form_and_download_permissions(self):
        self.confirm();self.fund('1000');inv=self.order.invoices.get(kind='supplier')
        self.client.force_login(self.operator)
        response=self.client.post(reverse('payment_create',args=[inv.pk]),{'amount':'100','date':timezone.localdate().isoformat(),'reference':'TRANSFER','request_key':str(uuid.uuid4()),'evidence':self.proof()})
        self.assertEqual(response.status_code,302)
        payment=inv.payments.get();proof=payment.evidences.get()
        page=self.client.get(reverse('invoice_detail',args=[inv.pk]))
        self.assertContains(page,proof.original_name)
        response=self.client.get(reverse('financial_evidence_download',args=[proof.pk]))
        self.assertEqual(response.status_code,200);response.close()
        self.client.post(reverse('payment_evidence_upload',args=[payment.pk]),{'file':self.proof('tambahan.pdf')})
        self.assertEqual(payment.evidences.count(),2)
        self.assertEqual(inv.payments.count(),1)
        entry=cash_movement(self.owner,'100','income',timezone.localdate(),'Modal privat',uuid.uuid4(),evidence=self.proof('privat.pdf'))
        cash_proof=entry.evidences.get()
        self.assertEqual(self.client.get(reverse('financial_evidence_download',args=[cash_proof.pk])).status_code,200)
        self.client.logout()
        self.assertEqual(self.client.get(reverse('financial_evidence_download',args=[proof.pk])).status_code,302)
    def test_add_proof_to_manual_cash_through_form(self):
        self.client.force_login(self.owner)
        data={'direction':'income','amount':'500','date':timezone.localdate().isoformat(),'description':'Modal','request_key':str(uuid.uuid4()),'evidence':self.proof('modal.pdf')}
        self.assertEqual(self.client.post(reverse('finance'),data).status_code,302)
        entry=LedgerEntry.objects.get()
        self.assertEqual(entry.evidences.count(),1)
        self.client.post(reverse('cash_evidence_upload',args=[entry.pk]),{'file':self.proof('tambahan-kas.pdf')})
        self.assertEqual(entry.evidences.count(),2)
        self.assertEqual(balance(),Decimal('500'))
    def test_invalid_file_is_rejected_before_payment_and_cash_mutations(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.confirm();self.fund('1000');inv=self.order.invoices.get(kind='supplier')
        bad=lambda:SimpleUploadedFile('evil.pdf',b'<script>bad</script>',content_type='application/pdf')
        with self.assertRaises(ValidationError):record_payment(self.operator,inv.pk,'100',timezone.localdate(),'BAD',uuid.uuid4(),evidence=bad())
        with self.assertRaises(ValidationError):cash_movement(self.owner,'100','income',timezone.localdate(),'BAD',uuid.uuid4(),evidence=bad())
        self.assertEqual(Payment.objects.count(),0)
        self.assertEqual(FinancialEvidence.objects.count(),0)
        self.assertEqual(balance(),Decimal('1000'))
    def test_storage_cleanup_if_payment_transaction_rolls_back(self):
        from pathlib import Path
        from unittest.mock import patch
        self.confirm();self.fund('1000');inv=self.order.invoices.get(kind='supplier')
        with patch('core.services.audit',side_effect=RuntimeError('Simulated audit failure')):
            with self.assertRaises(RuntimeError):record_payment(self.operator,inv.pk,'100',timezone.localdate(),'ROLLBACK',uuid.uuid4(),evidence=self.proof())
        self.assertEqual(Payment.objects.count(),0)
        self.assertEqual(FinancialEvidence.objects.count(),0)
        self.assertEqual(balance(),Decimal('1000'))
        self.assertEqual([p for p in Path(self.media.name).rglob('*') if p.is_file()],[])

class RestoreFinanceMigrationTests(TransactionTestCase):
    def test_backfill_supplier_and_cash_preserves_existing_payments_without_double_posting(self):
        from django.db.migrations.executor import MigrationExecutor
        import importlib
        before=('core','0003_import_supplier_history')
        target=('core','0005_restore_supplier_and_cash')
        try:
            executor=MigrationExecutor(connection);executor.migrate([before])
            apps=executor.loader.project_state([before]).apps
            User=apps.get_model('auth','User');Partner=apps.get_model('core','Partner')
            Product=apps.get_model('core','Product');Order=apps.get_model('core','Procurement')
            Item=apps.get_model('core','OrderItem');Invoice=apps.get_model('core','Invoice')
            Payment=apps.get_model('core','Payment');Wallet=apps.get_model('core','Wallet');Entry=apps.get_model('core','LedgerEntry')
            user=User.objects.create(username='restore-test')
            supplier=Partner.objects.create(name='Supplier',kind='supplier')
            coop=Partner.objects.create(name='Koperasi',kind='cooperative');kitchen=Partner.objects.create(name='Dapur',kind='kitchen')
            product=Product.objects.create(code='R',name='Telur',category='Protein',unit='kg')
            orders=[]
            for idx in range(3):
                order=Order.objects.create(cooperative=coop,kitchen=kitchen,delivery_date=timezone.localdate(),status='confirmed' if idx<2 else 'draft',confirmed_at=timezone.now() if idx<2 else None,created_by=user)
                Item.objects.create(procurement=order,product=product,supplier=supplier,quantity=1,supplier_price=100,kms_price=120,cooperative_price=130,kitchen_price=140)
                orders.append(order)
            supplier_invoice=Invoice.objects.create(procurement=orders[0],kind='supplier',supplier=supplier,issuer_name='Supplier',recipient_name='KMS',total=100,due_date=timezone.localdate(),number='OLD-SUP')
            kms_invoice=Invoice.objects.create(procurement=orders[0],kind='kms',issuer_name='KMS',recipient_name='Koperasi',total=120,due_date=timezone.localdate())
            coop_invoice=Invoice.objects.create(procurement=orders[0],kind='cooperative',issuer_name='Koperasi',recipient_name='Dapur',total=130,due_date=timezone.localdate())
            payment=Payment.objects.create(invoice=supplier_invoice,amount=40,date=timezone.localdate(),reference='OLD',created_by=user)
            Payment.objects.create(invoice=kms_invoice,amount=60,date=timezone.localdate(),reference='V1.1',created_by=user)
            Payment.objects.create(invoice=coop_invoice,amount=70,date=timezone.localdate(),reference='COOP',created_by=user)
            wallet,_=Wallet.objects.get_or_create(name='KMS')
            Entry.objects.create(wallet=wallet,amount=100,description='Modal lama',created_by=user)
            Entry.objects.create(wallet=wallet,payment=payment,amount=-40,description='Pembayaran lama',created_by=user)
            executor=MigrationExecutor(connection);executor.migrate([target])
            apps=executor.loader.project_state([target]).apps
            NewInvoice=apps.get_model('core','Invoice');NewEntry=apps.get_model('core','LedgerEntry')
            self.assertEqual(NewInvoice.objects.get(pk=supplier_invoice.pk).number,'OLD-SUP')
            self.assertEqual(NewInvoice.objects.filter(procurement_id=orders[1].pk,kind='supplier').count(),1)
            self.assertEqual(NewInvoice.objects.filter(procurement_id=orders[2].pk).count(),0)
            self.assertEqual(NewEntry.objects.count(),3)
            self.assertEqual(sum(e.amount for e in NewEntry.objects.all()),Decimal('120'))
            self.assertEqual(apps.get_model('core','Payment').objects.count(),3)
            # The restoration itself is idempotent if rerun for maintenance.
            with connection.schema_editor() as editor:
                importlib.import_module('core.migrations.0005_restore_supplier_and_cash').restore(apps,editor)
            self.assertEqual(NewEntry.objects.count(),3)
            self.assertEqual(NewInvoice.objects.filter(kind='supplier').count(),2)
        finally:
            MigrationExecutor(connection).migrate([('core','0010_freeze_existing_procurement_reports')])

class CashConcurrencyTests(FixtureMixin,TransactionTestCase):
    def test_two_supplier_payments_cannot_spend_the_same_balance(self):
        if connection.vendor!='postgresql':self.skipTest('PostgreSQL required')
        self.confirm();self.fund('1500000')
        order=Procurement.objects.create(cooperative=self.coop,kitchen=self.kitchen,delivery_date=timezone.localdate(),created_by=self.owner)
        OrderItem.objects.create(procurement=order,product=self.product,supplier=self.supplier,quantity=100,supplier_price=13000,kms_price=13500,cooperative_price=14000,kitchen_price=14500)
        confirm_order(self.owner,order.pk)
        ids=[self.order.invoices.get(kind='supplier').pk,order.invoices.get(kind='supplier').pk]
        uid=self.operator.pk
        def worker(invoice_id):
            close_old_connections()
            try:
                record_payment(get_user_model().objects.get(pk=uid),invoice_id,'1000000',timezone.localdate(),'CONCURRENT-SUP',uuid.uuid4())
                return True
            except ValidationError:return False
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(worker,ids))
        self.assertEqual(results.count(True),1)
        self.assertEqual(balance(),Decimal('500000'))
        self.assertEqual(Payment.objects.filter(invoice__kind='supplier').count(),1)
