"""Transactional business services. Call these from views/admin, never mutate stock directly."""
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .models import (
    AuditLog, GoodsReceipt, GoodsReceiptItem, Inventory, Product,
    PurchaseItem, PurchaseOrder, StockMovement,
)


def _decimal(value, field_name):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError({field_name: 'Enter a valid numeric value.'})
    if not result.is_finite():
        raise ValidationError({field_name: 'Value must be finite.'})
    return result


@transaction.atomic
def place_purchase_order(purchase_order_id, actor):
    """Move a draft PO to ordered; it intentionally does not change inventory."""
    po = PurchaseOrder.objects.select_for_update().get(pk=purchase_order_id)
    if not actor.is_authenticated or not (actor.is_superuser or actor.has_perm('ecommerce.change_purchaseorder')):
        raise ValidationError('You do not have permission to place purchase orders.')
    if po.status != PurchaseOrder.STATUS_DRAFT:
        raise ValidationError('Only draft purchase orders can be placed.')
    items = list(po.items.select_related('product').all())
    if not items:
        raise ValidationError('Add at least one product line before placing this purchase order.')
    total = Decimal('0.00')
    for item in items:
        if item.quantity_ordered <= 0 or item.unit_cost < 0:
            raise ValidationError('Purchase quantities must be positive and costs cannot be negative.')
        total += item.quantity_ordered * item.unit_cost
    po.total_amount = total.quantize(Decimal('0.01'))
    po.status = PurchaseOrder.STATUS_ORDERED
    po.ordered_at = timezone.now()
    po.save(update_fields=['total_amount', 'status', 'ordered_at'])
    AuditLog.objects.create(actor=actor, action='purchase_order_placed', entity_type='PurchaseOrder', entity_id=str(po.pk), details={'po_number': po.po_number, 'total': str(po.total_amount)})
    return po


@transaction.atomic
def post_goods_receipt(*, purchase_order_id, actor, lines, receipt_number=None, notes='', idempotency_key=None):
    """Post a partial/full delivery atomically.

    lines is an iterable of {'purchase_item_id': int, 'quantity': decimal-like}.
    Receipt rows, inventory changes, movement ledger and PO status either all commit or all roll back.
    """
    if not actor.is_authenticated or not (actor.is_superuser or actor.has_perm('ecommerce.add_goodsreceipt')):
        raise ValidationError('You do not have permission to receive goods.')
    if not lines:
        raise ValidationError('Provide at least one receipt line.')
    if idempotency_key:
        existing = GoodsReceipt.objects.filter(idempotency_key=idempotency_key).first()
        if existing:
            if existing.purchase_order_id != purchase_order_id or existing.status != GoodsReceipt.STATUS_POSTED:
                raise ValidationError('This idempotency key was already used for a different or incomplete receipt.')
            return existing

    po = PurchaseOrder.objects.select_for_update().get(pk=purchase_order_id)
    if po.status not in (PurchaseOrder.STATUS_ORDERED, PurchaseOrder.STATUS_PARTIAL):
        raise ValidationError('Only ordered or partially received purchase orders can receive goods.')

    normalized = []
    seen = set()
    for line in lines:
        try:
            item_id = int(line['purchase_item_id'])
        except (KeyError, TypeError, ValueError):
            raise ValidationError('Each receipt line requires a valid purchase_item_id.')
        qty = _decimal(line.get('quantity'), 'quantity')
        if qty <= 0:
            raise ValidationError('Received quantity must be greater than zero.')
        if item_id in seen:
            raise ValidationError('A purchase order line may appear only once in a receipt.')
        seen.add(item_id)
        normalized.append((item_id, qty))

    purchase_items = {
        item.pk: item for item in PurchaseItem.objects.select_for_update()
        .filter(purchase_order=po, pk__in=seen).select_related('product')
    }
    if len(purchase_items) != len(seen):
        raise ValidationError('Every receipt line must belong to this purchase order.')

    for item_id, qty in normalized:
        item = purchase_items[item_id]
        received = item.receipt_items.filter(receipt__status=GoodsReceipt.STATUS_POSTED).aggregate(total=Sum('quantity_received'))['total'] or Decimal('0.000')
        remaining = item.quantity_ordered - received
        if qty > remaining:
            raise ValidationError(f'{item.product.name}: requested {qty}, but only {remaining} remain to be received.')

    receipt = GoodsReceipt.objects.create(
        receipt_number=receipt_number or f'GR-{timezone.now():%Y%m%d%H%M%S}-{uuid4().hex[:6].upper()}',
        purchase_order=po, received_by=actor, notes=notes,
        idempotency_key=idempotency_key or None, status=GoodsReceipt.STATUS_DRAFT,
    )

    # Lock/create inventory rows in deterministic product order to reduce deadlock risk.
    product_ids = sorted({purchase_items[item_id].product_id for item_id, _ in normalized})
    for product_id in product_ids:
        product = Product.objects.get(pk=product_id)
        Inventory.objects.get_or_create(product=product)
    inventories = {inv.product_id: inv for inv in Inventory.objects.select_for_update().filter(product_id__in=product_ids).order_by('product_id')}

    receipt_items = []
    for item_id, qty in normalized:
        item = purchase_items[item_id]
        inv = inventories[item.product_id]
        receipt_item = GoodsReceiptItem.objects.create(
            receipt=receipt, purchase_item=item, quantity_received=qty, unit_cost=item.unit_cost,
        )
        inv.quantity_on_hand += qty
        inv.save(update_fields=['quantity_on_hand', 'updated_at'])
        receipt_items.append(receipt_item)
        StockMovement.objects.create(
            product=item.product, movement_type=StockMovement.TYPE_RECEIPT,
            quantity_delta=qty, quantity_after=inv.quantity_on_hand,
            receipt_item=receipt_item, reference=receipt.receipt_number,
            reason='Supplier goods receipt', created_by=actor,
        )

    receipt.status = GoodsReceipt.STATUS_POSTED
    receipt.save(update_fields=['status'])

    all_items = list(PurchaseItem.objects.filter(purchase_order=po))
    fully_received = True
    any_received = False
    for item in all_items:
        qty_received = item.receipt_items.filter(receipt__status=GoodsReceipt.STATUS_POSTED).aggregate(total=Sum('quantity_received'))['total'] or Decimal('0.000')
        any_received = any_received or qty_received > 0
        if qty_received < item.quantity_ordered:
            fully_received = False
    po.status = PurchaseOrder.STATUS_RECEIVED if fully_received else (PurchaseOrder.STATUS_PARTIAL if any_received else PurchaseOrder.STATUS_ORDERED)
    po.save(update_fields=['status'])
    AuditLog.objects.create(actor=actor, action='goods_receipt_posted', entity_type='GoodsReceipt', entity_id=str(receipt.pk), details={'receipt_number': receipt.receipt_number, 'po_number': po.po_number, 'lines': len(receipt_items)})
    return receipt


@transaction.atomic
def adjust_stock(*, product_id, quantity_delta, actor, reason, movement_type=StockMovement.TYPE_ADJUSTMENT, reference=''):
    """Apply a controlled stock correction and append an immutable movement record."""
    if not actor.is_authenticated or not (actor.is_superuser or actor.has_perm('ecommerce.change_inventory')):
        raise ValidationError('You do not have permission to adjust stock.')
    if not reason or not reason.strip():
        raise ValidationError({'reason': 'A reason is required for every stock adjustment.'})
    delta = _decimal(quantity_delta, 'quantity_delta')
    if delta == 0:
        raise ValidationError({'quantity_delta': 'Adjustment must not be zero.'})
    product = Product.objects.get(pk=product_id)
    inventory, _ = Inventory.objects.get_or_create(product=product)
    inventory = Inventory.objects.select_for_update().get(pk=inventory.pk)
    new_quantity = inventory.quantity_on_hand + delta
    if new_quantity < inventory.quantity_reserved:
        raise ValidationError('Adjustment would make stock lower than reserved quantity.')
    if new_quantity < 0:
        raise ValidationError('Stock cannot become negative.')
    inventory.quantity_on_hand = new_quantity
    inventory.save(update_fields=['quantity_on_hand', 'updated_at'])
    movement = StockMovement.objects.create(
        product=product, movement_type=movement_type, quantity_delta=delta,
        quantity_after=new_quantity, reference=reference, reason=reason.strip(), created_by=actor,
    )
    AuditLog.objects.create(actor=actor, action='stock_adjusted', entity_type='StockMovement', entity_id=str(movement.pk), details={'product_id': product.pk, 'delta': str(delta), 'reason': reason.strip()})
    return movement
