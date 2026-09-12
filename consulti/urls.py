from django.urls import path

from . import views, views_decisione, views_dettatura, views_percorso, views_smistamento

app_name = 'consulti'

urlpatterns = [
    path('', views.mie_richieste, name='mie_richieste'),
    # Richiesta guidata: passi 1-2 prima che la bozza esista, poi <pk>/<passo>/.
    path('nuova/', views_percorso.nuova_paziente, name='nuova'),
    path('nuova/esame/', views_percorso.nuova_esame, name='nuova_esame'),
    path('esperti/', views_percorso.esperti, name='esperti'),
    # Dettatura vocale: «Ripulisci» il testo dettato (solo testo all'AI).
    path('ripulisci/', views_dettatura.ripulisci, name='ripulisci'),
    path('<int:pk>/paziente/', views_percorso.passo_paziente, name='passo_paziente'),
    path('<int:pk>/esame/', views_percorso.passo_esame, name='passo_esame'),
    path('<int:pk>/carica/', views_percorso.passo_carica, name='passo_carica'),
    path('<int:pk>/riepilogo/', views_percorso.passo_riepilogo, name='passo_riepilogo'),
    # Eco: tavolo di smistamento del passo 3 (eco/smistamento/).
    path('<int:pk>/smistamento/avvia/', views_smistamento.avvia, name='smistamento_avvia'),
    path('<int:pk>/smistamento/stato/', views_smistamento.stato, name='smistamento_stato'),
    path('<int:pk>/smistamento/sposta/', views_smistamento.sposta, name='smistamento_sposta'),
    path('<int:pk>/smistamento/conferma/', views_smistamento.conferma, name='smistamento_conferma'),
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
