"""CSV file to BIBFRAME 2.0 Linked Data"""
__author__ = "Jeremy Nelson, Mike Stabile"

import click
import csv
import logging
import rdflib

from ingesters.ingester import Ingester, new_graph, NS_MGR
from ingesters.sparql import GET_ADDL_PROPS

import ingesters
MLOG_LVL = logging.DEBUG
logging.basicConfig(level=logging.DEBUG)

class RowIngester(Ingester):
    """Comma-separated Value Class takes a filepath to a CSV file where the
    the first row is assumed to be the column names""" 

    def __init__(self, source=None, custom=None):
        rules = ['kds-bibcat-csv-ingestion.ttl',]
        if isinstance(custom, str):
            rules.append(custom)
        elif isinstance(custom, list):
            rules.extend(custom) 
        super(RowIngester, self).__init__(
            rules_ttl=rules,
            source=source)

    def __handle_linked_pattern__(self, **kwargs):
        """Helper takes an entity, a rule made up of the field's key, and
        extracts and saves the destination property to the destination 
        class.

        Keyword args:
            entity(rdflib.URIRef): Entity's URI
            rule(str): String literal 
            destination_class(rdflib.URIRef): Destination class
            destination_property(rdflib.URIRef): Destination property
        """
        entity = kwargs.get("entity")
        rule = kwargs.get("rule")
        destination_class = kwargs.get("destination_class")
        destination_property = kwargs.get("destination_property")
        target_property = kwargs.get("target_property")
        target_subject = kwargs.get("target_subject")
        delimiter = self.rules_graph.value(
            subject=target_subject,
            predicate=NS_MGR.kds.delimiterProp)
        value = self.current_row.get(rule)
        if len(str(value).strip()) < 1:
            return
        if delimiter is not None:
            for row in value.split(str(delimiter)):
                bnode_class = self.new_existing_bnode(
                    target_property,
                    target_subject)
                self.graph.add(
                    (bnode_class,
                     rdflib.RDF.type,
                     destination_class))
                self.graph.add(
                    (bnode_class,
                     destination_property,
                     rdflib.Literal(row)))
                for pred, obj in self.rules_graph.query(
                        GET_ADDL_PROPS.format(target_subject)):
                    self.graph.add((bnode_class, pred, obj))
        else:
            bnode_class = self.new_existing_bnode(
                 target_property,
                 target_subject)
            self.graph.add(
                (bnode_class,
                 rdflib.RDF.type,
                 destination_class))
            self.graph.add(
                (bnode_class,
                 destination_property,
                 rdflib.Literal(row)))
            for pred, obj in self.rules_graph.query(
                    GET_ADDL_PROPS.format(target_subject)):
                self.graph.add((bnode_class, pred, obj))
           
                    
            

    def __handle_pattern__(self, **kwargs):
        """Helper takes an entity, rule, BIBFRAME class, rdfs:label 
        and extracts and saves the destination property to the destination
        class.

        Keyword args:
            entity(rdflib.URIRef): Entity's URI
            rule(str): Key for row
            destination_class(rdflib.URIRef): Destination class
            destination_property(rdflib.URIRef): Destination property
            target_property(rdflib.URIRef): Target range in final class
            target_subject(rdflib.URIRef): Rule subject URI in rules graph
        """
        entity = kwargs.get("entity")
        rule = kwargs.get("rule")
        destination_class = kwargs.get("destination_class")
        destination_property = kwargs.get("destination_property")
        if isinstance(destination_property, rdflib.BNode):
            for pred, obj in self.rules_graph.predicate_objects(
                    subject=destination_property):
                self.graph.add((entity, pred, obj))
        elif rule is not None:
            value = self.source.get(rule)
            bnode_class = self.new_existing_bnode(
                target_property,
                target_subject)
            self.graph.add(
                (bnode_class,
                 rdflib.RDF.type,
                 destination_class))
            self.graph.add(
                (bnode_class,
                 destination_property,
                 rdflib.Literal(value)))

    def transform(self, row=None):
        if row is not None:
            self.source = row
            self.graph = new_graph()
        super(RowIngester, self).transform()

        

