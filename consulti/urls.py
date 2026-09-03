from django.urls import path

from . import views

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
    path('<int:pk>/upload/stato/', views.upload_stato, name='upload_stato'),
    path('<int:pk>/upload/pezzo/', views.upload_pezzo, name='upload_pezzo'),
    path('<int:pk>/upload/concludi/', views.upload_concludi, name='upload_concludi'),
]
