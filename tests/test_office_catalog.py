import unittest
from office_catalog import parse_directory

class OfficialOfficeCatalogTests(unittest.TestCase):
    def test_only_offices_with_explicit_tie_services_are_included(self):
        html = """
        <h3>Oficinas de trámites de extranjería en Barcelona</h3>
        <h4>Comisaría de L'Hospitalet</h4>
        <p>Dirección</p><p>Pl. Repartidor n.º 8</p>
        <p>Teléfono</p><p>932602709</p>
        <p>Trámites</p><ul><li>Expedición de TIE</li><li>Certificados NIE</li></ul>
        <h4>Comisaría sin servicio TIE</h4>
        <p>Dirección</p><p>Calle Falsa 1</p>
        <p>Trámites</p><ul><li>Cartas de Invitación</li></ul>
        """
        records = parse_directory(html)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["prov"], "Barcelona")
        self.assertEqual(records[0]["name"], "Comisaría de L'Hospitalet")
        self.assertEqual(records[0]["address"], "Pl. Repartidor n.º 8")
        self.assertEqual(records[0]["phone"], "932602709")
        self.assertIn("Expedición de TIE", records[0]["services"])

if __name__ == "__main__":
    unittest.main()
