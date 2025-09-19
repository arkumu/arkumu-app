"""
Catalog views using harmonization rules for unified resource browsing.
"""

from django.views.generic import ListView, DetailView, TemplateView, View
from django.shortcuts import get_object_or_404
from django.db.models import F, Q, Count
from django.core.cache import cache
from django.http import Http404, HttpResponse
from django.template.loader import render_to_string
from django.middleware.csrf import get_token
from django.shortcuts import render
from django.db.models import Prefetch
from django.contrib.postgres.search import TrigramSimilarity


from arkumu.metadata.models.resource import ResourceType
from arkumu.metadata.models import Resource
from arkumu.metadata.models import Triple

from time import perf_counter
import uuid
from functools import singledispatchmethod




class Entity:
    @singledispatchmethod
    def __init__(self, arg):
        raise NotImplementedError("Not implemented for these arguments")

    @__init__.register
    def _(self, arg: Resource):
        self.uri = arg.uri
        self.init_helper(arg.id)

    @__init__.register
    def _(self, arg: Triple):
        self.uri = Resource.objects.get(id = arg.subject_id).uri
        self.init_helper(arg.subject_id)

    @__init__.register
    def _(self, arg: str):
        self.uri = arg
        subject = Resource.objects.get(uri=arg)
        self.init_helper(subject.id)
    
    @__init__.register
    def _(self, arg: uuid.UUID):
        self.uri = Resource.objects.get(id=arg).uri
        self.init_helper(arg)

    def init_helper(self, subject_id):
        self.id = subject_id
        self.name = Resource.objects.get(id=subject_id).name
        self.resources = {}
        for entity_field_triple in Triple.objects.filter(subject_id=subject_id):
            if Resource.objects.get(id=entity_field_triple.predicate_id).name not in self.resources:
                self.resources[Resource.objects.get(id=entity_field_triple.predicate_id).name] = [Resource.objects.get(id=entity_field_triple.object_id)]
            else:
                self.resources[Resource.objects.get(id=entity_field_triple.predicate_id).name].append(Resource.objects.get(id=entity_field_triple.object_id))
        self.properties = {}
        for entity_field_triple in Triple.objects.filter(subject_id=subject_id):
            if Resource.objects.get(id=entity_field_triple.predicate_id).name not in self.properties:
                self.properties[Resource.objects.get(id=entity_field_triple.predicate_id).name] = [Resource.objects.get(id=entity_field_triple.predicate_id)]
            else:
                self.properties[Resource.objects.get(id=entity_field_triple.predicate_id).name].append(Resource.objects.get(id=entity_field_triple.predicate_id))
        self.field_names = []
        for entity_field_triple in Triple.objects.filter(subject_id=subject_id):
            if Resource.objects.get(id=entity_field_triple.predicate_id).name not in self.field_names:
                self.field_names.append(Resource.objects.get(id=entity_field_triple.predicate_id).name)

    def __repr__(self):
        ret = {field_name : [resource.value for resource in self.resources[field_name]] if self.resources[field_name][0].resource_type == ResourceType.LITERAL else [resource.uri for resource in self.resources[field_name]] for field_name in self.field_names}
        return f"Entity with id: {self.id} \nvalues: {ret}"

    def __str__(self):
        return self.__repr__()

def split_breadcrumb(breadcrumb: str):
    return breadcrumb.split(">")[-1].strip()

def search_algo(search_string, search_fields = ["Bevorzugter Titel", "Bevorzugter Untertitel", "Schlagwort", "Beschreibung"]):
 #   title_predicates = Resource.objects.filter(name="Bevorzugter Titel")
  #  keyword_predicates = Resource.objects.filter(name="Schlagwort")
  #  description_predicates = Resource.objects.filter(name="Beschreibung")

    predicates = Resource.objects.filter(name__in=search_fields)


    query = Q()
    for predicate in predicates:
        query |= Q(predicate=predicate)

    if search_string == "":
        return  [Entity(triple) for triple in Triple.objects.filter(predicate=Resource.objects.filter(name="Bevorzugter Titel").last()).all()[:10]]
    
   # all_predicates = list(title_predicates) + list(keyword_predicates) + list(description_predicates)


    results = Triple.objects.filter(query).annotate(
        text_value=F('object__value')  # Get the actual text value
    ).annotate(
        similarity=TrigramSimilarity('text_value', search_string)
    ).filter(
        similarity__gt=0.1
    ).order_by('-similarity')[:10]
    
    return [Entity(triple) for triple in results]



# Hier wäre django.core.cache besonders gut
class Projekt:
    
    def __init__(self, proj: Entity):
        self.proj = proj

    @property
    def institution(self):
        return Entity(self.proj.resources["Einliefernde Hochschule"][0]).resources["Deutscher Name der Einliefernden Hochschule"][0].value

    @property
    def title(self):
        return self.proj.resources["Bevorzugter Titel"][0].value
    
    @property
    def alternative_title_set(self):
        if "Alternativer Titel-Set" in self.proj.resources:
            return [Entity(alt_title_resource).resources["Alternativer Titel"][0].value for alt_title_resource in self.proj.resources["Alternativer Titel-Set"]]
        else:
            return ""                

    @property
    def projektart(self):
        if "Projektart" in self.proj.resources:
            return [Entity(alt_title_resource).resources["Deutscher Name der Projektart"][0].value for alt_title_resource in self.proj.resources["Projektart"]]
        else:
            return "" 


    @property
    def subtitle(self):
        if "Bevorzugter Untertitel" in self.proj.resources:
            return self.proj.resources["Bevorzugter Untertitel"][0].value
        else:
            return ""

    @property
    def uri(self):
        return self.proj.uri
    
    def __calcActor(self):
        pred_im_ereignis = Im_ereignis_singleton().get_pred_im_ereignis(self.uri.split("/")[4])
        self.akteur_role_dict = {}
        self.min_date = 99999999999999
        self.max_date = -99999999999999
        if "Ereignis" in self.proj.resources:
            for ereignis_resource in self.proj.resources["Ereignis"]:
                
                ereignis = Entity(ereignis_resource)
                if "Ereignisbeginn" in ereignis.resources:
                    self.min_date = min(self.min_date, int(ereignis.resources["Ereignisbeginn"][0].value.split('-')[0]))
                if "Ereignisende" in ereignis.resources:
                    self.max_date = max(self.max_date, int(ereignis.resources["Ereignisende"][0].value.split('-')[0]))

                triples_cross_table = Triple.objects.filter(predicate_id=pred_im_ereignis.id, object_id=ereignis.id)


                akteur_ereignis_cross_entries = [Entity(triple) for triple in triples_cross_table]

                for cross_entry in akteur_ereignis_cross_entries:
                    # Extract Akteur entity

                    akteur = Entity(cross_entry.resources["AkteurIn im Ereignis"][0])


                    # Process roles
                    rollen_entities = [
                        Entity(rolle) for rolle in cross_entry.resources["Rollen der AkteurIn im Ereignis"]
                    ]

                    rollen_names = []
                    for rolle in rollen_entities:
                        if "Deutscher Name der Rolle (Breadcrumb)" in rolle.resources:
                            rollen_names.append(split_breadcrumb(rolle.resources["Deutscher Name der Rolle (Breadcrumb)"][0].value))

                    if akteur.resources["Deutscher Name"][0].value not in self.akteur_role_dict:
                        self.akteur_role_dict[akteur.resources["Deutscher Name"][0].value] = set(rollen_names)
                    else:
                        self.akteur_role_dict[akteur.resources["Deutscher Name"][0].value] |= set(rollen_names)

    @property
    def date_range(self):
        if "min_date" not in self.__dict__ or "max_date" not in self.__dict__:
            self.__calcActor()

        if self.min_date == 99999999999999 and self.max_date == -99999999999999:
            return  "?"
        else: 
            return f"{self.min_date if self.min_date != 99999999999999 else "?"} bis {self.max_date if self.max_date != -99999999999999 else "?"}" if self.min_date != self.max_date else f"{self.min_date}"
        
    @property
    def actors(self):
        if "akteur_role_dict" not in self.__dict__:
            self.__calcActor()
        return self.akteur_role_dict

    @property
    def categories(self):
        project_categories = [Entity(proj_cat) for proj_cat in self.proj.resources["Projektkategorie"]]
        return [split_breadcrumb(category.resources["Deutscher Name der Projektkategorie (Breadcrumb)"][0].value) for category in project_categories]
    
    @property
    def descriptions(self):
        if "Beschreibung" in self.proj.resources:
            return [Entity(alt_title_resource).resources["Beschreibung"][0].value for alt_title_resource in self.proj.resources["Beschreibung"]]
        else:
            return "" 

    @property
    def catchphrases(self):
        if "Schlagwort" in self.proj.resources:
            return [Entity(alt_title_resource).resources["Deutsches Wikidata-Label"][0].value for alt_title_resource in self.proj.resources["Schlagwort"]]
        else:
            return "" 
        

class Im_ereignis_singleton:
    _instance = None
    

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.data = {}
        return cls._instance

    def get_pred_im_ereignis(self, str):
        if str not in self.data:
                self.data.update({str: Resource.objects.get(uri=f"http://arkumu.org/data/{str}/properties/im-ereignis")})
        return self.data[str]
    
        
class Card:

    def search_cards(request):
        query = request.GET.get('query', None)

        #TODO Python fixen das es schneller wird

        projects = search_algo(query)
        project_ret = []

        for j, project in enumerate(projects):
            proj_entity = Projekt(project)

            project_ret.append({
                "year": proj_entity.date_range,
                "image":"images/main/card_1.png",
                "institution": proj_entity.institution,
                "title": proj_entity.title,
                "subtitle": proj_entity.subtitle,
                "button_text":"Projekt ansehen",
                "uri": proj_entity.uri
            })

            for i, (name, value) in enumerate(proj_entity.actors.items()):
                project_ret[j][f"contributor{i+1}_name"] = name
                project_ret[j][f"contributor{i+1}_role"] = ", ".join(value)
            
            for i, category in enumerate(proj_entity.categories):
                project_ret[j][f"category{i+1}"] = category

            if (len(proj_entity.actors) > 4):
                project_ret[j]["additional_contributors"] = f"{len(proj_entity.actors)-4} weitere{'s' if len(proj_entity.actors)-4 == 1 else ''}"

            if (len(proj_entity.categories) > 4):
                project_ret[j]["additional_categories"] = f"{len(proj_entity.categories)-4} weitere{'s' if len(proj_entity.categories)-4 == 1 else ''}"
            

        context = {'query': query,
            'results': project_ret}
        
        return render(request, 'catalog/card_grid_template.html', context)
    
class ProjektShow:
    
    def projekt(request):
        prt = "<Nothing to Print>"
        prt2 = "<Nothing to Print>"
        prt3 = "<Nothing to Print>"
        projekt_uri = request.GET.get('projekt', None)
        project_resource = Resource.objects.get(uri=projekt_uri)
        project = Entity(project_resource)
        
        
        proj_entity = Projekt(project)

        project_ret = {
            "year_range": proj_entity.date_range,
            "image":"images/main/card_1.png",
            "institution": proj_entity.institution,
            "title": proj_entity.title,
            "subtitle": proj_entity.subtitle,
            "alternative_title": "; ".join(proj_entity.alternative_title_set),
            "projektart": "; ".join(proj_entity.projektart),
            "categories": proj_entity.categories,
            "descriptions": proj_entity.descriptions,
            "catchphrases": proj_entity.catchphrases,
        }


        #TODO Python fixen das es schneller wird
        
        prt = keyword_cloud(10) # project_ret
        prt2 = proj_entity.alternative_title_set
        context = {'project': project_ret, "print": prt, "print2": prt2, "print3": prt3}
        
        
        return render(request, 'catalog/projekt.html', context)

# Temporary REST-API functions have been moved to arkumu/catalog/services/catalog_insights_service.py
# and are now accessible via the /api/catalog/ endpoints
