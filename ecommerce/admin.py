import json
from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.http import HttpResponseRedirect
from django.utils.html import format_html

from .models import (
    Address, AuditLog, Cart, Category, GoodsReceipt, GoodsReceiptItem,
    Inventory, Order, OrderItem, Payment, Product, PurchaseItem,
    PurchaseOrder, StockMovement, Supplier, User,
)
from .services import place_purchase_order, post_goods_receipt


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'is_active', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('name', 'slug')
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'sku', 'category', 'cost_price', 'price', 'is_active', 'stock_summary')
    list_filter = ('is_active', 'category')
    search_fields = ('name', 'sku', 'slug')
    prepopulated_fields = {'slug': ('name',)}
    readonly_fields = ('created_at',)

    @admin.display(description='Available stock')
    def stock_summary(self, obj):
        try:
            return obj.inventory.quantity_available
        except Inventory.DoesNotExist:
            return 'Not initialized'


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ('name', 'contact_name', 'email', 'phone', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('name', 'contact_name', 'email', 'phone')


class PurchaseItemInline(admin.TabularInline):
    model = PurchaseItem
    extra = 1
    fields = ('product', 'quantity_ordered', 'unit_cost')


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display = ('po_number', 'supplier', 'status', 'total_amount', 'expected_date', 'created_by', 'created_at', 'receive_link')
    list_filter = ('status', 'supplier', 'created_at')
    search_fields = ('po_number', 'supplier__name')
    readonly_fields = ('total_amount', 'ordered_at', 'created_at')
    inlines = [PurchaseItemInline]
    actions = ['place_selected_purchase_orders']

    def get_urls(self):
        custom_urls = [path('<int:po_id>/receive/', self.admin_site.admin_view(self.receive_view), name='ecommerce_purchaseorder_receive')]
        return custom_urls + super().get_urls()

    @admin.display(description='Goods receiving')
    def receive_link(self, obj):
        if obj.status in (PurchaseOrder.STATUS_ORDERED, PurchaseOrder.STATUS_PARTIAL):
            url = reverse('admin:ecommerce_purchaseorder_receive', args=[obj.pk])
            return format_html('<a href="{}">Receive goods</a>', url)
        return '—'

    def receive_view(self, request, po_id):
        po = PurchaseOrder.objects.prefetch_related('items__product').get(pk=po_id)
        if not (request.user.is_superuser or request.user.has_perm('ecommerce.add_goodsreceipt')):
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied
        if po.status not in (PurchaseOrder.STATUS_ORDERED, PurchaseOrder.STATUS_PARTIAL):
            self.message_user(request, 'Only ordered or partially received purchase orders can receive goods.', level=messages.ERROR)
            return HttpResponseRedirect(reverse('admin:ecommerce_purchaseorder_change', args=[po.pk]))
        if request.method == 'POST':
            lines = []
            for item in po.items.all():
                raw = request.POST.get(f'qty_{item.pk}', '').strip()
                if raw:
                    lines.append({'purchase_item_id': item.pk, 'quantity': raw})
            try:
                receipt = post_goods_receipt(purchase_order_id=po.pk, actor=request.user, lines=lines,
                                             notes=request.POST.get('notes', '').strip())
                self.message_user(request, f'Receipt {receipt.receipt_number} posted successfully.', level=messages.SUCCESS)
                return HttpResponseRedirect(reverse('admin:ecommerce_purchaseorder_change', args=[po.pk]))
            except ValidationError as exc:
                error_message = '; '.join(exc.messages)
            except Exception as exc:
                # Keep user-facing message useful without leaking database internals.
                error_message = 'Receipt could not be posted. Check the quantities and try again.'
        else:
            error_message = ''
        context = {
            **self.admin_site.each_context(request), 'opts': self.model._meta,
            'title': f'Receive goods for {po.po_number}', 'purchase_order': po,
            'items': po.items.all(), 'error_message': error_message,
        }
        return TemplateResponse(request, 'admin/ecommerce/purchaseorder/receive.html', context)

    def save_model(self, request, obj, form, change):
        if not change and not obj.created_by_id:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    @admin.action(description='Place selected draft purchase orders')
    def place_selected_purchase_orders(self, request, queryset):
        success = 0
        for po in queryset:
            try:
                place_purchase_order(po.pk, request.user)
                success += 1
            except ValidationError as exc:
                self.message_user(request, f'{po.po_number}: {exc}', level=messages.ERROR)
        if success:
            self.message_user(request, f'{success} purchase order(s) placed. Inventory was not changed.', level=messages.SUCCESS)


class GoodsReceiptItemInline(admin.TabularInline):
    model = GoodsReceiptItem
    extra = 0
    readonly_fields = ('purchase_item', 'quantity_received', 'unit_cost')
    can_delete = False


@admin.register(GoodsReceipt)
class GoodsReceiptAdmin(admin.ModelAdmin):
    list_display = ('receipt_number', 'purchase_order', 'status', 'received_by', 'received_at')
    list_filter = ('status', 'received_at')
    search_fields = ('receipt_number', 'purchase_order__po_number')
    readonly_fields = ('receipt_number', 'purchase_order', 'status', 'received_by', 'received_at', 'notes', 'idempotency_key')
    inlines = [GoodsReceiptItemInline]
    actions = None

    def has_add_permission(self, request):
        # Receipts must be posted through the validated receiving service, not hand-entered in admin.
        return False


@admin.register(Inventory)
class InventoryAdmin(admin.ModelAdmin):
    list_display = ('product', 'quantity_on_hand', 'quantity_reserved', 'quantity_available', 'updated_at', 'adjustment_link')
    search_fields = ('product__name', 'product__sku')
    readonly_fields = ('product', 'quantity_on_hand', 'quantity_reserved', 'updated_at')

    @admin.display(description='Available')
    def quantity_available(self, obj):
        return obj.quantity_available

    def get_urls(self):
        custom_urls = [path('<int:product_id>/adjust/', self.admin_site.admin_view(self.adjust_view), name='ecommerce_inventory_adjust')]
        return custom_urls + super().get_urls()

    @admin.display(description='Stock action')
    def adjustment_link(self, obj):
        url = reverse('admin:ecommerce_inventory_adjust', args=[obj.product_id])
        return format_html('<a href="{}">Adjust stock</a>', url)

    def adjust_view(self, request, product_id):
        product = Product.objects.get(pk=product_id)
        if not (request.user.is_superuser or request.user.has_perm('ecommerce.change_inventory')):
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied
        if request.method == 'POST':
            try:
                from .services import adjust_stock
                movement_type = request.POST.get('movement_type', StockMovement.TYPE_ADJUSTMENT)
                allowed_types = {StockMovement.TYPE_OPENING, StockMovement.TYPE_ADJUSTMENT, StockMovement.TYPE_DAMAGE, StockMovement.TYPE_RETURN}
                if movement_type not in allowed_types:
                    raise ValidationError('Unsupported stock adjustment type.')
                movement = adjust_stock(
                    product_id=product.pk, quantity_delta=request.POST.get('quantity_delta'),
                    actor=request.user, reason=request.POST.get('reason', ''),
                    movement_type=movement_type, reference=request.POST.get('reference', '').strip(),
                )
                self.message_user(request, f'Stock movement {movement.pk} recorded.', level=messages.SUCCESS)
                return HttpResponseRedirect(reverse('admin:ecommerce_inventory_changelist'))
            except ValidationError as exc:
                error_message = '; '.join(exc.messages)
            except Exception:
                error_message = 'Stock adjustment failed. Check the quantity and try again.'
        else:
            error_message = ''
        try:
            inventory = product.inventory
        except Inventory.DoesNotExist:
            inventory = None
        context = {**self.admin_site.each_context(request), 'opts': self.model._meta,
                   'title': f'Adjust stock: {product.name}', 'product': product,
                   'inventory': inventory, 'error_message': error_message}
        return TemplateResponse(request, 'admin/ecommerce/inventory/adjust.html', context)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'product', 'movement_type', 'quantity_delta', 'quantity_after', 'reference', 'created_by')
    list_filter = ('movement_type', 'created_at')
    search_fields = ('product__name', 'product__sku', 'reference', 'reason')
    readonly_fields = tuple(field.name for field in StockMovement._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'actor', 'action', 'entity_type', 'entity_id')
    list_filter = ('action', 'entity_type', 'created_at')
    search_fields = ('actor__username', 'action', 'entity_type', 'entity_id')
    readonly_fields = tuple(field.name for field in AuditLog._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


# Existing commerce records remain available in Django admin.
for model in (User, Address, Order, OrderItem, Cart, Payment):
    try:
        admin.site.register(model)
    except admin.sites.AlreadyRegistered:
        pass

admin.site.site_header = 'Shivika E-Commerce Administration'
admin.site.site_title = 'Shivika Admin'
admin.site.index_title = 'Catalogue, purchasing and inventory operations'
