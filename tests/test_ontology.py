from earnings_call_graph.ontology import OntologyConcept, load_ontology, load_ontology_relations, map_entity_to_concepts


def test_default_ontology_maps_company_specific_entities_to_shared_concepts():
    concepts = load_ontology()

    cloud = map_entity_to_concepts("Google Cloud", "BusinessSegment", ontology=concepts)
    capex = map_entity_to_concepts("technical infrastructure spend", "Metric", ontology=concepts)
    backlog = map_entity_to_concepts("remaining performance obligation", "Metric", ontology=concepts)

    assert cloud[0].concept.id == "concept-cloud-platform-segment"
    assert capex[0].concept.id == "concept-infrastructure-capex"
    assert backlog[0].concept.id == "concept-backlog-rpo"


def test_default_ontology_declares_concept_hierarchy_and_schema_relations():
    concepts = {concept.id: concept for concept in load_ontology()}
    relations = {(relation.source_id, relation.relation_type, relation.target_id) for relation in load_ontology_relations()}

    assert concepts["concept-business-domain"].concept_type == "Root"
    assert ("concept-cloud-platform-segment", "IS_A", "concept-business-segment") in relations
    assert ("concept-data-center-capacity", "PART_OF", "concept-ai-infrastructure") in relations
    assert ("concept-ai-demand", "DRIVES_SCHEMA", "concept-infrastructure-capex") in relations


def test_ontology_mapping_is_conservative_for_company_nodes():
    assert map_entity_to_concepts("Alphabet", "Company") == ()


def test_ontology_mapping_uses_entity_properties_as_context():
    concepts = (
        OntologyConcept(
            id="concept-margin",
            name="Operating Margin Pressure",
            concept_type="Risk",
            aliases=("operating margin", "P&L pressure"),
        ),
    )

    matches = map_entity_to_concepts(
        "P&L pressure",
        "BusinessOutcome",
        properties={"context": "headwind to operating margin"},
        ontology=concepts,
    )

    assert matches[0].concept.id == "concept-margin"
    assert matches[0].confidence >= 0.88


def test_entity_resolution_rules_group_cross_company_synonyms():
    cloud_growth = map_entity_to_concepts("cloud growth", "Theme", limit=4)
    component_cost = map_entity_to_concepts("component cost", "Theme")
    regulatory = map_entity_to_concepts("Regulatory Compliance", "Theme")
    pricing = map_entity_to_concepts("Pricing Strategy", "Theme")
    capital_returns = map_entity_to_concepts("Capital Returns to Shareholders", "Theme")

    assert {match.concept.id for match in cloud_growth} >= {
        "concept-cloud-platform-segment",
        "concept-revenue-growth",
    }
    assert component_cost[0].concept.id == "concept-component-cost-pressure"
    assert regulatory[0].concept.id == "concept-regulatory-compliance-risk"
    assert pricing[0].concept.id == "concept-pricing-power"
    assert capital_returns[0].concept.id == "concept-capital-allocation"


def test_entity_resolution_does_not_overmap_generic_single_tokens():
    revenue = map_entity_to_concepts("Revenue", "Metric", limit=5)
    product = map_entity_to_concepts("Product", "Product", limit=5)
    pricing_power = map_entity_to_concepts("pricing power", "Theme", limit=5)

    assert [match.concept.id for match in revenue] == ["concept-revenue-growth"]
    assert product == ()
    assert "concept-power-cooling" not in {match.concept.id for match in pricing_power}
