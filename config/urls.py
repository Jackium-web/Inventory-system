"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth import views as auth_views
from inventory.views import InventoryLoginView, admin_dashboard, admin_login
from django.urls import path, include
urlpatterns = [
    path(
        'admin-login/',
        admin_login,
        name='admin_login',
    ),
    path(
        'admin-dashboard/',
        admin_dashboard,
        name='admin_dashboard',
    ),
    path(
        'login/',
        InventoryLoginView.as_view(),
        name='login',
    ),
    path(
        'logout/',
        auth_views.LogoutView.as_view(),
        name='logout',
    ),
    # path('inventory/', include('inventory.urls')),
    path('', include('inventory.urls')),  # Set inventory app as the default route
]

urlpatterns += static(
    settings.MEDIA_URL,
    document_root=settings.MEDIA_ROOT
)