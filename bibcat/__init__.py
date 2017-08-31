"""BIBCAT is a RDF-based Bibliographic Catalog"""
import re
import urllib.parse
import pkg_resources
import rdflib
from rdflib.term import _is_valid_uri

__author__ = "Jeremy Nelson, Mike Stabile, Jay Peterson"
__version__ = pkg_resources.get_distribution("bibcat").version

def clean_uris(graph):
    """Iterates through all URIRef subjects and objects and attempts to fix any
    issues with URL.

    Args:
        graph(rdflib.Graph): BIBFRAME RDF Graph
    """
    def fix_uri(uri):
        """Function attempts to take an invalid uri and return a valid URI

        Args:
            uri(str): Questionable URI
        """
        url_sections = urllib.parse.urlparse(str(uri))
        new_url = (url_sections.scheme,
                   url_sections.netloc,
                   urllib.parse.quote(url_sections.path),
                   urllib.parse.quote(url_sections.params),
                   urllib.parse.quote(url_sections.query),
                   urllib.parse.quote(url_sections.fragment))
        new_uri = rdflib.URIRef(
            str(urllib.parse.urlunparse(new_url)))
        replace_iri(graph, uri, new_uri)
    all_uri_sparql = """SELECT DISTINCT ?uri
        WHERE {
            ?uri ?p ?o .
            ?s ?p1 ?uri .
        FILTER(isIRI(?uri))
    }"""
    for iri in graph.query(all_uri_sparql):
        try:
            if _is_valid_uri(str(iri[0])) is False:
                fix_uri(iri[0])
        except rdflib.exceptions.SubjectTypeError:
            fix_uri(iri)

def delete_bnode(bnode, graph):
    """Deletes blank node and associated triples

    Args:
        bnode(rdflib.BNode): Blank node to delete
        graph(rdflib.Graph|rdflib.ConjuctiveGraph): Graph
    """
    for pred, obj in graph.predicate_objects(subject=bnode):
        if isinstance(obj, rdflib.BNode):
            delete_bnode(obj, graph)
        graph.remove((bnode, pred, obj))
    for sub, pred in graph.subject_predicates(object=bnode):
        graph.remove((sub, pred, bnode))


def delete_iri(entity_iri, graph):
    """Deletes all triples associated with an entity in a graph

    Args:
        entity_iri(rdflib.URIRef): IRI of entity
        graph(rdflib.Graph|rdflib.ConjuctiveGraph): Graph
    """
    for pred, obj in graph.predicate_objects(subject=entity_iri):
        if isinstance(obj, rdflib.BNode):
            delete_bnode(obj, graph)
        graph.remove((entity_iri, pred, obj))
    for subj, pred in graph.subject_predicates(object=entity_iri):
        graph.remove((subj, pred, entity_iri))

def replace_iri(graph, old_iri, new_iri):
    """Replaces old IRI with a new IRI in the graph

    Args:

    ----
        graph: rdflib.Graph
        old_iri: rdflib.URIRef, Old IRI
        new_iri: rdflib.URIRef, New IRI
    """
    if old_iri == new_iri:
        # Otherwise deletes all occurrences of the iri in the
        # graph
        return
    for pred, obj in graph.predicate_objects(subject=old_iri):
        graph.add((new_iri, pred, obj))
        graph.remove((old_iri, pred, obj))
    for subj, pred in graph.subject_predicates(object=old_iri):
        graph.add((subj, pred, new_iri))
        graph.remove((subj, pred, old_iri))


def slugify(value):
    """
    Converts to lowercase, removes non-word characters (alphanumerics and
    underscores) and converts spaces to hyphens. Also strips leading and
    trailing whitespace. Adapted from Django's slugify function
    """
    value = re.sub(r'[^\w\s-]', '', value).strip().lower()
    return re.sub(r'[-\s]+', '-', value)


def wikify(value):
    """Converts value to wikipedia "style" of URLS, removes non-word characters
    and converts spaces to hyphens and leaves case of value.
    """
    value = re.sub(r'[^\w\s-]', '', value).strip()
    return re.sub(r'[-\s]+', '_', value)
