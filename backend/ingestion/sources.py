"""Small explicit source registry; no credentials required by these public reads."""

from dataclasses import dataclass, replace
from datetime import date


@dataclass(frozen=True)
class Source:
    name: str
    url: str
    where: str
    fields: tuple[str, ...]
    reference_date: str | None = None


SOURCES = {
    "imdc_power": Source(
        "imdc_power",
        "https://gisweb.miamidade.gov/arcgis/rest/services/Wasd/iMDCUtilityCoordination_2_v1/MapServer/9",
        "1=1",
        ("PROJECTID", "GlobalID", "PRJNAME", "PRJSCOPE", "AGCYNAME", "FACTYPE",
         "GENPRJSTAT", "AGYPRJSTAT", "STARTDATE", "ENDDATE"),
    ),
    "fdot_work_program": Source(
        "fdot_work_program",
        "https://gis.fdot.gov/arcgis/rest/services/Work_Program_Current/FeatureServer/2",
        "CONTYNAM LIKE 'MIAMI%'",
        ("FINPROJ", "FINPRJSQ", "FISCALYR", "LOCALFULL", "WPITSTNM",
         "CONTYNAM", "RDWYID", "BEGSECPT", "ENDSECPT"),
    ),
    "fdot_active": Source(
        "fdot_active",
        "https://gis.fdot.gov/arcgis/rest/services/Active_Construction_Projects/FeatureServer/1",
        "County LIKE '%MIAMI%' AND is820days = 'N'",
        ("ContractId", "Item", "ItemSeg", "County", "Description", "StartDate",
         "EstEndDate", "FinProjNum", "is820days"),
    ),
}


def source_for(name: str, as_of: date) -> Source:
    """Bound work-program collection without inventing day-level schedules."""
    source = SOURCES[name]
    where = source.where
    if name == "fdot_work_program":
        where += f" AND FISCALYR >= {as_of.year}"
    return replace(source, where=where, reference_date=as_of.isoformat())
