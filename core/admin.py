from django.contrib import admin
from django.contrib.auth.models import Group
from .models import Product,Partner,Procurement,OrderItem,Invoice,Payment,Attachment,AuditEvent,SupplierPrice,InvoiceProfile,InvoiceCounter,LedgerEntry,Wallet,FinancialEvidence,SupplierProduct

@admin.register(Product,Partner)
class MasterAdmin(admin.ModelAdmin):
    def has_module_permission(self,request): return request.user.is_superuser
    def has_view_permission(self,request,obj=None): return request.user.is_superuser
    def has_change_permission(self,request,obj=None): return request.user.is_superuser
    def has_add_permission(self,request): return request.user.is_superuser
    def has_delete_permission(self,request,obj=None): return False

@admin.register(Procurement,OrderItem,Invoice,Payment,Attachment,AuditEvent,SupplierPrice,InvoiceProfile,InvoiceCounter,LedgerEntry,Wallet,FinancialEvidence,SupplierProduct)
class ReadOnlyTransactionAdmin(admin.ModelAdmin):
    """All transaction mutations go through application services, even for superusers."""
    def has_module_permission(self,request): return request.user.is_superuser
    def has_view_permission(self,request,obj=None): return request.user.is_superuser
    def has_add_permission(self,request): return False
    def has_change_permission(self,request,obj=None): return False
    def has_delete_permission(self,request,obj=None): return False
admin.site.site_header='KMS · Administrasi akun'
