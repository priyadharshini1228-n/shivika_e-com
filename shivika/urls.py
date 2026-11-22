from django.contrib import admin
from django.urls import path
from ecommerce import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.home, name='home'),
    path('products/<slug:slug>/', views.product_detail, name='product_detail'),
    path('wishlist/', views.wishlist_view, name='wishlist'),
    path('wishlist/<slug:slug>/toggle/', views.wishlist_toggle, name='wishlist_toggle'),
    path('cart/', views.cart_view, name='cart'),
    path('cart/add/<slug:slug>/', views.cart_add, name='cart_add'),
    path('cart/item/<int:item_id>/update/', views.cart_update, name='cart_update'),
    path('checkout/', views.checkout, name='checkout'),
    path('orders/', views.order_list, name='order_list'),
    path('orders/<str:order_number>/', views.order_detail, name='order_detail'),
    path('login/', views.customer_login, name='login'),
    path('register/', views.customer_register, name='register'),
    path('logout/', views.customer_logout, name='logout'),
]
