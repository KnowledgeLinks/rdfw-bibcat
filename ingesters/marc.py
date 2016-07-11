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
from ingesters import Ingester, new_graph 
from ingesters.sparql import *
from collections import OrderedDict

# get the current file name for logs and set logging level
MNAME = inspect.stack()[0][1]
MLOG_LVL = logging.DEBUG
logging.basicConfig(level=logging.DEBUG)

class MARCIngester(Ingester):

    def __init__(self, record):
        super(MARCIngester, self).__init__(
            rules_ttl="kds-bibcat-marc-ingestion.ttl",
            source=record)
        self.logger = logging.getLogger("%s-%s" % (MNAME, inspect.stack()[0][3]))
        self.logger.setLevel(MLOG_LVL)

    def __handle_linked_pattern__(self, **kwargs):
        """Helper takes an entity, rule, BIBFRAME class, kds:srcPropUri 
        and extracts and saves the destination property to the destination
        class.

        Keyword args:
            entity(rdflib.URIRef): Entity's URI
            rule(rdflib.URIRef): MARC Rule
            destination_class(rdflib.URIRef): Destination class
            destination_property(rdflib.URIRef): Destination property
        """
        entity = kwargs.get("entity")
        marc_rule = kwargs.get("rule")
        destination_class = kwargs.get("destination_class")
        destination_property = kwargs.get("destination_property")
        target_property = kwargs.get("target_property")
        target_subject = kwargs.get("target_subject")
        pattern = str(marc_rule).split("/")[-1]
        for value in self.match_marc(pattern):
            if len(value.strip()) < 1:
                continue
            bf_class = self.new_existing_bnode(
                target_property, 
                target_subject)
            self.graph.add((bf_class, self.ns.rdf.type, destination_class))
            self.graph.add((entity, target_property, bf_class))
            self.graph.add(
                (bf_class, 
                 destination_property, 
                 rdflib.Literal(value)))
            # Sets additional properties
            for pred, obj in self.rules_graph.query(
                GET_ADDL_PROPS.format(target_subject)):
                self.graph.add((bf_class, pred, obj))

    def __handle_pattern__(self, **kwargs):
        """Helper takes an entity, rule, BIBFRAME class, kds:srcPropUri 
        and extracts and saves the destination property to the destination
        class.

        Keyword args:
            entity(rdflib.URIRef): Entity's URI
            rule(rdflib.Literal): MARC21 Pattern
            destination_class(rdflib.URIRef): Destination class
            destination_property(rdflib.URIRef): Destination property
            target_property(rdflib.URIRef): Target range in final class
            target_subject(rdflib.URIRef): Rule subject URI in rules graph
        """
        entity = kwargs.get("entity")
        rule = kwargs.get("rule")
        destination_class = kwargs.get("destination_class")
        destination_property = kwargs.get("destination_property")
        target_property = kwargs.get("target_property")
        target_subject = kwargs.get("target_subject")
        pattern =  str(rule).split("/")[-1]
        for value in self.match_marc(pattern):
            self.graph.add((entity, 
                destination_property, 
                rdflib.Literal(value)))


    def __handle_ordered__(self, **kwargs):
        """Helper takes an entity, MARC21 rule, BIBFRAME class, kds:srcPropUri 
        and extracts and saves the destination property to the destination
        class in a defined order in the rule.

        Keyword args:
            entity(rdflib.URIRef): Entity's URI
            rule(rdflib.Literal): MARC21 Pattern
            destination_class(rdflib.URIRef): Destination class
            destination_property(rdflib.URIRef): Destination property
            target_property(rdflib.URIRef): Target range in final class
            target_subject(rdflib.URIRef): Rule subject URI in rules graph
        """
        entity = kwargs.get("entity")
        entity_class = kwargs.get("entity_class")
        destination_property = kwargs.get("destination_property")
        destination_class = kwargs.get("destination_class")
        rule = kwargs.get("rule")
        target_property = kwargs.get("target_property")
        target_subject = kwargs.get("target_subject")
        pattern =  str(rule).split("/")[-1]
        field_name = pattern[1:4]
        indicators = pattern[4:6]
        subfields = pattern[6:]
        fields = self.source.get_fields(field_name)
        for field in fields:
            bf_class = self.new_existing_bnode(prop, subj)
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
                self.graph.add(
                     (bf_class, 
                      dest_property, 
                      rdflib.Literal(ordered_value.strip())))
                self.graph.add(
                    (bf_class, 
                     self.ns.rdf.type, 
                     dest_class))
                self.graph.add((entity, prop, bf_class))
            # Sets additional properties
            for pred, obj in self.rules_graph.query(
                GET_ADDL_PROPS.format(target_subject)):
                self.graph.add((bf_class, pred, obj))



    def deduplicate_instances(self, identifiers=[]):
        """ Takes a BIBFRAME 2.0 graph and attempts to de-duplicate 
            Instances.

        Args:
            identifiers (list): List of BIBFRAME identifiers to run 
        """
        if len(identifiers) < 1:
            identifiers = [self.ns.bf.Isbn,]
        for identifier in identifiers:
            sparql = GET_IDENTIFIERS.format(self.ns.bf.Instance, identifier) 
            for row in self.graph.query(sparql):
                instance_uri, ident_value = row
                # get temp Instance URIs and 
                sparql = DEDUP_ENTITIES.format(
                    self.ns.bf.identifiedBy, 
                    identifier, 
                    ident_value)
                result = requests.post(TRIPLESTORE_URL,
                    data={"query": sparql,
                      "format": "json"})
                self.logger.debug("\nquery: %s", sparql)
                if result.status_code > 399:
                    self.logger.warn("result.status_code: %s", result.status_code)
                    continue
                bindings = result.json().get('results', dict()).get('bindings', [])
                if len(bindings) < 1:
                    continue
                #! Exits out of all for loops with the first match
                existing_uri = rdflib.URIRef(
                    bindings[0].get('entity',{}).get('value'))
                replace_uris(graph, instance_uri, existing_uri, [self.ns.bf.hasItem,])
                

    def deduplicate_agents(self, filter_class, agent_class):
        """Deduplicates graph"""
        lg = logging.getLogger("%s-%s" % (MNAME, inspect.stack()[0][3]))
        lg.setLevel(MLOG_LVL)
        sparql = PREFIX + """
        SELECT DISTINCT ?subject ?value
        WHERE {{
            ?subject rdf:type <{0}> .
            ?subject <{1}> ?value .
        }}""".format(agent_class, filter_class)
        for row in self.graph.query(sparql):
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
            for subject, pred in self.graph.subject_predicates(object=agent_uri):
                self.graph.remove((subject, pred, agent_uri))
                self.graph.add((subject, pred, new_agent_uri))
            for pred, obj in self.graph.predicate_objects(subject=agent_uri):
                self.graph.remove((agent_uri, pred, obj))
                self.graph.add((new_agent_uri, pred, obj))
        
    

    def match_marc(self, pattern, record=None):
        """Takes a MARC21 and pattern extracted from the last element from a 
        http://marc21rdf.info/ URI

        Args:
            pattern(str): Pattern to match
            record(pymarc.Record): Optional MARC21 Record, default's to instance
        Returns:
            list of subfield values
        """
        output = []
        field_name = pattern[1:4]
        indicators = pattern[4:6]
        subfield = pattern[-1]
        if record is None:
            fields = self.source.get_fields(field_name)
        else:
            fields = record.get_fields(field_name)
        self.logger.debug("\nfield_name: %s\nindicators: %s\nsubfield:%s",
                 field_name,
                indicators,
                subfield)
             
        for field in fields:
            self.logger.debug("field: %s", field)
            if field.is_control_field():
                self.logger.debug("control field")
                start, end = pattern[4:].split("-")
                output.append(field.data[int(start):int(end)+1])
                continue
            indicator_key = "{}{}".format(
                field.indicators[0].replace(" ", "_"),
                field.indicators[1].replace(" ", "_"))
            self.logger.debug("indicator_key: %s", indicator_key)
            if indicator_key == indicators:
                subfields = field.get_subfields(subfield)
                self.logger.debug("subfields: %s", subfields)
                output.extend(subfields)
        self.logger.debug("\n**** output ****\n%s", output)
        return output

    def transform(self, record=None):
        """Method transforms a MARC record (either instance source
        or passed in MARC21 record) into BIBFRAME 2.0 

        Args:
            record(pymarc.Record): MARC21 Record
        """
        if record is not None:
            if isinstance(record, pymarc.Record):
                self.source = record
                self.graph = self.new_graph()
        bf_instance, bf_item = super(MARCIngester, self).transform()
        # Run de-duplication methods
        self.deduplicate_instances()
        self.deduplicate_agents(SCHEMA.oclc, self.ns.bf.Organization)

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

