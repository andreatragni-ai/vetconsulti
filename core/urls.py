from django.urls import path

from . import views

app_name = 'core'

urlpatterns = [
    path('privacy/', views.privacy, name='privacy'),
    path('termini/', views.termini, name='termini'),
]
