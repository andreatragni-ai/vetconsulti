from django.urls import path

from . import views

app_name = 'referti'

urlpatterns = [
    # Pagina del refertatore: pk e' la RICHIESTA.
    path('caso/<int:pk>/', views.refertazione, name='refertazione'),
    path('caso/<int:pk>/salva/', views.salva_bozza, name='salva_bozza'),
    path('caso/<int:pk>/firma/', views.firma, name='firma'),
    path('caso/<int:pk>/rettifica/', views.rettifica, name='rettifica'),
    path('caso/<int:pk>/anteprima/', views.anteprima, name='anteprima'),
    # PDF firmati: pk e' il REFERTO (ultima versione) o la VERSIONE.
    path('<int:pk>/pdf/', views.stampa, name='stampa'),
    path('versione/<int:pk>/pdf/', views.stampa_versione, name='stampa_versione'),
]
