from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.shortcuts import redirect, render
from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken

from .serializers import RegisterSerializer, UserSerializer


# ──────────────────────────────────────────────
# API views (JSON, for Central Unit communication)
# ──────────────────────────────────────────────


class ApiRegisterView(generics.CreateAPIView):
    """Register a new user and return JWT tokens."""

    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        refresh = RefreshToken.for_user(user)
        return Response(
            {
                "user": UserSerializer(user).data,
                "access": str(refresh.access_token),
                "refresh": str(refresh),
            },
            status=201,
        )


class MeView(generics.RetrieveAPIView):
    """Return the currently authenticated user's profile."""

    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user


# ──────────────────────────────────────────────
# Web views (HTML, for browser)
# ──────────────────────────────────────────────


from django import forms

class CustomUserCreationForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = UserCreationForm.Meta.fields + ("email",)

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        if commit:
            user.save()
        return user

def register_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    if request.method == "POST":
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect("dashboard")
    else:
        form = CustomUserCreationForm()
    return render(request, "accounts/register.html", {"form": form})


@login_required
def dashboard_view(request):
    return render(request, "dashboard.html")


from django.contrib.auth.decorators import user_passes_test
from django.contrib import messages

def is_admin(user):
    return user.is_authenticated and user.is_superuser

@user_passes_test(is_admin, login_url="dashboard")
def manage_users_view(request):
    if request.method == "POST":
        updated_count = 0
        
        for key, new_role in request.POST.items():
            if key.startswith("role_"):
                try:
                    target_user_id = int(key.split("_")[1])
                    target_user = User.objects.get(id=target_user_id)
                    
                    # Prevent modifying the root admin or yourself
                    if target_user.username == "admin" or target_user == request.user:
                        continue
                        
                    # State tracking to avoid unnecessary saves
                    original_superuser = target_user.is_superuser
                    original_staff = target_user.is_staff
                    
                    if new_role == "superuser":
                        target_user.is_superuser = True
                        target_user.is_staff = True
                    elif new_role == "staff":
                        target_user.is_superuser = False
                        target_user.is_staff = True
                    else:
                        target_user.is_superuser = False
                        target_user.is_staff = False
                        
                    # Save only if there's a real change
                    if (original_superuser != target_user.is_superuser) or (original_staff != target_user.is_staff):
                        target_user.save()
                        updated_count += 1
                        
                except (ValueError, User.DoesNotExist):
                    continue
                    
        if updated_count > 0:
            messages.success(request, f"Pomyślnie zaktualizowano uprawnienia (zmieniono rekordów: {updated_count}).")
        else:
            messages.info(request, "Nie wykryto żadnych różnic wymagających zapisania.")
            
        return redirect("manage_users")
        
    all_users = User.objects.all().order_by("id")
    return render(request, "accounts/manage_users.html", {"users": all_users})

def custom_csrf_failure(request, reason=""):
    messages.error(request, "Twoja sesja bezpieczeństwa wygasła lub została przerwana. Zaloguj się ponownie.")
    return redirect("login")
