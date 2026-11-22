from decimal import Decimal
from uuid import uuid4

from django.contrib import messages
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.shortcuts import render, get_object_or_404, redirect
from django.utils import timezone

from .models import (
    Address, Cart, Category, Inventory, Order, OrderItem, Payment,
    Product, StockMovement, Wishlist, User,
)


def _legacy_user(request):
    auth_user = request.user
    if not auth_user.is_authenticated:
        return None
    user, _ = User.objects.get_or_create(
        username=auth_user.username,
        defaults={
            'email': auth_user.email or f'{auth_user.username}@local.shivika',
            'password': '!', 'first_name': auth_user.first_name,
            'last_name': auth_user.last_name,
        },
    )
    return user


def _customer_context(request):
    user = _legacy_user(request)
    cart_count = Cart.objects.filter(user=user).count() if user else 0
    wishlist_count = Wishlist.objects.filter(user=user).count() if user else 0
    return {'cart_count': cart_count, 'wishlist_count': wishlist_count}


def home(request):
    products = Product.objects.filter(is_active=True, category__is_active=True).select_related('category', 'inventory').order_by('-created_at')
    query = request.GET.get('q', '').strip()
    category_slug = request.GET.get('category', '').strip()
    if query:
        products = products.filter(Q(name__icontains=query) | Q(description__icontains=query) | Q(sku__icontains=query))
    if category_slug:
        products = products.filter(category__slug=category_slug)
    categories = Category.objects.filter(is_active=True).order_by('name')
    wishlist_ids = set()
    legacy_user = _legacy_user(request)
    if legacy_user:
        wishlist_ids = set(Wishlist.objects.filter(user=legacy_user).values_list('product_id', flat=True))
    context = _customer_context(request)
    context.update({'products': products, 'categories': categories, 'query': query,
                    'selected_category': category_slug, 'wishlist_ids': wishlist_ids,
                    'featured_category': categories.first() if categories else None})
    return render(request, 'ecommerce/home.html', context)


def product_detail(request, slug):
    product = get_object_or_404(Product.objects.select_related('category'), slug=slug, is_active=True, category__is_active=True)
    try:
        available = product.inventory.quantity_available
    except Inventory.DoesNotExist:
        available = 0
    legacy_user = _legacy_user(request)
    in_wishlist = bool(legacy_user and Wishlist.objects.filter(user=legacy_user, product=product).exists())
    related = Product.objects.filter(category=product.category, is_active=True).exclude(pk=product.pk).select_related('category')[:4]
    context = _customer_context(request)
    context.update({'product': product, 'available_stock': available, 'in_wishlist': in_wishlist, 'related': related})
    return render(request, 'ecommerce/product_detail_modern.html', context)


@login_required(login_url='/login/')
def wishlist_toggle(request, slug):
    if request.method != 'POST':
        return redirect('product_detail', slug=slug)
    product = get_object_or_404(Product, slug=slug, is_active=True)
    user = _legacy_user(request)
    item = Wishlist.objects.filter(user=user, product=product)
    if item.exists():
        item.delete()
        messages.success(request, 'Removed from your wishlist.')
    else:
        Wishlist.objects.create(user=user, product=product)
        messages.success(request, 'Added to your wishlist.')
    next_url = request.POST.get('next')
    return redirect(next_url or 'wishlist')


@login_required(login_url='/login/')
def wishlist_view(request):
    user = _legacy_user(request)
    items = Wishlist.objects.filter(user=user).select_related('product', 'product__category')
    context = _customer_context(request)
    context['wishlist_items'] = items
    return render(request, 'ecommerce/wishlist.html', context)


@login_required(login_url='/login/')
def cart_add(request, slug):
    if request.method != 'POST':
        return redirect('product_detail', slug=slug)
    product = get_object_or_404(Product, slug=slug, is_active=True)
    try:
        available = product.inventory.quantity_available
    except Inventory.DoesNotExist:
        available = 0
    quantity = max(1, min(int(request.POST.get('quantity', 1) or 1), 10))
    if available < quantity:
        messages.error(request, 'Not enough stock is available for this quantity.')
        return redirect(request.POST.get('next') or 'product_detail', slug=slug)
    user = _legacy_user(request)
    item, created = Cart.objects.get_or_create(user=user, product=product, defaults={'quantity': quantity})
    if not created:
        item.quantity = min(item.quantity + quantity, int(available), 10)
        item.save(update_fields=['quantity'])
    messages.success(request, f'{product.name} added to cart.')
    if request.POST.get('buy_now'):
        return redirect('checkout')
    return redirect(request.POST.get('next') or 'cart')


@login_required(login_url='/login/')
def cart_view(request):
    user = _legacy_user(request)
    items = list(Cart.objects.filter(user=user).select_related('product', 'product__category'))
    subtotal = sum((item.product.price * item.quantity for item in items), Decimal('0.00'))
    delivery = Decimal('0.00') if subtotal >= Decimal('499.00') or subtotal == 0 else Decimal('49.00')
    context = _customer_context(request)
    context.update({'cart_items': items, 'subtotal': subtotal, 'delivery': delivery,
                    'grand_total': subtotal + delivery})
    return render(request, 'ecommerce/cart.html', context)


@login_required(login_url='/login/')
def cart_update(request, item_id):
    if request.method != 'POST':
        return redirect('cart')
    item = get_object_or_404(Cart, pk=item_id, user=_legacy_user(request))
    action = request.POST.get('action')
    if action == 'remove':
        item.delete()
        messages.success(request, 'Item removed from cart.')
    else:
        quantity = int(request.POST.get('quantity', item.quantity) or 1)
        try:
            available = item.product.inventory.quantity_available
        except Inventory.DoesNotExist:
            available = 0
        item.quantity = max(1, min(quantity, int(available), 10))
        item.save(update_fields=['quantity'])
    return redirect('cart')


@login_required(login_url='/login/')
@transaction.atomic
def checkout(request):
    user = _legacy_user(request)
    cart_items = list(Cart.objects.select_for_update().filter(user=user).select_related('product'))
    if not cart_items:
        messages.info(request, 'Your cart is empty.')
        return redirect('home')

    subtotal = sum((item.product.price * item.quantity for item in cart_items), Decimal('0.00'))
    delivery = Decimal('0.00') if subtotal >= Decimal('499.00') else Decimal('49.00')
    grand_total = subtotal + delivery
    addresses = Address.objects.filter(user=user).order_by('-is_default', '-pk')

    if request.method == 'POST':
        selected_address = request.POST.get('address')
        if selected_address:
            address = get_object_or_404(Address, pk=selected_address, user=user)
        else:
            full_name = request.POST.get('full_name', '').strip()
            phone = request.POST.get('phone', '').strip()
            line1 = request.POST.get('address_line1', '').strip()
            city = request.POST.get('city', '').strip()
            state = request.POST.get('state', '').strip()
            postal = request.POST.get('postal_code', '').strip()
            if not all([full_name, phone, line1, city, state, postal]):
                messages.error(request, 'Please complete all required delivery address fields.')
                context = _customer_context(request)
                context.update({'cart_items': cart_items, 'addresses': addresses, 'subtotal': subtotal,
                                'delivery': delivery, 'grand_total': grand_total})
                return render(request, 'ecommerce/checkout.html', context)
            address = Address.objects.create(user=user, full_name=full_name, phone=phone,
                address_line1=line1, address_line2=request.POST.get('address_line2', '').strip(),
                city=city, state=state, postal_code=postal, country=request.POST.get('country', 'India').strip() or 'India',
                is_default=not addresses.exists())

        inventories = {inv.product_id: inv for inv in Inventory.objects.select_for_update().filter(product_id__in=[item.product_id for item in cart_items])}
        for item in cart_items:
            inventory = inventories.get(item.product_id)
            available = inventory.quantity_available if inventory else Decimal('0')
            if item.quantity > available:
                messages.error(request, f'{item.product.name} is no longer available in the requested quantity.')
                return redirect('cart')

        order = Order.objects.create(user=user, address=address,
            order_number=f'SHV-{uuid4().hex[:10].upper()}', status='Processing',
            total_amount=grand_total, payment_method=request.POST.get('payment_method', 'Cash on Delivery'),
            payment_status='Pending')
        for item in cart_items:
            subtotal_line = item.product.price * item.quantity
            OrderItem.objects.create(order=order, product=item.product, quantity=item.quantity,
                                     price=item.product.price, subtotal=subtotal_line)
            inventory = inventories[item.product_id]
            inventory.quantity_on_hand -= Decimal(item.quantity)
            inventory.save(update_fields=['quantity_on_hand', 'updated_at'])
            StockMovement.objects.create(product=item.product, movement_type=StockMovement.TYPE_SALE,
                quantity_delta=Decimal(-item.quantity), quantity_after=inventory.quantity_on_hand,
                reference=order.order_number, reason='Customer order sale', created_by=request.user)
        payment_status = 'Completed' if order.payment_method != 'Cash on Delivery' else 'Pending'
        order.payment_status = payment_status
        order.save(update_fields=['payment_status'])
        Payment.objects.create(order=order, amount=grand_total,
            status=payment_status, method_number='', paid_at=timezone.now() if payment_status == 'Completed' else None)
        Cart.objects.filter(user=user).delete()
        messages.success(request, f'Order {order.order_number} placed successfully.')
        return redirect('order_detail', order_number=order.order_number)

    context = _customer_context(request)
    context.update({'cart_items': cart_items, 'addresses': addresses, 'subtotal': subtotal,
                    'delivery': delivery, 'grand_total': grand_total})
    return render(request, 'ecommerce/checkout.html', context)


@login_required(login_url='/login/')
def order_list(request):
    user = _legacy_user(request)
    orders = Order.objects.filter(user=user).prefetch_related('items__product').order_by('-created_at')
    context = _customer_context(request)
    context['orders'] = orders
    return render(request, 'ecommerce/orders.html', context)


@login_required(login_url='/login/')
def order_detail(request, order_number):
    user = _legacy_user(request)
    order = get_object_or_404(Order.objects.prefetch_related('items__product', 'payments'),
                              order_number=order_number, user=user)
    context = _customer_context(request)
    context['order'] = order
    return render(request, 'ecommerce/order_detail.html', context)


def customer_login(request):
    if request.user.is_authenticated:
        return redirect('home')
    if request.method == 'POST':
        auth_user = authenticate(request, username=request.POST.get('username', '').strip(),
                                 password=request.POST.get('password', ''))
        if auth_user:
            login(request, auth_user)
            return redirect(request.GET.get('next') or 'home')
        messages.error(request, 'Incorrect username or password.')
    return render(request, 'ecommerce/login.html')


def customer_register(request):
    if request.user.is_authenticated:
        return redirect('home')
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        UserModel = get_user_model()
        if not all([username, email, password, first_name]):
            messages.error(request, 'Please complete all required fields.')
        elif UserModel.objects.filter(username=username).exists():
            messages.error(request, 'That username is already taken.')
        elif UserModel.objects.filter(email=email).exists():
            messages.error(request, 'That email is already registered.')
        else:
            auth_user = UserModel.objects.create_user(username=username, email=email, password=password,
                                                      first_name=first_name, last_name=last_name)
            login(request, auth_user)
            messages.success(request, 'Welcome to Shivika!')
            return redirect('home')
    return render(request, 'ecommerce/register.html')


def customer_logout(request):
    logout(request)
    return redirect('home')
