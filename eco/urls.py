from django.urls import path

from . import views

app_name = 'eco'

urlpatterns = [
    path('protocollo/', views.protocollo, name='protocollo'),
    path('protocollo.pdf', views.protocollo_pdf, name='protocollo_pdf'),
]
