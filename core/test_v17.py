from io import BytesIO
from decimal import Decimal
import uuid
from django.test import TestCase,TransactionTestCase
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.urls import reverse
from django.utils import timezone
from django.core.exceptions import ValidationError,PermissionDenied
from openpyxl import load_workbook
from .tests import FixtureMixin
from .models import Procurement,Invoice,Payment,LedgerEntry,OrderItem,FinancialEvidence
from .forms import ProcurementForm,ItemForm,SalesFormSet
from . import services
from .procurement_exports import report_rows,report_schema,pdf_bytes
from .test_ui import picture


class NewFlowTests(FixtureMixin,TestCase):
    def setUp(self):
        super().setUp();self.client.force_login(self.owner)
    def test_new_order_forms_end_at_kitchen_and_ignore_forged_office_fields(self):
        response=self.client.post(reverse('order_create'),{'cooperative':self.coop.pk,'kitchen':self.kitchen.pk,'delivery_date':timezone.localdate(),'office_name':'FAKE OFFICE'})
        new=Procurement.objects.exclude(pk=self.order.pk).get()
        self.assertEqual(new.flow_version,'standard');self.assertNotEqual(new.office_name,'FAKE OFFICE')
        self.assertNotIn('office_name',ProcurementForm().fields)
        self.assertNotIn('kitchen_price',ItemForm(user=self.owner).fields)
        page=self.client.get(reverse('sales_lines',args=[self.order.pk]))
        self.assertNotContains(page,'name="prices-0-kitchen_price"');self.assertNotContains(page,'Dapur → Kantor')
    def test_confirmation_only_issues_active_stages_with_zero_old_price(self):
        self.item.kitchen_price=0;self.item.save()
        self.confirm()
        self.assertEqual(set(self.order.invoices.values_list('kind',flat=True)),{'supplier','kms','cooperative'})
        self.assertEqual(self.order.invoices.get(kind='cooperative').recipient_name,self.kitchen.name)
        self.assertEqual(self.order.invoices.get(kind='cooperative').total,Decimal('1400000'))
        with self.assertRaises(ValidationError):services.issue_invoice(self.order,'kitchen','Dapur','Kantor',100,timezone.localdate())
    def test_sales_bulk_only_persists_two_prices_and_rejects_missing_new_price(self):
        data={'prices-TOTAL_FORMS':1,'prices-INITIAL_FORMS':1,'prices-0-id':self.item.pk,'prices-0-kms_price':13600,'prices-0-cooperative_price':14200,'prices-0-kitchen_price':'999999999999999999999999999999999'}
        formset=SalesFormSet(data,prefix='prices',form_kwargs={'user':self.operator})
        services.save_sales_lines(self.operator,self.order.pk,formset,0)
        self.item.refresh_from_db();self.assertEqual(self.item.kitchen_price,14500);self.assertEqual(self.item.kms_price,13600)
        data['prices-0-cooperative_price']=''
        self.assertFalse(SalesFormSet(data,prefix='prices',form_kwargs={'user':self.operator}).is_valid())
        with self.assertRaises(PermissionDenied):services.confirm_order(self.operator,self.order.pk)
    def test_main_reports_and_exports_do_not_show_office_revenue_or_profit(self):
        self.confirm()
        for route in ['reports','dashboard']:
            page=self.client.get(reverse(route));self.assertNotIn('kitchen_sales',page.context['totals']);self.assertNotIn('kitchen_margin',page.context['totals']);self.assertNotContains(page,'Profit dapur')
        book=load_workbook(BytesIO(self.client.get(reverse('reports'),{'export':'xlsx'}).content))
        headers=[c.value for c in book['Omzet dan profit'][1]]
        self.assertNotIn('Omzet dapur',headers);self.assertNotIn('Profit dapur',headers)
        self.client.force_login(self.operator)
        self.assertNotIn('kms_margin',self.client.get(reverse('reports')).context['totals'])
    def test_completed_new_export_has_eleven_columns_and_final_kitchen_amount(self):
        self.confirm();services.advance_order(self.operator,self.order.pk);services.advance_order(self.operator,self.order.pk);self.order.refresh_from_db()
        rows=report_rows(self.order);self.assertEqual(len(rows[0]),11);self.assertEqual(rows[0][-1],Decimal('1400000'))
        book=load_workbook(BytesIO(self.client.get(reverse('procurement_export',args=[self.order.pk,'xlsx'])).content));sheet=book.active
        self.assertEqual(sheet.max_column,11)
        header=next(c.row for row in sheet for c in row if c.value=='NO')
        self.assertEqual(sheet.cell(header,10).value,'HARGA BELI DAPUR');self.assertEqual(sheet.cell(header,11).value,'TOTAL KE DAPUR')
        self.assertEqual(sheet.cell(header+2,11).value,1400000)
        values=' '.join(str(c.value or '') for row in sheet for c in row)
        self.assertNotIn('PROFIT DAPUR',values);self.assertNotIn('REKOMENDASI DAPUR',values);self.assertIn('Kepada Yth. '+self.kitchen.name,values)
        self.assertTrue(self.client.get(reverse('procurement_export',args=[self.order.pk,'pdf'])).content.startswith(b'%PDF-'))
    def test_cash_and_supplier_partial_payments_keep_original_rules(self):
        self.confirm();self.fund('1000');supplier=self.order.invoices.get(kind='supplier');self.pay(supplier,100)
        self.assertEqual(services.balance(),900);self.assertEqual(supplier.remaining,Decimal('1299900'))
        self.pay(self.order.invoices.get(kind='cooperative'),200);self.assertEqual(services.balance(),900)
        self.pay(self.order.invoices.get(kind='kms'),300);self.assertEqual(services.balance(),1200)


class ArchiveTests(FixtureMixin,TestCase):
    def setUp(self):
        super().setUp();self.confirm()
        Procurement.objects.filter(pk=self.order.pk).update(flow_version='legacy',office_name='Kantor Arsip')
        self.order.refresh_from_db()
        self.legacy=Invoice.objects.create(procurement=self.order,kind='kitchen',issuer_name='Dapur lama',recipient_name='Kantor Arsip',number='ARSIP/2026/00001',total=1450000,due_date=timezone.localdate(),print_snapshot={'title':'INVOICE LAMA','heading':'Kop arsip asli','signers':[{'title':'Ketua','name':'Nama lama','identity':'NRP lama'}]})
        self.client.force_login(self.owner)
    def test_archive_menu_keeps_old_documents_out_of_active_invoice_list(self):
        page=self.client.get(reverse('invoices'));self.assertNotContains(page,self.legacy.code)
        page=self.client.get(reverse('office_invoice_archive'));self.assertContains(page,self.legacy.code);self.assertContains(page,'Arsip Invoice Kantor Lama')
        self.assertRedirects(self.client.get(reverse('invoices'),{'kind':'kitchen'}),reverse('office_invoice_archive'))
        detail=self.client.get(reverse('invoice_detail',args=[self.legacy.pk]));self.assertContains(detail,'Kop arsip asli');self.assertContains(detail,'Nama lama');self.assertContains(detail,'Arsip alur lama')
        detail=self.client.get(reverse('order_detail',args=[self.order.pk]));self.assertContains(detail,'Arsip Invoice Kantor Lama')
    def test_legacy_settlement_proof_and_cancellation_are_still_auditable(self):
        before=services.balance()
        payment=services.record_payment(self.operator,self.legacy.pk,100,timezone.localdate(),'Pelunasan arsip',uuid.uuid4(),evidence=picture('arsip.png'))
        proof=payment.evidences.get();response=self.client.get(reverse('financial_evidence_download',args=[proof.pk]));self.assertEqual(response.status_code,200);response.close()
        self.assertEqual(services.balance(),before)
        services.cancel_payment(self.owner,payment.pk,'Pembayaran arsip duplikat');self.legacy.refresh_from_db()
        self.assertEqual(self.legacy.paid,0);self.assertEqual(payment.evidences.count(),1)
        self.assertEqual(self.legacy.print_snapshot['heading'],'Kop arsip asli')
    def test_legacy_export_preserves_thirteen_columns_and_old_profit(self):
        self.order.status='received';self.order.save(update_fields=['status'])
        self.assertEqual(len(report_rows(self.order)[0]),13);self.assertEqual(report_rows(self.order)[0][-1],50000)
        sheet=load_workbook(BytesIO(self.client.get(reverse('procurement_export',args=[self.order.pk,'xlsx'])).content)).active
        self.assertEqual(sheet.max_column,13)
        values=' '.join(str(c.value or '') for row in sheet for c in row)
        self.assertIn('TOTAL PROFIT DAPUR',values);self.assertIn('Kepada Yth. Kantor Arsip',values)
        totals=self.client.get(reverse('reports')).context['totals'];self.assertEqual(totals['coop_sales'],1400000);self.assertNotIn('kitchen_margin',totals)


class FlowMigrationTests(TransactionTestCase):
    def test_upgrade_marks_issued_records_as_archive_preserves_all_existing_values(self):
        before=('core','0010_freeze_existing_procurement_reports');after=('core','0011_procurement_flow_version')
        try:
            executor=MigrationExecutor(connection);executor.migrate([before]);apps=executor.loader.project_state([before]).apps
            User=apps.get_model('auth','User');Partner=apps.get_model('core','Partner');Product=apps.get_model('core','Product');Order=apps.get_model('core','Procurement');Item=apps.get_model('core','OrderItem');OldInvoice=apps.get_model('core','Invoice');OldPayment=apps.get_model('core','Payment');Evidence=apps.get_model('core','FinancialEvidence');Wallet=apps.get_model('core','Wallet');Entry=apps.get_model('core','LedgerEntry')
            user=User.objects.create(username='migration17');supplier=Partner.objects.create(kind='supplier',name='S');coop=Partner.objects.create(kind='cooperative',name='C');kitchen=Partner.objects.create(kind='kitchen',name='D');product=Product.objects.create(code='MIG',name='Produk lama',category='Tes',unit='kg')
            old=Order.objects.create(cooperative=coop,kitchen=kitchen,created_by=user,delivery_date=timezone.localdate(),status='received',office_name='Kantor asli',report_snapshot={'heading':'Kop terkunci','title':'Penawaran lama'})
            draft=Order.objects.create(cooperative=coop,kitchen=kitchen,created_by=user,delivery_date=timezone.localdate(),status='draft')
            cancelled=Order.objects.create(cooperative=coop,kitchen=kitchen,created_by=user,delivery_date=timezone.localdate(),status='cancelled',cancellation_reason='Batal lama')
            for order in [old,draft]:Item.objects.create(procurement=order,product=product,supplier=supplier,quantity=2,supplier_price=100,kms_price=120,cooperative_price=130,kitchen_price=150,product_name='Produk lama',unit='kg')
            invoice=OldInvoice.objects.create(procurement=old,kind='kitchen',number='DPR-LAMA-001',issuer_name='Dapur lama',recipient_name='Kantor asli',total=300,due_date=timezone.localdate(),print_snapshot={'heading':'Logo dan kop lama','logo_left':'invoice_logos/original.png'})
            payment=OldPayment.objects.create(invoice=invoice,amount=50,date=timezone.localdate(),reference='BUKTI-LAMA',created_by=user)
            Evidence.objects.create(payment=payment,file='financial_evidence/old.jpg',original_name='lama.jpg',thumbnail='thumbnails/old.jpg',uploaded_by=user)
            wallet=Wallet.objects.create(name='KMS');Entry.objects.create(wallet=wallet,amount=1000,date=timezone.localdate(),description='Modal lama',created_by=user)
            preserved={model._meta.model_name:list(model.objects.order_by('pk').values()) for model in [Item,OldInvoice,OldPayment,Evidence,Entry]}
            executor=MigrationExecutor(connection);executor.migrate([after]);apps=executor.loader.project_state([after]).apps
            for model_name,values in preserved.items():self.assertEqual(list(apps.get_model('core',model_name).objects.order_by('pk').values()),values)
            NewOrder=apps.get_model('core','Procurement')
            self.assertEqual(NewOrder.objects.get(pk=old.pk).flow_version,'legacy');self.assertEqual(NewOrder.objects.get(pk=cancelled.pk).flow_version,'legacy');self.assertEqual(NewOrder.objects.get(pk=draft.pk).flow_version,'standard')
            self.assertEqual(NewOrder.objects.get(pk=old.pk).report_snapshot,{'heading':'Kop terkunci','title':'Penawaran lama'})
            self.assertEqual(NewOrder.objects.get(pk=old.pk).office_name,'Kantor asli')
        finally:MigrationExecutor(connection).migrate([after])
