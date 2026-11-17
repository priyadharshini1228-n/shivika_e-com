from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import render, get_object_or_404
from .models import Category, Inventory, Product


def home(request):
    products = Product.objects.filter(is_active=True, category__is_active=True).select_related('category').order_by('name')
    query = request.GET.get('q', '').strip()
    category_slug = request.GET.get('category', '').strip()
    if query:
        products = products.filter(Q(name__icontains=query) | Q(description__icontains=query) | Q(sku__icontains=query))
    if category_slug:
        products = products.filter(category__slug=category_slug)
    categories = Category.objects.filter(is_active=True).order_by('name')
    page_obj = Paginator(products, 12).get_page(request.GET.get('page'))
    return render(request, 'ecommerce/home.html', {
        'page_obj': page_obj, 'categories': categories, 'query': query,
        'selected_category': category_slug,
    })


def product_detail(request, slug):
    product = get_object_or_404(Product.objects.select_related('category'), slug=slug, is_active=True, category__is_active=True)
    try:
        available = product.inventory.quantity_available
    except Inventory.DoesNotExist:
        available = 0
    return render(request, 'ecommerce/product_detail.html', {'product': product, 'available_stock': available})
