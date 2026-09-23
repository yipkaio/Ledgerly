"""Read stored XLSX cell values without depending on Excel calculation or formatting."""

from decimal import Decimal
from io import BytesIO
from xml.etree import ElementTree
from zipfile import ZipFile


NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def sheet_cells(workbook: bytes, sheet_number: int) -> dict[str, str | Decimal]:
    with ZipFile(BytesIO(workbook)) as archive:
        strings_xml = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
        strings = ["".join(node.itertext()) for node in strings_xml.findall("x:si", NS)]
        sheet_xml = ElementTree.fromstring(archive.read(f"xl/worksheets/sheet{sheet_number}.xml"))
    values = {}
    for cell in sheet_xml.findall(".//x:sheetData/x:row/x:c", NS):
        value = cell.find("x:v", NS)
        if value is not None and value.text is not None:
            values[cell.attrib["r"]] = (strings[int(value.text)] if cell.get("t") == "s"
                                         else Decimal(value.text))
    return values
