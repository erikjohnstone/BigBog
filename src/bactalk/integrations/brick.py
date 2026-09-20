from __future__ import annotations

import contextlib
import io
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import quote

from pyshacl import validate
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS

from bactalk.domain import JobSpec, PointRole

BACTALK = Namespace("urn:bactalk:")
BRICK = Namespace("https://brickschema.org/schema/Brick#")

SHAPES_TTL = """
@prefix brick: <https://brickschema.org/schema/Brick#> .
@prefix bactalk: <urn:bactalk:> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix sh: <http://www.w3.org/ns/shacl#> .

bactalk:EquipmentShape a sh:NodeShape ;
    sh:targetSubjectsOf brick:hasPoint ;
    sh:property [
        sh:path brick:hasPoint ;
        sh:minCount 1 ;
        sh:message "Equipment must have at least one point." ;
    ] .

bactalk:PointShape a sh:NodeShape ;
    sh:targetObjectsOf brick:hasPoint ;
    sh:property [
        sh:path rdf:type ;
        sh:minCount 1 ;
        sh:message "Each point must have a Brick class." ;
    ] ;
    sh:property [
        sh:path rdfs:label ;
        sh:minCount 1 ;
        sh:message "Each point must have a label." ;
    ] .
"""

FALLBACK_POINT_CLASSES = {
    PointRole.SENSOR: BRICK.Sensor,
    PointRole.SETPOINT: BRICK.Setpoint,
    PointRole.COMMAND: BRICK.Command,
    PointRole.STATUS: BRICK.Status,
    PointRole.ALARM: BRICK.Alarm,
}


@dataclass(frozen=True)
class BrickResult:
    turtle: str
    conforms: bool
    validation_report: str
    triples: int


def _entity_uri(*parts: str) -> URIRef:
    return URIRef("urn:bactalk:" + ":".join(quote(part, safe="") for part in parts))


@lru_cache(maxsize=1)
def _brick_classes() -> frozenset[URIRef]:
    # py-brickschema prints an optional SQL-backend warning at import time even
    # though BACTalk does not request persistence. Keep application output clean.
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        from brickschema import Graph as BrickGraph

        ontology = BrickGraph(load_brick=True)
    return frozenset(ontology.subjects(RDF.type, OWL.Class))


def build_and_validate_brick(job: JobSpec) -> BrickResult:
    """Create a portable Brick model and validate classes/relationships locally."""

    brick_classes = _brick_classes()
    data = Graph()
    data.bind("brick", BRICK)
    data.bind("bactalk", BACTALK)

    site = _entity_uri("site", job.site)
    equipment = _entity_uri("equipment", job.site, job.equipment_name)
    data.add((site, RDF.type, BRICK.Building))
    data.add((site, RDFS.label, Literal(job.site)))
    if not job.equipment_brick_class.startswith("brick:"):
        raise ValueError("equipment Brick class must use the brick: prefix")
    equipment_class = BRICK[job.equipment_brick_class.removeprefix("brick:")]
    if equipment_class not in brick_classes:
        raise ValueError(f"equipment references unknown Brick class {job.equipment_brick_class}")
    data.add((equipment, RDF.type, equipment_class))
    data.add((equipment, RDFS.label, Literal(job.equipment_name)))
    data.add((site, BRICK.hasPart, equipment))

    for point in job.points:
        point_uri = _entity_uri("point", job.site, job.equipment_name, point.name)
        point_class = FALLBACK_POINT_CLASSES[point.role]
        if point.brick_class:
            if not point.brick_class.startswith("brick:"):
                raise ValueError(f"point {point.name} Brick class must use the brick: prefix")
            point_class = BRICK[point.brick_class.removeprefix("brick:")]
            if point_class not in brick_classes:
                raise ValueError(
                    f"point {point.name} references unknown Brick class {point.brick_class}"
                )
        data.add((point_uri, RDF.type, point_class))
        data.add((point_uri, RDFS.label, Literal(point.label)))
        data.add((equipment, BRICK.hasPoint, point_uri))
        if point.units:
            data.add((point_uri, BACTALK.engineeringUnits, Literal(point.units)))
        if point.bacnet_device_instance is not None:
            data.add(
                (
                    point_uri,
                    BACTALK.bacnetDeviceInstance,
                    Literal(point.bacnet_device_instance),
                )
            )
        if point.bacnet_object:
            data.add((point_uri, BACTALK.bacnetObjectIdentifier, Literal(point.bacnet_object)))

    conforms, _, report = validate(data_graph=data, shacl_graph=SHAPES_TTL)
    turtle = data.serialize(format="turtle")
    return BrickResult(
        turtle=turtle,
        conforms=bool(conforms),
        validation_report=str(report),
        triples=len(data),
    )
