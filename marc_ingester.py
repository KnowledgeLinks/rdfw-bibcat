"""MARC21 to BIBFRAME 2.0 command-line ingester"""
__author__ = "Jeremy Nelson, Mike Stabile"

import os
import datetime
import logging
import inspect
import pymarc
import rdflib
import requests
import click
import uuid
from ingester import add_admin_metadata, add_admin_metadata, new_graph 
from collections import OrderedDict

# get the current file name for logs and set logging level
MNAME = inspect.stack()[0][1]
MLOG_LVL = logging.DEBUG
logging.basicConfig(level=logging.DEBUG)

BF = rdflib.Namespace("http://id.loc.gov/ontologies/bibframe/")
KDS = rdflib.Namespace("http://knowledgelinks.io/ns/data-structures/")
RELATORS = rdflib.Namespace("http://id.loc.gov/vocabulary/relators/")
SCHEMA = rdflib.Namespace("http://schema.org/")

BIBCAT_URL = "http://bibcat.org/"

# SPARQL query templates
PREFIX  = """PREFIX bf: <{}>
PREFIX kds: <{}>
PREFIX rdf: <{}>
PREFIX rdfs: <{}>
PREFIX bc: <http://knowledgelinks.io/ns/bibcat/> 
PREFIX m21: <http://knowledgelinks.io/ns/marc21/> 
PREFIX relators: <{}>
PREFIX schema: <{}>""".format(
    BF,
    KDS,
    rdflib.RDF,
    rdflib.RDFS,
    RELATORS,
    SCHEMA)

#GET_ENTITY_MARC = PREFIX + """
#SELECT ?prop ?marc
#WHERE {{
#    ?prop rdfs:domain <{0}> .
#    ?prop kds:marc2bibframe ?marc
#}}
#ORDER BY ?marc"""

DEDUP_ENTITIES = PREFIX + """
SELECT DISTINCT ?entity
WHERE {{
    ?entity <{0}> ?identifier .
    ?identifier rdf:type <{1}> .
    ?identifier rdf:value "{2}" .
}}"""

DEDUP_AGENTS = PREFIX + """
SELECT DISTINCT ?agent
WHERE {{
    ?agent rdf:type <{0}> .
    ?agent <{1}>  "{2}" .
}}"""

GET_ADDL_PROPS = PREFIX + """
SELECT ?pred ?obj
WHERE {{
  <{0}> kds:destAdditionalPropUris ?subj .
  ?subj ?pred ?obj .
}}"""

GET_BLANK_NODE = PREFIX + """
SELECT ?subject 
WHERE {{
    ?instance <{0}> ?subject .
}}"""

GET_LINKED_CLASSES = PREFIX + """
SELECT ?dest_prop ?dest_class ?linked_range ?subj
WHERE {{
   ?subj kds:destClassUri ?dest_class .
   ?subj kds:destPropUri ?dest_prop .
   ?subj kds:linkedRange ?linked_range .
   ?subj kds:linkedClass <{0}> .
   ?subj rdf:type kds:PropertyLinker .
}}"""

GET_ORDERED_CLASSES = PREFIX + """
SELECT ?dest_prop ?dest_class ?linked_range ?subj
WHERE {{
   ?subj kds:destClassUri ?dest_class .
   ?subj kds:destPropUri ?dest_prop .
   ?subj kds:linkedRange ?linked_range .
   ?subj kds:linkedClass <{0}> .
   ?subj rdf:type kds:OrderedPropertyLinker .
BF = rdflib.Namespace("http://id.loc.gov/ontologies/bibframe/")
KDS = rdflib.Namespace("http://knowledgelinks.io/ns/data-structures/")
RELATORS = rdflib.Namespace("http://id.loc.gov/vocabulary/relators/")
SCHEMA = rdflib.Namespace("http://schema.org/")
}}"""

BF = rdflib.Namespace("http://id.loc.gov/ontologies/bibframe/")
KDS = rdflib.Namespace("http://knowledgelinks.io/ns/data-structures/")
RELATORS = rdflib.Namespace("http://id.loc.gov/vocabulary/relators/")
SCHEMA = rdflib.Namespace("http://schema.org/")

GET_DIRECT_PROPS = PREFIX + """
SELECT ?dest_prop ?marc
WHERE {{
    ?subj kds:destClassUri <{0}> .
    ?subj kds:destPropUri ?dest_prop .
    ?subj kds:srcPropUri ?marc .
}}"""

GET_IDENTIFIERS = PREFIX + """
SELECT ?entity ?ident_value
WHERE {{
    ?entity rdf:type <{0}> .
    ?entity bf:identifiedBy ?identifier .
    ?identifier rdf:type <{1}> .
    ?identifier rdf:value ?ident_value .
}}"""

GET_ORDERED_MARC_LIST = PREFIX + """
SELECT ?marc
WHERE {{
    ?subj kds:srcOrderedPropUri/rdf:rest*/rdf:first ?marc .
    ?subj kds:destClassUri <{0}> .
}}"""

GET_MARC = PREFIX + """
SELECT ?marc
WHERE {{
    ?subj kds:srcPropUri ?marc .
    ?subj kds:destClassUri <{0}> .
    ?subj kds:destPropUri <{1}> .
    ?subj kds:linkedClass <{2}> .
    ?subj rdf:type <{3}> .
}}"""

HAS_MULTI_NODES = PREFIX + """
SELECT DISTINCT ?is_multi_nodes
WHERE {{
    <{0}> kds:hasIndividualNodes ?is_multi_nodes .
}}"""


MARC2BIBFRAME = None
TRIPLESTORE_URL = "http://localhost:8080/blazegraph/sparql"


def deduplicate_instances(graph, identifiers=[BF.Isbn]):
    """ Takes a BIBFRAME 2.0 graph and attempts to de-duplicate 
        Instances.

    Args:
        graph (rdflib.Graph): RDF Graph of transformed MARC to BIBFRAME
        identifiers (list): List of BIBFRAME identifiers to run 
    """
    # setup log
    lg = logging.getLogger("%s-%s" % (MNAME, inspect.stack()[0][3]))
    lg.setLevel(MLOG_LVL)
    for identifier in identifiers:
        sparql = GET_IDENTIFIERS.format(BF.Instance, identifier) 
        for row in graph.query(sparql):
            instance_uri, ident_value = row
            # get temp Instance URIs and 
            sparql = DEDUP_ENTITIES.format(
                BF.identifiedBy, 
                identifier, 
                ident_value)
            result = requests.post(TRIPLESTORE_URL,
                data={"query": sparql,
                      "format": "json"})
            lg.debug("\nquery: %s", sparql)
            if result.status_code > 399:
                lg.warn("result.status_code: %s", result.status_code)
                continue
            bindings = result.json().get('results', dict()).get('bindings', [])
            if len(bindings) < 1:
                continue
            #! Exits out of all for loops with the first match
            existing_uri = rdflib.URIRef(
                    bindings[0].get('entity',{}).get('value'))
            replace_uris(graph, instance_uri, existing_uri, [BF.hasItem,])

def deduplicate_agents(graph, filter_class, agent_class):
    """Deduplicates graph"""
    lg = logging.getLogger("%s-%s" % (MNAME, inspect.stack()[0][3]))
    lg.setLevel(MLOG_LVL)
    sparql = PREFIX + """
        SELECT DISTINCT ?subject ?value
        WHERE {{
            ?subject rdf:type <{0}> .
            ?subject <{1}> ?value .
        }}""".format(agent_class, filter_class)
    for row in graph.query(sparql):
        agent_uri, value = row
        sparql = DEDUP_AGENTS.format(
            agent_class,
            filter_class,
            value)
        result = requests.post(TRIPLESTORE_URL,
            data={"query": sparql,
                  "format": "json"})
        if result.status_code > 399:
            lg.warn("result.status_code: %s", result.status_code)
            continue
        bindings = result.json().get('results', dict()).get('bindings', [])
        if len(bindings) < 1:
            # Agent doesn't exit in triplestore add new URI
            new_agent_uri = rdflib.URIRef("http://bibcat.org/{}".format(uuid.uuid1()))
        else:
            new_agent_uri = rdflib.URIRef(bindings[0].get("agent").get("value"))
        for subject, pred in graph.subject_predicates(object=agent_uri):
            graph.remove((subject, pred, agent_uri))
            graph.add((subject, pred, new_agent_uri))
        for pred, obj in graph.predicate_objects(subject=agent_uri):
            graph.remove((agent_uri, pred, obj))
            graph.add((new_agent_uri, pred, obj))
        #graph.remove((agent_uri, 
        #replace_uris(graph, agent_uri, new_agent_uri)
        

    

def remove_blank_nodes(graph, bnode):
    for pred, obj in graph.predicate_objects(subject=bnode):
        graph.remove((bnode, pred, obj))
        if isinstance(obj, rdflib.BNode):
            remove_blank_nodes(graph, obj)


def replace_uris(graph, old_uri, new_uri, excludes=[]):
    """Replaces all occurrences of an old uri with a new uri"""
    #! SPARQL not working so looping graph manually :-(
    for pred, obj in graph.predicate_objects(subject=old_uri):
        if isinstance(obj, rdflib.BNode):
            remove_blank_nodes(graph, obj)
        graph.remove((old_uri, pred, obj))
        if not pred in excludes:
            graph.add((new_uri, pred, obj))
    

def match_marc(record, pattern):
    """Takes a MARC21 and pattern extracted from the last element from a 
    http://marc21rdf.info/ URI

    Args:
        record:  MARC21 Record
        pattern: Pattern to match
    Returns:
        list of subfield values
    """
    
    # setup log
    lg = logging.getLogger("%s-%s" % (MNAME, inspect.stack()[0][3]))
    lg.setLevel(MLOG_LVL)
    
    output = []
    field_name = pattern[1:4]
    indicators = pattern[4:6]
    subfield = pattern[-1]
    fields = record.get_fields(field_name)
    
    lg.debug("\nfield_name: %s\nindicators: %s\nsubfield:%s",
             field_name,
             indicators,
             subfield)
             
    for field in fields:
        lg.debug("field: %s", field)
        if field.is_control_field():
            lg.debug("control field")
            start, end = pattern[4:].split("-")
            output.append(field.data[int(start):int(end)+1])
            continue
        indicator_key = "{}{}".format(
            field.indicators[0].replace(" ", "_"),
            field.indicators[1].replace(" ", "_"))
        lg.debug("indicator_key: %s", indicator_key)
        if indicator_key == indicators:
            subfields = field.get_subfields(subfield)
            lg.debug("subfields: %s", subfields)
            output.extend(subfields)
    lg.debug("\n**** output ****\n%s", output)
    return output

def new_existing_bnode(graph, bf_property, rule):
    """Returns existing blank node or a new if it doesn't exist

    Args:
        graph (rdflib.Graph): RDF graph of new entity
        bf_property (str): RDF property URI
        rule (rdflib.URIRef): RDF subject of the map rule

    Returns:
        rdflib.BNode: Existing or New blank node
    """
    blank_node = None
    for row in MARC2BIBFRAME.query(HAS_MULTI_NODES.format(rule)):
        if str(row[0]).lower().startswith("true"):
            return rdflib.BNode()
    for subject in graph.query(GET_BLANK_NODE.format(bf_property)):
        # set to first and exist loop
        blank_node = subject[0]
        break
    if not blank_node:
        blank_node = rdflib.BNode()
    return blank_node


@click.command()
@click.argument("filepath")
def process(filepath):
    # setup log
    lg = logging.getLogger("%s-%s" % (MNAME, inspect.stack()[0][3]))
    lg.setLevel(MLOG_LVL)
    
    lg.debug("filepath: %s", filepath)
    marc_reader = pymarc.MARCReader(open(filepath, "rb"), 
        to_unicode=True)
    start = datetime.datetime.utcnow()
    total = 0
    lg.info("Started at %s", start)
    for i, record in enumerate(marc_reader):
        bf_graph = transform(record)
        if not i%10 and i > 0:
            lg.info(".", end="")
        if not i%100:
            lg.info(i, end="")
        total = i
    end = datetime.datetime.utcnow()
    lg.info("\nFinished %s at %s, total time=%s mins",
            total,
            end,
            (end-start).seconds / 60.0)  

def populate_entity(entity_class, graph, record):
    # setup log
    lg = logging.getLogger("%s-%s" % (MNAME, inspect.stack()[0][3]))
    lg.setLevel(MLOG_LVL)
    
    entity = rdflib.URIRef("http://bibcat.org/{}".format(uuid.uuid1()))
    graph.add((entity, rdflib.RDF.type, entity_class))
    update_linked_classes(entity_class, entity, graph, record)
    update_direct_properties(entity_class, entity, graph, record)
    update_ordered_linked_classes(entity_class, entity, graph, record)
    add_admin_metadata(graph, entity)
    return entity

def update_direct_properties(entity_class, 
                             entity,
                             graph, 
                             record):
    """Update the graph by adding all direct literal properties of the entity 
    in the graph.

    Args:
        entity_class (url): URL of the entity's class
        entity (rdflib.URIRef): RDFlib Entity
        graph (rdflib.Graph): RDFlib Graph
        record (pymarc.Record): MARC21 Record
    """
    sparql = GET_DIRECT_PROPS.format(entity_class)
    for dest_prop, marc in MARC2BIBFRAME.query(sparql):
        for value in match_marc(record, str(marc).split("/")[-1]):
            graph.add((entity, dest_prop, rdflib.Literal(value)))

def update_linked_classes(entity_class,
                          entity, 
                          graph, 
                          record):
    """Updates RDF Graph of linked classes

    Args:
        entity_class (url): URL of the entity's class
        entity (rdflib.URIRef): RDFlib Entity
        graph (rdflib.Graph): RDFlib Graph
        record (pymarc.Record): MARC21 Record
    """
    sparql = GET_LINKED_CLASSES.format(entity_class)
    for dest_property, dest_class, prop, subj in MARC2BIBFRAME.query(sparql):
        #! Should dedup dest_class here, return found URI or BNode
        for row in MARC2BIBFRAME.query(
            GET_MARC.format(
                dest_class, 
BF = rdflib.Namespace("http://id.loc.gov/ontologies/bibframe/")
KDS = rdflib.Namespace("http://knowledgelinks.io/ns/data-structures/")
RELATORS = rdflib.Namespace("http://id.loc.gov/vocabulary/relators/")
SCHEMA = rdflib.Namespace("http://schema.org/")
                dest_property,
                entity_class, 
                KDS.PropertyLinker)):
            marc = row[0]
            pattern = str(marc).split("/")[-1]
            for value in match_marc(record, pattern):
                if len(value.strip()) < 1:
                    continue
                bf_class = new_existing_bnode(graph, prop, subj)
                graph.add((bf_class, rdflib.RDF.type, dest_class))
                graph.add((entity, prop, bf_class))
                graph.add((bf_class, dest_property, rdflib.Literal(value)))
                # Sets additional properties
                for pred, obj in MARC2BIBFRAME.query(
                        GET_ADDL_PROPS.format(subj)):
                    graph.add((bf_class, pred, obj))


def update_ordered_linked_classes(entity_class,
                                  entity,
                                  graph,
                                  record):
    sparql = GET_ORDERED_CLASSES.format(entity_class)
    for dest_property, dest_class, prop, subj in MARC2BIBFRAME.query(sparql):
        for row in MARC2BIBFRAME.query(
            GET_MARC.format(dest_class,
                            dest_property,
                            entity_class,
                            KDS.OrderedPropertyLinker)):
            marc = row[0]
            pattern =  str(marc).split("/")[-1]
            field_name = pattern[1:4]
            indicators = pattern[4:6]
            subfields = pattern[6:]
            fields = record.get_fields(field_name)
            for field in fields:
                bf_class = new_existing_bnode(graph, prop, subj)
                indicator_key = "{}{}".format(
                    field.indicators[0].replace(" ", "_"),
                    field.indicators[1].replace(" ", "_"))
                if indicator_key != indicators:
                    continue
                ordered_value = ''
                for subfield in subfields:
                    ordered_value += ' '.join(
                        field.get_subfields(subfield)) + " "
                if len(ordered_value) > 0:
                    graph.add(
                        (bf_class, dest_property, rdflib.Literal(ordered_value.strip())))
                    graph.add((bf_class, rdflib.RDF.type, dest_class))
                    graph.add((entity, prop, bf_class))
                    # Retrieve and set additional properties 

               
            

def setup():
    # setup log
    lg = logging.getLogger("%s-%s" % (MNAME, inspect.stack()[0][3]))
    lg.setLevel(MLOG_LVL)
    
    global MARC2BIBFRAME
    
    MARC2BIBFRAME = new_graph()
    marc2bf_filepath = os.path.join(os.path.abspath(os.path.dirname(__file__)),
                                    "rdfw-definitions",
                                    "kds-bibcat-marc-ingestion.ttl")
    lg.debug("MARC2BIBFRAME: %s\nmarc2bf_filepath: %s", 
             MARC2BIBFRAME,
             marc2bf_filepath)
    MARC2BIBFRAME.parse(marc2bf_filepath, format="turtle")
 
def transform(record):
    """Function takes a MARC21 record and extracts BIBFRAME entities and 
    properties.

    Args:
        record:  MARC21 Record
    """
    # Assumes each MARC record will have at least 1 Work, Instance, and Item
    
    # setup log
    lg = logging.getLogger("%s-%s" % (MNAME, inspect.stack()[0][3]))
    lg.setLevel(MLOG_LVL)
    
    lg.debug("*** record ***\n&s", record)
    if not MARC2BIBFRAME:
        setup()
    g = new_graph()
    item = populate_entity(BF.Item, g, record)
    instance = populate_entity(BF.Instance, g, record)
    g.add((instance, BF.hasItem, item))
    g.add((item, BF.itemOf, instance))
    deduplicate_instances(g)
    deduplicate_agents(g, SCHEMA.oclc, BF.Organization) 
    add_to_triplestore(g)
    return g
                               
if __name__ == "__main__":
    if not MARC2BIBFRAME:
        setup()
    process()
