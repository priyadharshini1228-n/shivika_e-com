from decimal import Decimal
from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


class User(models.Model):
    """Legacy customer profile table retained for compatibility with the current project."""
    username = models.CharField(max_length=150, unique=True)
    email = models.EmailField(max_length=254, unique=True)
    password = models.CharField(max_length=128)  # Do not use this model to authenticate passwords.
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    phone = models.CharField(max_length=15)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_superuser = models.BooleanField(default=False)
    date_joined = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'users'

    def __str__(self):
        return self.username


class Address(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='addresses')
    full_name = models.CharField(max_length=100)
    phone = models.CharField(max_length=15)
    address_line1 = models.CharField(max_length=255)
    address_line2 = models.CharField(max_length=255, null=True, blank=True)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    postal_code = models.CharField(max_length=10)
    country = models.CharField(max_length=100)
    is_default = models.BooleanField(default=False)

    class Meta:
        db_table = 'addresses'

    def __str__(self):
        return f'{self.full_name}, {self.city}'


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    description = models.TextField(null=True, blank=True)
    image = models.CharField(max_length=255, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'categories'
        ordering = ['name']

    def __str__(self):
        return self.name


class Product(models.Model):
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name='products')
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True)
    sku = models.CharField(max_length=64, unique=True, null=True, blank=False)
    description = models.TextField()
    cost_price = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'), validators=[MinValueValidator(Decimal('0.00'))])
    price = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.00'))])
    # Legacy field retained for existing screens/data. Inventory.quantity_on_hand is authoritative.
    stock = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    reorder_level = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal('0.000'), validators=[MinValueValidator(Decimal('0.000'))])
    image = models.CharField(max_length=255, blank=True, default='')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'products'
        ordering = ['name']
        indexes = [models.Index(fields=['is_active', 'name'], name='product_active_name_idx')]

    def __str__(self):
        return f'{self.name} ({self.sku or "SKU pending"})'


class Order(models.Model):
    STATUS_CHOICES = [('Pending', 'Pending'), ('Processing', 'Processing'), ('Shipped', 'Shipped'), ('Delivered', 'Delivered'), ('Cancelled', 'Cancelled')]
    PAYMENT_STATUS_CHOICES = [('Pending', 'Pending'), ('Completed', 'Completed'), ('Failed', 'Failed')]
    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name='orders')
    address = models.ForeignKey(Address, on_delete=models.PROTECT, related_name='orders')
    order_number = models.CharField(max_length=50, unique=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending')
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.00'))])
    payment_method = models.CharField(max_length=50)
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='Pending')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'orders'
        ordering = ['-created_at']

    def __str__(self):
        return self.order_number


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='order_items')
    quantity = models.IntegerField(validators=[MinValueValidator(1)])
    price = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.00'))])
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.00'))])

    class Meta:
        db_table = 'order_items'


class Cart(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='cart_items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='cart_items')
    quantity = models.IntegerField(default=1, validators=[MinValueValidator(1)])
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'carts'
        constraints = [models.UniqueConstraint(fields=['user', 'product'], name='unique_user_cart_product')]


class Payment(models.Model):
    PAYMENT_STATUS_CHOICES = [('Pending', 'Pending'), ('Completed', 'Completed'), ('Failed', 'Failed')]
    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name='payments')
    payment_id = models.CharField(max_length=100, null=True, blank=True, unique=True)
    method_number = models.CharField(max_length=50, blank=True, default='')
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.00'))])
    status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='Pending')
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'payments'
        indexes = [models.Index(fields=['status', 'created_at'], name='payment_status_created_idx')]

    def __str__(self):
        return f'Payment for {self.order.order_number}'


class Supplier(models.Model):
    name = models.CharField(max_length=200, unique=True)
    contact_name = models.CharField(max_length=150, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    address = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'suppliers'
        ordering = ['name']

    def __str__(self):
        return self.name


class PurchaseOrder(models.Model):
    STATUS_DRAFT = 'draft'
    STATUS_ORDERED = 'ordered'
    STATUS_PARTIAL = 'partially_received'
    STATUS_RECEIVED = 'received'
    STATUS_CANCELLED = 'cancelled'
    STATUS_CHOICES = [
        (STATUS_DRAFT, 'Draft'), (STATUS_ORDERED, 'Ordered'),
        (STATUS_PARTIAL, 'Partially received'), (STATUS_RECEIVED, 'Received'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]
    po_number = models.CharField(max_length=40, unique=True)
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name='purchase_orders')
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default=STATUS_DRAFT, db_index=True)
    expected_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    total_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='created_purchase_orders')
    created_at = models.DateTimeField(auto_now_add=True)
    ordered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'purchase_orders'
        ordering = ['-created_at']
        indexes = [models.Index(fields=['status', 'created_at'], name='po_status_created_idx'), models.Index(fields=['supplier', 'created_at'], name='po_supplier_created_idx')]

    def __str__(self):
        return self.po_number


class PurchaseItem(models.Model):
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.PROTECT, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='purchase_items')
    quantity_ordered = models.DecimalField(max_digits=12, decimal_places=3, validators=[MinValueValidator(Decimal('0.001'))])
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.00'))])

    class Meta:
        db_table = 'purchase_items'
        constraints = [models.UniqueConstraint(fields=['purchase_order', 'product'], name='unique_product_per_po')]

    @property
    def quantity_received(self):
        total = self.receipt_items.filter(receipt__status=GoodsReceipt.STATUS_POSTED).aggregate(total=models.Sum('quantity_received'))['total']
        return total or Decimal('0.000')

    @property
    def quantity_remaining(self):
        return self.quantity_ordered - self.quantity_received

    @property
    def line_total(self):
        return self.quantity_ordered * self.unit_cost

    def __str__(self):
        return f'{self.purchase_order.po_number}: {self.product.name}'


class GoodsReceipt(models.Model):
    STATUS_DRAFT = 'draft'
    STATUS_POSTED = 'posted'
    STATUS_CHOICES = [(STATUS_DRAFT, 'Draft'), (STATUS_POSTED, 'Posted')]
    receipt_number = models.CharField(max_length=40, unique=True)
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.PROTECT, related_name='receipts')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='goods_receipts')
    received_at = models.DateTimeField(default=timezone.now)
    notes = models.TextField(blank=True)
    idempotency_key = models.CharField(max_length=100, unique=True, null=True, blank=True)

    class Meta:
        db_table = 'goods_receipts'
        ordering = ['-received_at']

    def __str__(self):
        return self.receipt_number


class GoodsReceiptItem(models.Model):
    receipt = models.ForeignKey(GoodsReceipt, on_delete=models.PROTECT, related_name='items')
    purchase_item = models.ForeignKey(PurchaseItem, on_delete=models.PROTECT, related_name='receipt_items')
    quantity_received = models.DecimalField(max_digits=12, decimal_places=3, validators=[MinValueValidator(Decimal('0.001'))])
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.00'))])

    class Meta:
        db_table = 'goods_receipt_items'
        constraints = [models.UniqueConstraint(fields=['receipt', 'purchase_item'], name='unique_po_line_per_receipt')]

    def __str__(self):
        return f'{self.receipt.receipt_number}: {self.purchase_item.product.name}'


class Inventory(models.Model):
    product = models.OneToOneField(Product, on_delete=models.PROTECT, related_name='inventory')
    quantity_on_hand = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal('0.000'), validators=[MinValueValidator(Decimal('0.000'))])
    quantity_reserved = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal('0.000'), validators=[MinValueValidator(Decimal('0.000'))])
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'inventory'
        constraints = [models.CheckConstraint(condition=models.Q(quantity_reserved__lte=models.F('quantity_on_hand')), name='reserved_lte_on_hand')]

    @property
    def quantity_available(self):
        return self.quantity_on_hand - self.quantity_reserved

    def __str__(self):
        return f'{self.product.sku or self.product.name}: {self.quantity_available} available'


class StockMovement(models.Model):
    TYPE_OPENING = 'opening'
    TYPE_RECEIPT = 'receipt'
    TYPE_ADJUSTMENT = 'adjustment'
    TYPE_DAMAGE = 'damage'
    TYPE_SALE = 'sale'
    TYPE_RETURN = 'return'
    TYPE_CHOICES = [(TYPE_OPENING, 'Opening balance'), (TYPE_RECEIPT, 'Purchase receipt'), (TYPE_ADJUSTMENT, 'Adjustment'), (TYPE_DAMAGE, 'Damage'), (TYPE_SALE, 'Sale'), (TYPE_RETURN, 'Return')]
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='stock_movements')
    movement_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    quantity_delta = models.DecimalField(max_digits=12, decimal_places=3)
    quantity_after = models.DecimalField(max_digits=12, decimal_places=3)
    receipt_item = models.OneToOneField(GoodsReceiptItem, on_delete=models.PROTECT, related_name='stock_movement', null=True, blank=True)
    reference = models.CharField(max_length=100, blank=True)
    reason = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='stock_movements')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'stock_movements'
        ordering = ['-created_at', '-id']
        indexes = [models.Index(fields=['product', 'created_at'], name='movement_product_date_idx')]

    def __str__(self):
        return f'{self.product}: {self.quantity_delta:+} ({self.movement_type})'


class AuditLog(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='ecommerce_audit_events')
    action = models.CharField(max_length=80)
    entity_type = models.CharField(max_length=80)
    entity_id = models.CharField(max_length=80)
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'audit_logs'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.action} {self.entity_type}#{self.entity_id}'


class Wishlist(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='wishlist_items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='wishlist_items')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'wishlists'
        constraints = [models.UniqueConstraint(fields=['user', 'product'], name='unique_user_wishlist_product')]

    def __str__(self):
        return f'{self.user.username}: {self.product.name}'
