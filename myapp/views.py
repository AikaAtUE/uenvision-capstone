from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, HttpResponse

from .models import CustomUser

# Create your views here.

def login_view(request):
    if request.method == "POST":
        email = request.POST.get("email")
        password = request.POST.get("password")
        user = authenticate(request, username=email, password=password)
        if user is not None:
            login(request, user)
            return redirect("dashboard")
        return render(request, "login.html", {"error": "Invalid email or password."})
    return render(request, "login.html")


def signup_view(request):
    if request.method == "POST":
        last_name = request.POST.get("last_name")
        first_name = request.POST.get("first_name")
        middle_name = request.POST.get("middle_name", "")
        email = request.POST.get("email")
        password = request.POST.get("password")
        password2 = request.POST.get("password2")

        if password != password2:
            return render(request, "signup.html", {"error": "Passwords do not match."})

        if CustomUser.objects.filter(email=email).exists():
            return render(request, "signup.html", {"error": "An account with this email already exists."})

        user = CustomUser.objects.create_user(
            email=email,
            password=password,
            first_name=first_name,
            middle_name=middle_name,
            last_name=last_name,
        )
        login(request, user)
        return redirect("dashboard")
    return render(request, "signup.html")


def logout_view(request):
    logout(request)
    return redirect("login")


def forgot_password_view(request):
    return render(request, "forgot_password.html")


def reset_password_view(request):
    return render(request, "reset_password.html")


@login_required
def dashboard_view(request):
    return render(request, "dashboard.html", {"active_page": "dashboard"})


@login_required
def data_view(request):
    return render(request, "data.html", {"active_page": "data"})


@login_required
def feedback_view(request):
    return render(request, "feedback.html", {"active_page": "feedback"})


@login_required
def about_view(request):
    return render(request, "about.html", {"active_page": "about"})


@login_required
def settings_view(request):
    return render(request, "settings.html", {"active_page": "settings"})