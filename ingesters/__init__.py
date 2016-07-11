"""BIBFRAME 2.0 ingester helper functions"""
__author__ = "Jeremy Nelson, Mike Stabile"

import datetime
import inspect
import logging
import os
import rdflib
import requests
import sys
import uuid

# get the current file name for logs and set logging leve
try:
    MNAME = inspect.stack()[0][1]
except:
    MNAME = "ingesters"
MLOG_LVL = logging.DEBUG
logging.basicConfig(level=logging.DEBUG)

sys.path.append(
    os.path.split(os.path.abspath(__file__))[0])
try:
    from instance import config
except ImportError:
    pass
try:
    version_path = os.path.join(
        os.path.abspath(
            os.path.split(
                os.path.dirname(__file__))[0]),
        "VERSION")
    with open(version_path) as version:
        __version__ = version.read().strip()  
except:
     __version__ = "unknown"

from rdfframework.utilities import RdfNsManager

class Ingester(object):
    """Base class for transforming various metadata format/vocabularies to 
    BIBFRAME RDF Linked Data"""
    
    # set the NameSpace Controller
    ns = RdfNsManager()

    def __init__(self, **kwargs):
        self.base_url = kwargs.get("base_url", "http://bibcat.org/")
        if "graph" in kwargs:
            self.graph = kwargs.get("graph")
        else:
            self.graph = new_graph()
        if not "rules_ttl" in kwargs:
            raise ValueError("Ingester Requires Rules Turtle file name")
        rules_filepath = os.path.join(
            os.path.abspath(
                os.path.split(os.path.dirname(__file__))[0]),
                "rdfw-definitions",
                kwargs.get("rules_ttl"))
        self.rules_graph = new_graph()
        if os.path.exists(rules_filepath):
            self.rules_graph.parse(rules_filepath, format='turtle')
            self.ns.load(rules_filepath)
        self.source = kwargs.get("source")
        self.triplestore_url = kwargs.get(
            "triplestore_url", 
            "http://localhost:8080/blazegraph/sparql")

    def add_admin_metadata(self, entity):
        """Takes a graph and adds the AdminMetadata for the entity

        Args:
            entity (rdflib.URIRef): URI of the entity
        """
        generate_msg = "Generated by BIBCAT version {} from KnowledgeLinks.io"
        generation_process = rdflib.BNode()
        self.graph.add((generation_process, rdflib.RDF.type, BF.GenerationProcess))
        self.graph.add((generation_process, 
            BF.generationDate, 
            rdflib.Literal(datetime.datetime.utcnow().isoformat())))
        self.graph.add((generation_process,
            rdflib.RDF.value,
            rdflib.Literal(generate_msg.format(__version__), 
                   lang="en")))
        #! Should add bibcat's current git MD5 commit 
        self.graph.add((entity, BF.generationProcess, generation_process))


    def add_to_triplestore(self):
       """Sends RDF graph via POST to add to triplestore
      """
       add_result = requests.post(self.triplestore_url,
           data=self.graph.serialize(format='turtle'),
           headers={"Content-Type": "text/turtle"})
       if add_result.status_code > 399:
           lg.error("Could not add graph to {}, status={}".format(
               self.triplestore_url,
               add_result.status_code))


    def new_existing_bnode(self, bf_property, rule):
       """Returns existing blank node or a new if it doesn't exist

       Args:
           bf_property (str): RDF property URI
           rule (rdflib.URIRef): RDF subject of the map rule

       Returns:
           rdflib.BNode: Existing or New blank node
       """
       blank_node = None
       for row in self.rules_graph.query(HAS_MULTI_NODES.format(rule)):
           if str(row[0]).lower().startswith("true"):
               return rdflib.BNode()
       for subject in self.graph.query(GET_BLANK_NODE.format(bf_property)):
           # set to first and exist loop
           blank_node = subject[0]
           break
       if not blank_node:
           blank_node = rdflib.BNode()
       return blank_node

    def populate_entity(self, bf_class, existing_uri=None):
        """Takes a BIBFRAME graph and MODS XML, extracts info for each
        entity's property and adds to graph.

        Args:
            bf_class(rdflib.URIRef): Namespace URI
        Returns:
           rdflib.URIRef: URI of new entity
        """
        uid = uuid.uuid1()
        if existing_uri:
            entity_uri = existing_uri
        else:
            if self.base_url.endswith("/"):
                pattern = "{0}{1}"
            else:
                pattern = "{0}/{1}"
            entity_uri = rdflib.URIRef(pattern.format(self.base_url, uid))
        self.graph.add((entity_uri, rdflib.RDF.type, bf_class))
        self.update_linked_classes(bf_class, entity_uri)
        self.update_direct_properties(bf_class, entity_uri)
        self.update_ordered_linked_classes(bf_class, entity_uri)
        self.add_admin_metadata(entity_uri)
        return entity_uri     

    def remove_blank_nodes(self, bnode):
        """Recursively removes all blank nodes

        Args:
            bnode(rdflib.BNode): Blank 
        """
        for pred, obj in self.graph.predicate_objects(subject=bnode):
            self.graph.remove((bnode, pred, obj))
            if isinstance(obj, rdflib.BNode):
                self.remove_blank_nodes(obj)

    def replace_uris(self, old_uri, new_uri, excludes=[]):
        """Replaces all occurrences of an old uri with a new uri

        Args:
            old_uri(rdflib.URIRef): 
            new_uri(rdflib.URIRef):
            excludes(list): 
        """
        for pred, obj in self.graph.predicate_objects(subject=old_uri):
            if isinstance(obj, rdflib.BNode):
                self.remove_blank_nodes(obj)
            self.graph.remove((old_uri, pred, obj))
            if not pred in excludes:
                self.graph.add((new_uri, pred, obj))

    def transform(self, source=None, instance_uri=None, item_uri=None):
        """Takes new source, sets new graph, and creates a BF.Instance and 
        BF.Item entities

        Args:
            source: New source, could be URL, XML, or CSV row
            instance_uri(rdflib.URIRef): Existing Instance URI, defaults to None
            item_uri(rdflib.URIRef): Existing Item URI, defaults to None

        Returns:
            tuple: BIBFRAME Instance and Item
        """
        if not source is None:
            self.source = source
            self.graph = new_graph()
        bf_instance = self.populate_entity(BF.Instance, instance_uri)
        bf_item = self.populate_entity(BF.Item,item_uri)
        self.graph.add((bf_item, BF.itemOf, bf_instance))
        return bf_instance, bf_item

    def update_direct_properties(self,
        entity_class, 
        entity):
        """Update the graph by adding all direct literal properties of the entity 
        in the graph.

        Args:
           entity_class (url): URL of the entity's class
           entity (rdflib.URIRef): RDFlib Entity
        """
        sparql = GET_DIRECT_PROPS.format(entity_class)
        for dest_prop, rule in self.rules_graph.query(sparql):
            self.__handle_pattern__(
                entity=entity, 
                rule=rule, 
                destination_property=dest_prop)
           
    def update_linked_classes(self,
        entity_class,
        entity):
        """Updates RDF Graph of linked classes

        Args:
           entity_class (url): URL of the entity's class
           entity (rdflib.URIRef): RDFlib Entity
        """
        sparql = GET_LINKED_CLASSES.format(entity_class)
        for dest_property, dest_class, prop, subj in \
            self.rules_graph.query(sparql):
            #! Should dedup dest_class here, return found URI or BNode
            if isinstance(dest_property, rdflib.BNode):
                self.__handle_linked_bnode__(
                    bnode=dest_property,
                    entity=entity,
                    destination_class=dest_class,
                    target_property=prop,
                    target_subject=subj)
                continue
            sparql_prop = GET_SRC_PROP.format(
                dest_class, 
                dest_property,
                entity_class, 
                KDS.PropertyLinker)
            for row in self.rules_graph.query(sparql_prop):
                self.__handle_linked_pattern__(
                    entity=entity, 
                    destination_class=dest_class,
                    destination_property=dest_property,
                    rule=row[0],
                    target_property=prop,
                    target_subject=subj)

    def update_ordered_linked_classes(self,
        entity_class,
        entity):
        """Updates RDF Graph of linked classes

        Args:
           entity_class (url): URL of the entity's class
           entity (rdflib.URIRef): RDFlib Entity
        """
        sparql = GET_ORDERED_CLASSES.format(entity_class)
        for dest_property, dest_class, prop, subj in \
            self.rules_graph.query(sparql):
            for row in self.rules_graph.query(
                GET_SRC_PROP.format(dest_class,
                    dest_property,
                    entity_class,
                    KDS.OrderedPropertyLinker)):
                self.__handle_ordered__(entity_class=entity_class, 
                    entity=entity,
                    destination_property=dest_property,
                    destination_class = dest_class,
                    target_property=prop,
                    target_subject=subj)
                
def new_graph():
    # setup log
    lg = logging.getLogger("%s-%s" % (MNAME, inspect.stack()[0][3]))
    lg.setLevel(MLOG_LVL)
    graph = rdflib.Graph(namespace_manager=RdfNsManager())
    return graph

from .sparql import *
