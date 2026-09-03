from django.urls import path

from . import views

app_name = 'referti'

urlpatterns = [
    path('<int:pk>/pdf/', views.stampa, name='stampa'),
]
