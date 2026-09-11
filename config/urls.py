"""Rotte di primo livello. Ogni app ha il suo urls.py con namespace."""

from django.contrib import admin
from django.urls import include, path

from core import views_media

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('core.urls')),
    path('', include('accounts.urls')),
    path('consulti/', include('consulti.urls')),
    path('referti/', include('referti.urls')),
    # Consegna protetta dei file: MAI static(MEDIA_URL) qui, nemmeno in DEBUG.
    path('allegati/<int:pk>/scarica/', views_media.scarica_allegato, name='scarica_allegato'),
    path('eco/riferimento/<int:pk>/', views_media.immagine_riferimento, name='immagine_riferimento'),
    path('esperti/<int:pk>/foto/', views_media.foto_refertatore, name='foto_refertatore'),
]

admin.site.site_header = 'VetWay Consulti — amministrazione'
admin.site.site_title = 'VetWay Consulti'
admin.site.index_title = 'Gestione del portale'
