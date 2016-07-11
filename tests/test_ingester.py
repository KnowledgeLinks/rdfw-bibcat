import datetime
import logging
import os
import pymarc
import rdflib
import requests
import sys
import unittest
import uuid

sys.path.append(os.path.abspath(os.path.curdir))
import ingesters

ingesters.MLOG_LVL = logging.CRITICAL
logging.getLogger("requests").setLevel(logging.CRITICAL)
logging.getLogger("urllib3").setLevel(logging.CRITICAL)

class TestAddingAdminData(unittest.TestCase):

    def setUp(self):
        self.entity = rdflib.URIRef("http://test/resource")
        self.ingester = ingesters.Ingester(rules_ttl="test.ttl")
        
        
    def test_add_admin_metadata(self):
        self.ingester.add_admin_metadata(self.entity)
        subjects = [s for s in self.ingester.graph.subjects()]
        self.assertTrue(self.entity in subjects)
        self.assertEqual(len(subjects), 4)
        
    def test_type_of(self):
        sparql = """SELECT ?bnode
WHERE {{
    ?bnode a <{0}> .
}}"""
        self.ingester.add_admin_metadata(self.entity)
        results = [row for row in self.ingester.graph.query(
            sparql.format(self.ingester.ns.bf.GenerationProcess))]
        self.assertEqual(len(results), 1)
        self.assertTrue(isinstance(results[0][0], rdflib.BNode))

    def test_generate_date(self):
        sparql = """SELECT ?generationDate
WHERE {{
    ?bnode <{0}> ?generationDate .
}}""".format(self.ingester.ns.bf.generationDate)
        self.ingester.add_admin_metadata(self.entity)
        results = [r for r in self.ingester.graph.query(sparql)]
        date_literal = results[0][0]
        generate_date = datetime.datetime.strptime(
            date_literal, 
            "%Y-%m-%dT%H:%M:%S.%f")
        self.assertTrue(generate_date < datetime.datetime.utcnow())

    def test_rdf_value(self):
        sparql = """SELECT ?default
WHERE {
    ?bnode <http://www.w3.org/1999/02/22-rdf-syntax-ns#value> ?default .
}"""
        self.ingester.add_admin_metadata(self.entity)
        results = [r for r in self.ingester.graph.query(sparql)]
        message = results[0][0]
        self.assertTrue(
            message.startswith(
                "Generated by BIBCAT version"))
        

class TestAddingToTriplestore(unittest.TestCase):

    def setUp(self):
        self.ingester = ingesters.Ingester(rules_ttl="test.ttl")

    def test_add_to_triplestore(self):
        self.ingester.add_to_triplestore()
   

class TestInitIngester(unittest.TestCase):

    def setUp(self):
        self.ingester = ingesters.Ingester(rules_ttl="test.ttl")

    def test_default_base_url(self):
        self.assertEqual(
            self.ingester.base_url,
            "http://bibcat.org/")

    def test_default_graph(self):
        self.assertEqual(
            len(self.ingester.graph),
            0)

    def test_default_rules_graph(self):
        self.assertEqual(
            len(self.ingester.rules_graph),
            0)

    def test_default_source(self):
        self.assertIsNone(self.ingester.source)

    def test_default_triplestore_url(self):
        self.assertEqual(
            self.ingester.triplestore_url,
            "http://localhost:8080/blazegraph/sparql")



class TestNewExistingBNode(unittest.TestCase):

    def setUp(self):
        self.ingester = ingesters.Ingester(rules_ttl="test.ttl")

    def test_new_bnode(self):
        result = self.ingester.new_existing_bnode(
            self.ingester.ns.schema.name,
            "M24510a")
        self.assertTrue(isinstance(result, rdflib.BNode)) 

class TestNewGraph(unittest.TestCase):

    def setUp(self):
        self.graph = ingesters.new_graph()

    def test_new_graph(self):
        default_turtle = self.graph.serialize(format='turtle').decode()
        self.assertEqual(default_turtle,
            """@prefix bf: <http://id.loc.gov/ontologies/bibframe/> .
@prefix kds: <http://knowledgelinks.io/ns/data-structures/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix relators: <http://id.loc.gov/vocabulary/relators/> .
@prefix schema: <http://schema.org/> .
@prefix xml: <http://www.w3.org/XML/1998/namespace> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

""")

class TestPopulateEntity(unittest.TestCase):

    def setUp(self):
        self.ingester = ingesters.Ingester(rules_ttl="test.ttl")


    def test_new_instance(self):
        entity = self.ingester.populate_entity(
            self.ingester.ns.bf.Instance)
        self.assertEqual(
            self.ingester.graph.value(subject=entity, 
                predicate=rdflib.RDF.type),
            self.ingester.ns.bf.Instance)

class TestRemoveBlankNodes(unittest.TestCase):

    def setUp(self):
        self.ingester = ingesters.Ingester(rules_ttl="test.ttl")
        self.bnode = rdflib.BNode()
        self.ingester.graph.add(
            (self.bnode, 
             rdflib.RDF.type, 
             self.ingester.ns.bf.Isbn))

    def test_flat_remove_blank_nodes(self):
        self.assertTrue(
            self.bnode in [s for s in self.ingester.graph.subjects()])
        self.ingester.remove_blank_nodes(self.bnode)
        self.assertFalse(
            self.bnode in [s for s in self.ingester.graph.subjects()])


class TestReplaceURIs(unittest.TestCase):

    def setUp(self):
        self.ingester = ingesters.Ingester(rules_ttl="test.ttl")
        self.old_uri = rdflib.URIRef("http://old.bibcat.org/{}".format(
            uuid.uuid1()))
        self.work_uri = rdflib.URIRef("http://bibcat.org/{}".format(
            uuid.uuid1()))
        self.ingester.graph.add((
            self.old_uri, 
            self.ingester.ns.bf.instanceOf, 
            self.work_uri))
        self.new_uri = rdflib.URIRef("http://new.bibcat.org/{}".format(
            uuid.uuid1()))

    def test_simple_replace_uri(self):
        self.assertEqual(
            self.ingester.graph.value(
                predicate=self.ingester.ns.bf.instanceOf,
                object=self.work_uri),
            self.old_uri)
        self.ingester.replace_uris(self.old_uri, self.new_uri)
        self.assertEqual(
            self.ingester.graph.value(
                predicate=self.ingester.ns.bf.instanceOf,
                object=self.work_uri),
            self.new_uri)


class TestTransform(unittest.TestCase):

    def setUp(self):
        self.ingester = ingesters.Ingester(rules_ttl="test.ttl")

    def test_default_transform(self):
        bf_instance, bf_item = self.ingester.transform()
        self.assertIsInstance(bf_instance, rdflib.URIRef)
        self.assertIsInstance(bf_item, rdflib.URIRef)


class TestUpdateDirectProperties(unittest.TestCase):

    def setUp(self):
        self.ingester = ingesters.Ingester(rules_ttl="test.ttl")
        self.entity = rdflib.URIRef("http://example.org/test")

    def test_default_method(self):
        self.assertIsNone(
            self.ingester.update_direct_properties(
                self.ingester.ns.bf.Item, 
                self.entity))

    def test_basic_rule(self):
        self.ingester.rules_graph.parse(
            data="""@prefix bc: <http://knowledgelinks.io/ns/bibcat/> .
@prefix bf: <http://id.loc.gov/ontologies/bibframe/> .
@prefix m21: <http://knowledgelinks.io/ns/marc21/> .
@prefix kds: <http://knowledgelinks.io/ns/data-structures/> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .

bc:m21-bf_copyrightDate a kds:PropertyLinker;
    kds:srcPropUri m21:M260__c;
    kds:destClassUri bf:Instance;
    kds:destPropUri bf:copyrightDate.""",
            format="turtle")
        self.ingester.update_direct_properties(
                self.ingester.ns.bf.Item, 
                self.entity)


class TestUpdateLinkedClasses(unittest.TestCase):

    def setUp(self):
        self.ingester = ingesters.Ingester(rules_ttl="test.ttl")
        self.entity = rdflib.URIRef("http://example.org/test")

    def test_default_method(self):
        self.assertIsNone(
            self.ingester.update_linked_classes(
                self.ingester.ns.bf.Item, 
                self.entity))

class TestUpdateOrderedLinkedClasses(unittest.TestCase):

    def setUp(self):
        self.ingester = ingesters.Ingester(rules_ttl="test.ttl")
        self.entity = rdflib.URIRef("http://example.org/test")

    def test_default_method(self):
        self.assertIsNone(
            self.ingester.update_ordered_linked_classes(
                self.ingester.ns.bf.Item,
                self.entity))
 


if __name__ == '__main__':
    unittest.main()
