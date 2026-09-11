from django.urls import path

from . import views, views_decisione

app_name = 'consulti'

urlpatterns = [
    path('', views.mie_richieste, name='mie_richieste'),
    path('nuova/', views.nuova_richiesta, name='nuova'),
    path('esperti/', views.esperti, name='esperti'),
    path('<int:pk>/', views.dettaglio, name='dettaglio'),
    path('<int:pk>/allegato/', views.carica_allegato, name='carica_allegato'),
    path('<int:pk>/allegato/<int:allegato_pk>/elimina/', views.elimina_allegato, name='elimina_allegato'),
    path('<int:pk>/invia/', views.invia, name='invia'),
    path('<int:pk>/annulla/', views.annulla, name='annulla'),
    path('<int:pk>/riassegna/', views.riassegna, name='riassegna'),
    # Refertatore: elenco e decisioni (la pagina e' referti:refertazione).
    path('ricevuti/', views_decisione.casi_ricevuti, name='casi_ricevuti'),
    path('<int:pk>/prendi-in-carico/', views_decisione.prendi_in_carico, name='prendi_in_carico'),
    path('<int:pk>/declina/', views_decisione.declina, name='declina'),
    path('<int:pk>/non-refertabile/', views_decisione.non_refertabile, name='non_refertabile'),
    path('<int:pk>/upload/stato/', views.upload_stato, name='upload_stato'),
    path('<int:pk>/upload/pezzo/', views.upload_pezzo, name='upload_pezzo'),
    path('<int:pk>/upload/concludi/', views.upload_concludi, name='upload_concludi'),
]
