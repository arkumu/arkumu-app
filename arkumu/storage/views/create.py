from django import forms
from django.http import HttpResponseRedirect
from django.shortcuts import render


class ProjectForm(forms.Form):
    bevorzugter_titel = forms.CharField(label="Bevorzugter Titel")
    sprache_bevorzugter_titel = forms.UUIDField(label="Sprache Bevorzugter Titel")
    bevorzugter_untertitel = forms.CharField(label="Bevorzugter Untertitel")
    sprache_bevorzugter_untertitel = forms.UUIDField(label="Sprache Bevorzugter Untertitel")
    beschreibung = forms.UUIDField(label="Beschreibung")
    projektart = forms.UUIDField(label="Projektart")
    deutscher_kommentar = forms.UUIDField(label="Deutscher Kommentar")
    englischer_kommentar = forms.UUIDField(label="Englischer Kommentar")

    # andere_normdaten = forms.UUIDField(label="Andere Normdatem")


def create_project(request):
    if request.method == "POST":
        form = ProjectForm(request.POST)
        if form.is_valid():
            return HttpResponseRedirect("/thanks/")
    else:
        form = ProjectForm()

    return render(request, "create/project.html", {"form": form})