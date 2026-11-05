"""
URL configuration for UEnvision project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
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
from django.contrib import admin
from django.urls import path, include

from django.views.generic import RedirectView

from myapp import views

urlpatterns = [
    # before admin.site.urls so the admin's own login form (no attempt limits) is never used
    path('admin/login/', views.admin_login_view, name='admin_login'),
    path('admin/', admin.site.urls),
    # Google sign-in (django-allauth). Only Google's login + callback and allauth's
    # inactive-account page are its own; its other pages go to UEnvision's.
    path('auth/login/', RedirectView.as_view(pattern_name='login', query_string=True)),
    path('auth/logout/', RedirectView.as_view(pattern_name='logout')),
    path('auth/3rdparty/', RedirectView.as_view(pattern_name='settings')),
    path('auth/3rdparty/signup/', RedirectView.as_view(pattern_name='signup')),
    path('auth/3rdparty/login/cancelled/', views.google_cancelled_view, name='google_cancelled'),
    path('auth/3rdparty/login/error/', views.google_error_view, name='google_error'),
    path('auth/', include('allauth.urls')),
    path('', include('myapp.urls'))
]
