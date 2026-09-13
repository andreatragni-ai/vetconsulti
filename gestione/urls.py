from django.urls import path

from . import views, views_persone, views_soldi

app_name = 'gestione'

urlpatterns = [
    path('', views.cruscotto, name='cruscotto'),
    path('casi/', views.casi, name='casi'),
    path('casi/<int:pk>/', views.caso, name='caso'),
    path('casi/<int:pk>/sposta/', views.sposta, name='sposta'),
    path('casi/<int:pk>/annulla/', views.annulla, name='annulla'),
    path('iscrizioni/', views_persone.iscrizioni, name='iscrizioni'),
    path('iscrizioni/clinica/<int:pk>/approva/', views_persone.clinica_approva, name='clinica_approva'),
    path('iscrizioni/libero/<int:pk>/approva/', views_persone.richiedente_approva, name='richiedente_approva'),
    path('refertatori/', views_persone.refertatori, name='refertatori'),
    path('refertatori/nuovo/', views_persone.refertatore_nuovo, name='refertatore_nuovo'),
    path('refertatori/<int:pk>/', views_persone.refertatore, name='refertatore'),
    path('refertatori/<int:pk>/invito/', views_persone.refertatore_invito, name='refertatore_invito'),
    path('listino/', views_soldi.listino, name='listino'),
    path('listino/<str:tipo>/cambia/', views_soldi.listino_cambia, name='listino_cambia'),
    path('listino/supplemento/<int:pk>/cambia/', views_soldi.supplemento_cambia, name='supplemento_cambia'),
    path('prestazioni/', views_soldi.prestazioni, name='prestazioni'),
    path('prestazioni/<int:pk>/fatturazione/', views_soldi.fatturazione_cambia, name='fatturazione_cambia'),
]
