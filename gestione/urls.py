from django.urls import path

from . import views

app_name = 'gestione'

urlpatterns = [
    path('', views.cruscotto, name='cruscotto'),
    path('casi/', views.casi, name='casi'),
    path('casi/<int:pk>/', views.caso, name='caso'),
    path('casi/<int:pk>/sposta/', views.sposta, name='sposta'),
    path('casi/<int:pk>/annulla/', views.annulla, name='annulla'),
]
