from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from . import views

app_name = 'accounts'

urlpatterns = [
    path('', views.home, name='home'),
    path('accedi/', views.Accedi.as_view(), name='accedi'),
    path('esci/', views.Esci.as_view(), name='esci'),
    path('registrati/', views.registrati, name='registrati'),
    path('registrati/<slug:tipo>/', views.registrati, name='registrati_tipo'),
    path('registrati/invito/<str:token>/', views.registrati_invitato, name='registrati_invitato'),
    path('conferma-email/<uidb64>/<token>/', views.conferma_email, name='conferma_email'),

    path('profilo/', views.profilo_richiedente, name='profilo_richiedente'),
    path('profilo/refertatore/', views.profilo_refertatore, name='profilo_refertatore'),
    path('profilo/refertatore/diventa-richiedente/', views.refertatore_diventa_richiedente,
         name='refertatore_diventa_richiedente'),

    path('gestione/refertatori/', views.admin_refertatori, name='admin_refertatori'),
    path('gestione/refertatori/nuovo/', views.admin_refertatore_aggiungi, name='admin_refertatore_aggiungi'),
    path('gestione/richiedenti/', views.admin_richiedenti, name='admin_richiedenti'),
    path('gestione/cliniche/<int:pk>/approva/', views.admin_clinica_approva, name='admin_clinica_approva'),
    path('gestione/richiedenti/<int:pk>/approva/', views.admin_richiedente_approva, name='admin_richiedente_approva'),

    # Cambio password (utente loggato) e reset: viste di Django con i nostri template.
    path('password/cambia/', auth_views.PasswordChangeView.as_view(
        template_name='accounts/password_cambia.html',
        success_url=reverse_lazy('accounts:password_cambiata')), name='password_cambia'),
    path('password/cambiata/', views.password_cambiata, name='password_cambiata'),
    path('password/reset/', auth_views.PasswordResetView.as_view(
        template_name='accounts/password_reset.html',
        email_template_name='accounts/password_reset_email.txt',
        subject_template_name='accounts/password_reset_subject.txt',
        success_url=reverse_lazy('accounts:password_reset_inviato')), name='password_reset'),
    path('password/reset/inviato/', auth_views.PasswordResetDoneView.as_view(
        template_name='accounts/password_reset_inviato.html'), name='password_reset_inviato'),
    path('password/reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        template_name='accounts/password_reset_conferma.html',
        success_url=reverse_lazy('accounts:password_reset_fatto')), name='password_reset_confirm'),
    path('password/reset/fatto/', auth_views.PasswordResetCompleteView.as_view(
        template_name='accounts/password_reset_fatto.html'), name='password_reset_fatto'),
]
