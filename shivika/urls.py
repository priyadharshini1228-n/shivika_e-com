from django.contrib import admin
from django.urls import path
from ecommerce import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.home, name='home'),
    path('products/<slug:slug>/', views.product_detail, name='product_detail'),
]
