from decimal import Decimal
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from .models import Category, GoodsReceipt, Inventory, Product, PurchaseItem, PurchaseOrder, StockMovement, Supplier
from .services import place_purchase_order, post_goods_receipt, adjust_stock, create_delivered_receipt


class PurchasingInventoryTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(username='testadmin', email='admin@example.test', password='a-very-long-test-password')
        self.category = Category.objects.create(name='Test', slug='test')
        self.product = Product.objects.create(category=self.category, name='Test Product', slug='test-product', sku='SKU-TEST-001', description='Test', cost_price=Decimal('50.00'), price=Decimal('120.00'))
        self.supplier = Supplier.objects.create(name='Supplier A')
        self.po = PurchaseOrder.objects.create(po_number='PO-TEST-001', supplier=self.supplier, created_by=self.admin)
        self.item = PurchaseItem.objects.create(purchase_order=self.po, product=self.product, quantity_ordered=Decimal('100.000'), unit_cost=Decimal('50.00'))

    def test_placing_po_does_not_increase_stock(self):
        place_purchase_order(self.po.pk, self.admin)
        self.assertEqual(self.po.__class__.objects.get(pk=self.po.pk).status, PurchaseOrder.STATUS_ORDERED)
        self.assertFalse(Inventory.objects.filter(product=self.product).exists())

    def test_partial_receipt_updates_inventory_and_status(self):
        place_purchase_order(self.po.pk, self.admin)
        receipt = post_goods_receipt(purchase_order_id=self.po.pk, actor=self.admin, lines=[{'purchase_item_id': self.item.pk, 'quantity': '60'}], receipt_number='GR-TEST-001')
        self.assertEqual(receipt.status, GoodsReceipt.STATUS_POSTED)
        self.assertEqual(Inventory.objects.get(product=self.product).quantity_on_hand, Decimal('60.000'))
        self.assertEqual(PurchaseOrder.objects.get(pk=self.po.pk).status, PurchaseOrder.STATUS_PARTIAL)
        self.assertEqual(StockMovement.objects.filter(receipt_item__receipt=receipt).count(), 1)

    def test_over_receipt_rolls_back_without_stock_change(self):
        place_purchase_order(self.po.pk, self.admin)
        with self.assertRaises(ValidationError):
            post_goods_receipt(purchase_order_id=self.po.pk, actor=self.admin, lines=[{'purchase_item_id': self.item.pk, 'quantity': '101'}], receipt_number='GR-TEST-002')
        self.assertFalse(GoodsReceipt.objects.filter(receipt_number='GR-TEST-002').exists())
        self.assertFalse(Inventory.objects.filter(product=self.product).exists())
        self.assertEqual(StockMovement.objects.count(), 0)

    def test_second_receipt_completes_po(self):
        place_purchase_order(self.po.pk, self.admin)
        post_goods_receipt(purchase_order_id=self.po.pk, actor=self.admin, lines=[{'purchase_item_id': self.item.pk, 'quantity': '60'}], receipt_number='GR-TEST-003')
        post_goods_receipt(purchase_order_id=self.po.pk, actor=self.admin, lines=[{'purchase_item_id': self.item.pk, 'quantity': '40'}], receipt_number='GR-TEST-004')
        self.assertEqual(Inventory.objects.get(product=self.product).quantity_on_hand, Decimal('100.000'))
        self.assertEqual(PurchaseOrder.objects.get(pk=self.po.pk).status, PurchaseOrder.STATUS_RECEIVED)

    def test_adjustment_requires_reason_and_creates_ledger(self):
        with self.assertRaises(ValidationError):
            adjust_stock(product_id=self.product.pk, quantity_delta='5', actor=self.admin, reason='')
        movement = adjust_stock(product_id=self.product.pk, quantity_delta='5', actor=self.admin, reason='Opening count')
        self.assertEqual(movement.quantity_after, Decimal('5.000'))
        self.assertEqual(StockMovement.objects.filter(pk=movement.pk).count(), 1)


class DeliveredReceiptTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(username='testadmin', email='admin@example.test', password='a-very-long-test-password')
        self.category = Category.objects.create(name='Test', slug='test')
        self.product = Product.objects.create(category=self.category, name='Test Product', slug='test-product', sku='SKU-TEST-001', description='Test', cost_price=Decimal('50.00'), price=Decimal('120.00'))
        self.supplier = Supplier.objects.create(name='Supplier A')
        self.po = PurchaseOrder.objects.create(po_number='PO-TEST-001', supplier=self.supplier, created_by=self.admin)
        self.item = PurchaseItem.objects.create(purchase_order=self.po, product=self.product, quantity_ordered=Decimal('100.000'), unit_cost=Decimal('50.00'))
        place_purchase_order(self.po.pk, self.admin)

        from .models import Address, Order, OrderItem, User as LegacyUser
        self.legacy_user = LegacyUser.objects.create(username='customer1', email='c@example.test', password='!', first_name='C', last_name='X')
        self.address = Address.objects.create(user=self.legacy_user, full_name='Customer One', phone='1234567890', address_line1='123 Main St', city='City', state='State', postal_code='123456', country='India')
        self.order = Order.objects.create(user=self.legacy_user, address=self.address, order_number='SHV-TEST-001', status='Delivered', total_amount=Decimal('120.00'), payment_method='Cash on Delivery')
        self.order_item = OrderItem.objects.create(order=self.order, product=self.product, quantity=10, price=Decimal('120.00'), subtotal=Decimal('1200.00'))

    def test_delivered_order_creates_receipt_and_updates_stock(self):
        receipt = create_delivered_receipt(order=self.order, actor=self.admin)
        self.assertIsNotNone(receipt)
        self.assertEqual(receipt.source_order_id, self.order.pk)
        self.assertEqual(receipt.status, GoodsReceipt.STATUS_POSTED)
        self.assertEqual(Inventory.objects.get(product=self.product).quantity_on_hand, Decimal('10.000'))
        self.assertEqual(PurchaseOrder.objects.get(pk=self.po.pk).status, PurchaseOrder.STATUS_PARTIAL)

    def test_delivered_receipt_is_idempotent(self):
        first = create_delivered_receipt(order=self.order, actor=self.admin)
        second = create_delivered_receipt(order=self.order, actor=self.admin)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Inventory.objects.get(product=self.product).quantity_on_hand, Decimal('10.000'))

    def test_delivered_order_without_open_po_creates_no_receipt(self):
        # Mark PO as fully received so no open line remains.
        post_goods_receipt(purchase_order_id=self.po.pk, actor=self.admin, lines=[{'purchase_item_id': self.item.pk, 'quantity': '100'}], receipt_number='GR-TEST-FULL')
        receipt = create_delivered_receipt(order=self.order, actor=self.admin)
        self.assertIsNone(receipt)
